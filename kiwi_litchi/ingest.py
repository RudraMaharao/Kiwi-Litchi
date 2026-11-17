"""Table adapters and reconciliation. Unreadable financial rows are never skipped."""
import csv
import io
import json
import re
import uuid
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from .common import UserError, digest, iso_date, money, normal
from .db import now

ALIASES = {
    "date": {"date", "txn date", "transaction date", "posting date", "value date", "tran date"},
    "narration": {"narration", "description", "particulars", "transaction particulars", "details", "remarks"},
    "debit": {"debit", "debit amount", "withdrawal", "withdrawals", "withdrawal amt", "withdrawal amount", "dr amount"},
    "credit": {"credit", "credit amount", "deposit", "deposits", "deposit amt", "deposit amount", "cr amount"},
    "balance": {"balance", "closing balance", "running balance", "available balance"},
    "amount": {"amount", "transaction amount", "txn amount"},
    "direction": {"dr cr", "cr dr", "type", "transaction type", "debit credit"},
    "reference": {"reference", "reference no", "ref no", "cheque no", "chq no", "chq ref no"},
}


def header_map(row):
    out = {}
    for i, cell in enumerate(row):
        val = normal(cell or "")
        val = re.sub(r"\s+(?:inr|rs)$", "", val)
        for key, aliases in ALIASES.items():
            if val in aliases and key not in out:
                out[key] = i
    if {"date", "narration", "balance"} <= out.keys() and ("amount" in out or {"debit", "credit"} <= out.keys()):
        return out
    return None


class HTMLTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row = []
        if tag in ("td", "th"): self.cell = []
        if tag == "br" and self.cell is not None: self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None: self.row.append("".join(self.cell).strip())
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def word_table(words):
    """Position-based fallback for borderless PDF/OCR tables; requires a detected header."""
    grouped = []
    def mid(w): return (w['top'] + w.get('bottom', w['top'])) / 2
    for w in sorted(words, key=lambda x: (mid(x), x['x0'])):
        if not grouped or abs(mid(grouped[-1][0]) - mid(w)) > 5:
            grouped.append([w])
        else:
            grouped[-1].append(w)
    for line in grouped:
        line.sort(key=lambda w: w['x0'])
    for start, line in enumerate(grouped):
        anchors = []
        i = 0
        while i < len(line):
            matched = False
            for width in (3, 2, 1):
                chunk = line[i:i + width]
                if len(chunk) != width: continue
                # A wide column gap must not merge "Debit" and "Credit" into "Dr/Cr".
                if any(b['x0'] - a.get('x1', a['x0'] + len(a['text'])*6) > 15 for a,b in zip(chunk,chunk[1:])):
                    continue
                label = normal(" ".join(w['text'] for w in chunk))
                if any(label in a for a in ALIASES.values()):
                    anchors.append((chunk[0]['x0'], label))
                    i += width
                    matched = True
                    break
            if not matched: i += 1
        if not header_map([x[1] for x in anchors]): continue
        # Each header's start is the boundary; numeric columns often align to the right.
        bounds = [anchors[0][0] - 8] + [a[0] - 8 for a in anchors[1:]]
        rows = [[a[1] for a in anchors]]
        for line2 in grouped[start + 1:]:
            cells = [""] * len(anchors)
            for w in line2:
                idx = max([i for i, left in enumerate(bounds) if w['x0'] >= left] or [0])
                cells[idx] += " " + w['text']
            rows.append([c.strip() for c in cells])
        return rows
    return []


def ocr_words(image):
    import subprocess
    import tempfile
    from PIL import ImageFilter, ImageOps
    image = ImageOps.exif_transpose(image).convert("L").filter(ImageFilter.MedianFilter(3))
    # Small-angle projection-profile deskew. No pixel-derived value is silently repaired.
    try:
        import numpy as np
        preview = image.copy()
        preview.thumbnail((1200, 1200))
        best, angle = -1, 0
        for a in range(-5, 6):
            arr = np.asarray(preview.rotate(a, expand=True, fillcolor=255)) < 170
            score = float(np.var(arr.sum(axis=1)))
            if score > best: best, angle = score, a
        image = image.rotate(angle, expand=True, fillcolor=255)
    except ImportError:
        pass
    with tempfile.TemporaryDirectory(prefix="kiwi-ocr-") as tmp:
        path = Path(tmp) / "page.png"
        image.save(path)
        try:
            result = subprocess.run(["tesseract", str(path), "stdout", "--psm", "6", "tsv"],
                                    capture_output=True, text=True, timeout=120, check=True)
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            raise UserError("OCR failed. Install tesseract-ocr and check image quality") from e
    return [{"text": r['text'], "x0": float(r['left']), "x1": float(r['left'])+float(r['width']),
             "top": float(r['top']), "bottom": float(r['top'])+float(r['height'])}
            for r in csv.DictReader(io.StringIO(result.stdout), delimiter='\t') if r.get('text', '').strip()]


