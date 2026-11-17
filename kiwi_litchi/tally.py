import json
import uuid
import xml.etree.ElementTree as ET
from bahi.tally import clean_reply
from .common import UserError, http, iso_date, money, rupees
from .db import now


def parse_xml(raw):
    if isinstance(raw, str): raw = raw.encode()
    if len(raw) > 50 * 1024 * 1024: raise UserError("XML exceeds 50 MB")
    # Tally emits UTF-16 as well as UTF-8; inspect decoded input before parsing.
    text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise UserError("DTD and entity declarations are not allowed")
    # Native Tally exports contain XML 1.0-invalid control references such as
    # &#4; in enum fields. Use the same narrow cleanup as the Kiwi connector.
    try: return ET.fromstring(clean_reply(text))
    except ET.ParseError as e: raise UserError(f"Invalid XML: {e}") from e


def tag(parent, name, value):
    ET.SubElement(parent, name).text = str(value)


def envelope(company, report='Vouchers'):
    root = ET.Element('ENVELOPE')
    header = ET.SubElement(root, 'HEADER')
    tag(header, 'TALLYREQUEST', 'Import Data')
    data = ET.SubElement(ET.SubElement(root, 'BODY'), 'IMPORTDATA')
    desc = ET.SubElement(data, 'REQUESTDESC')
    tag(desc, 'REPORTNAME', report)
    tag(ET.SubElement(desc, 'STATICVARIABLES'), 'SVCURRENTCOMPANY', company)
    return root, ET.SubElement(data, 'REQUESTDATA')


def ledger_xml(store, client):
    cfg = store.config(client)
    root, data = envelope(cfg['company'], 'All Masters')
    with store.connect(client) as con:
        for row in con.execute("SELECT * FROM ledgers ORDER BY name"):
            ledger = ET.SubElement(ET.SubElement(data, 'TALLYMESSAGE'), 'LEDGER', NAME=row['name'], ACTION='Create')
            tag(ledger, 'NAME', row['name'])
            tag(ledger, 'PARENT', row['parent'])
            tag(ledger, 'ISBILLWISEON', 'No')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def make_batch(store, client, sid):
    cfg = store.config(client)
    with store.connect(client) as con:
        con.execute("BEGIN IMMEDIATE")
        old = con.execute("SELECT * FROM batches WHERE statement_id=?", (sid,)).fetchone()
        if old: return dict(old)
        stmt = con.execute("SELECT * FROM statements WHERE id=?", (sid,)).fetchone()
        if not stmt: raise UserError("Statement not found")
        if json.loads(stmt['issues']): raise UserError("Statement has unresolved parsing or closing-balance errors")
        rows = con.execute("SELECT * FROM entries WHERE statement_id=? ORDER BY position", (sid,)).fetchall()
        # Exclusion handles genuine overlaps only; it must not hide a broken balance proof.
        if any(any(x.startswith('BLOCK:') for x in json.loads(r['issues'])) for r in rows):
            raise UserError("A row fails reconciliation; correct the statement before exporting")
        rows = [r for r in rows if not r['excluded']]
        if not rows: raise UserError("No included rows")
        if any(not r['approved'] or r['duplicate'] or not r['ledger'] for r in rows):
            raise UserError("Review every included row and resolve duplicate flags first")
        batch = uuid.uuid4().hex
        root, data = envelope(cfg['company'])
        for r in rows:
            group = con.execute("SELECT parent FROM ledgers WHERE name=?", (r['ledger'],)).fetchone()
            contra = group and group[0] in ('Bank Accounts', 'Cash-in-Hand')
            kind = 'Contra' if contra else ('Payment' if r['debit'] else 'Receipt')
            # Stable GUID, tied to a reviewed row. Exporting again returns the frozen batch.
            guid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kiwi:{client}:{sid}:{r['id']}"))
            v = ET.SubElement(ET.SubElement(data, 'TALLYMESSAGE'), 'VOUCHER', VCHTYPE=kind, ACTION='Create', OBJVIEW='Accounting Voucher View')
            for key, val in [('DATE', r['day'].replace('-', '')), ('GUID', guid), ('REMOTEID', guid),
                             ('VOUCHERTYPENAME', kind), ('PERSISTEDVIEW', 'Accounting Voucher View'),
                             ('NARRATION', f"{r['narration']} [Kiwi {batch}]"), ('ISINVOICE', 'No')]:
                tag(v, key, val)
            # Tally XML: debit is negative, credit is positive. Bank payment credits bank.
            bank_amount = r['debit'] - r['credit']
            for name, amount in ((stmt['account'], bank_amount), (r['ledger'], -bank_amount)):
                entry = ET.SubElement(v, 'ALLLEDGERENTRIES.LIST')
                tag(entry, 'LEDGERNAME', name)
                tag(entry, 'ISDEEMEDPOSITIVE', 'Yes' if amount < 0 else 'No')
                tag(entry, 'AMOUNT', rupees(amount))
        xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        con.execute("INSERT INTO batches(id,statement_id,created,xml) VALUES(?,?,?,?)", (batch, sid, now(), xml))
        store.event(con, 'batch_exported', {'id': batch, 'vouchers': len(rows)})
        return dict(con.execute("SELECT * FROM batches WHERE id=?", (batch,)).fetchone())


