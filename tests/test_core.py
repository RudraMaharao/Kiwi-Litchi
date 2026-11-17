import base64
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from kiwi_litchi.common import UserError, money, rupees, iso_date, local_url, write_json
from kiwi_litchi.db import Store
from kiwi_litchi.demo import seed, demo_xml
from kiwi_litchi.ingest import parse_tables, import_statement, review_entry, read_tables, narration_parts
from kiwi_litchi.tally import make_batch, parse_xml, import_books, send_batch, undo_xml, export_request
from kiwi_litchi.intelligence import book_answer, parse_question, audit, embed_books, predict, evaluate, unit, pack, nearest
from kiwi_litchi.law import import_law, search_law, index_law, law_db, Qdrant
from kiwi_litchi.operations import backup, restore, batch, watch_once
from kiwi_litchi.web import Application, set_password

ROOT=Path(__file__).resolve().parents[1]
HEADER=['Date','Narration','Debit','Credit','Balance']


class FakeModel:
    stamp='test@immutable'
    def embed(self,texts,query=False):
        return [unit([1 if 'Mehta' in t else 0.01,1 if 'rent' in t else 0.01,1 if 'Asha' in t else 0.01]) for t in texts]
    def unload(self): pass


class MoneyTests(unittest.TestCase):
    def test_indian_format(self): self.assertEqual(money('₹1,23,456.78'),12345678)
    def test_no_float_rounding(self): self.assertEqual(money('0.29'),29)
    def test_negative_balance(self): self.assertEqual(money('12,345.00 Dr'),-1234500)
    def test_parentheses(self): self.assertEqual(money('(100.01)'),-10001)
    def test_reject_fractional_paise(self):
        with self.assertRaises(UserError): money('0.001')
    def test_reject_nan(self):
        for x in ('NaN','Infinity','abc','1e100'):
            with self.assertRaises(UserError): money(x)
    def test_format(self): self.assertEqual(rupees(-109),'-1.09')
    def test_day_first(self): self.assertEqual(iso_date('04/05/2026'),'2026-05-04')
    def test_impossible_date(self):
        with self.assertRaises(UserError): iso_date('31/02/2026')
    def test_local_only(self):
        for url in ('https://api.example.com','http://8.8.8.8','http://user:pass@localhost:123','http://localhost:1?x=1','http://169.254.169.254'):
            with self.assertRaises(UserError): local_url(url)
        self.assertEqual(local_url('http://127.0.0.1:6333'),'http://127.0.0.1:6333')
        self.assertEqual(local_url('http://192.168.1.5:9000',True),'http://192.168.1.5:9000')


