"""Connect the original Kiwi/Bahi review workflow to Litchi without double-counting books."""
import json
from contextlib import contextmanager
from .common import UserError, write_json, digest
from .intelligence import predict, line_text


def kiwi_config(store):
    from bahi.config import load, init_home
    home = store.root/'kiwi'
    init_home(home)
    cfg = load(home)
    cfg.ensure_dirs()
    return cfg


@contextmanager
def kiwi_db(store):
    from bahi.db import connect
    con = connect(kiwi_config(store).db_path)
    try: yield con
    finally: con.close()


def sync_clients(store):
    """Share client identity, ledgers and rules. Do not turn unposted bank rows into vouchers."""
    from bahi import db
    synced = []
    with kiwi_db(store) as kiwi:
        for client in db.clients(kiwi):
            slug = f"kiwi-{client['id']}"
            if not (store.root/'clients'/slug/'config.json').exists(): store.create_client(slug,client['name'])
            cfg = store.config(slug)
            cfg.update(name=client['name'],company=client['tally_company'] or client['name'],kiwi_client_id=client['id'])
            tc = kiwi_config(store).tally
            host = tc.get('host','localhost')
            cfg['tally_url'] = f"http://{host}:{int(tc.get('port',9000))}"
            cfg['own_accounts'] = [r['tally_ledger'] for r in db.accounts(kiwi,client['id']) if r['tally_ledger']]
            write_json(store.client_path(slug)/'config.json',cfg)
            with store.connect(slug) as con:
                for ledger in db.ledgers(kiwi,client['id']):
                    parent = 'Bank Accounts' if ledger['kind']=='bank' else ('Cash-in-Hand' if ledger['kind']=='cash' else ledger['parent'] or 'Unknown')
                    con.execute('INSERT INTO ledgers VALUES(?,?) ON CONFLICT(name) DO UPDATE SET parent=excluded.parent',(ledger['name'],parent))
                for name in cfg['own_accounts']:con.execute("INSERT OR REPLACE INTO ledgers VALUES(?,'Bank Accounts')",(name,))
            synced.append(slug)
    return synced


def queue(store,client):
    cfg = store.config(client)
    if not cfg.get('kiwi_client_id'): return []
    with kiwi_db(store) as con:
        rows = [dict(r) for r in con.execute("""SELECT id,date,narration,amount,direction,party,vpa,ledger,map_source,check_status,status
          FROM txns WHERE client_id=? AND status='review' AND map_source IN ('match','suspense','litchi') ORDER BY date,id""",(cfg['kiwi_client_id'],))]
    with store.connect(client) as con:
        for row in rows:
            cached=con.execute('SELECT * FROM kiwi_predictions WHERE txn_id=? AND source_hash=?',(row['id'],row_hash(row))).fetchone()
            row['prediction']=json.loads(cached['result']) if cached else None
    return rows


def row_hash(row):
    return digest(json.dumps({k:row[k] for k in ('id','date','narration','amount','direction','party')},sort_keys=True).encode())


def suggest_row(store,client,txn_id,model=None):
    rows = [r for r in queue(store,client) if r['id']==txn_id]
    if not rows: raise UserError('This row is no longer eligible for Litchi suggestions')
    r = rows[0]
    features = {'narration':r['narration'],'party':r['party'],'amount':r['amount'] if r['direction']=='debit' else -r['amount']}
    result=predict(store,client,line_text(features),r['date'],model)
    from .db import now
    with store.connect(client) as con:
        con.execute('INSERT OR REPLACE INTO kiwi_predictions VALUES(?,?,?,?,?)',(txn_id,row_hash(r),model.stamp if model else store.config(client)['embedding_model'],json.dumps(result),now()))
    return {'row':r,**result}


def apply_suggestion(store,client,txn_id,ledger):
    from bahi.service import set_ledger
    cfg = store.config(client)
    if not cfg.get('kiwi_client_id'): raise UserError('Client is not linked to Kiwi')
    with store.connect(client) as con:
        if not con.execute('SELECT 1 FROM ledgers WHERE name=?',(ledger,)).fetchone():raise UserError('Choose an existing client ledger')
    with kiwi_db(store) as con:
        row=con.execute('SELECT * FROM txns WHERE id=? AND client_id=?',(txn_id,cfg['kiwi_client_id'])).fetchone()
        if not row or row['status']!='review' or row['map_source'] not in ('match','suspense','litchi'):
            raise UserError('Row changed or has a higher-priority decision. Refresh first')
        changed,similar=set_ledger(con,cfg['kiwi_client_id'],[txn_id],ledger)
    return {'changed':changed,'similar':similar,'note':'Applied through Kiwi’s existing correction and learning flow.'}


