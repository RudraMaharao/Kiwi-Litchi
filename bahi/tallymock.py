"""A small Tally simulator for tests and demos without TallyPrime.

It answers on port 9000 like TallyPrime does: lists companies, ledgers and
groups, and imports ledgers and vouchers with the checks Tally makes (ledger
exists, debits equal credits, Contra uses only cash/bank, Educational-mode
dates). It is not Tally: always test real imports on TallyPrime too.
"""

from __future__ import annotations

import json
import re
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .tally import clean_reply, x, xa

PREDEFINED_GROUPS = {
    "Branch / Divisions": "", "Capital Account": "", "Current Assets": "", "Current Liabilities": "",
    "Direct Expenses": "", "Direct Incomes": "", "Fixed Assets": "", "Indirect Expenses": "", "Indirect Incomes": "",
    "Investments": "", "Loans (Liability)": "", "Misc. Expenses (ASSET)": "", "Purchase Accounts": "",
    "Sales Accounts": "", "Suspense A/c": "",
    "Bank Accounts": "Current Assets", "Bank OD A/c": "Loans (Liability)", "Cash-in-Hand": "Current Assets",
    "Deposits (Asset)": "Current Assets", "Duties & Taxes": "Current Liabilities",
    "Loans & Advances (Asset)": "Current Assets", "Provisions": "Current Liabilities",
    "Reserves & Surplus": "Capital Account", "Secured Loans": "Loans (Liability)",
    "Stock-in-Hand": "Current Assets", "Sundry Creditors": "Current Liabilities",
    "Sundry Debtors": "Current Assets", "Unsecured Loans": "Loans (Liability)",
}

DEMO_COMPANY = "Sharma Traders (Demo)"
DEMO_LEDGERS = {
    "Cash": "Cash-in-Hand",
    "Sample Bank A/c 5678": "Bank Accounts",
    "Sample Bank Current A/c 7766": "Bank Accounts",
    "Gupta Electricals": "Sundry Debtors",
    "Shree Ganesh Traders": "Sundry Debtors",
    "Mehta & Sons": "Sundry Debtors",
    "Patil Constructions Pvt Ltd": "Sundry Debtors",
    "Krishna Enterprises": "Sundry Debtors",
    "Ambika Steel Pvt Ltd": "Sundry Creditors",
    "Balaji Packaging": "Sundry Creditors",
    "Om Sai Transport": "Sundry Creditors",
    "Bank Charges": "Indirect Expenses",
    "Rent": "Indirect Expenses",
    "Salary": "Indirect Expenses",
    "Staff Welfare": "Indirect Expenses",
    "Fuel Expenses": "Indirect Expenses",
    "Telephone Expenses": "Indirect Expenses",
    "Office Expenses": "Indirect Expenses",
    "Interest Received": "Indirect Incomes",
    "Interest Paid": "Indirect Expenses",
    "Bajaj Finance Ltd": "Unsecured Loans",
    "GST Cash Ledger": "Duties & Taxes",
    "TDS Payable": "Duties & Taxes",
    "Advance to Staff": "Loans & Advances (Asset)",
}
VOUCHER_TYPES = ["Payment", "Receipt", "Contra", "Journal", "Sales", "Purchase", "Debit Note", "Credit Note"]


class Company:
    def __init__(self, name: str, ledgers: dict[str, str] | None = None):
        self.name = name
        self.groups = dict(PREDEFINED_GROUPS)
        self.ledgers = dict(ledgers or {"Cash": "Cash-in-Hand"})
        self.vouchers: list[dict] = []
        self.voucher_types = list(VOUCHER_TYPES)
        self.next_id = 1

    def ledger(self, name: str) -> str | None:
        for k in self.ledgers:
            if k.lower() == name.lower():
                return k
        return None

    def under(self, group: str, target: str) -> bool:
        seen = 0
        while group and seen < 40:
            if group.lower() == target.lower():
                return True
            group = self.groups.get(group, "")
            seen += 1
        return False

    def is_cash_bank(self, ledger: str) -> bool:
        parent = self.ledgers.get(ledger, "")
        return any(self.under(parent, g) for g in ("Bank Accounts", "Bank OD A/c", "Cash-in-Hand"))


