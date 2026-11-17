"""Import, learn, post and export: the whole flow on the demo client."""

import json
import xml.etree.ElementTree as ET

import pytest

from bahi import db, exports, service
from bahi.mapping import ClientContext, Ledger, Mapper, OwnAccount, Rule
from bahi.narration import parse

from .conftest import SAMPLES


def _demo(conn, cfg):
    cid = service.load_demo(conn, cfg)
    return cid, db.txns(conn, cid)


def test_demo_import_suggests_most_ledgers(conn, cfg):
    cid, rows = _demo(conn, cfg)
    counts = db.counts(conn, cid)
    assert len(rows) == 47
    assert counts["ready"] >= 30 and counts.get("review", 0) <= 17
    by_party = {r["party"]: r for r in rows}
    assert by_party["Mehta And Sons"]["ledger"] == "Mehta & Sons"  # '&' and 'and' match
    own = [r for r in rows if r["map_source"] == "own"]
    assert own and own[0]["ledger"] == "Sample Bank Current A/c 7766"
    cash = [r for r in rows if r["category"] == "cash_withdrawal"]
    assert cash and all(r["ledger"] == "Cash" for r in cash)


def test_same_file_twice_is_refused(conn, cfg):
    cid, _ = _demo(conn, cfg)
    with pytest.raises(service.AlreadyImported):
        service.import_statement(conn, cfg, cid, SAMPLES / "layout_a.pdf")


def test_overlapping_statement_rows_marked_duplicate(conn, cfg):
    cid, _ = _demo(conn, cfg)
    out = service.import_statement(conn, cfg, cid, SAMPLES / "excel_layout_a.xlsx")  # same rows, other format
    assert out.duplicates == out.rows


def test_learning_fills_the_same_party(conn, cfg):
    cid, rows = _demo(conn, cfg)
    jain = [r for r in rows if r["party"] == "Jain Hardware Stores"]
    assert len(jain) >= 3 and all(r["map_source"] == "suspense" for r in jain)
    n, similar = service.set_ledger(conn, cid, [jain[0]["id"]], "Jain Hardware Stores")
    assert (n, similar) == (1, len(jain) - 1)
    assert db.memory(conn, cid)["party:jain hardware stores"] == "Jain Hardware Stores"
    # next month's statement for the same client remembers it
    out = service.import_statement(conn, cfg, cid, SAMPLES / "layout_a_newest_first.pdf")
    later = [r for r in db.txns(conn, cid, statement_id=out.statement_id) if r["party"] == "Jain Hardware Stores"]
    assert later and all(r["ledger"] == "Jain Hardware Stores" and r["map_source"] == "memory" for r in later)


def test_rule_beats_everything(conn, cfg):
    cid, _ = _demo(conn, cfg)
    db.add_rule(conn, cid, "AMAZON", "Office Expenses", "debit")
    service.remap(conn, cid)
    amazon = [r for r in db.txns(conn, cid) if "AMAZON" in r["narration"]]
    assert amazon and all(r["ledger"] == "Office Expenses" and r["status"] == "ready" for r in amazon)


def test_post_to_tally_creates_ledgers_and_vouchers(conn, cfg, tally):
    cid, rows = _demo(conn, cfg)
    jain = [r for r in rows if r["party"] == "Jain Hardware Stores"]
    service.set_ledger(conn, cid, [jain[0]["id"]], "Jain Hardware Stores")
    plan = service.plan_vouchers(conn, cfg, cid)
    assert "Jain Hardware Stores" in plan.new_ledgers
    out = service.post_to_tally(conn, cfg, cid)
    assert out.failed == 0 and out.posted == len(plan.specs)
    assert "Jain Hardware Stores" in out.ledgers_created
    company = tally.companies["Sharma Traders (Demo)"]
    assert len(company.vouchers) == out.posted
    types = {v["type"] for v in company.vouchers}
    assert types == {"Payment", "Receipt", "Contra"}
    assert db.counts(conn, cid).get("ready", 0) == 0
    # nothing is posted twice
    with pytest.raises(service.NothingFound):
        service.post_to_tally(conn, cfg, cid)


def test_failed_vouchers_stay_ready_with_the_reason(conn, cfg, tally):
    cid, _ = _demo(conn, cfg)
    s = db.client_settings(conn, cid)
    s["voucher_types"] = {"payment": "Bank Payment", "receipt": "Receipt", "contra": "Contra"}
    db.save_client_settings(conn, cid, s)
    out = service.post_to_tally(conn, cfg, cid)
    assert out.failed > 0
    stuck = db.txns(conn, cid, status="ready")
    assert stuck and all("Voucher Type" in r["post_error"] for r in stuck)


def test_export_xml_and_undo(conn, cfg):
    cid, _ = _demo(conn, cfg)
    ready = db.counts(conn, cid)["ready"]
    out = service.export_xml(conn, cfg, cid)
    assert out.vouchers == ready and out.files[-1].name.endswith("vouchers.xml")
    root = ET.fromstring(out.files[-1].read_bytes())
    assert len(root.findall(".//VOUCHER")) == ready
    assert db.counts(conn, cid).get("exported") == ready
    assert service.undo_batch(conn, cid, out.batch_id) == ready
    assert db.counts(conn, cid)["ready"] == ready