class ParserTests(unittest.TestCase):
    def test_running_balance(self):
        rows,issues=parse_tables([[HEADER,['01/10/2026','Paid','10','','90']]],10000,9000)
        self.assertFalse(issues); self.assertFalse(rows[0]['issues'])
    def test_bad_balance_not_repaired(self):
        rows,issues=parse_tables([[HEADER,['01/10/2026','Paid','11','','90']]],10000,9000)
        self.assertTrue(issues); self.assertEqual(rows[0]['debit'],1100); self.assertTrue(rows[0]['issues'][0].startswith('BLOCK'))
    def test_missing_row_is_not_skipped(self):
        rows,issues=parse_tables([[HEADER,['01/10/2026','Paid','10','','90'],['bad date','Paid','10','','80']]],10000,8000)
        self.assertTrue(any('date' in s for s in issues))
    def test_direction_inference_requires_review(self):
        rows,issues=parse_tables([[['Date','Narration','Amount','Balance'],['01/10/2026','Paid','10','90']]],10000,9000)
        self.assertEqual(rows[0]['debit'],1000); self.assertTrue(rows[0]['issues']); self.assertFalse(issues)
    def test_reverse_statement(self):
        rows,issues=parse_tables([[HEADER,['02/10/2026','B','10','','80'],['01/10/2026','A','10','','90']]],10000,8000)
        self.assertEqual(rows[0]['narration'],'A'); self.assertFalse(issues); self.assertTrue(all(not r['issues'] for r in rows))
    def test_multiline_narration(self):
        rows,issues=parse_tables([[HEADER,['01/10/2026','UPI','10','','90'],['','Mehta','','','']]],10000,9000)
        self.assertEqual(rows[0]['narration'],'UPI Mehta'); self.assertFalse(issues)
    def test_ocr_is_flagged(self):
        rows,_=parse_tables([[HEADER,['01/10/2026','Paid','10','','90']]],10000,9000,'ocr')
        self.assertTrue(any('OCR' in s for s in rows[0]['issues']))
    def test_both_sides_block(self):
        rows,_=parse_tables([[HEADER,['01/10/2026','Paid','20','10','90']]],10000,9000)
        self.assertTrue(rows[0]['issues'][0].startswith('BLOCK'))
    def test_source_adapters(self):
        tables,kind=read_tables(ROOT/'examples/demo-statement.csv')
        rows,issues=parse_tables(tables,1000000,1735000,kind)
        self.assertEqual(len(rows),3); self.assertFalse(issues)
    def test_narration(self):
        p=narration_parts('UPI/Mehta Hardware/mehta@ybl/123456789012')
        self.assertEqual(p['upi'],'mehta@ybl'); self.assertEqual(p['party'],'mehta hardware')


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.tmp.name)/'data'); seed(self.store)
    def tearDown(self): self.tmp.cleanup()
    def statement(self): return import_statement(self.store,'demo',ROOT/'examples/demo-statement.csv','Demo Bank',1000000,1735000)
    def approve(self,sid):
        with self.store.connect('demo') as con: rows=list(con.execute('SELECT id,ledger FROM entries WHERE statement_id=?',(sid,)))
        for r in rows: review_entry(self.store,'demo',r['id'],r['ledger'])


