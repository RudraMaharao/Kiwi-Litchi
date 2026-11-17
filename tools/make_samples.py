"""Generate synthetic bank statements for tests and demos.

Every file is fake data for a fictional business ('Sharma Traders'), drawn in
column layouts that resemble what Indian banks print. Each file has a JSON
twin in samples/expected/ with the true rows, so the parser can be checked.

    python tools/make_samples.py            # writes samples/
"""

from __future__ import annotations

import datetime as dt
import json
import random
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"

CUSTOMERS = [
    ("GUPTA ELECTRICALS", "guptaelec@okhdfcbank", "HDFC0001882"),
    ("SHREE GANESH TRADERS", "shreeganesh@ybl", "SBIN0004431"),
    ("MEHTA AND SONS", "mehtasons@oksbi", "ICIC0000234"),
    ("PATIL CONSTRUCTIONS PVT LTD", "", "UTIB0000917"),
    ("KRISHNA ENTERPRISES", "krishnaent@paytm", "KKBK0001207"),
    ("R K DISTRIBUTORS", "rkdist@okaxis", "PUNB0123400"),
]
SUPPLIERS = [
    ("AMBIKA STEEL PVT LTD", "UTIB0000123"),
    ("BALAJI PACKAGING", "SBIN0007721"),
    ("OM SAI TRANSPORT", "HDFC0000045"),
    ("JAIN HARDWARE STORES", "ICIC0006612"),
]
MERCHANTS = [
    ("SWIGGY", "swiggy.stores@axb"),
    ("AMAZON PAY", "amazonpay@apl"),
    ("BHARAT PETROLEUM", "bpclfuel@icici"),
    ("AIRTEL", "airtel.payments@axisbank"),
    ("RELIANCE RETAIL", "relianceretail@ybl"),
]
PEOPLE = [("RAHUL VERMA", "rahulv@okicici"), ("PRIYA NAIR", "priyanair@ybl"), ("SURESH KUMAR", "suresh.k@oksbi")]
BANK4 = ["HDFC", "SBIN", "ICIC", "UTIB", "KKBK", "YESB"]


def _ref(rng, n=12):
    return "".join(rng.choice("0123456789") for _ in range(n))


