import fcntl
import json
import resource
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from .common import UserError, digest, http, money, write_json
from .db import now
from .ingest import import_statement
from .intelligence import Ollama, audit, embed_books
from .law import Qdrant, law_db


def backup(store, qdrant=False):
    folder = store.backup()
    source = store.root/'kiwi'
    if (source/'data/bahi.db').exists():
        target = folder/'kiwi'
        target.mkdir(mode=0o700)
        src,dest=sqlite3.connect(source/'data/bahi.db'),sqlite3.connect(target/'bahi.db')
        try:src.backup(dest)
        finally:src.close();dest.close()
        if (source/'bahi.toml').exists():shutil.copy2(source/'bahi.toml',target/'bahi.toml')
        for name in ('uploads','exports'):
            if (source/'data'/name).exists():shutil.copytree(source/'data'/name,target/name)
    if qdrant:
        with law_db(store) as con:
            row = con.execute("SELECT value FROM law_meta WHERE key='active_qdrant'").fetchone()
        if row:
            collection = json.loads(row[0])['collection']
            snap = Qdrant().snapshot(collection)['result']['name']
            raw = http(f'http://127.0.0.1:6333/collections/{collection}/snapshots/{snap}',xml=True,method='GET')
            p = folder/'qdrant.snapshot'
            p.write_bytes(raw)
            p.chmod(0o600)
            write_json(folder/'qdrant.json',{'collection':collection,'snapshot':snap})
    checksums = {str(p.relative_to(folder)):digest(p.read_bytes()) for p in folder.rglob('*') if p.is_file()}
    write_json(folder/'checksums.json',checksums)
    # Retain the most recent 14 successful backup sets in our own backup directory.
    completed=sorted(p for p in folder.parent.iterdir() if p.is_dir() and not p.is_symlink() and (p/'checksums.json').is_file())
    for old in completed[:-14]:shutil.rmtree(old)
    return folder


def restore(store, folder):
    """Restore only into a fresh data directory; never overwrite a live client."""
    folder = Path(folder)
    if store.clients() or (store.root/'law.sqlite3').exists() or (store.root/'kiwi/data/bahi.db').exists(): raise UserError('Restore requires an empty data directory; use --data-dir /path/to/new-folder')
    manifest = json.loads((folder/'manifest.json').read_text())
    hashes = json.loads((folder/'checksums.json').read_text())
    for rel, expected in hashes.items():
        p = (folder/rel).resolve()
        if not p.is_relative_to(folder.resolve()): raise UserError('Unsafe backup path')
        if digest(p.read_bytes()) != expected: raise UserError('Backup checksum mismatch: '+rel)
    for client in manifest['clients']:
        cfg = json.loads((folder/client/'config.json').read_text())
        store.create_client(client,cfg['name'])
        target = store.client_path(client)
        # Store creation opens/closes its DB, so no WAL writers exist in this new target.
        shutil.copy2(folder/client/'books.sqlite3',target/'books.sqlite3')
        write_json(target/'config.json',cfg)
        with store.connect(client) as con:
            if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise UserError('Restored database failed integrity check')
    if (folder/'law.sqlite3').exists():
        shutil.copy2(folder/'law.sqlite3',store.root/'law.sqlite3')
        with law_db(store) as con:
            # The source library restores independently of Docker; reindex rather than reference missing state.
            con.execute("DELETE FROM law_meta WHERE key='active_qdrant'")
    if (folder/'kiwi/bahi.db').exists():
        target=store.root/'kiwi'
        (target/'data').mkdir(parents=True,mode=0o700)
        shutil.copy2(folder/'kiwi/bahi.db',target/'data/bahi.db')
        if (folder/'kiwi/bahi.toml').exists():shutil.copy2(folder/'kiwi/bahi.toml',target/'bahi.toml')
        for name in ('uploads','exports'):
            if (folder/'kiwi'/name).exists():shutil.copytree(folder/'kiwi'/name,target/'data'/name)
    return {'restored_clients':manifest['clients'],'next':'Set password; rebuild law Qdrant index if used.'}


def batch(store, embeddings=False):
    lock = open(store.root/'batch.lock','a')
    try:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e: raise UserError('A nightly batch is already running') from e
        started = time.monotonic()
        from .bridge import sync_clients,queue,suggest_row
        sync_clients(store)
        results, errors = [], []
        for cfg in store.clients():
            client_start = time.monotonic()
            report = {'client':cfg['id'],'started':now()}
            if embeddings:
                engine = Ollama(cfg['embedding_model'])
                try:
                    report['embeddings'] = embed_books(store,cfg['id'],engine)
                    predicted=0
                    for row in queue(store,cfg['id']):
                        if row['prediction'] is None:
                            suggest_row(store,cfg['id'],row['id'],engine)
                            predicted+=1
                    report['kiwi_predictions']=predicted
                except Exception as e:
                    report['embedding_error'] = str(e)
                    errors.append({'client':cfg['id'],'error':str(e)})
                finally:
                    try: engine.unload()
                    except Exception: pass
            report['review'] = audit(store,cfg['id'])
            report['seconds'] = round(time.monotonic()-client_start,3)
            report['finished'] = now()
            # ru_maxrss on Linux is KiB; on Darwin bytes. Linux is the deployment target.
            import sys
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report['python_peak_mb'] = round(peak/(1024*1024 if sys.platform=='darwin' else 1024),1)
            report['memory_note'] = 'Python peak only. Ollama and Docker memory must be checked separately.'
            root = store.client_path(cfg['id'])/'reports'
            write_json(root/(datetime.now().strftime('%Y%m%d-%H%M%S')+'.json'),report)
            write_json(root/'latest.json',report)
            results.append(report)
        return {'seconds':round(time.monotonic()-started,3),'clients':results,'errors':errors}
    finally:
        lock.close()


def watch_once(store):
    """Each drop uses a JSON sidecar with explicit client/account/opening/closing values."""
    inbox = store.root/'inbox'
    inbox.mkdir(exist_ok=True,mode=0o700)
    results = []
    for sidecar in sorted(inbox.glob('*.json')):
        if sidecar.name.endswith(('.result.json','.error.json')): continue
        try:
            d = json.loads(sidecar.read_text())
            source = (inbox/d['file']).resolve()
            if not source.is_relative_to(inbox.resolve()) or source == sidecar.resolve(): raise UserError('Watch file must be inside the inbox')
            # Do not read files still being copied. Writers should rename both files into place atomically.
            if not source.is_file() or time.time()-source.stat().st_mtime < 5: continue
            sid = import_statement(store,d['client'],source,d['account'],money(d['opening']),money(d['closing']))
            result = {'statement':sid,'file':source.name}
            write_json(sidecar.with_suffix('.result.json'),result)
            sidecar.rename(sidecar.with_suffix('.done'))
            results.append(result)
        except Exception as e:
            result = {'file':sidecar.name,'error':str(e)}
            write_json(sidecar.with_suffix('.error.json'),result)
            sidecar.rename(sidecar.with_suffix('.failed'))
            results.append(result)
    return results
