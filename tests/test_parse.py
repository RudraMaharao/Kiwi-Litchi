"""Every sample statement must come out exactly right: dates, amounts, directions, balances."""

import datetime as dt

import pytest

from bahi import pdftext
from bahi.statement import CHECK_OK, parse_file

from .conftest import SAMPLES, expected, has_tesseract

TEXT_SAMPLES = ["layout_a", "layout_b", "layout_c", "layout_d", "layout_a_newest_first",
                "excel_layout_a", "html_disguised_as", "csv_amount_type"]
FILES = {p.stem: p for p in SAMPLES.iterdir() if p.is_file()}


def _money(rows, txns):
    return sum(1 for e, t in zip(rows, txns)
               if (e["date"], e["amount"], e["direction"], e["balance"]) ==
               (t.date.isoformat(), t.amount, t.direction, t.balance))


@pytest.mark.parametrize("name", TEXT_SAMPLES)
def test_text_statements_exact(name):
    exp = expected(name)
    st = parse_file(FILES[name])
    assert len(st.txns) == len(exp["rows"])
    assert _money(exp["rows"], st.txns) == len(exp["rows"])
    # a line that ends exactly at the column edge can be a word wrap or a cut word: allow the odd one
    exact = sum(1 for e, t in zip(exp["rows"], st.txns) if e["narration"] == t.narration)
    assert exact >= 0.95 * len(exp["rows"])
    assert st.status == "verified", st.warnings
    assert st.opening == exp["opening"]
    assert st.closing == exp["closing"]
    assert all(t.check in CHECK_OK for t in st.txns)


def test_metadata_and_period():
    st = parse_file(FILES["layout_a"])
    assert st.account_no == "50100012345678"
    assert (st.period_from, st.period_to) == (dt.date(2026, 4, 1), dt.date(2026, 4, 30))
    assert st.printed_closing == st.closing  # read from the label-over-value summary box


def test_newest_first_is_reordered():
    st = parse_file(FILES["layout_a_newest_first"])
    assert st.reversed
    assert [t.date for t in st.txns] == sorted(t.date for t in st.txns)


def test_overdraft_balances_with_dr_suffix():
    st = parse_file(FILES["layout_d"])
    assert min(t.balance for t in st.txns) < 0
    assert st.closing == expected("layout_d")["closing"]


def test_locked_pdf_needs_password():
    with pytest.raises(pdftext.PasswordRequired):
        parse_file(FILES["layout_b_locked"])
    with pytest.raises(pdftext.WrongPassword):
        parse_file(FILES["layout_b_locked"], password="nope")
    st = parse_file(FILES["layout_b_locked"], password="sharma123")
    assert len(st.txns) == len(expected("layout_b_locked")["rows"])
    assert st.status == "verified"


@pytest.mark.skipif(not has_tesseract(), reason="Tesseract not installed")
@pytest.mark.parametrize("name", ["layout_a_scanned", "layout_a_photo_page1"])
def test_scans_and_photos(name):
    exp = expected(name)
    st = parse_file(FILES[name])
    assert st.source.endswith("ocr")
    assert len(st.txns) == len(exp["rows"])
    assert _money(exp["rows"], st.txns) == len(exp["rows"])
    assert st.status == "verified"


def test_balance_chain_flags_a_missing_row():
    from bahi.pdfparse import RawRow
    from bahi.statement import finalize

    d = dt.date(2026, 4, 1)
    rows = [RawRow(d, amount=10000, direction="credit", balance=110000),
            RawRow(d, amount=5000, direction="debit", balance=105000),
            # a 2,000 debit is missing here
            RawRow(d, amount=1000, direction="debit", balance=102000)]
    txns, opening, closing, _, warnings = finalize(rows, 100000, None, "pdf-text")
    assert [t.check for t in txns] == ["ok", "ok", "mismatch"]
    assert any("don't match" in w for w in warnings)


def test_balance_decides_direction_when_columns_lie():
    from bahi.pdfparse import RawRow
    from bahi.statement import finalize

    d = dt.date(2026, 4, 2)
    rows = [RawRow(d, amount=10000, direction="debit", balance=110000)]  # balance went up: it's a credit
    txns, *_ = finalize(rows, 100000, None, "pdf-text")
    assert txns[0].direction == "credit" and txns[0].check == "flipped"


def test_ocr_amount_fixed_from_balances():
    from bahi.pdfparse import RawRow
    from bahi.statement import finalize

    d = dt.date(2026, 4, 3)
    rows = [RawRow(d, amount=10000, direction="credit", balance=110000),
            RawRow(d, amount=8000, direction="debit", balance=105000),  # really 5,000: OCR misread
            RawRow(d, amount=1000, direction="debit", balance=104000)]
    txns, *_ = finalize(rows, 100000, None, "pdf-ocr")
    assert txns[1].check == "corrected" and txns[1].amount == 5000


def test_ocr_date_out_of_order_is_fixed():
    from bahi.pdfparse import RawRow
    from bahi.statement import finalize

    d15, d18 = dt.date(2026, 4, 15), dt.date(2026, 4, 18)
    rows = [RawRow(d15, amount=100, direction="credit", balance=1100),
            RawRow(d18, amount=100, direction="credit", balance=1200),
            RawRow(d15, amount=100, direction="credit", balance=1300)]
    txns, *_ = finalize(rows, 1000, None, "image-ocr")
    assert txns[1].date == d15 and "date read as" in txns[1].note


def test_excel_header_split_over_two_rows():
    from bahi.tabular import parse_rows

    rows = [["Statement of account"], ["Date", "Narration", "Amount", "", "Balance"], ["", "", "Debit", "Credit", ""],
            ["01/04/2026", "UPI-A-a@ybl-1", "100.00", "", "900.00"], ["02/04/2026", "NEFT CR-B", "", "50.00", "950.00"]]
    t = parse_rows(rows)
    assert [(r.amount, r.direction) for r in t.rows] == [(10000, "debit"), (5000, "credit")]
