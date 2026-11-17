"""Talk to Tally: voucher and ledger XML, the HTTP connection on port 9000, and Tally's replies.

Tally's sign rule for ledger entries: a debit is ISDEEMEDPOSITIVE=Yes with a
negative AMOUNT; a credit is ISDEEMEDPOSITIVE=No with a positive AMOUNT.
Money leaving the bank (a debit in the statement) is a credit to the bank
ledger in the books, and the other way round.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from .util import plain_amount

_BAD_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_CHAR_REFS = re.compile(r"&#(?:x0*([0-9a-fA-F]+)|0*(\d+));")


def x(text) -> str:
    """Escape text for an XML element."""
    return escape(_BAD_XML_CHARS.sub(" ", str(text or "")))


def xa(text) -> str:
    """Escape text for an XML attribute (with quotes)."""
    return quoteattr(_BAD_XML_CHARS.sub(" ", str(text or "")))


def tdate(d: dt.date) -> str:
    return d.strftime("%Y%m%d")


def edu_date(d: dt.date) -> dt.date:
    """TallyPrime Educational mode only accepts the 1st, 2nd and 31st of a month."""
    if d.day in (1, 2, 31):
        return d
    return d.replace(day=1 if d.day <= 15 else 2)


# ------------------------------------------------------------------ vouchers

@dataclass
class VoucherSpec:
    date: dt.date
    vtype: str  # voucher type name in Tally, e.g. "Payment" or "HDFC Payment"
    bank_ledger: str
    counter_ledger: str
    amount: int  # paise, > 0
    money_out: bool  # True when the bank statement shows a debit
    narration: str = ""
    instrument_no: str = ""
    instrument_type: str = "Others"
    bank_date: dt.date | None = None
    favouring: str = ""
    other_is_bank: bool = False


def _entry(ledger: str, debit: bool, amount: int, alloc: str = "") -> str:
    amt = -amount if debit else amount
    return ("<ALLLEDGERENTRIES.LIST>"
            f"<LEDGERNAME>{x(ledger)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{'Yes' if debit else 'No'}</ISDEEMEDPOSITIVE>"
            f"<AMOUNT>{plain_amount(amt)}</AMOUNT>"
            f"{alloc}"
            "</ALLLEDGERENTRIES.LIST>")


def _bank_alloc(v: VoucherSpec, debit: bool) -> str:
    amt = -v.amount if debit else v.amount
    parts = [
        "<BANKALLOCATIONS.LIST>",
        f"<DATE>{tdate(v.date)}</DATE>",
        f"<INSTRUMENTDATE>{tdate(v.date)}</INSTRUMENTDATE>",
        f"<TRANSACTIONTYPE>{x(v.instrument_type)}</TRANSACTIONTYPE>",
    ]
    if v.favouring and v.money_out:
        parts.append(f"<PAYMENTFAVOURING>{x(v.favouring[:100])}</PAYMENTFAVOURING>")
    if v.instrument_no:
        parts.append(f"<INSTRUMENTNUMBER>{x(v.instrument_no[:40])}</INSTRUMENTNUMBER>")
    if v.bank_date:
        parts.append(f"<BANKERSDATE>{tdate(v.bank_date)}</BANKERSDATE>")
    parts += ["<STATUS>No</STATUS>", "<PAYMENTMODE>Transacted</PAYMENTMODE>",
              f"<AMOUNT>{plain_amount(amt)}</AMOUNT>", "</BANKALLOCATIONS.LIST>"]
    return "".join(parts)


def voucher_xml(v: VoucherSpec, bank_allocations: bool = True) -> str:
    # money out: Dr the other ledger, Cr the bank.  money in: Dr the bank, Cr the other ledger.
    bank_debit = not v.money_out
    alloc = _bank_alloc(v, bank_debit) if bank_allocations else ""
    other = _entry(v.counter_ledger, not bank_debit, v.amount)
    bank = _entry(v.bank_ledger, bank_debit, v.amount, alloc)
    return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF">'
            f'<VOUCHER VCHTYPE={xa(v.vtype)} ACTION="Create" OBJVIEW="Accounting Voucher View">'
            f"<DATE>{tdate(v.date)}</DATE>"
            f"<EFFECTIVEDATE>{tdate(v.date)}</EFFECTIVEDATE>"
            f"<VOUCHERTYPENAME>{x(v.vtype)}</VOUCHERTYPENAME>"
            f"<PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>"
            f"<ISINVOICE>No</ISINVOICE>"
            f"<NARRATION>{x(v.narration[:500])}</NARRATION>"
            f"{other}{bank}"
            "</VOUCHER></TALLYMESSAGE>")


def ledger_xml(name: str, parent: str) -> str:
    return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF">'
            f'<LEDGER NAME={xa(name)} ACTION="Create">'
            f'<NAME.LIST TYPE="String"><NAME>{x(name)}</NAME></NAME.LIST>'
            f"<PARENT>{x(parent)}</PARENT>"
            "<ISBILLWISEON>No</ISBILLWISEON><AFFECTSSTOCK>No</AFFECTSSTOCK>"
            "</LEDGER></TALLYMESSAGE>")


def envelope(messages: list[str], report: str = "Vouchers", company: str = "") -> str:
    company_part = (f"<STATICVARIABLES><SVCURRENTCOMPANY>{x(company)}</SVCURRENTCOMPANY></STATICVARIABLES>"
                    if company else "")
    body = "\n".join(messages)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            "<ENVELOPE>\n<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>\n"
            "<BODY><IMPORTDATA>\n"
            f"<REQUESTDESC><REPORTNAME>{x(report)}</REPORTNAME>{company_part}</REQUESTDESC>\n"
            f"<REQUESTDATA>\n{body}\n</REQUESTDATA>\n"
            "</IMPORTDATA></BODY>\n</ENVELOPE>\n")


INSTRUMENT_TYPES = {
    "CHEQUE": "Cheque", "NEFT": "e-Fund Transfer", "RTGS": "e-Fund Transfer", "IMPS": "e-Fund Transfer",
    "UPI": "e-Fund Transfer",
}


def instrument_type(channel: str, overrides: dict | None = None) -> str:
    table = dict(INSTRUMENT_TYPES)
    table.update(overrides or {})
    return table.get(channel, "Others")


# ------------------------------------------------------------------ replies

def clean_reply(text: str) -> str:
    """Tally writes characters such as &#4; that XML parsers reject."""
    def fix(m):
        num = int(m.group(1), 16) if m.group(1) else int(m.group(2))
        if num in (9, 10, 13) or num >= 32:
            return m.group(0)
        return ""
    return _BAD_XML_CHARS.sub("", _BAD_CHAR_REFS.sub(fix, text))