def test_missing_bank_ledger_blocks_posting(conn, cfg):
    cid = db.add_client(conn, "No Ledger Co")
    service.import_statement(conn, cfg, cid, SAMPLES / "layout_b.pdf")
    service.set_status(conn, cid, [r["id"] for r in db.txns(conn, cid)], "approve")
    with pytest.raises(service.SetupNeeded, match="bank ledger"):
        service.export_xml(conn, cfg, cid)


def test_locked_pdf_password_is_remembered(conn, cfg):
    cid = db.add_client(conn, "Locked Co")
    with pytest.raises(service.PasswordRequired):
        service.import_statement(conn, cfg, cid, SAMPLES / "layout_b_locked.pdf")
    out = service.import_statement(conn, cfg, cid, SAMPLES / "layout_b_locked.pdf", password="sharma123")
    assert db.account(conn, out.account_id)["pdf_password"] == "sharma123"


def test_excel_workbook(conn, cfg):
    cid, _ = _demo(conn, cfg)
    from openpyxl import load_workbook
    import io

    wb = load_workbook(io.BytesIO(exports.workbook(conn, cid)))
    ws = wb["Transactions"]
    assert ws.max_row == 48 and ws["A1"].value == "Date"


def test_mapper_order_and_fuzzy_match():
    ctx = ClientContext(
        client_name="Sharma Traders",
        ledgers={"Gupta Electricals": Ledger("Gupta Electricals", "Sundry Debtors", "debtor"),
                 "HDFC 5678": Ledger("HDFC 5678", "Bank Accounts", "bank"),
                 "Bank Charges": Ledger("Bank Charges", "Indirect Expenses", "expense")},
        rules=[Rule("SWIGGY", "Staff Welfare")],
        memory={"vpa:rahul@ybl": "Advance to Staff"},
        own_accounts=[OwnAccount(1, "HDFC 5678", "50100012345678", "HDFC 5678"),
                      OwnAccount(2, "SBI 1111", "30111111111", "SBI 1111")])
    m = Mapper(ctx)
    n = "UPI-SWIGGY-swiggy@axb-UTIB0000123-612345678901-PAY"
    assert m.suggest(n, "debit", parse(n)).source == "rule"
    n = "UPI-RAHUL-rahul@ybl-YESB0000123-612345678902-PAY"
    assert m.suggest(n, "debit", parse(n)).ledger == "Advance to Staff"
    n = "NEFT CR-HDFC0000001-GUPTA ELECTRICAL-SHARMA TRADERS-HDFCN52026"
    sug = m.suggest(n, "credit", parse(n))
    assert sug.ledger == "Gupta Electricals" and sug.source == "match"
    n = "IB FUNDS TRANSFER DR-50100012345678-SHARMA TRADERS"
    sug = m.suggest(n, "debit", parse(n), account_id=2)
    assert sug.ledger == "HDFC 5678" and m.voucher_role(sug.ledger, "debit") == "contra"
    sug = m.suggest(n, "credit", parse(n), account_id=2)
    assert sug.skip  # money in from own account: posted from the other side
    n = "SMS CHGS APR26"
    assert m.suggest(n, "debit", parse(n)).ledger == "Bank Charges"
    n = "UPI-UNKNOWN PERSON-unknown@ybl-YESB0000123-612345678903-PAY"
    assert m.suggest(n, "debit", parse(n)).source == "suspense"


def test_settings_merge_keeps_defaults():
    from bahi.mapping import merged_settings

    s = merged_settings({"category_ledgers": {"tax_gst": "GST Cash Ledger"}})
    assert s["category_ledgers"]["tax_gst"] == "GST Cash Ledger"
    assert s["category_ledgers"]["bank_charges"] == "Bank Charges"
    assert json.dumps(s)


def test_fresh_tally_company_gets_every_missing_ledger(conn, cfg, tally):
    """A new company in Tally has only Cash: banks, parties, tax and suspense ledgers are created in the right groups."""
    from bahi import tallymock

    tally.companies["Sharma Traders (Demo)"] = tallymock.Company("Sharma Traders (Demo)")
    cid, rows = _demo(conn, cfg)
    service.fetch_ledgers(conn, cfg, cid)
    service.set_status(conn, cid, [r["id"] for r in db.txns(conn, cid) if r["status"] == "review"], "approve")
    plan = service.plan_vouchers(conn, cfg, cid)
    assert plan.new_ledgers["Sample Bank A/c 5678"] == "Bank Accounts"
    assert plan.new_ledgers["Sample Bank Current A/c 7766"] == "Bank Accounts"
    assert plan.new_ledgers["GST Cash Ledger"] == "Duties & Taxes"
    assert plan.new_ledgers["Suspense A/c"] == "Suspense A/c"
    out = service.post_to_tally(conn, cfg, cid)
    assert out.failed == 0 and out.posted == len(plan.specs)
    company = tally.companies["Sharma Traders (Demo)"]
    assert company.ledgers["Interest Received"] == "Indirect Incomes"
    assert company.ledgers["Suspense A/c"] == "Suspense A/c"  # unknown parties wait in suspense
