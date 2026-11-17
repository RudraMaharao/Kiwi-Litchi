"""Positioned words -> lines -> cells, and the statement's column layout.

Bank statements are tables drawn as loose text. This module groups words
into lines, merges close words into cells, finds the header row and works
out where each column sits, so the parser can tell a narration from an
amount from a balance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pdftext import Word
from .util import norm_key


@dataclass
class Cell:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    words: list[Word] = field(default_factory=list)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Line:
    cells: list[Cell]
    top: float
    bottom: float
    page: int

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self.cells)

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def x0(self) -> float:
        return min(c.x0 for c in self.cells)

    @property
    def x1(self) -> float:
        return max(c.x1 for c in self.cells)


def _median(values, default=8.0):
    vals = sorted(values)
    return vals[len(vals) // 2] if vals else default


def group_lines(words: list[Word], page: int = 1) -> list[Line]:
    """Cluster words into lines by vertical position, then merge close words into cells."""
    if not words:
        return []
    med_h = _median([w.h for w in words])
    rows: list[list[Word]] = []
    centers: list[float] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        if rows and abs(w.cy - centers[-1]) <= max(1.2, 0.45 * med_h):
            rows[-1].append(w)
            n = len(rows[-1])
            centers[-1] = centers[-1] + (w.cy - centers[-1]) / n
        else:
            rows.append([w])
            centers.append(w.cy)
    gap_limit = max(1.6, 0.5 * med_h)
    lines = []
    for ws in rows:
        ws.sort(key=lambda w: w.x0)
        cells: list[Cell] = []
        for w in ws:
            if cells and w.x0 - cells[-1].x1 <= gap_limit:
                c = cells[-1]
                c.text = f"{c.text} {w.text}"
                c.x1 = max(c.x1, w.x1)
                c.top = min(c.top, w.top)
                c.bottom = max(c.bottom, w.bottom)
                c.words.append(w)
            else:
                cells.append(Cell(w.text, w.x0, w.x1, w.top, w.bottom, [w]))
        lines.append(Line(cells, min(c.top for c in cells), max(c.bottom for c in cells), page))
    return lines


# ------------------------------------------------------------ header roles

_ROLE_PATTERNS = [
    ("value_date", r"(value|val)( (date|dt))?"),
    ("date", r"((txn|tran|trans|transaction|post|posting|book|booking|entry) )?(date|dt)"),
    ("serial", r"(s|sr|sl|serial) ?(no|num|number)?|sno|srno|slno"),
    ("narration", r"((transaction|txn|tran) )?(narration|description|particulars|details|remarks|desc)( narration)?"),
    ("ref", r"(chq|cheque|check|ref|reference|instrument|utr)( .*)?"),
    ("drcr", r"(dr ?cr|cr ?dr|d ?c|dr or cr|type|txn type|transaction type)"),
    ("amount", r"((txn|transaction) )?(amount|amt)( (in )?(inr|rs))?|(debit|withdrawal) (credit|deposit)( amount)?"),
    ("debit", r"(withdrawals?|debits?|dr|paid out)( (amt|amount|dr|in|inr|rs))*"),
    ("credit", r"(deposits?|credits?|cr|paid in)( (amt|amount|cr|in|inr|rs))*"),
    ("balance", r"((closing|running|available|ledger|book) )?(balance|bal)( (amt|amount|in|inr|rs|dr|cr))*"),
]
_ROLE_RES = [(role, re.compile(rf"^(?:{pat})$")) for role, pat in _ROLE_PATTERNS]

NUMERIC_ROLES = ("debit", "credit", "amount", "balance")
TEXT_ROLES = ("serial", "date", "value_date", "ref", "narration", "drcr")


def match_role(text: str) -> str | None:
    key = norm_key(text)
    if not key or len(key) > 40:
        return None
    for role, rx in _ROLE_RES:
        if rx.match(key):
            return role
    return None


@dataclass
class Col:
    role: str
    x0: float
    x1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class ColumnModel:
    cols: dict[str, Col]
    top: float
    bottom: float
    page: int
    width: float

    @property
    def roles(self) -> set[str]:
        return set(self.cols)

    def has(self, role: str) -> bool:
        return role in self.cols

    def _ordered(self) -> list[Col]:
        return sorted(self.cols.values(), key=lambda c: c.x0)

    def text_span(self, role: str) -> tuple[float, float] | None:
        """Left-aligned span of a text column: from its label to the next label."""
        col = self.cols.get(role)
        if not col:
            return None
        ordered = self._ordered()
        idx = ordered.index(col)
        tol = min(10.0, 0.35 * (col.x1 - col.x0) + 2)
        left = col.x0 - tol
        if idx > 0:
            prev = ordered[idx - 1]
            if prev.role in NUMERIC_ROLES:
                left = max(left, prev.x1 + 1)
        right = ordered[idx + 1].x0 - min(10.0, 0.35 * (ordered[idx + 1].x1 - ordered[idx + 1].x0) + 2) \
            if idx + 1 < len(ordered) else self.width + 1
        return left, max(right, col.x1)

    def text_role_of(self, cell: Cell) -> str | None:
        best, best_left = None, None
        for role in TEXT_ROLES:
            span = self.text_span(role)
            if span and span[0] <= cell.x0 < span[1]:
                if best_left is None or span[0] > best_left:
                    best, best_left = role, span[0]
        return best

    def numeric_role_of(self, cell: Cell) -> str | None:
        cands = [c for c in self.cols.values() if c.role in NUMERIC_ROLES]
        if not cands:
            return None
        return min(cands, key=lambda c: abs(c.cx - cell.cx) + 0.3 * abs(c.x1 - cell.x1)).role

    @property
    def amount_zone_x0(self) -> float:
        nums = [c for c in self.cols.values() if c.role in NUMERIC_ROLES]
        if not nums:
            return self.width
        first = min(nums, key=lambda c: c.x0)
        texts = [c for c in self.cols.values() if c.role not in NUMERIC_ROLES and c.x1 <= first.x0]
        left_bound = max((c.x1 for c in texts), default=0)
        # numbers may be wider than their label and stick out to the left
        return max(left_bound, first.x0 - 0.6 * (first.x0 - left_bound))

    @property
    def date_right(self) -> float:
        """Right edge of the leading date/serial columns."""
        span = self.text_span("date") or self.text_span("value_date")
        return span[1] if span else 0


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _labels(line: Line, below: Line | None) -> list[tuple[str, float, float]]:
    """Header label candidates: each cell, joined with the cell under it if the header wraps."""
    out = []
    used_below = set()
    for c in line.cells:
        text, x0, x1 = c.text, c.x0, c.x1
        if below is not None:
            for j, b in enumerate(below.cells):
                ov = _overlap(c.x0, c.x1, b.x0, b.x1)
                if ov > 0.3 * min(c.x1 - c.x0, b.x1 - b.x0):
                    text = f"{text} {b.text}"
                    x0, x1 = min(x0, b.x0), max(x1, b.x1)
                    used_below.add(j)
        out.append((text, x0, x1))
    if below is not None:
        for j, b in enumerate(below.cells):
            if j not in used_below:
                out.append((b.text, b.x0, b.x1))
    return out


def _split_label(text: str, x0: float, x1: float) -> list[tuple[str, float, float]]:
    """A cell may hold several labels set close together ('Date Narration'): split greedily."""
    words = text.split()
    if not 1 < len(words) <= 10:
        return []
    char_w = (x1 - x0) / max(1, len(text))
    starts, pos = [], 0
    for w in words:
        starts.append(pos)
        pos += len(w) + 1
    out, i = [], 0
    while i < len(words):
        for n in range(min(4, len(words) - i), 0, -1):
            chunk = " ".join(words[i:i + n])
            role = match_role(chunk)
            if role:
                sx = x0 + char_w * starts[i]
                out.append((role, sx, sx + char_w * len(chunk)))
                i += n
                break
        else:
            i += 1
    return out


def _roles_from_labels(labels) -> dict[str, Col]:
    cols: dict[str, Col] = {}

    def add(role, x0, x1):
        if role == "date" and "date" in cols and "value_date" not in cols:
            role = "value_date"
        if role not in cols:
            cols[role] = Col(role, x0, x1)

    for text, x0, x1 in sorted(labels, key=lambda t: t[1]):
        role = match_role(text)
        if role is not None:
            add(role, x0, x1)
            continue
        for r, sx, ex in _split_label(text, x0, x1):
            add(r, sx, ex)
    return cols


def _valid(cols: dict[str, Col]) -> int:
    roles = set(cols)
    if "date" not in roles and "value_date" not in roles:
        return 0
    money = roles & {"debit", "credit", "amount", "balance"}
    if not money:
        return 0
    core = roles & {"narration", "debit", "credit", "amount", "balance"}
    if len(core) < 2:
        return 0
    return len(roles)


def _looks_like_data(line: Line) -> bool:
    from .util import parse_amount, starts_with_date

    for c in line.cells:
        if starts_with_date(c.text)[0] is not None or parse_amount(c.text, require_decimals=True):
            return True
    return False


def find_header(lines: list[Line], page_width: float) -> tuple[ColumnModel, int, int] | None:
    """Return (model, index of first header line, number of header lines)."""
    best = None
    for i, line in enumerate(lines):
        if len(line.cells) < 3:
            continue
        for span in (1, 2):
            below = lines[i + 1] if span == 2 and i + 1 < len(lines) else None
            if span == 2 and (below is None or below.top - line.bottom > 1.5 * (line.bottom - line.top) + 2
                              or _looks_like_data(below)):
                continue
            cols = _roles_from_labels(_labels(line, below))
            score = _valid(cols)
            if not score:
                continue
            if "date" not in cols and "value_date" in cols:
                cols["date"] = cols.pop("value_date")
                cols["date"].role = "date"
            if best is None or score > best[0]:
                bottom = (below or line).bottom
                best = (score, ColumnModel(cols, line.top, bottom, line.page, page_width), i, span)
        if best is not None and i > best[2] + 2:
            break
    if best is None:
        return None
    _, model, idx, span = best
    return model, idx, span