class WorkflowTests(StoreCase):
    def test_client_path_traversal(self):
        with self.assertRaises(UserError): self.store.client_path('../demo')
    def test_statement_dedupe(self):
        self.statement()
        with self.assertRaises(UserError): self.statement()
    def test_overlap_is_flagged(self):
        self.statement()
        p=Path(self.tmp.name)/'overlap.csv'; p.write_text((ROOT/'examples/demo-statement.csv').read_text()+'\n')
        sid=import_statement(self.store,'demo',p,'Demo Bank',1000000,1735000)
        with self.store.connect('demo') as con:
            rows=list(con.execute('SELECT * FROM entries WHERE statement_id=?',(sid,)))
        self.assertTrue(all(r['duplicate'] for r in rows))
        with self.assertRaises(UserError): review_entry(self.store,'demo',rows[0]['id'],rows[0]['ledger'])
    def test_cannot_export_unreviewed(self):
        with self.assertRaises(UserError): make_batch(self.store,'demo',self.statement())
    def test_balanced_xml_and_frozen_repeat(self):
        sid=self.statement(); self.approve(sid); batch=make_batch(self.store,'demo',sid)
        root=parse_xml(batch['xml']); vouchers=root.findall('.//VOUCHER')
        self.assertEqual(len(vouchers),3)
        for v in vouchers: self.assertEqual(sum(money(e.findtext('AMOUNT')) for e in v.findall('ALLLEDGERENTRIES.LIST')),0)
        self.assertEqual(money(vouchers[0].findtext('ALLLEDGERENTRIES.LIST/AMOUNT')),250000)
        self.assertEqual(make_batch(self.store,'demo',sid)['xml'],batch['xml'])
        with self.assertRaises(UserError): review_entry(self.store,'demo',1,'Cash')
    def test_wrong_closing_blocks(self):
        sid=import_statement(self.store,'demo',ROOT/'examples/demo-statement.csv','Demo Bank',1000000,1735001)
        self.approve(sid)
        with self.assertRaises(UserError): make_batch(self.store,'demo',sid)
    def test_wrong_amount_cannot_be_approved(self):
        path=Path(self.tmp.name)/'bad.csv';path.write_text('Date,Narration,Debit,Credit,Balance\n01/10/2026,Paid,11,,90\n')
        sid=import_statement(self.store,'demo',path,'Demo Bank',10000,9000)
        with self.store.connect('demo') as con: row=con.execute('SELECT id FROM entries WHERE statement_id=?',(sid,)).fetchone()
        with self.assertRaises(UserError): review_entry(self.store,'demo',row['id'],'Mehta Hardware')
    def test_exclusion_cannot_hide_bad_balance(self):
        path=Path(self.tmp.name)/'bad.csv';path.write_text('Date,Narration,Debit,Credit,Balance\n01/10/2026,Paid,11,,90\n02/10/2026,Paid,9,,80\n')
        sid=import_statement(self.store,'demo',path,'Demo Bank',10000,8000)
        with self.store.connect('demo') as con: ids=[r[0] for r in con.execute('SELECT id FROM entries WHERE statement_id=?',(sid,))]
        for i in ids: review_entry(self.store,'demo',i,'',exclude=True)
        with self.assertRaises(UserError): make_batch(self.store,'demo',sid)
    def test_same_bank_cannot_be_counterledger(self):
        self.statement()
        with self.assertRaises(UserError): review_entry(self.store,'demo',1,'Demo Bank')
    def test_post_timeout_is_uncertain_and_no_retry(self):
        sid=self.statement();self.approve(sid);b=make_batch(self.store,'demo',sid)
        with patch('kiwi_litchi.tally.http',side_effect=TimeoutError('test timeout')):
            result=send_batch(self.store,'demo',b['id'],'Demo Trading Company')
        self.assertEqual(result['state'],'uncertain')
        with self.assertRaises(UserError): send_batch(self.store,'demo',b['id'],'Demo Trading Company')
    def test_partial_post_is_uncertain(self):
        sid=self.statement();self.approve(sid);b=make_batch(self.store,'demo',sid)
        with patch('kiwi_litchi.tally.http',return_value=b'<RESPONSE><CREATED>1</CREATED><ERRORS>1</ERRORS></RESPONSE>'):
            self.assertEqual(send_batch(self.store,'demo',b['id'],'Demo Trading Company')['state'],'uncertain')
    def test_post_confirmation(self):
        sid=self.statement();self.approve(sid);b=make_batch(self.store,'demo',sid)
        with self.assertRaises(UserError): send_batch(self.store,'demo',b['id'],'Wrong company')
    def test_undo_only_batch_guids(self):
        sid=self.statement();self.approve(sid);b=make_batch(self.store,'demo',sid)
        v=parse_xml(undo_xml(self.store,'demo',b['id'])).findall('.//VOUCHER')
        self.assertTrue(all(x.get('ACTION')=='Delete' and x.get('TAGVALUE')==x.findtext('GUID') for x in v))
    def test_xml_external_entities(self):
        with self.assertRaises(UserError): parse_xml(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')
    def test_sync_idempotent_and_sql_totals(self):
        import_books(self.store,'demo',demo_xml())
        with self.store.connect('demo') as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0],39)
        r=book_answer(self.store,'demo',question='Mehta Hardware ko FY 2026-27 kitna gaya?')
        self.assertEqual(r['total_paise'],1750000); self.assertEqual(len(r['vouchers']),7)
        self.assertEqual(sum(v['amount_paise'] for v in r['vouchers']),r['total_paise'])
    def test_receipts_sign(self):
        r=book_answer(self.store,'demo',question='Receipts from Asha Stores FY 2026-27')
        self.assertEqual(r['total_paise'],7000000)
    def test_unbalanced_book_import_rolls_back(self):
        raw=demo_xml().replace(b'-2500.00',b'-2501.00',1)
        with self.assertRaises(UserError): import_books(self.store,'demo',raw)
        self.assertEqual(book_answer(self.store,'demo',question='Payments Mehta Hardware FY 2026-27')['total_paise'],1750000)
    def test_no_ledger_injection(self):
        with self.assertRaises(UserError): book_answer(self.store,'demo',intent={'ledger':"' OR 1=1 --",'measure':'payments','start':'2026-04-01','end':'2027-03-31'})
    def test_ambiguous_name(self):
        with self.store.connect('demo') as con: con.execute("INSERT INTO ledgers VALUES('Mehta Sons','Sundry Creditors')")
        with self.assertRaises(UserError): book_answer(self.store,'demo',question='Mehta ko FY 2026-27 kitna gaya')
    def test_unknown_period(self):
        with self.assertRaises(UserError): book_answer(self.store,'demo',question='How much paid Mehta Hardware last week')
    def test_invalid_financial_year(self):
        with self.assertRaises(UserError): parse_question('Mehta paid FY 2026-29',['Mehta'])
    def test_no_books_leak_between_clients(self):
        self.store.create_client('other','Other')
        with self.store.connect('other') as con: con.execute("INSERT INTO ledgers VALUES('Mehta Hardware','Sundry Creditors')")
        self.assertEqual(book_answer(self.store,'other',question='Payments Mehta Hardware FY 2026-27')['total_paise'],0)
    def test_vectors_and_holdout(self):
        model=FakeModel();r=embed_books(self.store,'demo',model)
        self.assertEqual(r['embedded'],39);self.assertEqual(embed_books(self.store,'demo',model)['embedded'],0)
        p=predict(self.store,'demo','Mehta Hardware','2026-10-01',model)
        self.assertEqual(p['suggestions'][0]['ledger'],'Mehta Hardware');self.assertTrue(p['requires_review'])
        self.assertTrue(all(n['day']<'2026-10-01' for n in p['neighbours']))
        result=evaluate(self.store,'demo','2026-10',model)
        self.assertEqual(result['top1_accuracy'],1);self.assertEqual(result['n'],3);self.assertEqual(result['ready_coverage'],0)
    def test_sync_invalidates_embeddings(self):
        embed_books(self.store,'demo',FakeModel());import_books(self.store,'demo',demo_xml())
        with self.store.connect('demo') as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0],0)
    def test_missing_legal_configuration_reported(self):
        r=audit(self.store,'demo');self.assertEqual(len(r['skipped']),2)
    def test_backup_and_restore(self):
        folder=backup(self.store);target=Store(Path(self.tmp.name)/'restored');restore(target,folder)
        self.assertEqual(book_answer(target,'demo',question='Mehta Hardware payments FY 2026-27')['total_paise'],1750000)
        with self.assertRaises(UserError): restore(self.store,folder)
    def test_tampered_backup_rejected(self):
        folder=backup(self.store);(folder/'demo/config.json').write_text('{}')
        with self.assertRaises(UserError): restore(Store(Path(self.tmp.name)/'new'),folder)
    def test_nightly_without_models(self):
        r=batch(self.store);self.assertFalse(r['errors']);self.assertTrue((self.store.client_path('demo')/'reports/latest.json').exists())
    def test_export_filter(self):
        r=parse_xml(export_request('A & B','Voucher','2026-04-01','2027-03-31'))
        self.assertEqual(r.findtext('.//SVCURRENTCOMPANY'),'A & B');self.assertIsNotNone(r.find('.//FILTER'))