def send_batch(store, client, batch_id, confirmation):
    cfg = store.config(client)
    if confirmation != cfg['company']: raise UserError("Confirmation must exactly match the Tally company name")
    with store.connect(client) as con:
        con.execute('BEGIN IMMEDIATE')
        batch = con.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not batch: raise UserError("Batch not found")
        if batch['state'] != 'exported': raise UserError("Batch already attempted. Reconcile in Tally before any manual retry")
        # Commit the attempt BEFORE the network request. A timeout may have posted some/all entries.
        con.execute("UPDATE batches SET state='uncertain' WHERE id=?", (batch_id,))
        store.event(con, 'posting_attempt', {'batch': batch_id, 'company': cfg['company']})
    try:
        response = http(cfg['tally_url'], batch['xml'], xml=True, timeout=60, allow_lan=True)
        root = parse_xml(response)
        created = int(root.findtext('.//CREATED', '0'))
        errors = int(root.findtext('.//ERRORS', '0'))
        expected = len(parse_xml(batch['xml']).findall('.//VOUCHER'))
        state = 'posted' if created == expected and not errors and root.find('.//LINEERROR') is None else 'uncertain'
        message = response.decode('utf-8', errors='replace')
    except Exception as e:
        state, message = 'uncertain', str(e)
    with store.connect(client) as con:
        con.execute("UPDATE batches SET state=?,response=? WHERE id=?", (state, message, batch_id))
        store.event(con, 'posting_result', {'batch': batch_id, 'state': state})
    return {'state': state, 'response': message}