def read_tables(path, password=None):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        raw = path.read_bytes()
        try: text = raw.decode("utf-8-sig")
        except UnicodeDecodeError: text = raw.decode("cp1252")
        try: dialect = csv.Sniffer().sniff(text[:8000], delimiters=",;\t|")
        except csv.Error: dialect = csv.excel_tab if suffix == '.tsv' else csv.excel
        return [list(csv.reader(io.StringIO(text), dialect))], "table"
    if suffix in (".html", ".htm") or (suffix == ".xls" and path.read_bytes()[:1000].lstrip().lower().startswith((b"<html", b"<table", b"<!doctype"))):
        parser = HTMLTable()
        parser.feed(path.read_text(encoding="utf-8-sig", errors="strict"))
        return [parser.rows], "table"
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try: return [[list(r) for r in s.values] for s in book.worksheets], "table"
        finally: book.close()
    if suffix == ".xls":
        import xlrd
        book = xlrd.open_workbook(path)
        tables = []
        for sheet in book.sheets():
            rows = []
            for ri in range(sheet.nrows):
                rows.append([xlrd.xldate_as_datetime(c.value, book.datemode) if c.ctype == xlrd.XL_CELL_DATE else c.value for c in sheet.row(ri)])
            tables.append(rows)
        return tables, "table"
    if suffix == '.pdf':
        import pdfplumber
        tables, used_ocr = [], False
        with pdfplumber.open(path, password=password) as pdf:
            if len(pdf.pages) > 150: raise UserError("Split PDFs longer than 150 pages")
            for page in pdf.pages:
                found = page.extract_tables() or []
                candidates = [t for t in found if any(header_map(r) for r in t[:30])]
                if candidates:
                    tables.extend(candidates)
                else:
                    words = page.extract_words()
                    if not words:
                        words = ocr_words(page.to_image(resolution=200).original)
                        used_ocr = True
                    table = word_table(words)
                    if not table:
                        raise UserError(f"Could not identify columns on PDF page {page.page_number}. Use a bank CSV/Excel export or a reviewed canonical CSV")
                    tables.append(table)
        return tables, "ocr" if used_ocr else "pdf"
    if suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"):
        from PIL import Image
        with Image.open(path) as image:
            if image.width * image.height > 40_000_000: raise UserError("Image exceeds 40 megapixels")
            table = word_table(ocr_words(image))
        if not table: raise UserError("OCR did not find a bank table. Use CSV or manually transcribe and verify")
        return [table], "ocr"
    raise UserError("Supported: CSV, TSV, XLSX, XLS, HTML, PDF, PNG, JPG, TIFF and WebP")


def narration_parts(text):
    upi = re.search(r"[\w.+-]+@[\w.-]+", text)
    ifsc = re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", text.upper())
    channel = re.search(r"\b(UPI|NEFT|IMPS|RTGS|ATM|CHEQUE|CHQ)\b", text.upper())
    ref = re.search(r"\b\d{10,22}\b", text)
    parts = [p.strip() for p in re.split(r"[/|]", text) if p.strip()]
    candidates = [p for p in parts if len(p) > 2 and not re.fullmatch(r"[\d\W]+", p) and '@' not in p
                  and normal(p) not in {"upi", "neft", "imps", "rtgs", "dr", "cr", "to", "by"}]
    party = normal(candidates[0] if candidates else text)
    return {"party": party, "upi": upi[0].lower() if upi else "", "ifsc": ifsc[0] if ifsc else "",
            "reference": ref[0] if ref else "", "channel": channel[0] if channel else ""}


