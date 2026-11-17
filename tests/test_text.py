"""Amounts, dates and narrations as Indian banks print them."""

import datetime as dt

import pytest

from bahi.banks import detect_account, detect_bank
from bahi.layout import match_role
from bahi.narration import parse, signature
from bahi.util import fix_ocr_digits, parse_amount, parse_date, plain_amount, rupees


@pytest.mark.parametrize("text,paise,drcr", [
    ("1,23,456.78", 12345678, None), ("5000.00 Cr", 500000, "CR"), ("12,000.00Dr", 1200000, "DR"),
    ("(1,200.00)", 120000, None), ("-45.50", 4550, None), ("₹ 2,500.00", 250000, None), ("3,864.76 (Dr)", 386476, "DR"),
])
def test_amounts(text, paise, drcr):
    a = parse_amount(text)
    assert a.paise == paise and a.drcr == drcr


def test_amount_rejects_references():
    assert parse_amount("612345678901", require_decimals=True) is None
    assert parse_amount("UPI-123") is None


def test_negative_amounts():
    assert parse_amount("(1,200.00)").signed() == -120000
    assert parse_amount("500.00 Dr").signed() == -50000


@pytest.mark.parametrize("text,date", [
    ("01/04/2026", dt.date(2026, 4, 1)), ("1-4-26", dt.date(2026, 4, 1)), ("01 Apr 2026", dt.date(2026, 4, 1)),
    ("1 April, 2026", dt.date(2026, 4, 1)), ("01-Apr-26", dt.date(2026, 4, 1)), ("2026-04-01", dt.date(2026, 4, 1)),
    ("Apr 01, 2026", dt.date(2026, 4, 1)), ("01/04/2026 10:23:45", dt.date(2026, 4, 1)), ("31/02/2026", None),
    ("15 Sept 2026", dt.date(2026, 9, 15)),
])
def test_dates(text, date):
    assert parse_date(text) == date


def test_indian_grouping():
    assert rupees(12345678) == "1,23,456.78"
    assert rupees(-50) == "-0.50"
    assert rupees(1234567890) == "1,23,45,678.90"
    assert plain_amount(-4636700) == "-46367.00"


@pytest.mark.parametrize("raw,fixed", [("1,60,209:00", "160209.00"), ("38,817.0O", "38817.00"),
                                      ("1,80,128.55,", "180128.55"), ("2,54,630.55 Cr", "254630.55 Cr")])
def test_ocr_digit_repair(raw, fixed):
    assert fix_ocr_digits(raw) == fixed


@pytest.mark.parametrize("label,role", [
    ("Withdrawal Amt.", "debit"), ("Deposit Amt.", "credit"), ("Closing Balance", "balance"),
    ("Chq./Ref.No.", "ref"), ("Value Dt", "value_date"), ("Txn Date", "date"), ("Transaction Remarks", "narration"),
    ("Withdrawal Amount (INR )", "debit"), ("Dr/Cr", "drcr"), ("Particulars", "narration"), ("S No.", "serial"),
    ("Balance (INR )", "balance"), ("Init. Br", None), ("Debit/Credit", "amount"),
])
def test_header_roles(label, role):
    assert match_role(label) == role


@pytest.mark.parametrize("narration,party,vpa,category", [
    ("UPI-SHREE GANESH TRADERS-shreeganesh@ybl-UTIB0000123-100772837832-PAYMENT FROM PHONE",
     "SHREE GANESH TRADERS", "shreeganesh@ybl", ""),
    ("BY TRANSFER-UPI/CR/017320865255/KRISHNA ENTERPRISES/YESB/krishnaent@paytm/UPI--",
     "KRISHNA ENTERPRISES", "krishnaent@paytm", ""),
    ("NEFT CR-SBIN0004431-SHREE GANESH TRADERS-SHARMA TRADERS-SBINN67916011084364", "SHREE GANESH TRADERS", "", ""),
    ("MMT/IMPS/309088714741/PRIYA NAIR/SBIN0001234", "PRIYA NAIR", "", ""),
    ("TO CLEARING-CHQ 442285 JAIN HARDWARE STORES--", "JAIN HARDWARE STORES", "", ""),
    ("ACH D- BAJAJ FINANCE LTD-CITI0000000123", "BAJAJ FINANCE LTD", "", "loan_emi"),
    ("IB FUNDS TRANSFER DR-50100099887766-SHARMA TRADERS", "SHARMA TRADERS", "", "own_transfer"),
    ("ATW-512345XXXXXX6276-S1ANMU55-MUMBAI", "", "", "cash_withdrawal"),
    ("GST PAYMENT CPIN 66304940326991 CBIC", "", "", "tax_gst"),
    ("SMS CHGS APR26", "", "", "bank_charges"),
    ("Int.Pd:01-04-2026 to 29-04-2026", "", "", "interest"),
    ("50100012345678-TPT-RENT APRIL-ANITA DESAI", "ANITA DESAI", "", ""),
    ("UPI-PAYTM-paytm-12345678@paytm-PYTM0123456-612345678901-OID123", "", "paytm-12345678@paytm", ""),
])
def test_narrations(narration, party, vpa, category):
    info = parse(narration)
    assert info.party == party
    assert info.vpa == vpa
    assert info.category == category


def test_keys_prefer_upi_id():
    info = parse("UPI-AMAZON PAY-amazonpay@apl-SBIN0000456-979262243933-PAY")
    assert info.key == "vpa:amazonpay@apl"
    assert signature("SMS CHGS APR26") == "SMS CHGS"


def test_bank_and_account_detection():
    assert detect_bank("STATE BANK OF INDIA\nIFSC Code : SBIN0001234") == "State Bank of India"
    assert detect_bank("Statement of account\nHDFC BANK LTD") == "HDFC Bank"
    assert detect_bank("Branch IFSC: UTIB0000917") == "Axis Bank"
    assert detect_account("Account No : 50100012345678\n12, MARKET ROAD") == "50100012345678"
    assert detect_account("A/C No. XXXXXXXX1234") == "XXXXXXXX1234"
