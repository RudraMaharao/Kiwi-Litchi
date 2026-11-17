"""Read Indian bank narrations: channel, counterparty, UPI ID, references.

Every bank writes narrations differently ('UPI-NAME-vpa-IFSC-ref-note',
'BY TRANSFER-UPI/CR/ref/NAME/BANK/vpa/UPI--', 'MMT/IMPS/ref/NAME/IFSC', ...).
Instead of one pattern per bank, the narration is split on its separators and
each piece is classified: UPI ID, IFSC, reference number, masked account,
banking jargon, or a name. The first name-like piece is the counterparty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .banks import BANK_CODES
from .util import norm_space, party_key

# Lower-case segments joined by hyphens can be part of a UPI ID ('paytm-1234@paytm'); upper-case words before
# a hyphen are the payee's name ('TRADERS-shree@ybl'), so they are left out.
VPA_RE = re.compile(r"(?<![A-Za-z0-9._])(?:[a-z0-9._]+-)*[A-Za-z0-9._]{2,}@[A-Za-z][A-Za-z0-9]{1,63}")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
UTR_RE = re.compile(r"^[A-Z]{4}[A-Z0-9]{9,}$|^[A-Z]{1,6}\d{8,}$|^N\d{8,}$")
MASKED_RE = re.compile(r"^[X\*]{2,}\d{2,}$|^\d{2,}[X\*]{3,}\d{2,}$")

CHANNELS = [
    ("UPI", r"\bUPI\b"),
    ("IMPS", r"\bIMPS\b|\bMMT\b"),
    ("NEFT", r"\bNEFT\b"),
    ("RTGS", r"\bRTGS\b"),
    ("ACH", r"\b(ACH|NACH|ECS)\b"),
    ("ATM", r"\b(ATM|ATW|NWD|NFS)\b|CASH\s*WDL|CASH\s*WITHDRAWAL"),
    ("CASH", r"CASH\s*DEP|CASH\s*DEPOSIT|\bBY\s*CASH\b|\bCDM\b|CSH\s*DEP|CASH\s*REMITTANCE"),
    ("CARD", r"\b(POS|PCD|VPS|ECOM|VISA|MASTERCARD|RUPAY)\b|DEBIT\s*CARD\s*PURCHASE"),
    ("CHEQUE", r"\b(CHQ|CHEQUE|CLG|CLEARING|CTS|MICR)\b"),
    ("BILLPAY", r"\b(BBPS|BILLPAY|BILL\s*PAY|BIL)\b"),
    ("TRANSFER", r"\b(IB\s*FUNDS\s*TRANSFER|FUNDS\s*TRANSFER|FT|TPT|INB|INFT|INF|TRF|TRANSFER)\b"),
]
_CHANNEL_RES = [(name, re.compile(rx, re.I)) for name, rx in CHANNELS]

CATEGORIES = [
    ("reversal", r"\b(REV|REVERSAL|REVERSED|RETURN|RETURNED|RTN|REFUND|CHARGEBACK)\b"),
    ("tax_gst", r"\bCPIN\b|\bCBIC\b|\bGSTN\b|GST\s*(PAYMENT|PMT|CHALLAN)|/GST/"),
    ("tax_income", r"\b(CBDT|ITNS|OLTAS|TIN\s*-?\s*NSDL|INCOME\s*TAX|ADVANCE\s*TAX|TDS\s*PAYMENT|CHALLAN\s*28\d)\b"),
    ("bank_charges", r"\b(CHG|CHGS|CHRG|CHRGS|CHARGE|CHARGES|FEE|FEES|AMC|COMMISSION|SMS\s*ALERT|MIN\s*BAL|"
                     r"NON\s*MAINT|PENAL)\b|GST\s*(@|ON\s*CHARGE)|CONSOLIDATED\s*CHARGES"),
    ("interest", r"\bINT\.?\s*PD\b|\bINT\.?\s*CR\b|\bINT\.PD|INTEREST|\bSB\s*INT\b|\bINT\s*COLL"),
    ("cash_withdrawal", r"\b(ATM|ATW|NWD|NFS)\b|CASH\s*WDL|CASH\s*WITHDRAWAL|SELF\s*CHQ|CASH\s*PAID"),
    ("cash_deposit", r"CASH\s*DEP|CASH\s*DEPOSIT|\bBY\s*CASH\b|\bCDM\b|CSH\s*DEP"),
    ("loan_emi", r"\bEMI\b|\bLOAN\b|FINANCE\s*(LTD|LIMITED)|\bNACH\b"),
    ("salary", r"\bSAL\b|\bSALARY\b|\bSALARIES\b|\bPAYROLL\b"),
    ("own_transfer", r"\bSELF\b|OWN\s*(A/?C|ACCOUNT|TRANSFER)|IB\s*FUNDS\s*TRANSFER|FUNDS\s*TRANSFER\s*TO\s*A/?C"),
]
_CATEGORY_RES = [(name, re.compile(rx, re.I)) for name, rx in CATEGORIES]

STOP_PHRASES = {
    "UPI", "NEFT", "RTGS", "IMPS", "MMT", "DR", "CR", "P2A", "P2M", "P2P", "INB", "IB", "BY", "TO", "TRANSFER",
    "TRF", "FT", "PAYMENT", "PAY", "PAID", "SENT", "RECEIVED", "RECD", "FROM", "NA", "N A", "REF", "REFNO",
    "TXN", "TRANSACTION", "MB", "MOB", "MOBILE", "NETBANK", "NET BANKING", "NETBANKING", "BIL", "ONL", "INFT",
    "INF", "CMS", "ACH", "NACH", "ECS", "D", "C", "CLG", "CHQ", "CHEQUE", "MICR", "CTS", "MICR CTS", "CHQ PAID",
    "PAID TO", "PAY TO", "NEFT CR", "NEFT DR", "RTGS CR", "RTGS DR", "IMPS CR", "IMPS DR", "UPI CR", "UPI DR",
    "ACH D", "ACH C", "ACH DR", "ACH CR", "NACH DR", "NACH CR", "INB IMPS", "INB NEFT", "INB RTGS", "FAST",
    "UPI REF", "PAYMENT FROM PHONE", "PAYMENT FROM PHONEPE", "PAY VIA UPI", "PAY VIA RAZO", "UPI PAYMENT",
    "COLLECT", "APP", "SELF", "OWN TRANSFER", "OWN", "IB FUNDS TRANSFER DR", "IB FUNDS TRANSFER CR",
    "IB FUNDS TRANSFER", "FUNDS TRANSFER", "TPT", "BRN", "BRN CLG", "CLG CHQ PAID TO", "TO CLG", "BY CLG",
    "INWARD", "OUTWARD", "GST", "TDS", "CBIC", "CPIN", "EMI", "SALARY", "SAL", "ADVANCE", "INVOICE", "INV",
    "BILL", "RENT", "NA NA", "OTHERS", "OTHER", "PURCHASE", "SETTLEMENT", "UPIINTENT", "INTENT",
    "BANK", "ICICI BANK", "ICICI BAN", "HDFC BANK", "YES BANK", "AXIS BANK", "STATE BANK OF INDIA", "SBI",
    "KOTAK MAHINDRA BANK", "KOTAK", "PAYTM PAYMENTS BANK", "AIRTEL PAYMENTS BANK", "PUNJAB NATIONAL BANK",
    "BANK OF BARODA", "CANARA BANK", "UNION BANK OF INDIA", "IDFC FIRST BANK", "INDUSIND BANK", "NETBANK MUM",
    "POS", "ATM", "ATW", "NFS", "NWD", "ATM WDL", "ATM CASH", "CASH WDL", "CASH DEP", "CASH DEPOSIT", "BY CASH",
    "DEBIT", "CREDIT", "CHRG", "CHG", "CHGS", "INT", "INT PD", "PD", "ECOM", "VPS", "PCD", "MMT IMPS",
    "IB FUNDS", "FUNDS", "FUNDS TRANSFER TO A", "FUNDS TRANSFER TO", "TRANSFER TO", "TRANSFER FROM", "A C", "AC",
    "REV", "REVERSAL", "REVERSED", "RETURN", "RETURNED", "RTN", "REFUND", "CHQ RET", "CHQ RETURN",
}
REMARK_WORDS = {"PAYMENT", "PAY", "INVOICE", "INV", "BILL", "RENT", "ADVANCE", "SALARY", "PURCHASE", "FEES",
                "REFUND", "ORDER", "BOOKING", "TRANSFER", "UPI", "VIA", "FOR", "THE", "AND", "OF", "TO", "FROM",
                "NOTE", "REMARK", "SENT", "USING", "PHONE", "PHONEPE", "GPAY", "GOOGLE", "PAYTM", "BHIM",
                "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC",
                "JANUARY", "FEBRUARY", "MARCH", "APRIL", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
                "NOVEMBER", "DECEMBER", "MONTH", "CHARGES", "FEE", "EMI"}
_STOP_SORTED = sorted(STOP_PHRASES, key=len, reverse=True)
NO_PARTY_CATEGORIES = {"bank_charges", "interest", "cash_withdrawal", "cash_deposit", "tax_gst", "tax_income"}


@dataclass
class NarrationInfo:
    channel: str = "OTHER"
    category: str = ""
    party: str = ""
    vpa: str = ""
    ifsc: str = ""
    ref: str = ""
    account: str = ""

    @property
    def key(self) -> str:
        """Stable key for remembering which ledger this counterparty goes to."""
        if self.vpa:
            return "vpa:" + self.vpa.lower()
        if self.party:
            return "party:" + party_key(self.party)
        return ""

    def keys(self) -> list[str]:
        out = []
        if self.vpa:
            out.append("vpa:" + self.vpa.lower())
        if self.party:
            out.append("party:" + party_key(self.party))
        return out


def signature(narration: str) -> str:
    """Words left after removing numbers and codes: 'SMS CHGS APR26' -> 'SMS CHGS'."""
    s = re.sub(r"[a-z0-9._\-]+@[a-z0-9]+", " ", narration, flags=re.I)
    s = re.sub(r"[^A-Za-z]+", " ", s).upper()
    words = [w for w in s.split() if len(w) > 1 and w not in {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG",
                                                               "SEP", "OCT", "NOV", "DEC"}]
    return " ".join(words[:4])


def _strip_leading_jargon(text: str) -> str:
    changed = True
    while changed and text:
        changed = False
        up = text.upper()
        for phrase in _STOP_SORTED:
            if up == phrase:
                return ""
            if up.startswith(phrase + " "):
                text = text[len(phrase) + 1:].strip()
                changed = True
                break
    return text


def _clean_piece(piece: str) -> str:
    p = norm_space(piece.replace(",", " ").replace(".", " ").replace("_", " "))
    # drop digit groups inside a piece: 'CHQ 467782 JAIN HARDWARE' -> 'CHQ JAIN HARDWARE'
    words = [w for w in p.split() if not re.search(r"\d{3,}", w) and not MASKED_RE.match(w.upper())]
    p = _strip_leading_jargon(" ".join(words))
    words = p.split()
    while words and words[0].upper() in REMARK_WORDS:
        words = words[1:]
    return " ".join(words)


def _is_name(piece: str) -> bool:
    up = piece.upper()
    if not piece or up in STOP_PHRASES or up in BANK_CODES:
        return False
    letters = sum(ch.isalpha() for ch in piece)
    if letters < 3 or letters < 0.7 * len(piece.replace(" ", "")):
        return False
    words = up.split()
    if all(w in REMARK_WORDS or w in STOP_PHRASES for w in words):
        return False
    return True


def parse(narration: str) -> NarrationInfo:
    info = NarrationInfo()
    text = norm_space(narration or "")
    up = text.upper()
    for name, rx in _CHANNEL_RES:
        if rx.search(up):
            info.channel = name
            break
    for name, rx in _CATEGORY_RES:
        if rx.search(up):
            info.category = name
            break
    m = VPA_RE.search(text)
    if m:
        info.vpa = m.group(0).lower().strip(".-_")
        text = text[: m.start()] + "/" + text[m.end():]
    body = re.sub(r"^(BY|TO)\s+(TRANSFER|CLEARING|CLG|CASH|INST)\s*[-:]?\s*", "", text, flags=re.I)
    pieces = [p.strip() for p in re.split(r"[/\-*|:]+|\s{2,}", body)]
    names = []
    for raw in pieces:
        if not raw:
            continue
        for tok in raw.split():
            t = tok.upper().strip(".,")
            digits = sum(ch.isdigit() for ch in t)
            if IFSC_RE.match(t):
                info.ifsc = info.ifsc or t
            elif MASKED_RE.match(t):
                info.account = info.account or t
            elif digits >= 6 and (digits >= 0.6 * len(t) or UTR_RE.match(t)):
                if not info.ref:
                    info.ref = t
        if " " not in raw and (IFSC_RE.match(raw.upper()) or MASKED_RE.match(raw.upper())):
            continue
        if raw.upper() in STOP_PHRASES:
            continue
        piece = _clean_piece(raw)
        if _is_name(piece):
            names.append(piece)
    if names and info.category not in NO_PARTY_CATEGORIES:
        info.party = names[0].upper()
    return info


def display_party(info: NarrationInfo) -> str:
    if info.party:
        return info.party.title()
    if info.vpa:
        return info.vpa
    return ""
