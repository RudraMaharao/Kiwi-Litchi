"""Voucher XML signs, Tally's replies, and the simulator."""

import datetime as dt
import xml.etree.ElementTree as ET

from bahi import tally
from bahi.tally import VoucherSpec


def _spec(**kw):
    base = dict(date=dt.date(2026, 4, 3), vtype="Payment", bank_ledger="HDFC Bank", counter_ledger="Rent",
                amount=3500000, money_out=True, narration="NEFT DR-ANITA DESAI-RENT", instrument_no="N123",
                instrument_type="e-Fund Transfer", bank_date=dt.date(2026, 4, 4), favouring="Anita Desai")
    base.update(kw)
    return VoucherSpec(**base)


def _entries(xml):
    root = ET.fromstring(f"<X>{xml}</X>")
    return [(e.findtext("LEDGERNAME"), e.findtext("ISDEEMEDPOSITIVE"), e.findtext("AMOUNT"))
            for e in root.iter("ALLLEDGERENTRIES.LIST")]


def test_payment_signs():
    assert _entries(tally.voucher_xml(_spec())) == [("Rent", "Yes", "-35000.00"), ("HDFC Bank", "No", "35000.00")]


def test_receipt_signs():
    xml = tally.voucher_xml(_spec(vtype="Receipt", counter_ledger="Gupta & Sons", money_out=False))
    assert _entries(xml) == [("Gupta & Sons", "No", "35000.00"), ("HDFC Bank", "Yes", "-35000.00")]
    assert "Gupta &amp; Sons" in xml


def test_bank_allocation_carries_bank_date():
    root = ET.fromstring(f"<X>{tally.voucher_xml(_spec())}</X>")
    alloc = root.find(".//BANKALLOCATIONS.LIST")
    assert alloc.findtext("BANKERSDATE") == "20260404"
    assert alloc.findtext("TRANSACTIONTYPE") == "e-Fund Transfer"
    assert alloc.findtext("AMOUNT") == "35000.00"
    assert "BANKALLOCATIONS" not in tally.voucher_xml(_spec(), bank_allocations=False)


def test_envelope_is_valid_xml_and_targets_company():
    xml = tally.envelope([tally.voucher_xml(_spec(narration="<odd> & \x07chars"))], company="A & B Ltd")
    root = ET.fromstring(xml.encode("utf-8"))
    assert root.findtext(".//SVCURRENTCOMPANY") == "A & B Ltd"
    assert root.findtext(".//NARRATION") == "<odd> &  chars"


def test_edu_dates():
    assert tally.edu_date(dt.date(2026, 4, 17)) == dt.date(2026, 4, 2)
    assert tally.edu_date(dt.date(2026, 4, 9)) == dt.date(2026, 4, 1)
    assert tally.edu_date(dt.date(2026, 3, 31)) == dt.date(2026, 3, 31)


def test_reply_parsing_old_and_new_formats():
    r = tally.parse_import_reply("<RESPONSE><CREATED>1</CREATED><ALTERED>0</ALTERED><ERRORS>0</ERRORS>"
                                 "<LASTVCHID>77</LASTVCHID></RESPONSE>")
    assert r.ok and r.last_vch_id == "77"
    r = tally.parse_import_reply("<RESPONSE><LINEERROR>Ledger 'X' does not exist!</LINEERROR><CREATED>0</CREATED>"
                                 "<ERRORS>1</ERRORS></RESPONSE>")
    assert not r.ok and r.messages == ["Ledger 'X' does not exist!"]
    r = tally.parse_import_reply("<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>0</STATUS></HEADER><BODY><DATA>"
                                 "<STATUS.LIST><CODE>0</CODE><DESC>Company not found</DESC></STATUS.LIST></DATA>"
                                 "</BODY></ENVELOPE>")
    assert not r.ok and "Company not found" in r.messages


def test_collection_parsing_survives_tally_control_chars():
    reply = ('<ENVELOPE><BODY><DATA><COLLECTION><GROUP NAME="Sundry Debtors"><PARENT TYPE="String">Current Assets'
             '</PARENT></GROUP><GROUP NAME="Current Assets"><PARENT TYPE="String">&#4; Primary</PARENT></GROUP>'
             '</COLLECTION></DATA></BODY></ENVELOPE>')
    groups = tally.parse_collection(reply, "GROUP")
    parents = {g["name"]: g["parent"] for g in groups}
    assert tally.ancestors(parents, "Sundry Debtors") == ["Sundry Debtors", "Current Assets"]


def test_client_against_simulator(tally_sim=None):
    from bahi.tallymock import start_background

    server, mock = start_background()
    try:
        c = tally.TallyClient("127.0.0.1", server.server_address[1])
        assert "Running" in c.ping()
        assert c.companies() == ["Sharma Traders (Demo)"]
        leds, groups = c.ledgers("Sharma Traders (Demo)")
        assert any(l["name"] == "Cash" for l in leds) and len(groups) == 28
        spec = _spec(bank_ledger="Sample Bank A/c 5678", counter_ledger="Rent")
        assert c.import_xml(tally.envelope([tally.voucher_xml(spec)], company="Sharma Traders (Demo)")).ok
        bad = _spec(bank_ledger="Sample Bank A/c 5678", counter_ledger="Nobody")
        res = c.import_xml(tally.envelope([tally.voucher_xml(bad)], company="Sharma Traders (Demo)"))
        assert not res.ok and "does not exist" in res.messages[0]
        contra = _spec(vtype="Contra", bank_ledger="Sample Bank A/c 5678", counter_ledger="Rent")
        res = c.import_xml(tally.envelope([tally.voucher_xml(contra)], company="Sharma Traders (Demo)"))
        assert not res.ok  # Contra may only use cash and bank ledgers
    finally:
        server.shutdown()
        server.server_close()


def test_simulator_educational_mode():
    from bahi.tallymock import start_background

    server, mock = start_background(edu_mode=True)
    try:
        c = tally.TallyClient("127.0.0.1", server.server_address[1])
        spec = _spec(bank_ledger="Sample Bank A/c 5678", date=dt.date(2026, 4, 17))
        assert not c.import_xml(tally.envelope([tally.voucher_xml(spec)])).ok
        spec.date = tally.edu_date(spec.date)
        assert c.import_xml(tally.envelope([tally.voucher_xml(spec)])).ok
    finally:
        server.shutdown()
        server.server_close()


def test_unreachable_tally_explains_what_to_do():
    import pytest

    with pytest.raises(tally.TallyError, match="Connectivity"):
        tally.TallyClient("127.0.0.1", 1, timeout=1).ping()
