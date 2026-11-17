"""What Bahi does, in one place: import statements, suggest ledgers, learn, post to Tally, export.

The web app and the command line both call these functions.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import db, narration
from .config import Config
from .mapping import (ClientContext, Ledger, Mapper, OwnAccount, Rule, Suggestion, kind_from_ancestors,
                      memory_keys, merged_settings)
from .pdftext import PasswordRequired, WrongPassword
from .statement import CHECK_OK, Statement, parse_file
from .tally import (ImportResult, TallyClient, TallyError, VoucherSpec, ancestors, edu_date, envelope,
                    instrument_type, ledger_xml, voucher_xml)
from .util import from_iso, iso, norm_space, now_iso, rupees, safe_filename, sha256_file, short_hash, write_atomic


class AlreadyImported(Exception):
    pass


class NothingFound(Exception):
    pass


class SetupNeeded(Exception):
    pass


__all__ = ["AlreadyImported", "NothingFound", "SetupNeeded", "PasswordRequired", "WrongPassword"]


# ------------------------------------------------------------------ mapping context

def mapper_for(conn, client_id: int) -> Mapper:
    row = db.client(conn, client_id)
    leds = {r["name"]: Ledger(r["name"], r["parent"], r["kind"]) for r in db.ledgers(conn, client_id)}
    rules = [Rule(r["pattern"], r["ledger"], r["direction"], r["id"]) for r in db.rules(conn, client_id)]
    own = [OwnAccount(a["id"], a["label"], a["number"], a["tally_ledger"]) for a in db.accounts(conn, client_id)]
    ctx = ClientContext(row["name"] if row else "", leds, rules, db.memory(conn, client_id),
                        merged_settings(db.client_settings(conn, client_id)), own)
    return Mapper(ctx)


def settings_for(conn, client_id: int) -> dict:
    return merged_settings(db.client_settings(conn, client_id))


def _status_for(sug: Suggestion, check: str, direction: str | None) -> str:
    if sug.skip:
        return "skipped"
    if direction is None or check not in CHECK_OK:
        return "review"
    return "ready" if sug.sure else "review"


# ------------------------------------------------------------------ import

@dataclass
class ImportOutcome:
    statement_id: int
    account_id: int
    account_label: str
    rows: int
    duplicates: int
    ready: int
    review: int
    skipped: int
    status: str
    warnings: list[str] = field(default_factory=list)
    summary: str = ""


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def match_account(conn, client_id: int, st: Statement) -> int | None:
    accs = db.accounts(conn, client_id)
    found = _digits(st.account_no)
    for a in accs:
        num = _digits(a["number"])
        if num and found and (num == found or (len(num) >= 4 and len(found) >= 4 and num[-4:] == found[-4:])):
            return a["id"]
    if len(accs) == 1 and (not accs[0]["number"] or not found):
        return accs[0]["id"]  # one account and nothing on the statement says otherwise
    return None


def _account_label(st: Statement) -> str:
    last4 = _digits(st.account_no)[-4:]
    bank = st.bank or "Bank"
    return f"{bank} {last4}".strip() if last4 else bank


def parse_with_passwords(cfg: Config, conn, client_id: int, path: Path, password: str | None,
                         progress=None) -> tuple[Statement, str | None]:
    tries: list[str | None] = [password] if password else [None]
    for a in db.accounts(conn, client_id):
        if a["pdf_password"] and a["pdf_password"] not in tries:
            tries.append(a["pdf_password"])
    last_exc: Exception | None = None
    for pw in tries:
        try:
            return parse_file(path, pw, ocr_settings=cfg.ocr, progress=progress), pw
        except WrongPassword as exc:
            last_exc = exc
        except PasswordRequired as exc:
            last_exc = exc
    if password:
        raise WrongPassword("That password didn't open the PDF.") from last_exc
    raise PasswordRequired("This PDF is password-protected. Enter its password.") from last_exc


def import_statement(conn, cfg: Config, client_id: int, path: Path, filename: str | None = None,
                     account_id: int | None = None, password: str | None = None, remember_password: bool = True,
                     progress=None) -> ImportOutcome:
    path = Path(path)
    filename = filename or path.name
    if db.client(conn, client_id) is None:
        raise ValueError("Unknown client.")
    sha = sha256_file(path)
    dup = conn.execute("SELECT s.id, s.filename FROM statements s JOIN accounts a ON a.id=s.account_id "
                       "WHERE a.client_id=? AND s.sha256=?", (client_id, sha)).fetchone()
    if dup:
        raise AlreadyImported(f"This file was already imported ({dup['filename']}).")
    st, used_pw = parse_with_passwords(cfg, conn, client_id, path, password, progress)
    if not st.txns:
        raise NothingFound("No transactions found in this file. " + " ".join(st.warnings[:2]))
    if account_id is None:
        account_id = match_account(conn, client_id, st)
    if account_id is None:
        account_id = db.add_account(conn, client_id, _account_label(st), st.bank, st.account_no)
    acc = db.account(conn, account_id)
    if acc["client_id"] != client_id:
        raise ValueError("That account belongs to another client.")
    if not acc["number"] and st.account_no:
        db.update_account(conn, account_id, number=st.account_no)
    if not acc["bank"] and st.bank:
        db.update_account(conn, account_id, bank=st.bank)
    if used_pw and remember_password and used_pw != acc["pdf_password"]:
        db.update_account(conn, account_id, pdf_password=used_pw)

    cur = conn.execute(
        """INSERT INTO statements(account_id, filename, sha256, source, bank, account_no, period_from, period_to,
           opening, closing, printed_opening, printed_closing, rows, flagged, status, warnings, ocr_confidence,
           imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (account_id, filename, sha, st.source, st.bank, st.account_no, iso(st.period_from), iso(st.period_to),
         st.opening, st.closing, st.printed_opening, st.printed_closing, len(st.txns), len(st.flagged), st.status,
         json.dumps(st.warnings), st.ocr_confidence, now_iso()))
    sid = cur.lastrowid
    try:
        dest = cfg.uploads_dir / str(client_id) / f"{sid}-{safe_filename(filename)}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        conn.execute("UPDATE statements SET stored_path=? WHERE id=?", (str(dest), sid))
    except OSError:
        pass

    mapper = mapper_for(conn, client_id)
    counts = {"ready": 0, "review": 0, "skipped": 0, "duplicate": 0}
    seen_fp: set[str] = set()
    for t in st.txns:
        fp = short_hash(account_id, iso(t.date), t.amount, t.direction, t.balance, norm_space(t.narration).upper())
        if fp in seen_fp:
            fp = short_hash(fp, t.seq)
        seen_fp.add(fp)
        info = narration.parse(t.narration)
        keys = memory_keys(t.narration, info)
        exists = conn.execute("SELECT 1 FROM txns WHERE account_id=? AND fingerprint=?", (account_id, fp)).fetchone()
        if exists:
            sug, status = Suggestion("", "", 0, "already imported from an earlier statement"), "duplicate"
        elif t.direction is None:
            sug = Suggestion(mapper.settings["suspense_ledger"], "suspense", 0, "debit or credit? set it first")
            status = "review"
        else:
            sug = mapper.suggest(t.narration, t.direction, info, account_id)
            status = _status_for(sug, t.check, t.direction)
        counts[status] = counts.get(status, 0) + 1
        conn.execute(
            """INSERT INTO txns(statement_id, account_id, client_id, seq, date, value_date, narration, ref, amount,
               direction, balance, check_status, check_note, channel, category, party, vpa, keys, ledger, map_source,
               map_score, map_note, status, fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, account_id, client_id, t.seq, iso(t.date), iso(t.value_date), t.narration, t.ref or info.ref,
             t.amount, t.direction, t.balance, t.check, t.note, info.channel, info.category,
             narration.display_party(info), info.vpa, json.dumps(keys), sug.ledger, sug.source, sug.score, sug.note,
             status, fp))
    conn.execute("UPDATE statements SET duplicates=? WHERE id=?", (counts["duplicate"], sid))
    conn.commit()
    acc = db.account(conn, account_id)
    return ImportOutcome(sid, account_id, acc["label"], len(st.txns), counts["duplicate"], counts["ready"],
                         counts["review"], counts["skipped"], st.status, st.warnings, st.summary())


# ------------------------------------------------------------------ review actions

EDITABLE = ("review", "ready", "skipped")


def remap(conn, client_id: int, include_ready: bool = True) -> int:
    """Re-suggest ledgers after new rules or a fresh ledger list. Your own choices are kept."""
    mapper = mapper_for(conn, client_id)
    statuses = ("review", "ready") if include_ready else ("review",)
    rows = conn.execute(
        f"SELECT * FROM txns WHERE client_id=? AND status IN ({','.join('?' * len(statuses))}) "
        "AND map_source NOT IN ('manual')", (client_id, *statuses)).fetchall()
    changed = 0
    for r in rows:
        if r["direction"] is None:
            continue
        info = narration.parse(r["narration"])
        sug = mapper.suggest(r["narration"], r["direction"], info, r["account_id"])
        status = _status_for(sug, r["check_status"], r["direction"])
        if (sug.ledger, sug.source, sug.score, status) != (r["ledger"], r["map_source"], r["map_score"], r["status"]):
            conn.execute("UPDATE txns SET ledger=?, map_source=?, map_score=?, map_note=?, status=? WHERE id=?",
                         (sug.ledger, sug.source, sug.score, sug.note, status, r["id"]))
            changed += 1
    conn.commit()
    return changed


def _owned(conn, client_id: int, ids: list[int]) -> list:
    if not ids:
        return []
    q = f"SELECT * FROM txns WHERE client_id=? AND id IN ({','.join('?' * len(ids))})"
    return conn.execute(q, (client_id, *ids)).fetchall()


def set_ledger(conn, client_id: int, ids: list[int], ledger: str, apply_similar: bool = True) -> tuple[int, int]:
    """Set the ledger on rows, remember it for their parties, and fill in other rows of the same parties."""
    ledger = norm_space(ledger)
    if not ledger:
        raise ValueError("Ledger name is empty.")
    mapper = mapper_for(conn, client_id)
    ledger = mapper.canonical(ledger)
    rows = [r for r in _owned(conn, client_id, ids) if r["status"] in EDITABLE]
    keys: set[str] = set()
    for r in rows:
        status = "ready" if (r["check_status"] in CHECK_OK and r["direction"]) else "review"
        if r["status"] == "skipped":
            status = "skipped"
        conn.execute("UPDATE txns SET ledger=?, map_source='manual', map_score=100, map_note='set by you', "
                     "status=? WHERE id=?", (ledger, status, r["id"]))
        keys.update(json.loads(r["keys"] or "[]"))
    if keys:
        db.remember(conn, client_id, sorted(keys), ledger)
    similar = 0
    if apply_similar and keys:
        others = conn.execute(
            "SELECT * FROM txns WHERE client_id=? AND status IN ('review','ready') "
            "AND map_source NOT IN ('manual','rule')", (client_id,)).fetchall()
        done = {r["id"] for r in rows}
        for o in others:
            if o["id"] in done or not keys.intersection(json.loads(o["keys"] or "[]")):
                continue
            status = "ready" if (o["check_status"] in CHECK_OK and o["direction"]) else "review"
            conn.execute("UPDATE txns SET ledger=?, map_source='memory', map_score=95, "
                         "map_note='same party as a row you set', status=? WHERE id=?", (ledger, status, o["id"]))
            similar += 1
    conn.commit()
    return len(rows), similar


def set_status(conn, client_id: int, ids: list[int], action: str) -> int:
    rows = [r for r in _owned(conn, client_id, ids) if r["status"] in EDITABLE]
    for r in rows:
        if action == "skip":
            status = "skipped"
        elif action == "approve":
            status = "ready" if r["direction"] and r["ledger"] and r["check_status"] in CHECK_OK else "review"
        else:  # restore
            status = "ready" if (r["map_score"] >= 80 and r["check_status"] in CHECK_OK and r["direction"]) \
                else "review"
        conn.execute("UPDATE txns SET status=? WHERE id=?", (status, r["id"]))
    conn.commit()
    return len(rows)


def set_direction(conn, client_id: int, txn_id: int, direction: str) -> None:
    if direction not in ("debit", "credit"):
        raise ValueError("Direction must be debit or credit.")
    rows = [r for r in _owned(conn, client_id, [txn_id]) if r["status"] in EDITABLE]
    for r in rows:
        conn.execute("UPDATE txns SET direction=?, check_note=? WHERE id=?",
                     (direction, (r["check_note"] + "; " if r["check_note"] else "") + "direction set by you", r["id"]))
    conn.commit()


# ------------------------------------------------------------------ ledgers

def fetch_ledgers(conn, cfg: Config, client_id: int) -> int:
    row = db.client(conn, client_id)
    client = TallyClient(cfg.tally.get("host", "localhost"), cfg.tally.get("port", 9000))
    leds, groups = client.ledgers(row["tally_company"])
    parent_of = {g["name"]: g["parent"] for g in groups}
    items = []
    for led in leds:
        chain = ancestors(parent_of, led["parent"]) if led["parent"] else []
        items.append((led["name"], led["parent"], kind_from_ancestors(chain)))
    db.replace_ledgers(conn, client_id, items, "tally")
    remap(conn, client_id)
    return len(items)


def add_ledgers_text(conn, client_id: int, text: str) -> int:
    n = 0
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"\t|,(?=[^,]*$)", line)
        name = parts[0].strip()
        group = parts[1].strip() if len(parts) > 1 else ""
        if name:
            db.add_ledger(conn, client_id, name, group, kind_from_ancestors(_group_chain(group)), "manual")
            n += 1
    remap(conn, client_id)
    return n


def _group_chain(group: str) -> list[str]:
    from .tallymock import PREDEFINED_GROUPS

    return ancestors(PREDEFINED_GROUPS, group) if group else []


# ------------------------------------------------------------------ vouchers

@dataclass
class Plan:
    rows: list = field(default_factory=list)
    specs: list[VoucherSpec] = field(default_factory=list)
    new_ledgers: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def plan_vouchers(conn, cfg: Config, client_id: int, ids: list[int] | None = None) -> Plan:
    plan = Plan()
    mapper = mapper_for(conn, client_id)
    s = mapper.settings
    accounts = {a["id"]: a for a in db.accounts(conn, client_id)}
    q = "SELECT * FROM txns WHERE client_id=? AND status='ready'"
    args: list = [client_id]
    if ids:
        q += f" AND id IN ({','.join('?' * len(ids))})"
        args += list(ids)
    rows = conn.execute(q + " ORDER BY date, account_id, seq", args).fetchall()
    missing_bank = set()
    edu = bool(cfg.tally.get("edu_mode"))
    for r in rows:
        if r['check_status'] not in CHECK_OK:
            plan.problems.append(f"Row {r['id']} has an unresolved balance check; correct the source statement before posting.")
            continue
        acc = accounts.get(r["account_id"])
        if not acc or not acc["tally_ledger"]:
            missing_bank.add(acc["label"] if acc else "?")
            continue
        if not r["ledger"] or not r["direction"]:
            continue
        date = from_iso(r["value_date"]) if s.get("date_basis") == "value" and r["value_date"] else from_iso(r["date"])
        bank_date = from_iso(r["value_date"]) or from_iso(r["date"])
        if edu:
            date, bank_date = edu_date(date), edu_date(bank_date)
        role = mapper.voucher_role(r["ledger"], r["direction"])
        vtype = s["voucher_types"].get(role, role.title())
        party = r["party"] if mapper.kind(r["ledger"]) in ("debtor", "creditor", "") else r["ledger"]
        spec = VoucherSpec(
            date=date, vtype=vtype, bank_ledger=acc["tally_ledger"], counter_ledger=r["ledger"], amount=r["amount"],
            money_out=r["direction"] == "debit", narration=r["narration"], instrument_no=r["ref"],
            instrument_type=instrument_type(r["channel"], s.get("instrument_types")), bank_date=bank_date,
            favouring=party or r["ledger"])
        plan.rows.append(r)
        plan.specs.append(spec)
        if mapper.ctx.ledgers and not mapper.known(acc["tally_ledger"]):
            plan.new_ledgers.setdefault(acc["tally_ledger"], s["new_ledger_groups"]["bank"])
        if not mapper.known(r["ledger"]) and r["ledger"].lower() != s["cash_ledger"].lower():
            plan.new_ledgers.setdefault(
                mapper.canonical(r["ledger"]),
                mapper.new_ledger_group(r["ledger"], r["direction"], r["map_source"], r["map_note"]))
    for label in sorted(missing_bank):
        plan.problems.append(f"Choose the Tally bank ledger for the account '{label}' first.")
    return plan


@dataclass
class PostOutcome:
    batch_id: int
    posted: int
    failed: int
    ledgers_created: list[str] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def post_to_tally(conn, cfg: Config, client_id: int, ids: list[int] | None = None, progress=None) -> PostOutcome:
    plan = plan_vouchers(conn, cfg, client_id, ids)
    if not plan.specs:
        if plan.problems:
            raise SetupNeeded(" ".join(plan.problems))
        raise NothingFound("Nothing is ready to post. Approve some rows first.")
    row = db.client(conn, client_id)
    company = row["tally_company"]
    tc = TallyClient(cfg.tally.get("host", "localhost"), cfg.tally.get("port", 9000))
    tc.ping()
    s = settings_for(conn, client_id)
    created = []
    for name, group in plan.new_ledgers.items():
        res = tc.import_xml(envelope([ledger_xml(name, group)], "All Masters", company))
        if res.created or any("already exists" in m.lower() for m in res.messages):
            created.append(name)
            db.add_ledger(conn, client_id, name, group, kind_from_ancestors(_group_chain(group)), "tally")
        else:
            plan.problems.append(f"Couldn't create ledger '{name}': {'; '.join(res.messages) or 'no reason given'}")
    cur = conn.execute("INSERT INTO batches(client_id, mode, created_at, vouchers) VALUES (?,?,?,?)",
                       (client_id, "tally", now_iso(), len(plan.specs)))
    batch_id = cur.lastrowid
    posted, errors = 0, []
    for i, (r, spec) in enumerate(zip(plan.rows, plan.specs)):
        try:
            res: ImportResult = tc.import_xml(envelope([voucher_xml(spec, s.get("bank_allocations", True))],
                                                      "Vouchers", company))
        except TallyError as exc:
            errors.append((r["id"], str(exc)))
            conn.execute("UPDATE txns SET post_error=? WHERE id=?", (str(exc)[:300], r["id"]))
            break
        if res.created >= 1 and not res.errors:
            posted += 1
            conn.execute("UPDATE txns SET status='posted', posted_at=?, batch_id=?, tally_id=?, post_error='' "
                         "WHERE id=?", (now_iso(), batch_id, res.last_vch_id, r["id"]))
        else:
            msg = "; ".join(res.messages) or "Tally didn't create the voucher"
            errors.append((r["id"], msg))
            conn.execute("UPDATE txns SET post_error=? WHERE id=?", (msg[:300], r["id"]))
        if progress:
            progress(i + 1, len(plan.specs), "Posting to Tally")
    conn.execute("UPDATE batches SET ok=?, failed=?, summary=? WHERE id=?",
                 (posted, len(errors), json.dumps({"ledgers": created, "errors": errors[:50]}), batch_id))
    conn.commit()
    return PostOutcome(batch_id, posted, len(errors), created, errors, plan.problems)


@dataclass
class ExportOutcome:
    batch_id: int
    vouchers: int
    files: list[Path]
    new_ledgers: dict[str, str]
    problems: list[str]


def export_xml(conn, cfg: Config, client_id: int, ids: list[int] | None = None) -> ExportOutcome:
    plan = plan_vouchers(conn, cfg, client_id, ids)
    if not plan.specs:
        if plan.problems:
            raise SetupNeeded(" ".join(plan.problems))
        raise NothingFound("Nothing is ready to export. Approve some rows first.")
    row = db.client(conn, client_id)
    s = settings_for(conn, client_id)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = cfg.exports_dir / safe_filename(row["name"], "client")
    files = []
    if plan.new_ledgers:
        masters = envelope([ledger_xml(n, g) for n, g in plan.new_ledgers.items()], "All Masters")
        p = folder / f"{stamp}-1-new-ledgers.xml"
        write_atomic(p, masters)
        files.append(p)
    vouchers = envelope([voucher_xml(v, s.get("bank_allocations", True)) for v in plan.specs], "Vouchers")
    p = folder / f"{stamp}-{'2' if plan.new_ledgers else '1'}-vouchers.xml"
    write_atomic(p, vouchers)
    files.append(p)
    cur = conn.execute(
        "INSERT INTO batches(client_id, mode, created_at, vouchers, ok, files, summary) VALUES (?,?,?,?,?,?,?)",
        (client_id, "xml", now_iso(), len(plan.specs), len(plan.specs), json.dumps([str(f) for f in files]),
         json.dumps({"ledgers": list(plan.new_ledgers)})))
    batch_id = cur.lastrowid
    conn.executemany("UPDATE txns SET status='exported', posted_at=?, batch_id=? WHERE id=?",
                     [(now_iso(), batch_id, r["id"]) for r in plan.rows])
    conn.commit()
    return ExportOutcome(batch_id, len(plan.specs), files, plan.new_ledgers, plan.problems)


def undo_batch(conn, client_id: int, batch_id: int) -> int:
    """Put an exported batch back to 'ready' (e.g. the import into Tally failed). Posted rows stay posted."""
    cur = conn.execute("UPDATE txns SET status='ready', batch_id=NULL, posted_at=NULL WHERE client_id=? AND "
                       "batch_id=? AND status='exported'", (client_id, batch_id))
    conn.commit()
    return cur.rowcount


# ------------------------------------------------------------------ demo

def load_demo(conn, cfg: Config) -> int:
    """A ready-made client with the demo company's ledgers and one sample statement."""
    from .tallymock import DEMO_COMPANY, DEMO_LEDGERS, PREDEFINED_GROUPS

    cid = db.add_client(conn, DEMO_COMPANY, DEMO_COMPANY)
    if db.accounts(conn, cid):
        return cid
    db.add_account(conn, cid, "Sample Bank 5678", "Sample Bank", "50100012345678", "Sample Bank A/c 5678")
    db.add_account(conn, cid, "Sample Bank Current 7766", "Sample Bank", "50100099887766",
                   "Sample Bank Current A/c 7766")
    items = [(n, p, kind_from_ancestors(ancestors(PREDEFINED_GROUPS, p))) for n, p in DEMO_LEDGERS.items()]
    db.replace_ledgers(conn, cid, items, "tally")
    settings = db.client_settings(conn, cid)
    settings.setdefault("category_ledgers", {}).update({"tax_gst": "GST Cash Ledger", "loan_emi": "Bajaj Finance Ltd"})
    db.save_client_settings(conn, cid, settings)
    sample = cfg.corpus_dir / "layout_a.pdf"
    if sample.exists():
        try:
            import_statement(conn, cfg, cid, sample, "sample-statement-april.pdf")
        except AlreadyImported:
            pass
    return cid


def describe_amount(paise: int | None) -> str:
    return rupees(paise)