class MockTally:
    def __init__(self, edu_mode: bool = False, demo: bool = True):
        self.edu_mode = edu_mode
        self.companies: dict[str, Company] = {}
        if demo:
            self.companies[DEMO_COMPANY] = Company(DEMO_COMPANY, DEMO_LEDGERS)
        self.lock = threading.Lock()
        self.requests: list[str] = []

    def company(self, name: str | None) -> Company | None:
        if not self.companies:
            return None
        if not name:
            return next(iter(self.companies.values()))
        for c in self.companies.values():
            if c.name.lower() == name.lower():
                return c
        return None

    # ------------------------------------------------------------ handlers

    def handle(self, body: str) -> str:
        with self.lock:
            self.requests.append(body[:2000])
            try:
                root = ET.fromstring(clean_reply(body).encode("utf-8"))
            except ET.ParseError as exc:
                return f"<RESPONSE><LINEERROR>Could not parse XML: {x(exc)}</LINEERROR></RESPONSE>"
            req = (root.findtext("HEADER/TALLYREQUEST") or "").strip().lower()
            if req == "export":
                return self._export(root)
            if req == "import data":
                return self._import(root)
            return "<RESPONSE>Unknown Request, cannot be processed</RESPONSE>"

    def _export(self, root) -> str:
        coll_type = (root.findtext(".//TDL/TDLMESSAGE/COLLECTION/TYPE") or "").strip().lower()
        company = self.company(root.findtext(".//STATICVARIABLES/SVCURRENTCOMPANY"))
        items = []
        if coll_type == "company":
            items = [f"<COMPANY NAME={xa(c.name)}><NAME>{x(c.name)}</NAME></COMPANY>" for c in self.companies.values()]
        elif company is None:
            return ("<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>0</STATUS></HEADER><BODY><DATA><STATUS.LIST>"
                    "<CODE>0</CODE><DESC>Could not find the company</DESC></STATUS.LIST></DATA></BODY></ENVELOPE>")
        elif coll_type == "ledger":
            for name, parent in company.ledgers.items():
                items.append(f'<LEDGER NAME={xa(name)} RESERVEDNAME=""><PARENT TYPE="String">{x(parent)}</PARENT>'
                             f"</LEDGER>")
        elif coll_type == "group":
            for name, parent in company.groups.items():
                p = x(parent) if parent else "&#4; Primary"
                items.append(f'<GROUP NAME={xa(name)} RESERVEDNAME={xa(name)}><PARENT TYPE="String">{p}</PARENT></GROUP>')
        return ("<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC></DESC><DATA>"
                f"<COLLECTION>{''.join(items)}</COLLECTION></DATA></BODY></ENVELOPE>")

    def _import(self, root) -> str:
        company_name = root.findtext(".//REQUESTDESC/STATICVARIABLES/SVCURRENTCOMPANY")
        company = self.company(company_name)
        if company is None:
            return (f"<RESPONSE><LINEERROR>Could not set 'SVCurrentCompany' to '{x(company_name or '')}'"
                    "</LINEERROR><CREATED>0</CREATED><ALTERED>0</ALTERED><ERRORS>1</ERRORS></RESPONSE>")
        created = errors = 0
        last = 0
        msgs: list[str] = []
        for msg in root.iter("TALLYMESSAGE"):
            for led in msg.findall("LEDGER"):
                name = led.get("NAME") or led.findtext("NAME.LIST/NAME") or ""
                parent = (led.findtext("PARENT") or "").strip()
                if not name:
                    errors += 1
                    msgs.append("Ledger name missing")
                elif company.ledger(name):
                    errors += 1
                    msgs.append(f"Ledger '{name}' already exists!")
                elif parent not in company.groups:
                    errors += 1
                    msgs.append(f"Group '{parent}' does not exist!")
                else:
                    company.ledgers[name] = parent
                    created += 1
            for v in msg.findall("VOUCHER"):
                err = self._voucher(company, v)
                if err:
                    errors += 1
                    msgs.append(err)
                else:
                    created += 1
                    last = company.next_id - 1
        lines = "".join(f"<LINEERROR>{x(m)}</LINEERROR>" for m in msgs)
        return (f"<RESPONSE>{lines}<CREATED>{created}</CREATED><ALTERED>0</ALTERED><DELETED>0</DELETED>"
                f"<LASTVCHID>{last}</LASTVCHID><LASTMID>0</LASTMID><COMBINED>0</COMBINED><IGNORED>0</IGNORED>"
                f"<ERRORS>{errors}</ERRORS><CANCELLED>0</CANCELLED></RESPONSE>")

    def _voucher(self, company: Company, v) -> str | None:
        vtype = (v.findtext("VOUCHERTYPENAME") or v.get("VCHTYPE") or "").strip()
        date = (v.findtext("DATE") or "").strip()
        if vtype not in company.voucher_types:
            return f"Voucher Type '{vtype}' does not exist!"
        if not re.fullmatch(r"\d{8}", date):
            return "Invalid date"
        if self.edu_mode and int(date[6:8]) not in (1, 2, 31):
            return "Educational Version: Date must be 1, 2 or 31 of the month"
        entries = []
        total = 0
        for e in v.findall("ALLLEDGERENTRIES.LIST"):
            name = (e.findtext("LEDGERNAME") or "").strip()
            real = company.ledger(name)
            if real is None:
                return f"Ledger '{name}' does not exist!"
            try:
                amt = round(float(e.findtext("AMOUNT") or "0") * 100)
            except ValueError:
                return "Invalid amount"
            deemed = (e.findtext("ISDEEMEDPOSITIVE") or "").strip().lower() == "yes"
            if deemed != (amt < 0):
                return f"ISDEEMEDPOSITIVE doesn't match the sign of the amount for '{name}'"
            total += amt
            entries.append((real, amt))
        if len(entries) < 2:
            return "Voucher needs at least two ledger entries"
        if total != 0:
            return "Voucher totals do not match!"
        cash_bank = [company.is_cash_bank(n) for n, _ in entries]
        if vtype == "Contra" and not all(cash_bank):
            return "Contra vouchers can only use cash and bank ledgers"
        if vtype in ("Payment", "Receipt") and not any(cash_bank):
            return f"{vtype} vouchers need a cash or bank ledger"
        vid = company.next_id
        company.next_id += 1
        company.vouchers.append({
            "id": vid, "type": vtype, "date": date, "narration": v.findtext("NARRATION") or "",
            "entries": [{"ledger": n, "amount": a} for n, a in entries],
            "bank_date": v.findtext(".//BANKALLOCATIONS.LIST/BANKERSDATE") or "",
        })
        return None


def make_handler(mock: MockTally):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            return

        def _send(self, text: str, ctype: str = "text/xml; charset=utf-8"):
            data = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/bahi/vouchers"):
                out = {c.name: c.vouchers for c in mock.companies.values()}
                return self._send(json.dumps(out, indent=1), "application/json")
            self._send("<RESPONSE>TallyPrime Server is Running (Bahi simulator)</RESPONSE>")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n).decode("utf-8", "replace")
            self._send(mock.handle(body))

    return Handler


def serve(host: str = "127.0.0.1", port: int = 9000, edu_mode: bool = False, demo: bool = True):
    mock = MockTally(edu_mode=edu_mode, demo=demo)
    server = ThreadingHTTPServer((host, port), make_handler(mock))
    return server, mock


def start_background(host: str = "127.0.0.1", port: int = 0, **kw):
    server, mock = serve(host, port, **kw)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, mock