def parse_tables(tables, opening, closing, kind="table"):
    records, issues = [], []
    for table_no, table in enumerate(tables, 1):
        mapping = None
        skip_header_row = None
        for n, raw in enumerate(table, 1):
            raw = list(raw)
            if n == skip_header_row:
                continue
            h = header_map(raw)
            if h:
                mapping = h
                continue
            if not mapping:
                # Some banks split column titles across two rows.
                if n < len(table):
                    nxt = table[n]
                    combined = [f"{raw[i] or ''} {nxt[i] or ''}" for i in range(min(len(raw), len(nxt)))]
                    mapping = header_map(combined)
                    if mapping:
                        skip_header_row = n + 1
                continue
            def cell(key):
                i = mapping.get(key)
                return str(raw[i]).strip() if i is not None and i < len(raw) and raw[i] is not None else ""
            if not any(str(c or '').strip() for c in raw): continue
            if header_map(raw): continue
            joined = normal(" ".join(str(x or '') for x in raw))
            if joined.startswith(("opening balance", "closing balance", "total", "page ", "statement summary")):
                continue
            # A continuation may contain narration only. Never silently drop a numeric row.
            has_numbers = any(cell(k) for k in ("debit", "credit", "amount", "balance"))
            if not cell('date') and not has_numbers and records and cell('narration'):
                records[-1]['narration'] += " " + cell('narration')
                continue
            try:
                day = iso_date(cell('date'))
                balance = money(cell('balance'), blank=None)
                if balance is None: raise UserError("Missing running balance")
                if 'amount' in mapping:
                    amount = abs(money(cell('amount')))
                    direction = normal(cell('direction'))
                    if direction in ('dr', 'debit', 'withdrawal'): debit, credit = amount, 0
                    elif direction in ('cr', 'credit', 'deposit'): debit, credit = 0, amount
                    else: debit, credit = None, None
                else:
                    debit, credit = money(cell('debit')), money(cell('credit'))
                    amount = 0
                    if debit < 0 or credit < 0: raise UserError("Debit and credit columns must be positive")
                records.append(dict(day=day, narration=cell('narration'), debit=debit, credit=credit,
                    amount=amount, balance=balance, reference=cell('reference'), issues=[]))
            except UserError as e:
                issues.append(f"Table {table_no}, row {n}: {e}")
        if not mapping:
            issues.append(f"Table {table_no}: no supported header found")
    if not records: raise UserError("No transaction rows found. Required: Date, Narration, Debit, Credit, Balance")
    days = [r['day'] for r in records]
    if days == sorted(days, reverse=True) and days != sorted(days):
        records.reverse()
    elif days != sorted(days):
        issues.append("Dates are out of order; provide a chronological statement")
    previous = opening
    for r in records:
        if r['debit'] is None:
            delta = r['balance'] - previous
            r['debit'], r['credit'] = (r['amount'], 0) if delta < 0 else (0, r['amount'])
            r['issues'].append("Direction inferred from running balance; verify against source")
        if r['debit'] and r['credit']:
            r['issues'].append("BLOCK: both debit and credit are nonzero")
        if r['debit'] == r['credit'] == 0:
            r['issues'].append("BLOCK: zero amount transaction")
        if previous + r['credit'] - r['debit'] != r['balance']:
            r['issues'].append("BLOCK: running balance does not reconcile")
        if kind == 'ocr': r['issues'].append("OCR: verify date, narration and every amount against the image")
        previous = r['balance']
    if previous != closing: issues.append("Closing balance does not equal the last row")
    if opening + sum(r['credit'] - r['debit'] for r in records) != closing:
        issues.append("Opening plus credits minus debits does not equal closing balance")
    return records, issues


def suggest(con, text, cfg):
    parts = narration_parts(text)
    for r in con.execute("SELECT * FROM rules ORDER BY priority,id"):
        if normal(r['pattern']) in normal(text): return r['ledger'], "firm rule"
    for key in (parts['upi'], parts['party']):
        m = con.execute("SELECT ledger FROM memory WHERE party=?", (key,)).fetchone()
        if m: return m[0], "previous correction"
    names = [r[0] for r in con.execute("SELECT name FROM ledgers")]
    for pattern, ledger in (("bank charge", "Bank Charges"), ("interest", "Interest"), ("atm", "Cash")):
        if pattern in normal(text) and ledger in names: return ledger, "category"
    matches = sorted(((SequenceMatcher(None, parts['party'], normal(n)).ratio(), n) for n in names), reverse=True)
    if matches and matches[0][0] >= .72: return matches[0][1], "name similarity"
    return "", "needs ledger selection"