class Gen:
    """Builds one month of transactions with a running balance."""

    def __init__(self, seed: int, start: dt.date, opening: int, n: int):
        self.rng = random.Random(seed)
        self.start = start
        self.opening = opening
        self.n = n

    def events(self):
        rng = self.rng
        kinds = (["upi_in"] * 6 + ["upi_out"] * 8 + ["neft_in"] * 4 + ["neft_out"] * 3 + ["imps_out"] * 2
                 + ["atm"] * 2 + ["cash_dep"] + ["chq_out"] + ["charges"] + ["emi"] + ["gst"] + ["rent"]
                 + ["salary"] + ["self_out"])
        days = sorted(rng.randint(0, 27) for _ in range(self.n))
        out = []
        for d in days:
            out.append((self.start + dt.timedelta(days=d), rng.choice(kinds)))
        out.append((self.start + dt.timedelta(days=28), "interest"))
        out.sort(key=lambda e: e[0])
        return out

    def amount(self, kind):
        rng = self.rng
        ranges = {
            "upi_in": (500, 45000), "upi_out": (80, 6000), "neft_in": (15000, 240000), "neft_out": (8000, 180000),
            "imps_out": (1000, 25000), "atm": (2000, 10000), "cash_dep": (5000, 50000), "chq_out": (5000, 90000),
            "charges": (11, 59), "emi": (12500, 12500), "gst": (8000, 60000), "rent": (35000, 35000),
            "salary": (18000, 32000), "self_out": (25000, 100000), "interest": (150, 2400),
        }
        lo, hi = ranges[kind]
        if kind in ("atm",):
            return rng.randint(lo // 500, hi // 500) * 50000
        if kind in ("emi", "rent"):
            return lo * 100
        return rng.randint(lo * 100, hi * 100) if kind in ("charges", "interest", "upi_out") else rng.randint(lo, hi) * 100


def narration(style: str, kind: str, rng, d: dt.date) -> tuple[str, str]:
    """(narration, ref) in the house style of a statement layout."""
    ref = ""
    if kind == "upi_in":
        name, vpa, _ = rng.choice(CUSTOMERS[:3] + [CUSTOMERS[4], CUSTOMERS[5]])
        r = _ref(rng)
        b = rng.choice(BANK4)
        n = {
            "a": f"UPI-{name}-{vpa}-{b}0000123-{r}-PAYMENT FROM PHONE",
            "b": f"BY TRANSFER-UPI/CR/{r}/{name}/{b}/{vpa}/UPI--",
            "c": f"UPI/{r}/Payment/{vpa}/{name}",
            "d": f"UPI/P2A/{r}/{name}/{b}/UPI",
        }[style]
        ref = r if style in ("a", "c") else ""
    elif kind == "upi_out":
        if rng.random() < 0.7:
            name, vpa = rng.choice(MERCHANTS)
        else:
            name, vpa = rng.choice(PEOPLE)
        r = _ref(rng)
        b = rng.choice(BANK4)
        n = {
            "a": f"UPI-{name}-{vpa}-{b}0000456-{r}-PAY",
            "b": f"TO TRANSFER-UPI/DR/{r}/{name}/{b}/{vpa}/Pay--",
            "c": f"UPI/{r}/Pay/{vpa}/{name}",
            "d": f"UPI/P2M/{r}/{name}/Pay via UPI/{b}",
        }[style]
        ref = r if style in ("a", "c") else ""
    elif kind == "neft_in":
        name, _, ifsc = rng.choice(CUSTOMERS)
        utr = ifsc[:4] + "N" + _ref(rng, 14)
        n = {
            "a": f"NEFT CR-{ifsc}-{name}-SHARMA TRADERS-{utr}",
            "b": f"BY TRANSFER-NEFT*{ifsc}*{utr}*{name}--",
            "c": f"NEFT-{utr}-{name}-/FAST///",
            "d": f"NEFT/{utr}/{name}/{ifsc}",
        }[style]
        ref = utr if style == "a" else ""
    elif kind == "neft_out":
        name, ifsc = rng.choice(SUPPLIERS)
        utr = "N" + _ref(rng, 12)
        n = {
            "a": f"NEFT DR-{ifsc}-{name}-NETBANK, MUM-{utr}-INV {rng.randint(100, 999)}",
            "b": f"TO TRANSFER-INB NEFT/{utr}/{name}/{ifsc}--",
            "c": f"INF/NEFT/{utr[1:]}/{ifsc}/{name}",
            "d": f"NEFT/{utr}/{name}/{ifsc}",
        }[style]
        ref = utr if style == "a" else ""
    elif kind == "imps_out":
        name, _ = rng.choice(PEOPLE)
        r = _ref(rng)
        n = {
            "a": f"IMPS-{r}-{name}-SBIN-XXXXXXXX{rng.randint(1000, 9999)}-ADVANCE",
            "b": f"TO TRANSFER-INB IMPS/P2A/{r}/XXXXXXX{rng.randint(1000, 9999)}/{name}--",
            "c": f"MMT/IMPS/{r}/{name}/SBIN0001234",
            "d": f"IMPS/P2A/{r}/{name}/SBIN/Advance",
        }[style]
        ref = r if style == "a" else ""
    elif kind == "atm":
        n = {
            "a": f"ATW-512345XXXXXX{rng.randint(1000, 9999)}-S1ANMU{rng.randint(10, 99)}-MUMBAI",
            "b": f"ATM WDL-ATM CASH {rng.randint(1000, 9999)} ANDHERI EAST MUMBAI-",
            "c": f"NFS/CASH WDL/{_ref(rng, 6)}/MUMBAI/{d.strftime('%d-%m-%y')}",
            "d": f"ATM-CASH/{_ref(rng, 6)}/ANDHERI MUMBAI",
        }[style]
    elif kind == "cash_dep":
        n = {"a": "CASH DEP ANDHERI EAST", "b": "CASH DEPOSIT-CASH DEPOSIT SELF--",
             "c": "BY CASH-ANDHERI EAST", "d": "CASH DEPOSIT BY SELF"}[style]
    elif kind == "chq_out":
        name, _ = rng.choice(SUPPLIERS)
        chq = f"{rng.randint(100000, 999999):06d}"
        n = {
            "a": f"CHQ PAID-MICR CTS-MU-{name}",
            "b": f"TO CLEARING-CHQ {chq} {name}--",
            "c": f"CLG/{name}/{chq}",
            "d": f"BRN-CLG-CHQ PAID TO {name}/{chq}",
        }[style]
        ref = chq if style in ("a", "b", "c") else ""
    elif kind == "charges":
        n = {"a": f"SMS CHGS {d.strftime('%b%y').upper()}", "b": "DEBIT-SMS CHARGES--",
             "c": "SMS Charges for the quarter", "d": "Consolidated Charges for A/c"}[style]
    elif kind == "emi":
        n = {"a": "ACH D- BAJAJ FINANCE LTD-CITI0000000123", "b": "TO TRANSFER-ACH/BAJAJ FINANCE LTD/EMI--",
             "c": "ACH/BAJAJ FINANCE LTD/EMI 08", "d": "NACH-DR-BAJAJ FINANCE LTD"}[style]
    elif kind == "gst":
        cpin = _ref(rng, 14)
        n = {"a": f"GST PAYMENT CPIN {cpin} CBIC", "b": f"TO TRANSFER-GST/{cpin}/CBIC--",
             "c": f"BIL/ONL/{cpin}/GST/CBIC", "d": f"GST/CPIN {cpin}/CBIC"}[style]
    elif kind == "rent":
        n = {"a": "NEFT DR-HDFC0000101-ANITA DESAI-NETBANK, MUM-N" + _ref(rng, 12) + "-RENT",
             "b": "TO TRANSFER-INB NEFT/N" + _ref(rng, 12) + "/ANITA DESAI/RENT--",
             "c": "BIL/INFT/" + _ref(rng, 9) + "/RENT/ANITA DESAI",
             "d": "NEFT/N" + _ref(rng, 12) + "/ANITA DESAI/RENT"}[style]
    elif kind == "salary":
        name = rng.choice(["RAMESH PAWAR", "SUNITA MORE", "AJAY SINGH"])
        n = {"a": f"IMPS-{_ref(rng)}-{name}-HDFC-XXXXXXXX4411-SALARY",
             "b": f"TO TRANSFER-INB IMPS/P2A/{_ref(rng)}/XXXXXXX4411/{name}--",
             "c": f"MMT/IMPS/{_ref(rng)}/SALARY/{name}", "d": f"IMPS/P2A/{_ref(rng)}/{name}/Salary"}[style]
    elif kind == "self_out":
        n = {"a": "IB FUNDS TRANSFER DR-50100099887766-SHARMA TRADERS",
             "b": "TO TRANSFER-INB Funds Transfer to A/c XXXXXX7766--",
             "c": "BIL/INFT/" + _ref(rng, 9) + "/Own transfer/SHARMA TRADERS",
             "d": "IMPS/P2A/" + _ref(rng) + "/SHARMA TRADERS/Self"}[style]
    elif kind == "interest":
        n = {"a": "CREDIT INTEREST CAPITALISED", "b": "CREDIT INTEREST--",
             "c": f"Int.Pd:{(d.replace(day=1)).strftime('%d-%m-%Y')} to {d.strftime('%d-%m-%Y')}",
             "d": "Int.Pd:SB Interest"}[style]
    else:
        raise ValueError(kind)
    return n, ref


CREDIT_KINDS = {"upi_in", "neft_in", "cash_dep", "interest"}


def build(seed, style, start, opening, n):
    g = Gen(seed, start, opening, n)
    bal = opening
    rows = []
    for d, kind in g.events():
        amt = g.amount(kind)
        credit = kind in CREDIT_KINDS
        if not credit and bal - amt < 5_000_00 and style != "d":
            kind, credit = "neft_in", True
            amt = g.amount("neft_in")
        narr, ref = narration(style, kind, g.rng, d)
        bal = bal + amt if credit else bal - amt
        vd = d if g.rng.random() < 0.85 else d + dt.timedelta(days=1)
        rows.append({"date": d.isoformat(), "value_date": vd.isoformat(), "narration": narr, "ref": ref,
                     "amount": amt, "direction": "credit" if credit else "debit", "balance": bal, "kind": kind})
    return rows


def inr(paise: int, dash_zero=False) -> str:
    if paise == 0 and dash_zero:
        return ""
    neg = paise < 0
    whole, frac = divmod(abs(paise), 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + f"{s}.{frac:02d}"


def wrap_words(text, width, font, size):
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if stringWidth(cand, font, size) <= width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            while stringWidth(w, font, size) > width:  # very long token: hard break
                k = len(w)
                while k > 1 and stringWidth(w[:k], font, size) > width:
                    k -= 1
                lines.append(w[:k])
                w = w[k:]
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def wrap_chars(text, nchars):
    return [text[i:i + nchars] for i in range(0, len(text), nchars)] or [""]


# --------------------------------------------------------------- PDF layouts

LAYOUTS = {
    # A: Date | Narration | Chq./Ref.No. | Value Dt | Withdrawal Amt. | Deposit Amt. | Closing Balance
    "a": dict(
        cols=[("Date", 28, "l", 46), ("Narration", 76, "l", 196), ("Chq./Ref.No.", 278, "l", 70),
              ("Value Dt", 352, "l", 40), ("Withdrawal Amt.", 452, "r", 0), ("Deposit Amt.", 507, "r", 0),
              ("Closing Balance", 567, "r", 0)],
        date_fmt="%d/%m/%y", wrap="chars", nchars=34, size=7.2, summary="hdfc", grid=False,
    ),
    # B: Txn Date | Value Date | Description | Ref No./Cheque No. | Debit | Credit | Balance
    "b": dict(
        cols=[("Txn Date", 28, "l", 50), ("Value Date", 80, "l", 50), ("Description", 132, "l", 170),
              ("Ref No./Cheque No.", 306, "l", 70), ("Debit", 440, "r", 0), ("Credit", 500, "r", 0),
              ("Balance", 567, "r", 0)],
        date_fmt="%-d %b %Y", wrap="words", size=7.4, summary="sbi", grid=False,
    ),
    # C: S No. | Value Date | Transaction Date | Cheque Number | Transaction Remarks | Withdrawal | Deposit | Balance
    "c": dict(
        cols=[("S No.", 26, "l", 18), ("Value\nDate", 46, "l", 44), ("Transaction\nDate", 92, "l", 44),
              ("Cheque\nNumber", 138, "l", 36), ("Transaction Remarks", 178, "l", 190),
              ("Withdrawal\nAmount (INR )", 446, "r", 0), ("Deposit\nAmount (INR )", 506, "r", 0),
              ("Balance (INR )", 568, "r", 0)],
        date_fmt="%d/%m/%Y", wrap="chars", nchars=40, size=7.0, summary=None, grid=True,
    ),
    # D: Tran Date | Particulars | Chq No | Amount | Dr/Cr | Balance  (balance with Cr/Dr)
    "d": dict(
        cols=[("Tran Date", 28, "l", 46), ("Particulars", 78, "l", 230), ("Chq No", 312, "l", 50),
              ("Amount", 452, "r", 0), ("Dr/Cr", 468, "l", 20), ("Balance", 567, "r", 0)],
        date_fmt="%d-%m-%Y", wrap="words", size=7.4, summary="axis", grid=False,
    ),
}


def draw_pdf(path, rows, style, opening, title, reverse=False, password=None, account="50100012345678",
             period=None, ifsc="SMPL0001234"):
    L = LAYOUTS[style]
    size = L["size"]
    font, bold = "Helvetica", "Helvetica-Bold"
    kw = {}
    if password:
        from reportlab.lib import pdfencrypt

        kw["encrypt"] = pdfencrypt.StandardEncryption(password, canPrint=1)
    c = canvas.Canvas(str(path), pagesize=A4, **kw)
    W, H = A4
    data = list(reversed(rows)) if reverse else rows
    line_h = size + 2.6
    page_no = 1
    pages_total = 1 + len(data) // 22

    def page_header(first):
        y = H - 40
        c.setFont(bold, 11)
        c.drawString(28, y, "SAMPLE BANK - synthetic statement for testing")
        c.setFont(font, 7.5)
        c.drawRightString(W - 28, y, f"Page {page_no} of {pages_total}")
        y -= 14
        if first:
            p0, p1 = period
            c.drawString(28, y, "M/S. SHARMA TRADERS")
            c.drawString(330, y, f"Account No : {account}")
            y -= 10
            c.drawString(28, y, "12, MARKET ROAD, ANDHERI EAST, MUMBAI 400069")
            c.drawString(330, y, f"IFSC : {ifsc}")
            y -= 10
            if style == "b":
                c.drawString(28, y, f"Statement from {p0.strftime('%d %b %Y')} to {p1.strftime('%d %b %Y')}")
                y -= 10
                c.drawString(28, y, f"Balance as on {p0.strftime('%d %b %Y')} : {inr(opening)}")
            elif style == "d":
                c.drawString(28, y, f"Statement of Account for the period {p0.strftime('%d-%m-%Y')} To "
                                    f"{p1.strftime('%d-%m-%Y')}")
            else:
                c.drawString(28, y, f"Statement From : {p0.strftime('%d/%m/%Y')} To : {p1.strftime('%d/%m/%Y')}")
            y -= 18
        else:
            y -= 6
        # column header
        c.setFont(bold, size)
        max_lines = max(len(lbl.split("\n")) for lbl, *_ in L["cols"])
        for lbl, x, align, _w in L["cols"]:
            for k, part in enumerate(lbl.split("\n")):
                yy = y - k * (size + 1.5)
                if align == "r":
                    c.drawRightString(x, yy, part)
                else:
                    c.drawString(x, yy, part)
        y -= (max_lines - 1) * (size + 1.5)
        if L["grid"]:
            c.line(24, y - 3, W - 24, y - 3)
        y -= line_h + 2
        c.setFont(font, size)
        return y

    y = page_header(True)
    per_page = [0]
    for i, r in enumerate(data):
        d = dt.date.fromisoformat(r["date"])
        vd = dt.date.fromisoformat(r["value_date"])
        narr = r["narration"]
        if L["wrap"] == "chars":
            parts = wrap_chars(narr, L["nchars"])
        else:
            width = [w for lbl, x, a, w in L["cols"] if lbl.startswith(("Description", "Particulars"))][0]
            parts = wrap_words(narr, width, font, size)
        need = len(parts) * line_h + 4
        if y - need < 60:
            c.setFont(font, 6.5)
            c.drawString(28, 40, "This is a computer generated statement and does not require a signature.")
            c.showPage()
            page_no += 1
            per_page.append(0)
            y = page_header(False)
        per_page[-1] += 1
        fmt = L["date_fmt"]
        ds = d.strftime(fmt.replace("%-d", str(d.day)))
        vds = vd.strftime(fmt.replace("%-d", str(vd.day)))
        dr = r["amount"] if r["direction"] == "debit" else 0
        cr = r["amount"] if r["direction"] == "credit" else 0
        c.setFont(font, size)
        if style == "a":
            c.drawString(28, y, ds)
            c.drawString(278, y, r["ref"][:16])
            c.drawString(352, y, vds)
            c.drawRightString(452, y, inr(dr, True))
            c.drawRightString(507, y, inr(cr, True))
            c.drawRightString(567, y, inr(r["balance"]))
            for k, p in enumerate(parts):
                c.drawString(76, y - k * line_h, p)
        elif style == "b":
            c.drawString(28, y, ds)
            c.drawString(80, y, vds)
            c.drawString(306, y, r["ref"][:16])
            c.drawRightString(440, y, inr(dr, True) or "")
            c.drawRightString(500, y, inr(cr, True) or "")
            c.drawRightString(567, y, inr(r["balance"]))
            for k, p in enumerate(parts):
                c.drawString(132, y - k * line_h, p)
        elif style == "c":
            mid = y
            c.drawString(26, mid, str(i + 1))
            c.drawString(46, mid, vds)
            c.drawString(92, mid, ds)
            c.drawString(138, mid, r["ref"][:8] if r["ref"] and len(r["ref"]) <= 8 else "")
            c.drawRightString(446, mid, inr(dr) if dr else "0.00")
            c.drawRightString(506, mid, inr(cr) if cr else "0.00")
            c.drawRightString(568, mid, inr(r["balance"]))
            for k, p in enumerate(parts):
                c.drawString(178, y - k * line_h, p)
        elif style == "d":
            c.drawString(28, y, ds)
            c.drawString(312, y, r["ref"][:10])
            c.drawRightString(452, y, inr(r["amount"]))
            c.drawString(468, y, "DR" if r["direction"] == "debit" else "CR")
            bal = r["balance"]
            c.drawRightString(567, y, inr(abs(bal)) + (" Cr" if bal >= 0 else " Dr"))
            for k, p in enumerate(parts):
                c.drawString(78, y - k * line_h, p)
        y -= len(parts) * line_h + (3 if L["grid"] else 2)
        if L["grid"]:
            c.setLineWidth(0.3)
            c.line(24, y + line_h - 2.5, W - 24, y + line_h - 2.5)
    # summary
    y -= 14
    c.setFont(font, size)
    deb = sum(r["amount"] for r in rows if r["direction"] == "debit")
    cre = sum(r["amount"] for r in rows if r["direction"] == "credit")
    closing = rows[-1]["balance"]
    if y < 100:
        c.showPage()
        page_no += 1
        y = H - 60
    if L["summary"] == "hdfc":
        c.setFont(bold, size)
        c.drawString(28, y, "STATEMENT SUMMARY :-")
        y -= 12
        labels = [("Opening Balance", 28), ("Dr Count", 150), ("Cr Count", 220), ("Debits", 330), ("Credits", 430),
                  ("Closing Bal", 520)]
        for lbl, x in labels:
            c.drawString(x, y, lbl)
        y -= 11
        c.setFont(font, size)
        vals = [inr(opening), str(sum(1 for r in rows if r["direction"] == "debit")),
                str(sum(1 for r in rows if r["direction"] == "credit")), inr(deb), inr(cre), inr(closing)]
        for (lbl, x), v in zip(labels, vals):
            c.drawString(x, y, v)
    elif L["summary"] == "axis":
        c.drawString(28, y, f"OPENING BALANCE : {inr(opening)}")
        y -= 10
        c.drawString(28, y, f"CLOSING BALANCE : {inr(abs(closing))} {'Dr' if closing < 0 else 'Cr'}")
    elif L["summary"] == "sbi":
        c.drawString(28, y, "**** END OF STATEMENT ****")
    c.setFont(font, 6.5)
    c.drawString(28, 40, "This is a computer generated statement and does not require a signature.")
    c.save()
    return per_page


def write_expected(name, rows, opening, extra=None):
    exp = {"opening": opening, "closing": rows[-1]["balance"], "rows": rows}
    exp.update(extra or {})
    (OUT / "expected").mkdir(parents=True, exist_ok=True)
    (OUT / "expected" / f"{name}.json").write_text(json.dumps(exp, indent=1))


def scan_pdf(src: Path, dst: Path, dpi=200, angle=0.35, seed=1, jpg: Path | None = None):
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    rng = random.Random(seed)
    doc = pdfium.PdfDocument(str(src))
    imgs = []
    for page in doc:
        img = page.render(scale=dpi / 72).to_pil().convert("L")
        img = img.rotate(angle, expand=False, fillcolor=255, resample=Image.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        px = img.load()
        for _ in range(img.width * img.height // 300):
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            px[x, y] = rng.choice([0, 255, 200, 90])
        imgs.append(img.convert("RGB"))
    doc.close()
    imgs[0].save(dst, save_all=True, append_images=imgs[1:], resolution=dpi)
    if jpg is not None:
        imgs[0].save(jpg, quality=70)


def excel_versions(rows, opening, period):
    import openpyxl

    p0, p1 = period
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Statement"
    ws.append(["SAMPLE BANK - synthetic statement for testing"])
    ws.append(["Account Name", "M/S. SHARMA TRADERS"])
    ws.append(["Account No", "'50100012345678"])
    ws.append(["Period", f"{p0:%d/%m/%Y} to {p1:%d/%m/%Y}"])
    ws.append([])
    ws.append(["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
    for r in rows:
        ws.append([dt.datetime.fromisoformat(r["date"]), r["narration"], r["ref"],
                   dt.datetime.fromisoformat(r["value_date"]),
                   r["amount"] / 100 if r["direction"] == "debit" else None,
                   r["amount"] / 100 if r["direction"] == "credit" else None, r["balance"] / 100])
    ws.append([])
    ws.append(["Opening Balance", opening / 100, "Closing Balance", rows[-1]["balance"] / 100])
    wb.save(OUT / "excel_layout_a.xlsx")
    write_expected("excel_layout_a", rows, opening)

    # 'Excel' download that is really an HTML table (some banks do this)
    html = ["<html><body><table>", "<tr><td>SAMPLE BANK - synthetic statement</td></tr>",
            "<tr><td>Account Number</td><td>50100012345678</td></tr>",
            "<tr><th>Txn Date</th><th>Value Date</th><th>Description</th><th>Ref No./Cheque No.</th>"
            "<th>Debit</th><th>Credit</th><th>Balance</th></tr>"]
    for r in rows:
        d = dt.date.fromisoformat(r["date"])
        html.append(
            f"<tr><td>{d:%d %b %Y}</td><td>{d:%d %b %Y}</td><td>{r['narration']}</td><td>{r['ref']}</td>"
            f"<td>{inr(r['amount']) if r['direction'] == 'debit' else ''}</td>"
            f"<td>{inr(r['amount']) if r['direction'] == 'credit' else ''}</td><td>{inr(r['balance'])}</td></tr>")
    html.append("</table></body></html>")
    (OUT / "html_disguised_as.xls").write_text("\n".join(html))
    write_expected("html_disguised_as", rows, opening)

    lines = ["Date,Description,Amount,Type,Balance"]
    for r in rows:
        d = dt.date.fromisoformat(r["date"])
        desc = r["narration"].replace('"', "'")
        lines.append(f'{d:%d-%m-%Y},"{desc}",{r["amount"] / 100:.2f},'
                     f'{"DR" if r["direction"] == "debit" else "CR"},{r["balance"] / 100:.2f}')
    (OUT / "csv_amount_type.csv").write_text("\n".join(lines) + "\n")
    write_expected("csv_amount_type", rows, opening, {"no_opening": True})


def main():
    OUT.mkdir(exist_ok=True)
    period = (dt.date(2026, 4, 1), dt.date(2026, 4, 30))
    specs = [
        ("layout_a", 11, "a", 2_45_310_55, 46, {}),
        ("layout_b", 22, "b", 1_23_456_78, 40, {}),
        ("layout_c", 33, "c", 3_10_000_00, 38, {}),
        ("layout_d", 44, "d", 85_000_00, 34, {}),
        ("layout_a_newest_first", 55, "a", 1_98_765_43, 30, {"reverse": True}),
    ]
    made = {}
    for name, seed, style, opening, n, opts in specs:
        rows = build(seed, style, period[0], opening, n)
        made[name] = (rows, opening, style)
        pages = draw_pdf(OUT / f"{name}.pdf", rows, style, opening, name, period=period, **opts)
        made[name + "_pages"] = pages
        write_expected(name, rows, opening, {"no_opening": style in ("c",) or opts.get("reverse", False)})
    # locked copy of layout B (password: sharma123)
    rows, opening, style = made["layout_b"]
    draw_pdf(OUT / "layout_b_locked.pdf", rows, "b", opening, "locked", password="sharma123", period=period)
    write_expected("layout_b_locked", rows, opening, {"password": "sharma123"})
    # scanned copy of layout A and a phone-style photo of page 1
    scan_pdf(OUT / "layout_a.pdf", OUT / "layout_a_scanned.pdf", jpg=OUT / "layout_a_photo_page1.jpg")
    rows, opening, _ = made["layout_a"]
    write_expected("layout_a_scanned", rows, opening)
    first_page = made["layout_a_pages"][0]
    write_expected("layout_a_photo_page1", rows[:first_page], opening)
    excel_versions(made["layout_a"][0], made["layout_a"][1], period)
    print("Wrote", len(list(OUT.glob("*.*"))), "files to", OUT)


if __name__ == "__main__":
    sys.exit(main())
