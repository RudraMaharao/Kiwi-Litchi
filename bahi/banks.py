"""Indian banks: names as printed on statements and IFSC prefixes."""

from __future__ import annotations

import re

# (display name, name pattern, IFSC prefixes)
BANKS = [
    ("HDFC Bank", r"\bhdfc\s*bank\b", ["HDFC"]),
    ("State Bank of India", r"\bstate\s*bank\s*of\s*india\b|\bsbi\b", ["SBIN"]),
    ("ICICI Bank", r"\bicici\s*bank\b", ["ICIC"]),
    ("Axis Bank", r"\baxis\s*bank\b", ["UTIB"]),
    ("Kotak Mahindra Bank", r"\bkotak\s*mahindra\s*bank\b|\bkotak\b", ["KKBK"]),
    ("Punjab National Bank", r"\bpunjab\s*national\s*bank\b|\bpnb\b", ["PUNB"]),
    ("Bank of Baroda", r"\bbank\s*of\s*baroda\b", ["BARB"]),
    ("Canara Bank", r"\bcanara\s*bank\b", ["CNRB"]),
    ("Union Bank of India", r"\bunion\s*bank\s*of\s*india\b", ["UBIN"]),
    ("Bank of India", r"\bbank\s*of\s*india\b", ["BKID"]),
    ("Indian Bank", r"\bindian\s*bank\b", ["IDIB"]),
    ("Central Bank of India", r"\bcentral\s*bank\s*of\s*india\b", ["CBIN"]),
    ("Indian Overseas Bank", r"\bindian\s*overseas\s*bank\b", ["IOBA"]),
    ("UCO Bank", r"\buco\s*bank\b", ["UCBA"]),
    ("Bank of Maharashtra", r"\bbank\s*of\s*maharashtra\b", ["MAHB"]),
    ("Punjab & Sind Bank", r"\bpunjab\s*(&|and)\s*sind\s*bank\b", ["PSIB"]),
    ("IndusInd Bank", r"\bindusind\s*bank\b", ["INDB"]),
    ("Yes Bank", r"\byes\s*bank\b", ["YESB"]),
    ("IDFC FIRST Bank", r"\bidfc\s*first\s*bank\b", ["IDFB"]),
    ("IDBI Bank", r"\bidbi\s*bank\b", ["IBKL"]),
    ("Federal Bank", r"\bfederal\s*bank\b", ["FDRL"]),
    ("RBL Bank", r"\brbl\s*bank\b|\bratnakar\s*bank\b", ["RATN"]),
    ("Bandhan Bank", r"\bbandhan\s*bank\b", ["BDBL"]),
    ("AU Small Finance Bank", r"\bau\s*small\s*finance\s*bank\b", ["AUBL"]),
    ("Equitas Small Finance Bank", r"\bequitas\b", ["ESFB"]),
    ("Ujjivan Small Finance Bank", r"\bujjivan\b", ["UJVN"]),
    ("South Indian Bank", r"\bsouth\s*indian\s*bank\b", ["SIBL"]),
    ("Karur Vysya Bank", r"\bkarur\s*vysya\s*bank\b", ["KVBL"]),
    ("City Union Bank", r"\bcity\s*union\s*bank\b", ["CIUB"]),
    ("Karnataka Bank", r"\bkarnataka\s*bank\b", ["KARB"]),
    ("Tamilnad Mercantile Bank", r"\btamilnad\s*mercantile\s*bank\b", ["TMBL"]),
    ("DCB Bank", r"\bdcb\s*bank\b", ["DCBL"]),
    ("Jammu & Kashmir Bank", r"\bj\s*&\s*k\s*bank\b|\bjammu\s*(&|and)\s*kashmir\s*bank\b", ["JAKA"]),
    ("Saraswat Bank", r"\bsaraswat\b", ["SRCB"]),
    ("Cosmos Bank", r"\bcosmos\s*(co-?operative\s*)?bank\b", ["COSB"]),
    ("Paytm Payments Bank", r"\bpaytm\s*payments\s*bank\b", ["PYTM"]),
    ("Airtel Payments Bank", r"\bairtel\s*payments\s*bank\b", ["AIRP"]),
    ("Standard Chartered", r"\bstandard\s*chartered\b", ["SCBL"]),
    ("HSBC", r"\bhsbc\b", ["HSBC"]),
    ("Citibank", r"\bcitibank\b", ["CITI"]),
    ("DBS Bank India", r"\bdbs\s*bank\b", ["DBSS"]),
]

_NAME_RES = [(name, re.compile(pat, re.I)) for name, pat, _ in BANKS]
IFSC_TO_BANK = {p: name for name, _, prefixes in BANKS for p in prefixes}
IFSC_RE = re.compile(r"\b([A-Z]{4})0[A-Z0-9]{6}\b")
BANK_CODES = set(IFSC_TO_BANK)


def detect_bank(text: str) -> str:
    """Bank name from the statement's header text (name first, then branch IFSC)."""
    m = re.search(r"IFSC\s*(code)?\s*[:\-]?\s*([A-Z]{4})0[A-Z0-9]{6}", text, re.I)
    if m and m.group(2).upper() in IFSC_TO_BANK:
        return IFSC_TO_BANK[m.group(2).upper()]
    hits = []
    for name, rx in _NAME_RES:
        mm = rx.search(text)
        if mm:
            hits.append((mm.start(), name))
    if hits:
        # 'Bank of India' also matches inside 'State Bank of India': prefer the longest name at the earliest spot
        hits.sort(key=lambda h: (h[0], -len(h[1])))
        return hits[0][1]
    for code in IFSC_RE.findall(text):
        if code in IFSC_TO_BANK:
            return IFSC_TO_BANK[code]
    return ""


ACCOUNT_RE = re.compile(
    r"(?:a\s*/\s*c|acct|account)[ \t]*(?:no|number|num|#)?\.?[ \t]*[:\-]?[ \t]*['\"‘’]?((?:[0-9Xx\*]{2,20}[ \-]?){1,5})",
    re.I,
)


def detect_account(text: str) -> str:
    for m in ACCOUNT_RE.finditer(text):
        raw = re.sub(r"[\s\-]", "", m.group(1))
        if len(raw) >= 6 and sum(ch.isdigit() for ch in raw) >= 4:
            return raw.upper()
    return ""
