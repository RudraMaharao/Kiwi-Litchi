import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .common import UserError, data_home, write_json

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ledgers(name TEXT PRIMARY KEY, parent TEXT NOT NULL DEFAULT 'Sundry Creditors');
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, pattern TEXT NOT NULL, ledger TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 10);
CREATE TABLE IF NOT EXISTS memory(party TEXT PRIMARY KEY, ledger TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS statements(
 id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, account TEXT NOT NULL,
 opening INTEGER NOT NULL, closing INTEGER NOT NULL, created TEXT NOT NULL,
 issues TEXT NOT NULL, source_kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entries(
 id INTEGER PRIMARY KEY, statement_id TEXT NOT NULL REFERENCES statements(id), position INTEGER NOT NULL,
 day TEXT NOT NULL, narration TEXT NOT NULL, debit INTEGER NOT NULL, credit INTEGER NOT NULL,
 balance INTEGER NOT NULL, party TEXT NOT NULL, upi TEXT NOT NULL DEFAULT '', ifsc TEXT NOT NULL DEFAULT '',
 reference TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT '', fingerprint TEXT NOT NULL,
 ledger TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', approved INTEGER NOT NULL DEFAULT 0,
 duplicate INTEGER NOT NULL DEFAULT 0, excluded INTEGER NOT NULL DEFAULT 0, issues TEXT NOT NULL DEFAULT '[]',
 UNIQUE(statement_id,position));
CREATE INDEX IF NOT EXISTS entry_fingerprint ON entries(fingerprint);
CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, statement_id TEXT NOT NULL UNIQUE REFERENCES statements(id),
 created TEXT NOT NULL, xml BLOB NOT NULL, state TEXT NOT NULL DEFAULT 'exported', response TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS vouchers(id TEXT PRIMARY KEY, day TEXT NOT NULL, type TEXT NOT NULL, narration TEXT NOT NULL,
 source TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS lines(id INTEGER PRIMARY KEY AUTOINCREMENT, voucher_id TEXT NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
 ledger TEXT NOT NULL, amount INTEGER NOT NULL, narration TEXT NOT NULL, party TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS line_ledger ON lines(ledger);
CREATE TABLE IF NOT EXISTS embeddings(kind TEXT NOT NULL,item_id TEXT NOT NULL,model TEXT NOT NULL,hash TEXT NOT NULL,
 vector BLOB NOT NULL,dimensions INTEGER NOT NULL,PRIMARY KEY(kind,item_id,model));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,created TEXT NOT NULL,action TEXT NOT NULL,details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kiwi_predictions(txn_id INTEGER PRIMARY KEY,source_hash TEXT NOT NULL,model TEXT NOT NULL,result TEXT NOT NULL,created TEXT NOT NULL);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_home()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        (self.root / "clients").mkdir(exist_ok=True, mode=0o700)

    def client_path(self, client):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", client):
            raise UserError("Client ID must be lowercase letters, numbers, hyphens or underscores")
        p = self.root / "clients" / client
        if not (p / "config.json").is_file():
            raise UserError("Client does not exist")
        return p

    def create_client(self, client, name):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", client) or not name.strip():
            raise UserError("Supply a client name and a lowercase client ID")
        p = self.root / "clients" / client
        if p.exists():
            raise UserError("Client ID already exists")
        p.mkdir(mode=0o700)
        write_json(p / "config.json", {"id": client, "name": name.strip(), "company": name.strip(),
            "tally_url": "http://127.0.0.1:9000", "embedding_model": "nomic-embed-text",
            "intent_model": "llama3.2:1b-instruct-q4_K_M", "own_accounts": [], "related_parties": [], "holidays": [],
            "cash_review_limit_paise": None, "cash_rule_source": "", "tds_review_rules": []})
        with self.connect(client):
            pass
        return client

    def clients(self):
        return [json.loads(p.read_text()) for p in sorted((self.root / "clients").glob("*/config.json"))]

    def config(self, client):
        return json.loads((self.client_path(client) / "config.json").read_text())

    @contextmanager
    def connect(self, client):
        p = self.client_path(client) / "books.sqlite3"
        con = sqlite3.connect(p, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            con.execute("INSERT OR IGNORE INTO meta VALUES('schema_version','1')")
            con.commit()
            p.chmod(0o600)
            with con:
                yield con
        finally:
            con.close()

    def event(self, con, action, details):
        con.execute("INSERT INTO events(created,action,details) VALUES(?,?,?)", (now(), action, json.dumps(details)))

    def backup(self):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        folder = self.root / "backups" / stamp
        folder.mkdir(parents=True, mode=0o700)
        for cfg in self.clients():
            target = folder / cfg['id']
            target.mkdir(mode=0o700)
            write_json(target / "config.json", cfg)
            with self.connect(cfg['id']) as src:
                dest = sqlite3.connect(target / "books.sqlite3")
                try:
                    src.backup(dest)
                    if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise UserError("Backup verification failed")
                finally:
                    dest.close()
            (target / "books.sqlite3").chmod(0o600)
        law = self.root / "law.sqlite3"
        if law.exists():
            src, dest = sqlite3.connect(law), sqlite3.connect(folder / "law.sqlite3")
            try:
                src.backup(dest)
            finally:
                src.close()
                dest.close()
            (folder / "law.sqlite3").chmod(0o600)
        write_json(folder / "manifest.json", {"created": now(), "clients": [c['id'] for c in self.clients()], "schema": 1})
        return folder