def import_statement(store, client, path, account, opening, closing, password=None):
    if not account.strip(): raise UserError("Bank ledger name is required")
    path = Path(path)
    if path.stat().st_size > 25 * 1024 * 1024: raise UserError("Maximum file size is 25 MB")
    filehash = digest(path.read_bytes())
    tables, kind = read_tables(path, password)
    rows, issues = parse_tables(tables, opening, closing, kind)
    sid = uuid.uuid4().hex
    cfg = store.config(client)
    with store.connect(client) as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT id FROM statements WHERE hash=?", (filehash,)).fetchone():
            raise UserError("This statement file was already imported")
        con.execute("INSERT INTO statements VALUES(?,?,?,?,?,?,?,?,?)",
                    (sid, filehash, path.name, account.strip(), opening, closing, now(), json.dumps(issues), kind))
        con.execute("INSERT OR IGNORE INTO ledgers VALUES(?, 'Bank Accounts')", (account.strip(),))
        for i, row in enumerate(rows, 1):
            parts = narration_parts(row['narration'])
            if row['reference']: parts['reference'] = row['reference']
            fp = digest(json.dumps([normal(account), row['day'], normal(row['narration']), row['debit'], row['credit'], row['balance']]).encode())
            duplicate = bool(con.execute("SELECT 1 FROM entries WHERE fingerprint=? AND excluded=0", (fp,)).fetchone())
            ledger, reason = suggest(con, row['narration'], cfg)
            con.execute("""INSERT INTO entries(statement_id,position,day,narration,debit,credit,balance,party,upi,ifsc,reference,channel,fingerprint,ledger,reason,duplicate,issues)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (sid, i, row['day'], row['narration'], row['debit'], row['credit'], row['balance'],
                parts['party'], parts['upi'], parts['ifsc'], parts['reference'], parts['channel'], fp, ledger, reason, int(duplicate), json.dumps(row['issues'])))
        store.event(con, "statement_imported", {"id": sid, "rows": len(rows), "issues": len(issues)})
    return sid


def review_entry(store, client, entry_id, ledger, exclude=False, duplicate_override=False):
    with store.connect(client) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        if not row: raise UserError("Entry not found")
        if con.execute("SELECT 1 FROM batches WHERE statement_id=?", (row['statement_id'],)).fetchone():
            raise UserError("An XML batch already freezes this statement; edits are locked")
        if not exclude:
            if any(x.startswith('BLOCK:') for x in json.loads(row['issues'])):
                raise UserError("Balance or amount errors cannot be approved. Correct the source and reimport")
            if not con.execute("SELECT 1 FROM ledgers WHERE name=?", (ledger,)).fetchone():
                raise UserError("Add or import this ledger first")
            account = con.execute("SELECT account FROM statements WHERE id=?", (row['statement_id'],)).fetchone()[0]
            if ledger == account: raise UserError("Counter ledger cannot be the same bank account")
            if row['duplicate'] and not duplicate_override:
                raise UserError("Possible duplicate: exclude it or explicitly confirm it is a different transaction")
        con.execute("UPDATE entries SET ledger=?,approved=?,excluded=?,duplicate=? WHERE id=?",
                    (ledger, int(not exclude), int(exclude), 0 if duplicate_override else row['duplicate'], entry_id))
        if not exclude:
            for key in (row['upi'], row['party']):
                if key: con.execute("INSERT INTO memory VALUES(?,?) ON CONFLICT(party) DO UPDATE SET ledger=excluded.ledger", (key, ledger))
            # Suggest on matching unreviewed rows; a human still approves each row.
            con.execute("UPDATE entries SET ledger=?,reason='correction for same party' WHERE party=? AND approved=0 AND statement_id NOT IN (SELECT statement_id FROM batches)", (ledger, row['party']))
        store.event(con, "entry_reviewed", {"id": entry_id, "ledger": ledger, "excluded": exclude, "duplicate_override": duplicate_override})
