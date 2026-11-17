"""Turn the lines of a PDF statement into raw transaction rows.

A row starts at a line with a date in the date column. Narration lines below
it belong to it until the next date. Amounts come from the money columns;
which one is the balance is decided by the header, or by position when the
statement has no header.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .layout import Cell, Col, ColumnModel, Line, find_header, group_lines
from .pdftext import PageWords
from .util import Amount, clean_ocr_text, fix_ocr_digits, norm_space, parse_amount, parse_date, starts_with_date

OPENING_RE = re.compile(
    r"^(opening\s*balance|opening\s*bal|balance\s*b\s*/?\s*f\b|b\s*/\s*f\b|brought\s*forward|"
    r"balance\s*forward|balance\s*as\s*(on|of)|op\.?\s*bal)", re.I)
CLOSING_RE = re.compile(r"^(closing\s*balance|closing\s*bal|balance\s*c\s*/?\s*f\b|c\s*/\s*f\b|carried\s*forward)", re.I)
END_LEFT_RE = re.compile(
    r"^(total|grand\s*total|statement\s*summary|summary|account\s*summary|end\s*of\s*statement|\*+|abbreviations|"
    r"legend|important|disclaimer|note\s*:|notes\s*:|unless\s*the\s*constituent|please\s*note)", re.I)
END_ANY_RE = re.compile(
    r"(page\s*\d+\s*(of|/)\s*\d+|this\s*is\s*a\s*(system|computer)[\s-]*generated|end\s*of\s*statement|"
    r"\*{3,}\s*end)", re.I)
DRCR_TOKEN = re.compile(r"^\(?\s*(cr|dr)\s*\)?\.?$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?$", re.I)


@dataclass
class AmountCell:
    amount: Amount
    x0: float
    x1: float

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2


@dataclass
class RawRow:
    date: object
    value_date: object = None
    narration: str = ""
    ref: str = ""
    amount: int = 0
    direction: str | None = None  # debit | credit | None (unknown)
    balance: int | None = None
    page: int = 0
    y: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class Extracted:
    rows: list[RawRow] = field(default_factory=list)
    header_lines: list[Line] = field(default_factory=list)
    all_lines: list[Line] = field(default_factory=list)
    openings: list[int] = field(default_factory=list)
    closings: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: ColumnModel | None = None
    headerless: bool = False
    table_headers: list[Line] = field(default_factory=list)


@dataclass
class _LineInfo:
    date: object = None
    value_date: object = None
    narr: list[Cell] = field(default_factory=list)
    ref: list[Cell] = field(default_factory=list)
    amounts: list[AmountCell] = field(default_factory=list)
    drcr: str | None = None
    left_junk: bool = False


@dataclass
class _Block:
    info: _LineInfo
    line: Line
    narr_lines: list[list[Cell]] = field(default_factory=list)
    ref_parts: list[str] = field(default_factory=list)
    amounts: list[AmountCell] = field(default_factory=list)
    drcr: str | None = None


def _amount_cells(cell: Cell, ocr: bool) -> list[AmountCell]:
    text = fix_ocr_digits(cell.text) if ocr else cell.text
    a = parse_amount(text, require_decimals=True)
    if a:
        return [AmountCell(a, cell.x0, cell.x1)]
    parts = text.split()
    if len(parts) < 2:
        return []
    out: list[AmountCell] = []
    char_w = (cell.x1 - cell.x0) / max(1, len(text))
    pos = 0
    for part in parts:
        start = text.index(part, pos)
        pos = start + len(part)
        if DRCR_TOKEN.match(part) and out:
            out[-1].amount.drcr = "CR" if "c" in part.lower() else "DR"
            continue
        a = parse_amount(part, require_decimals=True)
        if not a:
            return []
        out.append(AmountCell(a, cell.x0 + start * char_w, cell.x0 + pos * char_w))
    return out


def _analyze(line: Line, model: ColumnModel, ocr: bool) -> _LineInfo:
    info = _LineInfo()
    amount_x0 = model.amount_zone_x0
    narr_span = model.text_span("narration")
    narr_left = narr_span[0] if narr_span else model.date_right
    for idx, cell in enumerate(line.cells):
        text = cell.text.strip()
        if not text:
            continue
        if cell.x1 > amount_x0 or cell.x0 >= amount_x0 - 1:
            found = _amount_cells(cell, ocr)
            if found and found[0].x0 >= amount_x0 - 2:
                info.amounts.extend(found)
                continue
            if DRCR_TOKEN.match(text) and cell.x0 >= amount_x0 - 2:
                if info.amounts:
                    info.amounts[-1].amount.drcr = "CR" if "c" in text.lower() else "DR"
                else:
                    info.drcr = "CR" if "c" in text.lower() else "DR"
                continue
            if text in {"-", "--", "—", "0", "NIL"} and cell.x0 >= amount_x0 - 2:
                continue
        role = model.text_role_of(cell)
        if role in ("date", "value_date", "serial") or (idx == 0 and role is None):
            d, rest = starts_with_date(text)
            if d is None and role == "serial" and re.fullmatch(r"\d{1,5}\.?", text):
                continue
            if d is not None:
                if role == "value_date" and model.has("date"):
                    info.value_date = info.value_date or d
                elif info.date is None:
                    info.date = d
                elif info.value_date is None:
                    info.value_date = d
                if rest and not TIME_RE.match(rest):
                    d2, rest2 = starts_with_date(rest)
                    if d2 is not None:
                        info.value_date = info.value_date or d2
                        rest = rest2
                    if rest and not TIME_RE.match(rest):
                        info.narr.append(Cell(rest, cell.x0, cell.x1, cell.top, cell.bottom))
                continue
        if role == "drcr" and DRCR_TOKEN.match(text):
            info.drcr = "CR" if "c" in text.lower() else "DR"
            continue
        if role == "ref":
            info.ref.append(cell)
            continue
        if TIME_RE.match(text) and info.date is not None and not info.narr:
            continue
        if cell.x0 < narr_left - 1 and role not in ("narration", "ref"):
            info.left_junk = True
        info.narr.append(cell)
    return info


def _frag(cells: list[Cell]) -> str:
    return " ".join(c.text.strip() for c in cells if c.text.strip())


def _wrap_width(blocks) -> int | None:
    """Banks that cut narrations at a fixed number of characters produce many full lines of one length."""
    from collections import Counter

    lengths = []
    for b in blocks:
        frags = [_frag(cells) for cells in b.narr_lines if cells]
        lengths.extend(len(f) for f in frags[:-1] if f)
    if len(lengths) < 3:
        return None
    counts = Counter(lengths)
    n, count = counts.most_common(1)[0]
    # full lines are N characters, or N-1 when the line ended on a space that was trimmed
    if n >= 12 and count >= 3 and count + counts.get(n - 1, 0) >= 0.75 * len(lengths):
        return n
    return None


def _join_narration(lines: list[list[Cell]], wrap_n: int | None, left_edge: float, right_edge: float,
                    char_w: float) -> str:
    out, prev_text, prev_cells = "", "", None
    for cells in lines:
        text = _frag(cells) if cells else ""
        if not text:
            continue
        if not out:
            out = text
        else:
            glue = " "
            indented = cells[0].x0 > left_edge + 0.35 * char_w
            if wrap_n:
                if len(prev_text) >= wrap_n and not indented:
                    glue = ""  # cut mid-word at the fixed width
            elif prev_cells and " " not in prev_text and not indented \
                    and right_edge - prev_cells[-1].x1 < 1.2 * char_w:
                glue = ""  # one long token filled the line to the edge, so it was broken
            out += glue + text
        prev_text, prev_cells = text, cells
    return norm_space(out)


class _PageParser:
    def __init__(self, model: ColumnModel, page: PageWords, out: Extracted):
        self.model = model
        self.page = page
        self.out = out
        self.ocr = page.source == "ocr"
        self.blocks: list[_Block] = []

    def run(self, lines: list[Line]):
        current: _Block | None = None
        ended = False
        for line in lines:
            if ended:
                break
            info = _analyze(line, self.model, self.ocr)
            narr_text = norm_space(" ".join(c.text for c in info.narr))
            whole = norm_space(line.text)
            if END_ANY_RE.search(whole) and info.date is None:
                current = self._flush(current)
                ended = True
                continue
            if info.date is not None:
                if OPENING_RE.match(narr_text):
                    current = self._flush(current)
                    if info.amounts:
                        self.out.openings.append(info.amounts[-1].amount.signed())
                    continue
                if CLOSING_RE.match(narr_text):
                    current = self._flush(current)
                    if info.amounts:
                        self.out.closings.append(info.amounts[-1].amount.signed())
                    continue
                current = self._flush(current)
                current = _Block(info, line, [info.narr], [c.text.strip() for c in info.ref], list(info.amounts),
                                 info.drcr)
                continue
            # a line without a date
            if OPENING_RE.match(whole) or OPENING_RE.match(narr_text):
                current = self._flush(current)
                if info.amounts:
                    self.out.openings.append(info.amounts[-1].amount.signed())
                continue
            if CLOSING_RE.match(whole) or CLOSING_RE.match(narr_text):
                current = self._flush(current)
                if info.amounts:
                    self.out.closings.append(info.amounts[-1].amount.signed())
                continue
            if info.left_junk:
                if END_LEFT_RE.match(whole):
                    current = self._flush(current)
                    ended = True
                    continue
                current = self._flush(current)
                continue
            if current is None:
                continue
            if info.amounts:
                if current.amounts:
                    current = self._flush(current)
                    continue
                current.amounts.extend(info.amounts)
            if info.drcr and not current.drcr:
                current.drcr = info.drcr
            if info.narr:
                current.narr_lines.append(info.narr)
            current.ref_parts.extend(c.text.strip() for c in info.ref)
        self._flush(current)
        self._emit()

    def _flush(self, block: _Block | None):
        if block is not None:
            self.blocks.append(block)
        return None

    def _emit(self):
        narr_cells = [c for b in self.blocks for ln in b.narr_lines for c in ln]
        right_edge = max((c.x1 for c in narr_cells), default=0)
        widths = [(c.x1 - c.x0) / max(1, len(c.text)) for c in narr_cells if len(c.text) >= 4]
        char_w = sorted(widths)[len(widths) // 2] if widths else 4.0
        firsts = [ln[0].x0 for b in self.blocks for ln in b.narr_lines if ln]
        left_edge = sorted(firsts)[len(firsts) // 4] if firsts else 0
        wrap_n = _wrap_width(self.blocks)
        for b in self.blocks:
            narration = _join_narration(b.narr_lines, wrap_n, left_edge, right_edge, char_w)
            row = self._row(b, narration)
            if row is not None:
                self.out.rows.append(row)

    def _row(self, b: _Block, narration: str) -> RawRow | None:
        model = self.model
        if self.ocr:
            narration = clean_ocr_text(narration)
        row = RawRow(date=b.info.date, value_date=b.info.value_date, narration=narration,
                     ref="".join(p for p in b.ref_parts if p), page=self.page.number, y=b.line.top)
        amts = list(b.amounts)
        if not amts:
            self.out.warnings.append(
                f"Page {self.page.number}: a dated line without amounts was skipped ({narration[:40] or 'no text'})."
            )
            return None
        roles = [model.numeric_role_of(Cell("", a.x0, a.x1, 0, 0)) for a in amts]
        balance_idx = None
        if model.has("balance"):
            bal = [i for i, r in enumerate(roles) if r == "balance"]
            if bal:
                balance_idx = max(bal, key=lambda i: amts[i].x1)
            elif len(amts) >= 2:
                balance_idx = max(range(len(amts)), key=lambda i: amts[i].x1)
        if balance_idx is not None:
            row.balance = amts[balance_idx].amount.signed()
        rest = [(a, r) for i, (a, r) in enumerate(zip(amts, roles)) if i != balance_idx]
        nonzero = [(a, r) for a, r in rest if a.amount.paise != 0]
        if not nonzero:
            row.amount = 0
            return row
        if len(nonzero) > 1:
            row.notes.append("two amounts on one row")
        a, role = nonzero[0]
        row.amount = a.amount.paise
        direction = None
        if role == "debit":
            direction = "debit"
        elif role == "credit":
            direction = "credit"
        drcr = a.amount.drcr or b.drcr
        if drcr and (role in ("amount", None) or not model.has("debit") or not model.has("credit")):
            direction = "credit" if drcr == "CR" else "debit"
        elif role in ("amount", None) and a.amount.negative:
            direction = "debit"
        row.direction = direction
        return row


def _headerless_model(lines: list[Line], width: float) -> ColumnModel | None:
    """No header row anywhere: infer columns from lines that start with a date and end with amounts."""
    samples = []
    for ln in lines:
        if len(ln.cells) < 3:
            continue
        d, _ = starts_with_date(ln.cells[0].text)
        if d is None:
            continue
        tail = [c for c in ln.cells[1:] if parse_amount(c.text, require_decimals=True)]
        if not tail or tail[-1] is not ln.cells[-1]:
            continue
        samples.append((ln.cells[0], tail))
    if len(samples) < 3:
        return None
    med = lambda vals: sorted(vals)[len(vals) // 2]  # noqa: E731
    date_x0 = min(s[0].x0 for s in samples)
    date_x1 = med([s[0].x1 for s in samples])
    bal_x1 = med([s[1][-1].x1 for s in samples])
    bal_x0 = med([s[1][-1].x0 for s in samples])
    two = [s[1][-2] for s in samples if len(s[1]) >= 2]
    cols = {"date": Col("date", date_x0, date_x1), "balance": Col("balance", bal_x0, bal_x1)}
    if two:
        cols["amount"] = Col("amount", med([c.x0 for c in two]), med([c.x1 for c in two]))
    cols["narration"] = Col("narration", date_x1 + 4, date_x1 + 40)
    return ColumnModel(cols, 0, 0, lines[0].page, width)


def extract(pages: list[PageWords]) -> Extracted:
    out = Extracted()
    model: ColumnModel | None = None
    for page in pages:
        lines = group_lines(page.words, page.number)
        out.all_lines.extend(lines)
        found = find_header(lines, page.width)
        if found:
            model, idx, span = found
            if out.model is None:
                out.header_lines.extend(lines[:idx])
                out.model = model
            out.table_headers.extend(lines[idx: idx + span])
            data = lines[idx + span:]
        elif model is None:
            guess = _headerless_model(lines, page.width)
            if guess is None:
                out.header_lines.extend(lines)
                continue
            model = out.model = guess
            out.headerless = True
            data = lines
        else:
            data = lines
        _PageParser(model, page, out).run(data)
    if out.model is None:
        out.warnings.append("Couldn't find the transaction table (no header row with Date and Balance).")
    return out


def summary_values(lines: list[Line], skip: list[Line] | None = None) -> dict[str, int]:
    """Opening/closing balance from summary boxes: 'Opening Balance: 1,000.00' or a label row over a value row."""
    found: dict[str, int] = {}
    keys = {
        "opening": re.compile(r"^(opening\s*bal(ance)?|op\.?\s*bal(ance)?|balance\s*b\s*/\s*f|"
                              r"balance\s*as\s*(on|of)\b.*\d{2,4}\s*:)", re.I),
        "closing": re.compile(r"^(closing\s*bal(ance)?|cl\.?\s*bal(ance)?|balance\s*c\s*/\s*f)\b", re.I),
    }
    skip_ids = {id(x) for x in (skip or [])}
    for i, ln in enumerate(lines):
        if id(ln) in skip_ids:
            continue
        for ci, cell in enumerate(ln.cells):
            text = norm_space(cell.text)
            for key, rx in keys.items():
                if key in found or not rx.match(text):
                    continue
                # value in the same cell: 'Opening Balance : 12,345.00 Cr'
                m = re.search(r"(?::|\s)\s*(-?\s*(?:₹|rs\.?|inr)?\s*[\d,]+\.\d{2}\s*(?:\(?(?:cr|dr)\)?)?)\s*$", text, re.I)
                if m and parse_amount(m.group(1).strip()):
                    found[key] = parse_amount(m.group(1).strip()).signed()
                    continue
                # value in the next cell(s) of the same line
                for nxt in ln.cells[ci + 1: ci + 3]:
                    a = parse_amount(nxt.text.replace(":", "").strip(), require_decimals=True)
                    if a:
                        found[key] = a.signed()
                        break
                if key in found:
                    continue
                # value in the line below, under the label
                if i + 1 < len(lines):
                    below = lines[i + 1]
                    best = None
                    for c in below.cells:
                        a = parse_amount(c.text.strip(), require_decimals=True)
                        if not a:
                            continue
                        dist = abs(c.cx - cell.cx)
                        if best is None or dist < best[0]:
                            best = (dist, a)
                    if best and best[0] < max(60.0, (cell.x1 - cell.x0) * 1.5):
                        found[key] = best[1].signed()
    return found


def parse_period(text: str):
    m = re.search(
        r"(?:from|period|statement\s*period|for\s*the\s*period)\s*[:\-]?\s*(?:from\s*)?"
        r"(\d{1,2}[\s/\-.][A-Za-z0-9]{1,9}[\s/\-.,]+\d{2,4})\s*(?:to|till|-|–)\s*[:\-]?\s*"
        r"(\d{1,2}[\s/\-.][A-Za-z0-9]{1,9}[\s/\-.,]+\d{2,4})",
        text, re.I)
    if not m:
        return None, None
    return parse_date(m.group(1)), parse_date(m.group(2))