class LawTests(StoreCase):
    def test_demo_separate_from_real(self):
        import_law(self.store,ROOT/'examples/law-demo.jsonl',True)
        self.assertFalse(search_law(self.store,'receipts',hybrid=False)['sources'])
        r=search_law(self.store,'receipts',on='2026-10-01',hybrid=False,demo=True)
        self.assertEqual(len(r['sources']),1);self.assertIn('fictional',r['sources'][0]['text'])
    def test_temporal_filter(self):
        import_law(self.store,ROOT/'examples/law-demo.jsonl',True)
        self.assertFalse(search_law(self.store,'receipts',on='2025-10-01',hybrid=False,demo=True)['sources'])
        self.assertFalse(search_law(self.store,'receipts',on='2027-10-01',hybrid=False,demo=True)['sources'])
    def test_reimport_deduplicates(self):
        for _ in range(2):import_law(self.store,ROOT/'examples/law-demo.jsonl',True)
        with law_db(self.store) as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM law_fts').fetchone()[0],1)
    def test_unreviewed_source_rejected(self):
        p=Path(self.tmp.name)/'law.jsonl';p.write_text((ROOT/'examples/law-demo.jsonl').read_text().replace('true','false'))
        with self.assertRaises(UserError):import_law(self.store,p)
    def test_qdrant_index_and_query(self):
        import_law(self.store,ROOT/'examples/law-demo.jsonl',True)
        class Backend:
            def create(self,c,d):self.collection=c
            def upsert(self,c,points):self.points=points
            def query(self,c,v,on,act,demo):return [{'id':p['id'],'score':.9} for p in self.points]
        backend=Backend();index_law(self.store,engine=FakeModel(),backend=backend)
        r=search_law(self.store,'receipts',on='2026-10-01',demo=True,engine=FakeModel(),backend=backend)
        self.assertEqual(r['mode'],'BM25 + Qdrant');self.assertEqual(len(r['sources']),1)
        self.assertTrue(backend.points[0]['payload']['demo'])
    def test_qdrant_unavailable_falls_back(self):
        import_law(self.store,ROOT/'examples/law-demo.jsonl',True)
        with law_db(self.store) as con:con.execute("INSERT INTO law_meta VALUES('active_qdrant',?)",(json.dumps({'model':'test@immutable','embedding_model':'test','collection':'demo'}),))
        with patch.object(Qdrant,'query',side_effect=ConnectionError('offline')):
            r=search_law(self.store,'receipts',on='2026-10-01',demo=True,engine=FakeModel())
        self.assertTrue(r['sources']);self.assertEqual(r['mode'],'BM25');self.assertTrue(r['notes'])