def decode_reply(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if len(raw) > 3 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


@dataclass
class ImportResult:
    created: int = 0
    altered: int = 0
    ignored: int = 0
    errors: int = 0
    exceptions: int = 0
    last_vch_id: str = ""
    messages: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.errors == 0 and self.exceptions == 0 and (self.created + self.altered) > 0


def _num(tag: str, text: str) -> int:
    m = re.search(rf"<{tag}>\s*(-?\d+)\s*</{tag}>", text, re.I)
    return int(m.group(1)) if m else 0


def parse_import_reply(text: str) -> ImportResult:
    text = clean_reply(text)
    r = ImportResult(raw=text[:4000])
    r.created = _num("CREATED", text)
    r.altered = _num("ALTERED", text)
    r.ignored = _num("IGNORED", text) + _num("COMBINED", text)
    r.errors = _num("ERRORS", text)
    r.exceptions = _num("EXCEPTIONS", text)
    m = re.search(r"<LASTVCHID>\s*(\d+)\s*</LASTVCHID>", text, re.I)
    r.last_vch_id = m.group(1) if m else ""
    r.messages = [re.sub(r"\s+", " ", m).strip() for m in re.findall(r"<LINEERROR>(.*?)</LINEERROR>", text, re.I | re.S)]
    status = re.search(r"<STATUS>\s*(-?\d+)\s*</STATUS>", text, re.I)
    if status and status.group(1) == "0" and not r.created:
        desc = re.findall(r"<DESC>(.*?)</DESC>", text, re.I | re.S)
        r.messages += [d.strip() for d in desc if d.strip()]
        r.errors = max(r.errors, 1)
    if not r.created and not r.altered and not r.errors and not r.messages:
        if re.search(r"<RESPONSE>\s*</RESPONSE>|unknown request|could not", text, re.I):
            r.errors = 1
            r.messages.append("Tally didn't accept the request: " + re.sub(r"<[^>]+>", " ", text).strip()[:200])
    return r


# ------------------------------------------------------------------ exports

def collection_request(name: str, obj_type: str, fields: list[str], company: str = "") -> str:
    company_part = f"<SVCURRENTCOMPANY>{x(company)}</SVCURRENTCOMPANY>" if company else ""
    methods = "".join(f"<NATIVEMETHOD>{f}</NATIVEMETHOD>" for f in fields)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>"
            f"<TYPE>Collection</TYPE><ID>{x(name)}</ID></HEADER>"
            "<BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
            f"{company_part}</STATICVARIABLES>"
            f'<TDL><TDLMESSAGE><COLLECTION NAME={xa(name)} ISMODIFY="No">'
            f"<TYPE>{x(obj_type)}</TYPE>{methods}</COLLECTION></TDLMESSAGE></TDL>"
            "</DESC></BODY></ENVELOPE>")


