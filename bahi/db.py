"""SQLite storage. Money is stored in paise (integers)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .util import now_iso

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    tally_company TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    bank TEXT NOT NULL DEFAULT '',
    number TEXT NOT NULL DEFAULT '',
    tally_ledger TEXT NOT NULL DEFAULT '',
    pdf_password TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (client_id, label)
);

CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL,
    source TEXT NOT NULL,
    bank TEXT NOT NULL DEFAULT '',
    account_no TEXT NOT NULL DEFAULT '',
    period_from TEXT, period_to TEXT,
    opening INTEGER, closing INTEGER,
    printed_opening INTEGER, printed_closing INTEGER,
    rows INTEGER NOT NULL DEFAULT 0,
    flagged INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    warnings TEXT NOT NULL DEFAULT '[]',
    ocr_confidence REAL,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_statements_sha ON statements(sha256);

CREATE TABLE IF NOT EXISTS txns (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    date TEXT NOT NULL,
    value_date TEXT,
    narration TEXT NOT NULL DEFAULT '',
    ref TEXT NOT NULL DEFAULT '',
    amount INTEGER NOT NULL,
    direction TEXT,
    balance INTEGER,
    check_status TEXT NOT NULL DEFAULT '',
    check_note TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    party TEXT NOT NULL DEFAULT '',
    vpa TEXT NOT NULL DEFAULT '',
    keys TEXT NOT NULL DEFAULT '[]',
    ledger TEXT NOT NULL DEFAULT '',
    map_source TEXT NOT NULL DEFAULT '',
    map_score INTEGER NOT NULL DEFAULT 0,
    map_note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'review',
    fingerprint TEXT NOT NULL,
    posted_at TEXT,
    batch_id INTEGER,
    tally_id TEXT NOT NULL DEFAULT '',
    post_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_txns_client ON txns(client_id, status);
CREATE INDEX IF NOT EXISTS ix_txns_account_fp ON txns(account_id, fingerprint);

CREATE TABLE IF NOT EXISTS ledgers (
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    parent TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'tally',
    PRIMARY KEY (client_id, name)
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    pattern TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'any',
    ledger TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    ledger TEXT NOT NULL,
    hits INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (client_id, key)
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    vouchers INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    files TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

SCHEMA_VERSION = "1"


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema', ?)", (SCHEMA_VERSION,))
    conn.commit()
    return conn


# ------------------------------------------------------------------ clients

def clients(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM clients ORDER BY name COLLATE NOCASE").fetchall()


def client(conn, client_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()


def client_by_name(conn, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clients WHERE name=? COLLATE NOCASE", (name.strip(),)).fetchone()


def add_client(conn, name: str, tally_company: str = "") -> int:
    name = name.strip()
    if not name:
        raise ValueError("Client name is empty.")
    existing = client_by_name(conn, name)
    if existing:
        return existing["id"]
    cur = conn.execute("INSERT INTO clients(name, tally_company, created_at) VALUES (?,?,?)",
                       (name, tally_company.strip(), now_iso()))
    conn.commit()
    return cur.lastrowid


def client_settings(conn, client_id: int) -> dict:
    row = client(conn, client_id)
    try:
        return json.loads(row["settings"] or "{}") if row else {}
    except json.JSONDecodeError:
        return {}


def save_client_settings(conn, client_id: int, settings: dict):
    conn.execute("UPDATE clients SET settings=? WHERE id=?", (json.dumps(settings), client_id))
    conn.commit()


def update_client(conn, client_id: int, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("name", "tally_company")}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    conn.execute(f"UPDATE clients SET {sets} WHERE id=?", (*allowed.values(), client_id))
    conn.commit()


def delete_client(conn, client_id: int):
    conn.execute("DELETE FROM clients WHERE id=?", (client_id,))
    conn.commit()


# ------------------------------------------------------------------ accounts

def accounts(conn, client_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM accounts WHERE client_id=? ORDER BY id", (client_id,)).fetchall()


def account(conn, account_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()


def add_account(conn, client_id: int, label: str, bank: str = "", number: str = "", tally_ledger: str = "") -> int:
    label = label.strip() or "Bank account"
    base, n = label, 2
    while conn.execute("SELECT 1 FROM accounts WHERE client_id=? AND label=?", (client_id, label)).fetchone():
        label = f"{base} ({n})"
        n += 1
    cur = conn.execute(
        "INSERT INTO accounts(client_id, label, bank, number, tally_ledger, created_at) VALUES (?,?,?,?,?,?)",
        (client_id, label, bank, number, tally_ledger, now_iso()))
    conn.commit()
    return cur.lastrowid


def update_account(conn, account_id: int, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("label", "bank", "number", "tally_ledger", "pdf_password")}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    conn.execute(f"UPDATE accounts SET {sets} WHERE id=?", (*allowed.values(), account_id))
    conn.commit()


# ------------------------------------------------------------------ statements & txns

def statements(conn, client_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT s.*, a.label AS account_label, a.client_id,
                  (SELECT COUNT(*) FROM txns t WHERE t.statement_id=s.id AND t.status='review') AS to_review,
                  (SELECT COUNT(*) FROM txns t WHERE t.statement_id=s.id AND t.status='ready') AS ready,
                  (SELECT COUNT(*) FROM txns t WHERE t.statement_id=s.id AND t.status IN ('posted','exported')) AS done
           FROM statements s JOIN accounts a ON a.id=s.account_id
           WHERE a.client_id=? ORDER BY s.period_from DESC, s.id DESC""", (client_id,)).fetchall()


