"""Statements downloaded as Excel, CSV, tab-separated text or HTML tables.

Many banks offer an 'Excel' download that is really an HTML page or a text
file with an .xls name, so files are sniffed by content, not by extension.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .layout import match_role
from .pdfparse import CLOSING_RE, OPENING_RE, RawRow
from .util import amount_from_number, norm_space, parse_amount, parse_date


class TableFileError(Exception):
    pass


def sniff(path: Path) -> str:
    head = Path(path).read_bytes()[:4096]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        return "xlsx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "xls"
    if head[:3] == b"\xff\xd8\xff" or head.startswith(b"\x89PNG") or head[:4] in (b"II*\x00", b"MM\x00*") \
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image"
    text = head.decode("utf-8", "ignore").lstrip("﻿ \r\n\t").lower()
    if text.startswith("<") and ("<table" in text or "<html" in text or "<!doctype" in text):
        return "html"
    if b"\x00" in head[:200]:
        try:
            if "<table" in head.decode("utf-16", "ignore").lower():
                return "html16"
        except Exception:
            pass
    return "text"


class _HTMLTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(norm_space("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(c for c in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and "\x00" in text[:50]:
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def read_rows(path: Path) -> tuple[list[list], str]:
    kind = sniff(path)
    data = Path(path).read_bytes()
    if kind == "xlsx":
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise TableFileError(f"Couldn't open this Excel file ({exc}). If it is password-protected, "
                                 "save an unlocked copy first.") from exc
        best: list[list] = []
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(v not in (None, "") for v in r)]
            if len(rows) > len(best):
                best = rows
        wb.close()
        return best, "excel"
    if kind == "xls":
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as exc:
            raise TableFileError(f"Couldn't open this .xls file ({exc}).") from exc
        best = []
        for sh in book.sheets():
            rows = []
            for r in range(sh.nrows):
                vals = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            vals.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                        except Exception:
                            vals.append(cell.value)
                    else:
                        vals.append(cell.value)
                if any(v not in (None, "") for v in vals):
                    rows.append(vals)
            if len(rows) > len(best):
                best = rows
        return best, "excel"
    if kind in ("html", "html16"):
        text = data.decode("utf-16", "replace") if kind == "html16" else _decode(data)
        p = _HTMLTable()
        p.feed(text)
        return p.rows, "html"
    if kind == "text":
        text = _decode(data)
        sample = text[:5000]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            delim = dialect.delimiter
        except csv.Error:
            delim = "\t" if sample.count("\t") > sample.count(",") else ","
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
        return rows, "csv"
    raise TableFileError("Not a table file.")


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return norm_space(str(v))


def _money(v) -> tuple[int | None, str | None]:
    """Cell -> (paise, 'CR'/'DR'/None). Numbers keep their sign."""
    if v is None or v == "":
        return None, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return amount_from_number(v), None
    a = parse_amount(str(v))
    if a is None:
        return None, None
    return (-a.paise if a.negative else a.paise), a.drcr


def _header_roles(cells: list[str]) -> dict[str, int]:
    roles: dict[str, int] = {}
    for j, text in enumerate(cells):
        role = match_role(text)
        if role == "date" and "date" in roles:
            role = "value_date" if "value_date" not in roles else None
        if role and role not in roles:
            roles[role] = j
    return roles


def find_table_header(rows: list[list]) -> tuple[int, dict[str, int]] | None:
    """The header row, or two rows read together when the header is split ('Amount' over 'Debit | Credit')."""
    best = None
    for i, row in enumerate(rows[:120]):
        texts = [_cell_text(v) for v in row]
        candidates = [(i, _header_roles(texts))]
        if i + 1 < len(rows):
            below = [_cell_text(v) for v in rows[i + 1]]
            width = max(len(texts), len(below))
            merged = []
            for j in range(width):
                a = texts[j] if j < len(texts) else ""
                b = below[j] if j < len(below) else ""
                if b and match_role(b):
                    merged.append(b)  # 'Debit' under a group label 'Amount'
                elif a and (match_role(a) or not b):
                    merged.append(a)
                else:
                    merged.append(f"{a} {b}".strip())
            candidates.append((i + 1, _header_roles(merged)))
        for idx, roles in candidates:
            if "date" not in roles and "value_date" in roles:
                roles["date"] = roles.pop("value_date")
            money = set(roles) & {"debit", "credit", "amount", "balance"}
            if "date" in roles and money and len(set(roles) & {"narration", "debit", "credit", "amount", "balance"}) >= 2:
                if best is None or len(roles) > len(best[1]):
                    best = (idx, roles)
    return best


@dataclass
class TableResult:
    rows: list[RawRow]
    pre: list[str]  # text above the table (bank, account, period)
    openings: list[int]
    closings: list[int]
    warnings: list[str]
    header_index: int = -1


def parse_rows(rows: list[list]) -> TableResult:
    found = find_table_header(rows)
    if not found:
        return TableResult([], [" ".join(_cell_text(v) for v in r) for r in rows[:40]], [], [], [
            "Couldn't find the header row (Date, Narration, Debit/Credit, Balance) in this file."])
    hi, roles = found
    pre = [" ".join(_cell_text(v) for v in r if _cell_text(v)) for r in rows[:hi]]
    out: list[RawRow] = []
    openings, closings, warnings = [], [], []

    def get(row, role):
        j = roles.get(role)
        return row[j] if j is not None and j < len(row) else None

    for n, row in enumerate(rows[hi + 1:], start=hi + 2):
        d = parse_date(get(row, "date"))
        narr = _cell_text(get(row, "narration"))
        if d is None:
            joined = " ".join(_cell_text(v) for v in row if _cell_text(v))
            if OPENING_RE.match(joined) or OPENING_RE.match(narr):
                bal, drcr = _money(get(row, "balance"))
                if bal is not None:
                    openings.append(-abs(bal) if drcr == "DR" else bal)
                continue
            if CLOSING_RE.match(joined) or CLOSING_RE.match(narr):
                bal, drcr = _money(get(row, "balance"))
                if bal is not None:
                    closings.append(-abs(bal) if drcr == "DR" else bal)
                continue
            if out and narr and not any(_money(get(row, r))[0] for r in ("debit", "credit", "amount")):
                out[-1].narration = norm_space(f"{out[-1].narration} {narr}")
                continue
            if re.match(r"^(total|grand total|\*+|end of statement)", joined, re.I) and out:
                break
            continue
        if OPENING_RE.match(narr):
            bal, drcr = _money(get(row, "balance"))
            if bal is not None:
                openings.append(-abs(bal) if drcr == "DR" else bal)
            continue
        if CLOSING_RE.match(narr):
            continue
        r = RawRow(date=d, value_date=parse_date(get(row, "value_date")), narration=narr,
                   ref=_cell_text(get(row, "ref")), page=n)
        dr, _ = _money(get(row, "debit"))
        cr, _ = _money(get(row, "credit"))
        amt, adrcr = _money(get(row, "amount"))
        if dr:
            r.amount, r.direction = abs(dr), "debit"
        elif cr:
            r.amount, r.direction = abs(cr), "credit"
        elif amt:
            r.amount = abs(amt)
            flag = _cell_text(get(row, "drcr")).upper()
            if adrcr:
                r.direction = "credit" if adrcr == "CR" else "debit"
            elif flag.startswith(("C", "DEP")):
                r.direction = "credit"
            elif flag.startswith(("D", "W")):
                r.direction = "debit"
            elif amt < 0:
                r.direction = "debit"
        bal, bdrcr = _money(get(row, "balance"))
        if bal is not None:
            r.balance = -abs(bal) if bdrcr == "DR" else bal
        out.append(r)
    return TableResult(out, pre, openings, closings, warnings, hi)


def is_date_like(v) -> bool:
    return isinstance(v, (dt.date, dt.datetime)) or parse_date(v) is not None