def parse_collection(text: str, tag: str) -> list[dict[str, str]]:
    """Objects of one type from an export reply: [{'name': ..., 'parent': ...}]."""
    text = clean_reply(text)
    out: list[dict[str, str]] = []
    try:
        root = ET.fromstring(text.encode("utf-8"))
        for el in root.iter():
            if el.tag.upper() != tag.upper():
                continue
            name = el.get("NAME") or el.get("Name") or ""
            if not name:
                n = el.find("NAME")
                name = (n.text or "") if n is not None else ""
                if not name:
                    nl = el.find("NAME.LIST/NAME")
                    name = (nl.text or "") if nl is not None else ""
            parent_el = el.find("PARENT")
            parent = (parent_el.text or "").strip() if parent_el is not None else ""
            if name.strip():
                out.append({"name": name.strip(), "parent": parent})
        return out
    except ET.ParseError:
        pass
    for m in re.finditer(rf"<{tag}\s+NAME=\"([^\"]+)\"[^>]*>(.*?)</{tag}>", text, re.I | re.S):
        pm = re.search(r"<PARENT[^>]*>(.*?)</PARENT>", m.group(2), re.I | re.S)
        out.append({"name": _unescape(m.group(1)).strip(), "parent": _unescape(pm.group(1)).strip() if pm else ""})
    return out


def _unescape(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
            .replace("&amp;", "&"))


def ancestors(parent_of: dict[str, str], start: str, limit: int = 30) -> list[str]:
    chain, cur = [], start
    lower = {k.lower(): v for k, v in parent_of.items()}
    while cur and len(chain) < limit:
        chain.append(cur)
        nxt = lower.get(cur.lower(), "")
        if not nxt or nxt.lower() in ("primary", cur.lower()):
            break
        cur = nxt
    return chain


# ------------------------------------------------------------------ client

class TallyError(Exception):
    pass


class TallyClient:
    def __init__(self, host: str = "localhost", port: int = 9000, timeout: float = 20):
        self.host = host
        self.port = int(port)
        self.timeout = timeout

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def _send(self, data: bytes | None) -> str:
        req = urllib.request.Request(self.url, data=data, method="POST" if data is not None else "GET")
        if data is not None:
            req.add_header("Content-Type", "text/xml;charset=utf-8")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return decode_reply(resp.read())
        except urllib.error.URLError as exc:
            raise TallyError(
                f"Can't reach Tally at {self.host}:{self.port}. Open TallyPrime with the company loaded, and in "
                "F1 Help > Settings > Connectivity set 'TallyPrime acts as' to Server (or Both) on port "
                f"{self.port}. ({exc.reason if hasattr(exc, 'reason') else exc})") from exc
        except (TimeoutError, OSError) as exc:
            raise TallyError(f"Tally didn't answer in time ({exc}).") from exc

    def ping(self) -> str:
        reply = self._send(None)
        text = re.sub(r"<[^>]+>", " ", reply).strip()
        return text or "Tally is running"

    def companies(self) -> list[str]:
        reply = self._send(collection_request("BahiCompanies", "Company", ["Name"]).encode("utf-8"))
        return [c["name"] for c in parse_collection(reply, "COMPANY")]

    def ledgers(self, company: str = "") -> tuple[list[dict], list[dict]]:
        led = self._send(collection_request("BahiLedgers", "Ledger", ["Name", "Parent"], company).encode("utf-8"))
        grp = self._send(collection_request("BahiGroups", "Group", ["Name", "Parent"], company).encode("utf-8"))
        return parse_collection(led, "LEDGER"), parse_collection(grp, "GROUP")

    def import_xml(self, xml: str) -> ImportResult:
        return parse_import_reply(self._send(xml.encode("utf-8")))