def statement(conn, statement_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT s.*, a.label AS account_label, a.client_id FROM statements s JOIN accounts a ON a.id=s.account_id "
        "WHERE s.id=?", (statement_id,)).fetchone()


def delete_statement(conn, statement_id: int):
    conn.execute("DELETE FROM statements WHERE id=?", (statement_id,))
    conn.commit()


def txns(conn, client_id: int, account_id: int | None = None, statement_id: int | None = None,
         status: str | None = None) -> list[sqlite3.Row]:
    q = "SELECT * FROM txns WHERE client_id=?"
    args: list = [client_id]
    if account_id:
        q += " AND account_id=?"
        args.append(account_id)
    if statement_id:
        q += " AND statement_id=?"
        args.append(statement_id)
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY account_id, date, statement_id, seq"
    return conn.execute(q, args).fetchall()


def txn(conn, txn_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM txns WHERE id=?", (txn_id,)).fetchone()


def counts(conn, client_id: int) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM txns WHERE client_id=? GROUP BY status",
                        (client_id,)).fetchall()
    return {r["status"]: r["n"] for r in rows}


# ------------------------------------------------------------------ ledgers, rules, memory

def ledgers(conn, client_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM ledgers WHERE client_id=? ORDER BY name COLLATE NOCASE",
                        (client_id,)).fetchall()


def replace_ledgers(conn, client_id: int, items: list[tuple[str, str, str]], source: str = "tally"):
    conn.execute("DELETE FROM ledgers WHERE client_id=? AND source=?", (client_id, source))
    conn.executemany("INSERT OR REPLACE INTO ledgers(client_id, name, parent, kind, source) VALUES (?,?,?,?,?)",
                     [(client_id, n, p, k, source) for n, p, k in items])
    conn.commit()


def add_ledger(conn, client_id: int, name: str, parent: str = "", kind: str = "", source: str = "manual"):
    conn.execute("INSERT OR IGNORE INTO ledgers(client_id, name, parent, kind, source) VALUES (?,?,?,?,?)",
                 (client_id, name.strip(), parent.strip(), kind, source))
    conn.commit()


def delete_ledger(conn, client_id: int, name: str):
    conn.execute("DELETE FROM ledgers WHERE client_id=? AND name=?", (client_id, name))
    conn.commit()


def rules(conn, client_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM rules WHERE client_id=? OR client_id IS NULL ORDER BY client_id IS NULL, id",
                        (client_id,)).fetchall()


def add_rule(conn, client_id: int | None, pattern: str, ledger: str, direction: str = "any") -> int:
    cur = conn.execute("INSERT INTO rules(client_id, pattern, direction, ledger, created_at) VALUES (?,?,?,?,?)",
                       (client_id, pattern.strip(), direction, ledger.strip(), now_iso()))
    conn.commit()
    return cur.lastrowid


def delete_rule(conn, rule_id: int):
    conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    conn.commit()


def memory(conn, client_id: int) -> dict[str, str]:
    return {r["key"]: r["ledger"] for r in conn.execute("SELECT key, ledger FROM memory WHERE client_id=?",
                                                        (client_id,))}


def memory_rows(conn, client_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM memory WHERE client_id=? ORDER BY updated_at DESC", (client_id,)).fetchall()


def remember(conn, client_id: int, keys: list[str], ledger: str):
    for key in keys:
        if not key:
            continue
        conn.execute(
            """INSERT INTO memory(client_id, key, ledger, hits, updated_at) VALUES (?,?,?,1,?)
               ON CONFLICT(client_id, key) DO UPDATE SET ledger=excluded.ledger, hits=memory.hits+1,
               updated_at=excluded.updated_at""", (client_id, key, ledger, now_iso()))


def forget(conn, client_id: int, key: str):
    conn.execute("DELETE FROM memory WHERE client_id=? AND key=?", (client_id, key))
    conn.commit()


def batches(conn, client_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM batches WHERE client_id=? ORDER BY id DESC LIMIT ?",
                        (client_id, limit)).fetchall()
