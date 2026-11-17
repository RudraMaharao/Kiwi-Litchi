import base64
import hashlib
import hmac
import json
import mimetypes
import secrets
import tempfile
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs
from .common import UserError, money, write_json
from .ingest import import_statement, review_entry
from .intelligence import audit, book_answer
from .law import search_law
from .tally import import_books, ledger_xml, make_batch


def set_password(store, password):
    if len(password) < 12: raise UserError('Use a password with at least 12 characters')
    salt = secrets.token_hex(24)
    hashed = hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()
    write_json(store.root/'auth.json',{'salt':salt,'hash':hashed})


class Application:
    def __init__(self, store, port=8765):
        self.store, self.port = store, port
        self.sessions, self.failures = {}, []
        self.lock = threading.Lock()
        self.authfile = store.root/'auth.json'
        if not self.authfile.exists(): raise UserError('Set a password first: python3 -m kiwi_litchi password')

    def __call__(self, env, start_response):
        headers = [('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),
                   ('Referrer-Policy','no-referrer'),('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'")]
        status, content_type = '200 OK','application/json; charset=utf-8'
        try:
            host = env.get('HTTP_HOST','')
            allowed = {f'127.0.0.1:{self.port}',f'localhost:{self.port}'}
            if host not in allowed: raise UserError('Unrecognised Host; open the localhost address printed in the terminal')
            method, path = env['REQUEST_METHOD'], env.get('PATH_INFO','/')
            if env.get('HTTP_ORIGIN') and env['HTTP_ORIGIN'] != 'http://'+host: raise UserError('Cross-origin requests are disabled')
            if env.get('HTTP_SEC_FETCH_SITE') == 'cross-site': raise UserError('Cross-site requests are disabled')
            data = {}
            if method == 'POST':
                if not env.get('CONTENT_TYPE','').startswith('application/json'): raise UserError('JSON request required')
                size = int(env.get('CONTENT_LENGTH') or 0)
                if size > 36*1024*1024: raise UserError('Request is too large')
                data = json.loads(env['wsgi.input'].read(size) or b'{}')
                if not isinstance(data,dict): raise UserError('Expected a JSON object')
            if path in ('/','/app.js','/style.css') and method == 'GET':
                name = 'index.html' if path == '/' else path[1:]
                body = (Path(__file__).parent/'static'/name).read_bytes()
                if name=='index.html' and env.get('SCRIPT_NAME'):
                    prefix=env['SCRIPT_NAME'].encode()
                    body=body.replace(b'href="/style.css"',b'href="'+prefix+b'/style.css"').replace(b'src="/app.js"',b'src="'+prefix+b'/app.js"')
                content_type = mimetypes.guess_type(name)[0] or 'text/plain'
            elif path == '/health' and method == 'GET':
                body = {'status':'ok','version':'0.1.0'}
            elif path == '/api/login' and method == 'POST':
                current = time.time()
                with self.lock:
                    self.failures = [t for t in self.failures if current-t < 300]
                    if len(self.failures) >= 10: raise UserError('Too many attempts. Wait five minutes')
                auth = json.loads(self.authfile.read_text())
                hashed = hashlib.pbkdf2_hmac('sha256',str(data.get('password','')).encode(),auth['salt'].encode(),600000).hex()
                if not hmac.compare_digest(auth['hash'],hashed):
                    with self.lock: self.failures.append(current)
                    raise UserError('Password is incorrect')
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                with self.lock:
                    self.sessions = {k:v for k,v in self.sessions.items() if current-v['at'] < 8*3600}
                    self.sessions[token] = {'at':current,'csrf':csrf}
                headers.append(('Set-Cookie',f'kiwi_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'))
                body = {'csrf':csrf}
            else:
                cookies = SimpleCookie(env.get('HTTP_COOKIE',''))
                token = cookies['kiwi_session'].value if 'kiwi_session' in cookies else ''
                with self.lock: session = self.sessions.get(token)
                if not session or time.time()-session['at'] > 8*3600:
                    status, body = '401 Unauthorized', {'error':'Please sign in'}
                else:
                    if method == 'POST' and not hmac.compare_digest(str(env.get('HTTP_X_CSRF_TOKEN','')),session['csrf']):
                        raise UserError('Missing or invalid form token; refresh and sign in again')
                    if path == '/api/session': body = {'csrf':session['csrf']}
                    elif path == '/api/logout' and method == 'POST':
                        with self.lock: self.sessions.pop(token,None)
                        headers.append(('Set-Cookie','kiwi_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'))
                        body = {'ok':True}
                    elif path == '/api/clients':
                        from .bridge import sync_clients
                        sync_clients(self.store)
                        if method == 'POST': self.store.create_client(data.get('id',''),data.get('name',''))
                        body = self.store.clients()
                    elif path.startswith('/api/c/'):
                        bits = path.split('/')
                        client, action = bits[3], '/'.join(bits[4:])
                        self.store.client_path(client)
                        body = self.client_api(client,action,method,data,parse_qs(env.get('QUERY_STRING','')))
                        if isinstance(body,bytes):
                            content_type = 'application/xml'
                            headers.append(('Content-Disposition','attachment; filename="kiwi-tally.xml"'))
                    elif path == '/api/law' and method == 'POST':
                        from .law import extract_answer
                        search=extract_answer if data.get('extract') else search_law
                        body = search(self.store,data.get('question',''),on=data.get('on'),act=data.get('act') or None,hybrid=bool(data.get('hybrid',False)))
                    else:
                        status, body = '404 Not Found', {'error':'Not found'}
        except (UserError,ValueError,KeyError,ImportError) as e:
            status, body = '400 Bad Request', {'error':str(e)}
        except Exception:
            import traceback
            traceback.print_exc()
            status, body = '500 Internal Server Error', {'error':'Operation failed. Check the terminal or service log'}
        if not isinstance(body,bytes): body = json.dumps(body,ensure_ascii=False).encode()
        headers += [('Content-Type',content_type),('Content-Length',str(len(body)))]
        start_response(status,headers)
        return [body]

    def client_api(self,client,action,method,data,query):
        store = self.store
        if action=='queue' and method=='GET':
            from .bridge import queue
            return queue(store,client)
        if action=='predict' and method=='POST':
            from .bridge import suggest_row
            return suggest_row(store,client,int(data['id']))
        if action=='apply-prediction' and method=='POST':
            from .bridge import apply_suggestion
            return apply_suggestion(store,client,int(data['id']),str(data['ledger']))
        if action == 'summary' and method == 'GET':
            from .bridge import sync_clients,linked_rules
            sync_clients(store)
            cfg=store.config(client)
            kiwi_stats=None
            if cfg.get('kiwi_client_id'):
                from .bridge import kiwi_db
                with kiwi_db(store) as k:
                    r=k.execute("SELECT COUNT(*) AS entries,SUM(status='review') AS review,SUM(status='posted') AS posted FROM txns WHERE client_id=?",(cfg['kiwi_client_id'],)).fetchone()
                    kiwi_stats=dict(r)
            with store.connect(client) as con:
                statements = [dict(r) for r in con.execute('SELECT s.*,COUNT(e.id) AS rows,SUM(e.approved) AS approved FROM statements s LEFT JOIN entries e ON e.statement_id=s.id GROUP BY s.id ORDER BY s.created DESC')]
                return {'config':cfg,'kiwi':kiwi_stats,'statements':statements,
                        'ledgers':[dict(r) for r in con.execute('SELECT * FROM ledgers ORDER BY name')],
                        'vouchers':con.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0],
                        'rules':linked_rules(store,client)}
        if action.startswith('statement/') and method == 'GET':
            sid = action.split('/')[1]
            with store.connect(client) as con:
                s = con.execute('SELECT * FROM statements WHERE id=?',(sid,)).fetchone()
                if not s: raise UserError('Statement not found')
                b = con.execute('SELECT id,state FROM batches WHERE statement_id=?',(sid,)).fetchone()
                return {'statement':dict(s),'entries':[dict(r) for r in con.execute('SELECT * FROM entries WHERE statement_id=? ORDER BY position',(sid,))], 'batch':dict(b) if b else None}
        if action == 'ledger' and method == 'POST':
            name, parent = str(data.get('name','')).strip(),str(data.get('parent','')).strip()
            if not name or not parent: raise UserError('Ledger name and Tally parent group required')
            from .bridge import save_ledger
            save_ledger(store,client,name,parent)
            return {'ok':True}
        if action == 'rule' and method == 'POST':
            from .bridge import save_rule
            save_rule(store,client,str(data.get('pattern','')),str(data.get('ledger','')),int(data.get('priority',10)))
            return {'ok':True}
        if action in ('import','import-books') and method == 'POST':
            raw = base64.b64decode(data.get('content',''),validate=True)
            if len(raw)>25*1024*1024: raise UserError('Maximum upload is 25 MB')
            if action == 'import-books': return import_books(store,client,raw)
            filename = Path(data.get('filename','statement.csv')).name
            if not filename or filename in ('.','..'): raise UserError('Invalid filename')
            with tempfile.TemporaryDirectory(prefix='kiwi-upload-') as tmp:
                path = Path(tmp)/filename
                path.write_bytes(raw)
                sid = import_statement(store,client,path,str(data.get('account','')),money(data.get('opening')),money(data.get('closing')),data.get('password') or None)
            return {'id':sid}
        if action == 'review' and method == 'POST':
            review_entry(store,client,int(data['id']),str(data.get('ledger','')),bool(data.get('exclude')),bool(data.get('duplicate_override')))
            return {'ok':True}
        if action == 'batch' and method == 'POST':
            b = make_batch(store,client,data['statement'])
            return {'id':b['id'],'state':b['state']}
        if action.startswith('batch/') and method == 'GET':
            with store.connect(client) as con:
                b = con.execute('SELECT xml FROM batches WHERE id=?',(action.split('/')[1],)).fetchone()
                if not b: raise UserError('Batch not found')
                return b[0]
        if action == 'masters' and method == 'GET': return ledger_xml(store,client)
        if action == 'ask' and method == 'POST':
            from .intelligence import model_intent
            intent=model_intent(store,client,data.get('question','')) if data.get('model_intent') else data.get('intent')
            return book_answer(store,client,question=data.get('question'),intent=intent)
        if action == 'audit' and method == 'POST': return audit(store,client)
        if action == 'report' and method == 'GET':
            p = store.client_path(client)/'reports/latest.json'
            return json.loads(p.read_text()) if p.exists() else {'note':'No nightly report yet. Run the audit or batch command.'}
        raise UserError('Unknown operation')


def serve(store, port=8765, dev=False):
    from .bridge import create_combined_app
    app = create_combined_app(store,port)
    print(f'Kiwi + Litchi: http://127.0.0.1:{port}',flush=True)
    if dev:
        from wsgiref.simple_server import make_server
        with make_server('127.0.0.1',port,app) as server: server.serve_forever()
    else:
        try: from waitress import serve as waitress_serve
        except ImportError as e: raise UserError('Run bash scripts/install-linux.sh, or use serve --dev for a local demo') from e
        waitress_serve(app,host='127.0.0.1',port=port,threads=4,max_request_body_size=36*1024*1024)
