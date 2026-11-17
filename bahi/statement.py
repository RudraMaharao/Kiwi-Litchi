"""Parse any statement file and check every row against the running balance.

The balance check is what makes the output trustworthy: each row's balance
must equal the previous balance plus the credit or minus the debit. When it
does, the row was read correctly, and it also tells us whether the money
went in or out, even when the columns were ambiguous.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from . import pdfparse, pdftext, tabular
from .banks import detect_account, detect_bank
from .pdfparse import RawRow
from .util import norm_space, rupees

CHECK_OK = {"ok", "flipped", "corrected"}


@dataclass
class Txn:
    seq: int
    date: dt.date
    narration: str
    amount: int  # paise, always >= 0
    direction: str | None  # debit (money out) | credit (money in) | None
    balance: int | None
    value_date: dt.date | None = None
    ref: str = ""
    check: str = ""  # ok | flipped | corrected | mismatch | unchecked | nobalance
    note: str = ""
    page: int = 0

    @property
    def debit(self) -> int:
        return self.amount if self.direction == "debit" else 0

    @property
    def credit(self) -> int:
        return self.amount if self.direction == "credit" else 0

    def signed(self) -> int:
        return self.amount if self.direction == "credit" else -self.amount


@dataclass
class Statement:
    source: str
    txns: list[Txn] = field(default_factory=list)
    bank: str = ""
    account_no: str = ""
    period_from: dt.date | None = None
    period_to: dt.date | None = None
    opening: int | None = None
    closing: int | None = None
    printed_opening: int | None = None
    printed_closing: int | None = None
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
    reversed: bool = False
    ocr_confidence: float | None = None

    @property
    def flagged(self) -> list[Txn]:
        return [t for t in self.txns if t.check not in CHECK_OK]

    @property
    def status(self) -> str:
        if not self.txns:
            return "empty"
        if all(t.check == "nobalance" for t in self.txns):
            return "unverified"
        bad = [t for t in self.txns if t.check in ("mismatch", "nobalance", "datecheck") or t.direction is None]
        if bad:
            return "partial"
        if self.printed_closing is not None and self.closing is not None and self.printed_closing != self.closing:
            return "partial"
        return "verified"

    def totals(self) -> tuple[int, int]:
        return sum(t.debit for t in self.txns), sum(t.credit for t in self.txns)

    def summary(self) -> str:
        dr, cr = self.totals()
        return (f"{len(self.txns)} rows, {self.status}; opening {rupees(self.opening)}, "
                f"debits {rupees(dr)}, credits {rupees(cr)}, closing {rupees(self.closing)}")


# ------------------------------------------------------------- balance chain

def _sign(amount: int, direction: str | None) -> int:
    return amount if direction == "credit" else -amount


def _chain(rows: list[RawRow], opening: int | None, ocr: bool) -> tuple[list[Txn], int]:
    """Validate rows in order. Returns (txns, number of rows that check out)."""
    txns: list[Txn] = []
    prev = opening
    good = 0
    for i, r in enumerate(rows):
        t = Txn(i + 1, r.date, r.narration, r.amount, r.direction, r.balance, r.value_date, r.ref, page=r.page)
        if r.notes:
            t.note = "; ".join(r.notes)
        if r.balance is None:
            t.check = "nobalance"
            prev = prev + _sign(r.amount, r.direction) if (prev is not None and r.direction) else None
            txns.append(t)
            continue
        if prev is None:
            t.check = "unchecked"
            prev = r.balance
            txns.append(t)
            continue
        delta = r.balance - prev
        if r.amount == 0 and delta == 0:
            t.check = "ok"
        elif delta == r.amount and r.amount:
            t.check = "ok" if r.direction in (None, "credit") else "flipped"
            t.direction = "credit"
        elif delta == -r.amount and r.amount:
            t.check = "ok" if r.direction in (None, "debit") else "flipped"
            t.direction = "debit"
        else:
            t.check = "mismatch"
            if ocr:
                nxt = rows[i + 1] if i + 1 < len(rows) else None
                if nxt is not None and nxt.balance is not None and abs(nxt.balance - r.balance) == nxt.amount and delta:
                    # the balance agrees with the next row, so the amount was misread
                    t.amount = abs(delta)
                    t.direction = "credit" if delta > 0 else "debit"
                    t.check = "corrected"
                    t.note = f"amount read as {rupees(r.amount)}; fixed from the balances"
                elif nxt is not None and nxt.balance is not None and r.direction:
                    expected = prev + _sign(r.amount, r.direction)
                    if abs(nxt.balance - expected) == nxt.amount:
                        t.balance = expected
                        t.check = "corrected"
                        t.note = f"balance read as {rupees(r.balance)}; fixed from the amounts"
            if t.check == "mismatch":
                t.note = (f"balance moved by {rupees(delta, sign=True)} but the row says "
                          f"{rupees(r.amount)}: a row may be missing or misread")
        if t.check in CHECK_OK:
            good += 1
        prev = t.balance
        txns.append(t)
    return txns, good


def _first_row(txns: list[Txn], opening: int | None) -> int | None:
    """The first row can only be checked against the opening balance."""
    if not txns:
        return opening
    first = txns[0]
    if first.check != "unchecked":
        return opening
    if opening is not None and first.balance is not None:
        delta = first.balance - opening
        if delta == first.amount and first.amount:
            first.check = "ok" if first.direction in (None, "credit") else "flipped"
            first.direction = "credit"
        elif delta == -first.amount and first.amount:
            first.check = "ok" if first.direction in (None, "debit") else "flipped"
            first.direction = "debit"
        elif first.amount == 0 and delta == 0:
            first.check = "ok"
        else:
            first.check = "mismatch"
            first.note = "doesn't match the opening balance printed on the statement"
        return opening
    if first.direction and first.balance is not None:
        first.check = "ok"
        first.note = "first row: checked by the column it was in"
        return first.balance - _sign(first.amount, first.direction)
    return None


def _check_ocr_dates(txns: list[Txn]) -> None:
    """The balance check can't see a misread date (5 read as 8), but statements run in date order:
    a date out of step with both neighbours is suspect, and fixable when the neighbours agree."""
    for i in range(1, len(txns) - 1):
        prev, cur, nxt = txns[i - 1].date, txns[i].date, txns[i + 1].date
        if prev <= cur <= nxt or prev > nxt:
            continue
        t = txns[i]
        read = cur.strftime("%d %b")
        if prev == nxt:
            t.date = prev
            if t.value_date and t.value_date < prev:
                t.value_date = prev
            t.check = "corrected" if t.check in CHECK_OK else t.check
            t.note = (t.note + "; " if t.note else "") + f"date read as {read}; set to {prev:%d %b} from the rows around it"
        else:
            if t.check in CHECK_OK:
                t.check = "datecheck"
            t.note = (t.note + "; " if t.note else "") + (
                f"date read as {read} but the rows around it are {prev:%d %b} and {nxt:%d %b}: check it")


def finalize(rows: list[RawRow], printed_opening: int | None, printed_closing: int | None,
             source: str) -> tuple[list[Txn], int | None, int | None, bool, list[str]]:
    warnings: list[str] = []
    rows = [r for r in rows if r.date is not None]
    if not rows:
        return [], printed_opening, printed_closing, False, warnings
    ocr = source.endswith("ocr")
    inc = sum(1 for a, b in zip(rows, rows[1:]) if b.date > a.date)
    dec = sum(1 for a, b in zip(rows, rows[1:]) if b.date < a.date)
    candidates = [False, True] if dec >= inc else [False]
    best = None
    for rev in candidates:
        ordered = rows[::-1] if rev else rows
        opening = printed_opening
        txns, good = _chain(ordered, None, ocr)
        score = good + (1 if (rev and dec > inc) or (not rev and inc >= dec) else 0) * 0.5
        if best is None or score > best[0]:
            best = (score, rev, ordered, txns)
    _, rev, ordered, txns = best
    opening = _first_row(txns, printed_opening)
    if ocr:
        _check_ocr_dates(txns)
    if opening is None and txns and txns[0].balance is not None and txns[0].direction is None:
        warnings.append("The first row's direction couldn't be checked: there is no opening balance on the statement.")
    closing = txns[-1].balance if txns and txns[-1].balance is not None else printed_closing
    if printed_opening is not None and opening is not None and printed_opening != opening:
        warnings.append(f"Opening balance printed on the statement ({rupees(printed_opening)}) differs from the one "
                        f"worked out from the rows ({rupees(opening)}).")
    if printed_closing is not None and closing is not None and printed_closing != closing:
        warnings.append(f"Closing balance printed on the statement ({rupees(printed_closing)}) differs from the last "
                        f"row's balance ({rupees(closing)}). A row may be missing.")
    if opening is not None and closing is not None and all(t.direction for t in txns):
        net = sum(t.signed() for t in txns)
        if all(t.balance is not None for t in txns) and opening + net != closing:
            warnings.append("Debits and credits don't add up from the opening to the closing balance.")
    mism = sum(1 for t in txns if t.check == "mismatch")
    if mism:
        warnings.append(f"{mism} row(s) don't match the running balance. Check them before posting.")
    unknown = sum(1 for t in txns if t.direction is None)
    if unknown:
        warnings.append(f"{unknown} row(s) have no clear debit or credit. Set them before posting.")
    return txns, opening, closing, rev, warnings


# ------------------------------------------------------------- entry point

def _meta_from_text(st: Statement, header_text: str):
    st.bank = st.bank or detect_bank(header_text)
    st.account_no = st.account_no or detect_account(header_text)
    if st.period_from is None:
        st.period_from, st.period_to = pdfparse.parse_period(header_text)


def parse_file(path: Path, password: str | None = None, ocr_settings: dict | None = None,
               progress=None) -> Statement:
    path = Path(path)
    kind = tabular.sniff(path)
    if kind in ("pdf", "image"):
        if kind == "pdf":
            pages = pdftext.read_pdf(path, password, ocr=True, ocr_settings=ocr_settings, progress=progress)
        else:
            pages = pdftext.read_image(path, ocr_settings)
        ocr_pages = [p for p in pages if p.source == "ocr"]
        source = "pdf-text" if not ocr_pages else ("image-ocr" if kind == "image" else "pdf-ocr")
        ex = pdfparse.extract(pages)
        st = Statement(source=source, pages=len(pages))
        if ocr_pages:
            confs = [p.ocr_confidence for p in ocr_pages if p.ocr_confidence is not None]
            st.ocr_confidence = round(sum(confs) / len(confs), 1) if confs else None
        header_text = "\n".join(ln.text for ln in ex.header_lines)
        _meta_from_text(st, header_text)
        sv = pdfparse.summary_values(ex.header_lines + ex.all_lines, skip=ex.table_headers)
        st.printed_opening = ex.openings[0] if ex.openings else sv.get("opening")
        st.printed_closing = ex.closings[-1] if ex.closings else sv.get("closing")
        raw = ex.rows
        st.warnings.extend(ex.warnings)
        if ex.headerless and raw:
            st.warnings.append("No header row found: columns were worked out from the numbers.")
    else:
        rows, src = tabular.read_rows(path)
        table = tabular.parse_rows(rows)
        raw = table.rows
        st = Statement(source=src, pages=1)
        header_text = "\n".join(table.pre)
        _meta_from_text(st, header_text)
        st.printed_opening = table.openings[0] if table.openings else None
        st.printed_closing = table.closings[-1] if table.closings else None
        if st.printed_opening is None or st.printed_closing is None:
            from .layout import Cell, Line

            fake = [Line([Cell(norm_space(str(v)), j * 100.0, j * 100.0 + 90, i * 10.0, i * 10.0 + 8)
                          for j, v in enumerate(r) if v not in (None, "")], i * 10.0, i * 10.0 + 8, 1)
                    for i, r in enumerate(rows) if i != table.header_index and any(v not in (None, "") for v in r)]
            sv = pdfparse.summary_values(fake)
            st.printed_opening = st.printed_opening if st.printed_opening is not None else sv.get("opening")
            st.printed_closing = st.printed_closing if st.printed_closing is not None else sv.get("closing")
        st.warnings.extend(table.warnings)
    txns, opening, closing, rev, warns = finalize(raw, st.printed_opening, st.printed_closing, st.source)
    st.txns, st.opening, st.closing, st.reversed = txns, opening, closing, rev
    st.warnings.extend(warns)
    if txns and st.period_from is None:
        st.period_from, st.period_to = txns[0].date, txns[-1].date
    if st.source.endswith("ocr"):
        st.warnings.insert(0, "Read with OCR from a scan or photo. Rows that pass the balance check are reliable; "
                              "check the narrations by eye.")
    return st
