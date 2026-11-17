import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from .common import UserError, money, write_json
from .db import Store


def main(argv=None):
    p = argparse.ArgumentParser(description='Kiwi + Litchi · local Linux bookkeeping pilot')
    p.add_argument('--data-dir',help='Default: ~/.local/share/kiwi-litchi')
    sub = p.add_subparsers(dest='command',required=True)
    for name in ('init','password','demo','clients','doctor','watch-once'):
        sub.add_parser(name)
    serve = sub.add_parser('serve'); serve.add_argument('--port',type=int,default=8765); serve.add_argument('--dev',action='store_true')
    add = sub.add_parser('client'); add.add_argument('id'); add.add_argument('name')
    imp = sub.add_parser('import'); imp.add_argument('client'); imp.add_argument('file'); imp.add_argument('--account',required=True); imp.add_argument('--opening',required=True); imp.add_argument('--closing',required=True); imp.add_argument('--pdf-password',action='store_true',help='Prompt without saving the PDF password')
    rev = sub.add_parser('review'); rev.add_argument('client'); rev.add_argument('id',type=int); rev.add_argument('--ledger',default=''); rev.add_argument('--exclude',action='store_true'); rev.add_argument('--distinct',action='store_true')
    led = sub.add_parser('ledger'); led.add_argument('client'); led.add_argument('name'); led.add_argument('parent')
    ex = sub.add_parser('export'); ex.add_argument('client'); ex.add_argument('statement'); ex.add_argument('output')
    master = sub.add_parser('masters'); master.add_argument('client'); master.add_argument('output')
    post = sub.add_parser('post'); post.add_argument('client'); post.add_argument('batch'); post.add_argument('--confirm-company',required=True)
    undo = sub.add_parser('undo-xml'); undo.add_argument('client'); undo.add_argument('batch'); undo.add_argument('output')
    books = sub.add_parser('import-books'); books.add_argument('client'); books.add_argument('file')
    pull = sub.add_parser('pull-books'); pull.add_argument('client'); pull.add_argument('--start',required=True); pull.add_argument('--end',required=True)
    embed = sub.add_parser('embed'); embed.add_argument('client'); embed.add_argument('--model')
    pred = sub.add_parser('predict'); pred.add_argument('client'); pred.add_argument('text'); pred.add_argument('--date')
    audit = sub.add_parser('audit'); audit.add_argument('client')
    ask = sub.add_parser('ask'); ask.add_argument('client'); ask.add_argument('question'); ask.add_argument('--model-intent',action='store_true',help='Use local LLM intent extraction, then display parsed intent and calculated result')
    ev = sub.add_parser('evaluate'); ev.add_argument('client'); ev.add_argument('--month',required=True); ev.add_argument('--model'); ev.add_argument('--output')
    cal=sub.add_parser('calibrate');cal.add_argument('client');cal.add_argument('--calibration-month',required=True);cal.add_argument('--test-month',required=True);cal.add_argument('--model');cal.add_argument('--output')
    li = sub.add_parser('law-import'); li.add_argument('file'); li.add_argument('--demo',action='store_true')
    ix = sub.add_parser('law-index'); ix.add_argument('--model',default='nomic-embed-text')
    ls = sub.add_parser('law-search'); ls.add_argument('question'); ls.add_argument('--on'); ls.add_argument('--act'); ls.add_argument('--bm25-only',action='store_true'); ls.add_argument('--demo',action='store_true'); ls.add_argument('--extract',action='store_true')
    bt = sub.add_parser('batch'); bt.add_argument('--embeddings',action='store_true')
    bk = sub.add_parser('backup'); bk.add_argument('--qdrant',action='store_true')
    rs = sub.add_parser('restore'); rs.add_argument('folder')
    sim = sub.add_parser('simulator'); sim.add_argument('--port',default=9000,type=int)
    args = p.parse_args(argv)
    os.umask(0o077)
    store = Store(args.data_dir)
    result = None
    try:
        c = args.command
        if c == 'init': result = {'data_dir':str(store.root),'next':'Set password, load demo, then serve'}
        elif c == 'password':
            from .web import set_password
            password = getpass.getpass('New local password (12+ characters): ')
            if password != getpass.getpass('Repeat password: '): raise UserError('Passwords do not match')
            set_password(store,password); result = {'password':'saved'}
        elif c == 'demo':
            from .demo import seed
            result = seed(store)
        elif c == 'clients': result = store.clients()
        elif c == 'client': result = store.create_client(args.id,args.name)
        elif c == 'serve':
            from .web import serve
            serve(store,args.port,args.dev)
        elif c == 'import':
            from .ingest import import_statement
            password = getpass.getpass('PDF password: ') if args.pdf_password else None
            result = {'statement':import_statement(store,args.client,args.file,args.account,money(args.opening),money(args.closing),password)}
        elif c == 'review':
            from .ingest import review_entry
            review_entry(store,args.client,args.id,args.ledger,args.exclude,args.distinct); result = {'reviewed':args.id}
        elif c == 'ledger':
            with store.connect(args.client) as con:
                con.execute('INSERT INTO ledgers VALUES(?,?) ON CONFLICT(name) DO UPDATE SET parent=excluded.parent',(args.name,args.parent))
            result = {'ledger':args.name}
        elif c in ('export','masters','undo-xml'):
            from .tally import make_batch,ledger_xml,undo_xml
            if c=='export':
                batch = make_batch(store,args.client,args.statement); raw = batch['xml']; result = {'batch':batch['id'],'state':batch['state']}
            elif c=='masters': raw=ledger_xml(store,args.client)
            else: raw=undo_xml(store,args.client,args.batch)
            target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True)
            # Explicit paths are user chosen; prevent accidental overwrites.
            with target.open('xb') as f: f.write(raw)
            result={**(result or {}),'output':str(target)}
        elif c=='post':
            from .tally import send_batch
            result=send_batch(store,args.client,args.batch,args.confirm_company)
        elif c=='import-books':
            from .tally import import_books
            result=import_books(store,args.client,Path(args.file).read_bytes())
        elif c=='pull-books':
            from .tally import pull_books
            result=pull_books(store,args.client,args.start,args.end)
        elif c=='embed':
            from .intelligence import embed_books,Ollama
            result=embed_books(store,args.client,Ollama(args.model) if args.model else None)
        elif c=='predict':
            from .intelligence import predict
            result=predict(store,args.client,args.text,args.date)
        elif c=='audit':
            from .intelligence import audit
            result=audit(store,args.client)
        elif c=='ask':
            from .intelligence import book_answer,model_intent
            result=book_answer(store,args.client,question=args.question,intent=model_intent(store,args.client,args.question) if args.model_intent else None)
        elif c=='evaluate':
            from .intelligence import evaluate,Ollama
            result=evaluate(store,args.client,args.month,Ollama(args.model) if args.model else None)
            if args.output: write_json(Path(args.output),result)
        elif c=='calibrate':
            from .intelligence import calibrate,Ollama
            result=calibrate(store,args.client,args.calibration_month,args.test_month,Ollama(args.model) if args.model else None)
            if args.output:write_json(Path(args.output),result)
        elif c=='law-import':
            from .law import import_law
            result=import_law(store,args.file,args.demo)
        elif c=='law-index':
            from .law import index_law
            result=index_law(store,args.model)
        elif c=='law-search':
            from .law import search_law,extract_answer
            func=extract_answer if args.extract else search_law
            result=func(store,args.question,on=args.on,act=args.act,hybrid=not args.bm25_only,demo=args.demo)
        elif c=='batch':
            from .operations import batch
            result=batch(store,args.embeddings)
        elif c=='backup':
            from .operations import backup
            result={'backup':str(backup(store,args.qdrant))}
        elif c=='restore':
            from .operations import restore
            result=restore(store,args.folder)
        elif c=='watch-once':
            from bahi.watch import scan_once
            from .bridge import kiwi_config,sync_clients
            result={'imports':scan_once(kiwi_config(store))}
            sync_clients(store)
        elif c=='simulator':
            from .simulator import serve
            serve(args.port)
        elif c=='doctor':
            import importlib.util,platform,shutil
            result={'platform':platform.platform(),'python':sys.version,'data':str(store.root),
                    'disk_free_gb':round(shutil.disk_usage(store.root).free/1024**3,1),
                    'packages':{m:bool(importlib.util.find_spec(m)) for m in ('waitress','pdfplumber','openpyxl','xlrd','sqlite_vec','PIL','numpy')},
                    'tesseract':bool(shutil.which('tesseract'))}
            if Path('/proc/meminfo').exists(): result['memory']=Path('/proc/meminfo').read_text().splitlines()[:3]
        if result is not None: print(json.dumps(result,indent=2,ensure_ascii=False))
        return 1 if isinstance(result,dict) and (result.get('errors') or result.get('state')=='uncertain') else 0
    except (UserError,ValueError,OSError,ImportError) as e:
        print('Error: '+str(e),file=sys.stderr)
        return 1


if __name__=='__main__': sys.exit(main())