def init_kiwi(store,demo=False):
    from bahi import service
    cfg=kiwi_config(store)
    with kiwi_db(store) as con:
        if demo:service.load_demo(con,cfg)
    return sync_clients(store)


def save_ledger(store,client,name,parent):
    from bahi import db,service
    from bahi.mapping import kind_from_ancestors
    cfg=store.config(client)
    if cfg.get('kiwi_client_id'):
        with kiwi_db(store) as con:
            db.add_ledger(con,cfg['kiwi_client_id'],name,parent,kind_from_ancestors(service._group_chain(parent)))
            con.execute('UPDATE ledgers SET parent=?,kind=? WHERE client_id=? AND name=?',
                (parent,kind_from_ancestors(service._group_chain(parent)),cfg['kiwi_client_id'],name))
            service.remap(con,cfg['kiwi_client_id'])
    with store.connect(client) as con:
        con.execute('INSERT INTO ledgers VALUES(?,?) ON CONFLICT(name) DO UPDATE SET parent=excluded.parent',(name,parent))
        store.event(con,'ledger_saved',{'name':name,'parent':parent})


def save_rule(store,client,pattern,ledger,priority=10):
    from bahi import db,service
    cfg=store.config(client)
    with store.connect(client) as con:
        if not pattern.strip():raise UserError('Pattern cannot be empty')
        if not con.execute('SELECT 1 FROM ledgers WHERE name=?',(ledger,)).fetchone():raise UserError('Choose an existing ledger')
    if cfg.get('kiwi_client_id'):
        with kiwi_db(store) as con:
            db.add_rule(con,cfg['kiwi_client_id'],pattern,ledger)
            service.remap(con,cfg['kiwi_client_id'])
    else:
        with store.connect(client) as con:
            con.execute('INSERT INTO rules(pattern,ledger,priority) VALUES(?,?,?)',(pattern,ledger,priority))


def linked_rules(store,client):
    from bahi import db
    cfg=store.config(client)
    if cfg.get('kiwi_client_id'):
        with kiwi_db(store) as con:return [dict(r) for r in db.rules(con,cfg['kiwi_client_id'])]
    with store.connect(client) as con:return [dict(r) for r in con.execute('SELECT * FROM rules ORDER BY priority,id')]


def create_combined_app(store,port=8765):
    from bahi.web import create_app
    from .web import Application
    from http.cookies import SimpleCookie
    import time
    cfg=kiwi_config(store)
    cfg.server['host']='127.0.0.1'
    cfg.server['open_browser']=False
    original=create_app(cfg)
    litchi=Application(store,port)
    sync_clients(store)
    def combined(env,start_response):
        path=env.get('PATH_INFO','/')
        host=env.get('HTTP_HOST','')
        if host not in (f'127.0.0.1:{port}',f'localhost:{port}') or (env.get('HTTP_ORIGIN') and env['HTTP_ORIGIN']!='http://'+host):
            start_response('400 Bad Request',[('Content-Type','text/plain')]);return [b'Local origin required']
        if path=='/litchi':
            start_response('302 Found',[('Location','/litchi/')]);return [b'']
        if path.startswith('/litchi/'):
            child=dict(env);child['PATH_INFO']=path[len('/litchi'):];child['SCRIPT_NAME']='/litchi'
            return litchi(child,start_response)
        if path=='/health':
            start_response('200 OK',[('Content-Type','application/json')]);return [b'{"status":"ok","app":"Kiwi + Litchi"}']
        cookie=SimpleCookie(env.get('HTTP_COOKIE',''));token=cookie['kiwi_session'].value if 'kiwi_session' in cookie else ''
        with litchi.lock: session=litchi.sessions.get(token)
        if not session or time.time()-session['at']>8*3600:
            start_response('302 Found',[('Location','/litchi/?next=kiwi'),('Cache-Control','no-store')]);return [b'']
        return original(env,start_response)
    return combined