class WebTests(StoreCase):
    def setUp(self):
        super().setUp();set_password(self.store,'test-password-12345');self.app=Application(self.store);self.cookie='';self.csrf=''
    def request(self,path,body=None,csrf=None,origin=None,host='127.0.0.1:8765'):
        raw=json.dumps(body).encode() if body is not None else b''
        env={'REQUEST_METHOD':'POST' if body is not None else 'GET','PATH_INFO':path,'QUERY_STRING':'','HTTP_HOST':host,
             'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_COOKIE':self.cookie,'HTTP_X_CSRF_TOKEN':self.csrf if csrf is None else csrf}
        if origin: env['HTTP_ORIGIN']=origin
        captured={}
        def start(status,headers): captured.update(status=status,headers=dict(headers))
        raw=b''.join(self.app(env,start));captured['body']=raw
        if captured['headers']['Content-Type'].startswith('application/json'):captured['json']=json.loads(raw)
        return captured
    def login(self):
        r=self.request('/api/login',{'password':'test-password-12345'});self.cookie=r['headers']['Set-Cookie'].split(';')[0];self.csrf=r['json']['csrf']
    def test_auth_required(self):self.assertEqual(self.request('/api/clients')['status'],'401 Unauthorized')
    def test_login_and_client(self):
        self.login();self.assertEqual(self.request('/api/clients')['json'][0]['id'],'demo')
    def test_csrf_required(self):
        self.login();self.assertEqual(self.request('/api/c/demo/audit',{},csrf='wrong')['status'],'400 Bad Request')
    def test_dns_rebinding_blocked(self):self.assertEqual(self.request('/',host='evil.example:8765')['status'],'400 Bad Request')
    def test_cross_origin_blocked(self):self.assertEqual(self.request('/api/login',{'password':'test-password-12345'},origin='http://evil.example')['status'],'400 Bad Request')
    def test_no_static_file_traversal(self):
        self.login();self.assertEqual(self.request('/../../auth.json')['status'],'404 Not Found')
    def test_upload_and_query(self):
        self.login();content=base64.b64encode((ROOT/'examples/demo-statement.csv').read_bytes()).decode()
        r=self.request('/api/c/demo/import',{'filename':'statement.csv','content':content,'account':'Demo Bank','opening':'10000','closing':'17350'})
        self.assertEqual(r['status'],'200 OK');self.assertTrue(r['json']['id'])
        q=self.request('/api/c/demo/ask',{'question':'Mehta Hardware payments FY 2026-27'})
        self.assertEqual(q['json']['total_paise'],1750000)
    def test_no_password_in_summary(self):
        self.login();self.assertNotIn('auth',self.request('/api/c/demo/summary')['body'].decode())


if __name__=='__main__':unittest.main()