def undo_xml(store, client, batch_id):
    """Produce a separately reviewed deletion file; never silently delete in Tally."""
    with store.connect(client) as con:
        row = con.execute('SELECT xml FROM batches WHERE id=?', (batch_id,)).fetchone()
    if not row: raise UserError('Batch not found')
    root = parse_xml(row[0])
    for v in root.findall('.//VOUCHER'):
        v.set('ACTION', 'Delete')
        v.set('TAGNAME', 'GUID')
        v.set('TAGVALUE', v.findtext('GUID'))
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def import_books(store, client, raw):
    root = parse_xml(raw)
    if root.find('.//LINEERROR') is not None: raise UserError(root.findtext('.//LINEERROR'))
    if root.findtext('.//HEADER/STATUS') == '0': raise UserError('Tally export failed')
    vouchers, ledger_count, deleted = 0, 0, 0
    with store.connect(client) as con:
        con.execute('BEGIN IMMEDIATE')
        for ledger in root.findall('.//LEDGER'):
            name = ledger.get('NAME') or ledger.findtext('NAME')
            if name:
                con.execute('INSERT INTO ledgers VALUES(?,?) ON CONFLICT(name) DO UPDATE SET parent=excluded.parent',
                            (name, ledger.findtext('PARENT', 'Unknown')))
                ledger_count += 1
        # CMPINFO/VOUCHER is a numeric summary, not an accounting object.
        counts = {id(v) for v in root.findall('.//CMPINFO/VOUCHER')}
        for v in root.findall('.//VOUCHER'):
            if id(v) in counts: continue
            guid = v.findtext('GUID') or v.get('REMOTEID') or v.findtext('MASTERID')
            if not guid: raise UserError('Voucher has no stable GUID/REMOTEID/MASTERID; cannot safely sync it')
            vid = 'tally:' + guid
            if v.findtext('ISCANCELLED', 'No').lower() == 'yes' or v.findtext('ISOPTIONAL', 'No').lower() == 'yes':
                con.execute('DELETE FROM vouchers WHERE id=?', (vid,))
                deleted += 1
                continue
            day = iso_date(v.findtext('DATE', ''))
            narration = v.findtext('NARRATION', '')
            lines = list(v.findall('ALLLEDGERENTRIES.LIST')) or list(v.findall('LEDGERENTRIES.LIST'))
            if not lines: raise UserError(f'Voucher {guid} has no supported ledger lines')
            parsed = []
            for line in lines:
                name = line.findtext('LEDGERNAME', '')
                if not name: raise UserError(f'Voucher {guid} has an unnamed ledger')
                parsed.append((name, -money(line.findtext('AMOUNT', ''))))
            if sum(p[1] for p in parsed) != 0: raise UserError(f'Voucher {guid} does not balance')
            # Transactionally replace altered voucher lines. Embeddings are invalidated.
            old_ids = [str(r[0]) for r in con.execute('SELECT id FROM lines WHERE voucher_id=?', (vid,))]
            for lid in old_ids: con.execute("DELETE FROM embeddings WHERE kind='line' AND item_id=?", (lid,))
            con.execute('DELETE FROM vouchers WHERE id=?', (vid,))
            con.execute('INSERT INTO vouchers VALUES(?,?,?,?,?,0)', (vid, day, v.findtext('VOUCHERTYPENAME', v.get('VCHTYPE', 'Journal')), narration, 'tally'))
            for name, amount in parsed:
                con.execute("INSERT OR IGNORE INTO ledgers VALUES(?, 'Unknown')", (name,))
                con.execute('INSERT INTO lines(voucher_id,ledger,amount,narration,party) VALUES(?,?,?,?,?)', (vid, name, amount, narration, v.findtext('PARTYLEDGERNAME', '')))
            vouchers += 1
        if not vouchers and not ledger_count and not deleted: raise UserError('No supported Tally masters or vouchers found')
        store.event(con, 'books_imported', {'vouchers': vouchers, 'ledgers': ledger_count, 'cancelled_or_optional': deleted})
    return {'vouchers': vouchers, 'ledgers': ledger_count, 'cancelled_or_optional': deleted}


def export_request(company, kind, start=None, end=None):
    root = ET.Element('ENVELOPE')
    h = ET.SubElement(root, 'HEADER')
    for k, v in [('VERSION', '1'), ('TALLYREQUEST', 'Export'), ('TYPE', 'Collection'), ('ID', 'KiwiCollection')]: tag(h, k, v)
    desc = ET.SubElement(ET.SubElement(root, 'BODY'), 'DESC')
    variables = ET.SubElement(desc, 'STATICVARIABLES')
    tag(variables, 'SVCURRENTCOMPANY', company)
    tag(variables, 'SVEXPORTFORMAT', '$$SysName:XML')
    if start: tag(variables, 'SVFROMDATE', iso_date(start).replace('-', ''))
    if end: tag(variables, 'SVTODATE', iso_date(end).replace('-', ''))
    msg = ET.SubElement(ET.SubElement(desc, 'TDL'), 'TDLMESSAGE')
    collection = ET.SubElement(msg, 'COLLECTION', NAME='KiwiCollection')
    tag(collection, 'TYPE', kind)
    tag(collection, 'FETCH', 'Name,Parent' if kind == 'Ledger' else 'GUID,MasterID,Date,VoucherTypeName,Narration,PartyLedgerName,IsCancelled,IsOptional,AllLedgerEntries.*')
    if kind == 'Voucher' and start and end:
        tag(collection, 'FILTER', 'KiwiDateFilter')
        ET.SubElement(msg, 'SYSTEM', TYPE='Formulae', NAME='KiwiDateFilter').text = '$Date >= ##SVFromDate AND $Date <= ##SVToDate'
    return ET.tostring(root, encoding='utf-8')


def pull_books(store, client, start, end):
    cfg = store.config(client)
    result = {}
    for kind in ('Ledger', 'Voucher'):
        raw = http(cfg['tally_url'], export_request(cfg['company'], kind, start, end), xml=True, allow_lan=True)
        result[kind] = import_books(store, client, raw)
    return result
