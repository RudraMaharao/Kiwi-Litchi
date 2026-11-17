"""The browser app: clients, upload, review, post to Tally.

Runs on this computer only (127.0.0.1) unless bahi.toml opens it to the
network, in which case a password is required.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template, request, send_file,
                   url_for)

from .. import __version__, db, exports, service
from ..config import Config
from ..mapping import merged_settings
from ..ocr import OCR
from ..pdftext import PasswordRequired, WrongPassword
from ..tally import TallyClient, TallyError
from ..util import from_iso, nice_date, rupees, safe_filename

CATEGORY_FIELDS = [
    ("bank_charges", "Bank charges", "SMS charges, card fees, minimum balance charges"),
    ("interest_received", "Interest received", "Savings and FD interest credited"),
    ("interest_paid", "Interest paid", "Interest debited on OD or loan accounts"),
    ("tax_gst", "GST payments", "Challans paid to the GST portal (CPIN)"),
    ("tax_income", "Income tax and TDS", "Challans 280, 281 and advance tax"),
    ("salary", "Salary", "Payments marked salary"),
    ("loan_emi", "Loan EMIs", "ACH/NACH debits to banks and finance companies"),
]
STATUS_TABS = [("review", "Needs review"), ("ready", "Ready"), ("skipped", "Skipped"), ("done", "Posted"),
               ("duplicate", "Duplicates"), ("all", "All")]


class Jobs:
    """Background work (reading scans, posting) so the page stays responsive."""

    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bahi-job")
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def submit(self, kind: str, fn, *args) -> str:
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "kind": kind, "status": "queued", "progress": None, "result": None, "error": None,
               "started": time.time()}
        with self.lock:
            self.jobs[jid] = job
            for old in [k for k, v in self.jobs.items() if time.time() - v["started"] > 3600]:
                self.jobs.pop(old, None)

        def progress(i, n, msg):
            job["progress"] = {"done": i, "total": n, "message": msg}

        def run():
            job["status"] = "running"
            try:
                job["result"] = fn(progress, *args)
                job["status"] = "done"
            except Exception as exc:  # shown to the user
                job["status"] = "error"
                job["error"] = str(exc) or type(exc).__name__

        self.pool.submit(run)
        return jid

    def get(self, jid: str) -> dict | None:
        return self.jobs.get(jid)


def create_app(cfg: Config) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    secret_file = cfg.data_dir / ".secret"
    if not secret_file.exists():
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(secrets.token_hex(32))
    app.secret_key = secret_file.read_text().strip()
    csrf_token = secrets.token_urlsafe(24)
    jobs = Jobs()
    incoming = cfg.data_dir / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    for old in incoming.glob("*"):
        if time.time() - old.stat().st_mtime > 86400:
            old.unlink(missing_ok=True)
    tally_cache = {"at": 0.0, "value": None}

    app.jinja_env.filters["inr"] = lambda p: rupees(p) if p is not None else ""
    app.jinja_env.filters["nice_date"] = nice_date
    app.jinja_env.filters["short_date"] = lambda s: from_iso(s).strftime("%d %b") if from_iso(s) else ""
    app.jinja_env.filters["fromjson"] = lambda s: json.loads(s or "[]")

    def conn():
        if "conn" not in g:
            g.conn = db.connect(cfg.db_path)
        return g.conn

    @app.teardown_appcontext
    def _close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    @app.before_request
    def _guard():
        password = cfg.server.get("password") or ""
        host = cfg.server.get("host", "127.0.0.1")
        if password or host not in ("127.0.0.1", "localhost"):
            auth = request.headers.get("Authorization", "")
            ok = False
            if auth.startswith("Basic "):
                try:
                    user, _, pw = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                    ok = bool(password) and hmac.compare_digest(pw, password) and user == "admin"
                except Exception:
                    ok = False
            if not ok:
                return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Bahi"'})
        if request.method == "POST":
            token = request.headers.get("X-Bahi-Token") or request.form.get("_token")
            if not token or not hmac.compare_digest(token, csrf_token):
                abort(400, "This page is out of date. Reload it and try again.")

    @app.context_processor
    def _ctx():
        return {"csrf": csrf_token, "version": __version__, "edu_mode": bool(cfg.tally.get("edu_mode")),
                "status_tabs": STATUS_TABS}

    def client_or_404(cid: int):
        row = db.client(conn(), cid)
        if row is None:
            abort(404)
        return row

    # ------------------------------------------------------------------ pages

    @app.get("/")
    def home():
        rows = []
        for c in db.clients(conn()):
            counts = db.counts(conn(), c["id"])
            accs = db.accounts(conn(), c["id"])
            last = conn().execute(
                "SELECT MAX(s.period_to) AS p FROM statements s JOIN accounts a ON a.id=s.account_id "
                "WHERE a.client_id=?", (c["id"],)).fetchone()["p"]
            rows.append({"c": c, "counts": counts, "accounts": accs, "last": last})
        return render_template("home.html", rows=rows)

    @app.post("/clients")
    def add_client():
        name = request.form.get("name", "").strip()
        if not name:
            flash("Type the client's name first.", "error")
            return redirect(url_for("home"))
        cid = db.add_client(conn(), name, request.form.get("tally_company", "").strip() or name)
        return redirect(url_for("client_page", cid=cid))

    @app.post("/demo")
    def demo():
        cid = service.load_demo(conn(), cfg)
        flash("Demo client loaded with a sample April statement and the demo company's ledgers.", "ok")
        return redirect(url_for("review", cid=cid))

    @app.get("/c/<int:cid>")
    def client_page(cid):
        c = client_or_404(cid)
        accs = db.accounts(conn(), cid)
        return render_template("client.html", c=c, accounts=accs, statements=db.statements(conn(), cid),
                               counts=db.counts(conn(), cid), batches=db.batches(conn(), cid, 8),
                               plan=service.plan_vouchers(conn(), cfg, cid))

    @app.get("/c/<int:cid>/review")
    def review(cid):
        c = client_or_404(cid)
        status = request.args.get("status", "")
        sid = request.args.get("statement", type=int)
        statements = db.statements(conn(), cid)
        stmt = db.statement(conn(), sid) if sid else None
        if stmt is not None and stmt["client_id"] != cid:
            abort(404)
        all_rows = db.txns(conn(), cid, statement_id=sid)
        counts = {k: 0 for k, _ in STATUS_TABS}
        for r in all_rows:
            key = "done" if r["status"] in ("posted", "exported") else r["status"]
            counts[key] = counts.get(key, 0) + 1
        counts["all"] = len(all_rows)
        if not status:
            status = "review" if counts.get("review") else ("ready" if counts.get("ready") else "all")
        if status == "all":
            rows = all_rows
        elif status == "done":
            rows = [r for r in all_rows if r["status"] in ("posted", "exported")]
        else:
            rows = [r for r in all_rows if r["status"] == status]
        mapper = service.mapper_for(conn(), cid)
        ledgers = db.ledgers(conn(), cid)
        settings = merged_settings(db.client_settings(conn(), cid))
        ledger_names = sorted({r["name"] for r in ledgers} | {settings["suspense_ledger"], settings["cash_ledger"]}
                              | {a["tally_ledger"] for a in db.accounts(conn(), cid) if a["tally_ledger"]},
                              key=str.lower)
        proof = None
        if stmt is not None:
            srows = all_rows
            dr = sum(r["amount"] for r in srows if r["direction"] == "debit")
            cr = sum(r["amount"] for r in srows if r["direction"] == "credit")
            proof = {"opening": stmt["opening"], "dr": dr, "cr": cr, "closing": stmt["closing"],
                     "n_dr": sum(1 for r in srows if r["direction"] == "debit"),
                     "n_cr": sum(1 for r in srows if r["direction"] == "credit"),
                     "printed_closing": stmt["printed_closing"], "status": stmt["status"],
                     "computed": (stmt["opening"] + cr - dr) if stmt["opening"] is not None else None,
                     "warnings": json.loads(stmt["warnings"] or "[]"),
                     "flagged": sum(1 for r in srows if r["check_status"] in ("mismatch", "nobalance"))}
        accounts = {a["id"]: a for a in db.accounts(conn(), cid)}
        return render_template("review.html", c=c, rows=rows, counts=counts, status=status, stmt=stmt,
                               statements=statements, ledger_names=ledger_names, proof=proof, mapper=mapper,
                               accounts=accounts, ledger_kinds={r["name"].lower(): r["kind"] for r in ledgers},
                               plan=service.plan_vouchers(conn(), cfg, cid))

    @app.get("/c/<int:cid>/ledgers")
    def ledgers_page(cid):
        c = client_or_404(cid)
        return render_template("ledgers.html", c=c, ledgers=db.ledgers(conn(), cid))

    @app.post("/c/<int:cid>/ledgers")
    def ledgers_action(cid):
        client_or_404(cid)
        action = request.form.get("action")
        try:
            if action == "fetch":
                n = service.fetch_ledgers(conn(), cfg, cid)
                flash(f"Fetched {n} ledgers from Tally. Suggestions were updated.", "ok")
            elif action == "add":
                n = service.add_ledgers_text(conn(), cid, request.form.get("text", ""))
                flash(f"Added {n} ledger(s).", "ok")
            elif action == "delete":
                db.delete_ledger(conn(), cid, request.form.get("name", ""))
                service.remap(conn(), cid)
        except TallyError as exc:
            flash(str(exc), "error")
        return redirect(url_for("ledgers_page", cid=cid))

    @app.get("/c/<int:cid>/rules")
    def rules_page(cid):
        c = client_or_404(cid)
        settings = merged_settings(db.client_settings(conn(), cid))
        names = sorted({r["name"] for r in db.ledgers(conn(), cid)} | {settings["suspense_ledger"]}, key=str.lower)
        return render_template("rules.html", c=c, rules=db.rules(conn(), cid), memory=db.memory_rows(conn(), cid),
                               ledger_names=names)

    @app.post("/c/<int:cid>/rules")
    def rules_action(cid):
        client_or_404(cid)
        action = request.form.get("action")
        if action == "add":
            pattern, ledger = request.form.get("pattern", "").strip(), request.form.get("ledger", "").strip()
            if pattern and ledger:
                scope = None if request.form.get("scope") == "all" else cid
                db.add_rule(conn(), scope, pattern, ledger, request.form.get("direction", "any"))
                n = service.remap(conn(), cid)
                flash(f"Rule added. {n} row(s) updated.", "ok")
            else:
                flash("A rule needs the words to look for and a ledger.", "error")
        elif action == "delete":
            db.delete_rule(conn(), request.form.get("id", type=int))
            service.remap(conn(), cid)
        elif action == "forget":
            db.forget(conn(), cid, request.form.get("key", ""))
            service.remap(conn(), cid)
        return redirect(url_for("rules_page", cid=cid))

    @app.get("/c/<int:cid>/settings")
    def client_settings(cid):
        c = client_or_404(cid)
        settings = merged_settings(db.client_settings(conn(), cid))
        ledgers = db.ledgers(conn(), cid)
        bank_ledgers = [r["name"] for r in ledgers if r["kind"] == "bank"]
        companies, tally_error = [], ""
        try:
            companies = TallyClient(cfg.tally.get("host"), cfg.tally.get("port"), timeout=3).companies()
        except TallyError as exc:
            tally_error = str(exc)
        return render_template("client_settings.html", c=c, s=settings, accounts=db.accounts(conn(), cid),
                               ledger_names=sorted((r["name"] for r in ledgers), key=str.lower),
                               bank_ledgers=bank_ledgers, categories=CATEGORY_FIELDS, companies=companies,
                               tally_error=tally_error)

    @app.post("/c/<int:cid>/settings")
    def client_settings_save(cid):
        client_or_404(cid)
        f = request.form
        if f.get("action") == "delete_client":
            if f.get("confirm", "").strip().lower() == "delete":
                db.delete_client(conn(), cid)
                flash("Client deleted.", "ok")
                return redirect(url_for("home"))
            flash("Type delete to confirm.", "error")
            return redirect(url_for("client_settings", cid=cid))
        db.update_client(conn(), cid, name=f.get("name", "").strip() or db.client(conn(), cid)["name"],
                         tally_company=f.get("tally_company", "").strip())
        for a in db.accounts(conn(), cid):
            fields = {"label": f.get(f"acc_label_{a['id']}", a["label"]).strip() or a["label"],
                      "tally_ledger": f.get(f"acc_ledger_{a['id']}", "").strip()}
            if f.get(f"acc_forget_pw_{a['id']}"):
                fields["pdf_password"] = ""
            db.update_account(conn(), a["id"], **fields)
        if f.get("new_account", "").strip():
            db.add_account(conn(), cid, f.get("new_account").strip(), tally_ledger=f.get("new_account_ledger", ""))
        settings = db.client_settings(conn(), cid)
        settings["suspense_ledger"] = f.get("suspense_ledger", "").strip() or "Suspense A/c"
        settings["cash_ledger"] = f.get("cash_ledger", "").strip() or "Cash"
        settings["category_ledgers"] = {k: f.get(f"cat_{k}", "").strip() for k, _, _ in CATEGORY_FIELDS}
        settings["voucher_types"] = {k: f.get(f"vt_{k}", "").strip() or k.title()
                                     for k in ("payment", "receipt", "contra")}
        settings["date_basis"] = "value" if f.get("date_basis") == "value" else "txn"
        settings["bank_allocations"] = bool(f.get("bank_allocations"))
        settings["skip_incoming_own_transfers"] = bool(f.get("skip_incoming_own_transfers"))
        db.save_client_settings(conn(), cid, settings)
        n = service.remap(conn(), cid)
        flash(f"Saved. {n} suggestion(s) updated." if n else "Saved.", "ok")
        return redirect(url_for("client_settings", cid=cid))

    @app.get("/settings")
    def app_settings():
        engine = OCR(cfg.ocr)
        tally_state, companies = "", []
        try:
            tc = TallyClient(cfg.tally.get("host"), cfg.tally.get("port"), timeout=3)
            tally_state = tc.ping()
            companies = tc.companies()
        except TallyError as exc:
            tally_state = str(exc)
        return render_template("settings.html", cfg=cfg, ocr_ok=engine.available(), ocr_version=engine.version(),
                               tally_state=tally_state, companies=companies)

    # ------------------------------------------------------------------ upload

    def _import_files(progress, cid: int, items: list[dict], account_id: int | None):
        c = db.connect(cfg.db_path)
        out = []
        try:
            for item in items:
                path = Path(item["path"])
                try:
                    res = service.import_statement(c, cfg, cid, path, item["name"], account_id, item.get("password"),
                                                   progress=progress)
                    out.append({"name": item["name"], "ok": True, "statement_id": res.statement_id,
                                "summary": res.summary, "account": res.account_label, "ready": res.ready,
                                "review": res.review, "duplicates": res.duplicates, "skipped": res.skipped,
                                "status": res.status, "warnings": res.warnings[:4],
                                "url": url_for_review(cid, res.statement_id)})
                    path.unlink(missing_ok=True)
                except WrongPassword:
                    out.append({"name": item["name"], "ok": False, "password": True, "token": item["token"],
                                "error": "That password didn't open it. Try again."})
                except PasswordRequired:
                    out.append({"name": item["name"], "ok": False, "password": True, "token": item["token"],
                                "error": "This PDF is locked. Enter its password."})
                except service.AlreadyImported as exc:
                    out.append({"name": item["name"], "ok": False, "error": str(exc)})
                    path.unlink(missing_ok=True)
                except Exception as exc:
                    out.append({"name": item["name"], "ok": False, "error": str(exc) or type(exc).__name__})
                    path.unlink(missing_ok=True)
        finally:
            c.close()
        return {"files": out}

    def url_for_review(cid, sid):
        return f"/c/{cid}/review?statement={sid}"

    @app.post("/c/<int:cid>/upload")
    def upload(cid):
        client_or_404(cid)
        files = request.files.getlist("files")
        if not files or not any(f.filename for f in files):
            return jsonify({"error": "Choose one or more statement files."}), 400
        items = []
        for f in files:
            if not f.filename:
                continue
            token = uuid.uuid4().hex[:16]
            dest = incoming / f"{token}-{safe_filename(f.filename)}"
            f.save(dest)
            items.append({"path": str(dest), "name": f.filename, "token": token,
                          "password": request.form.get("password") or None})
        account_id = request.form.get("account_id", type=int) or None
        jid = jobs.submit("import", _import_files, cid, items, account_id)
        return jsonify({"job": jid})

    @app.post("/c/<int:cid>/upload/retry")
    def upload_retry(cid):
        client_or_404(cid)
        token = request.form.get("token", "")
        match = [p for p in incoming.glob(f"{safe_filename(token)}-*")]
        if not match:
            return jsonify({"error": "That upload has expired. Choose the file again."}), 400
        path = match[0]
        name = path.name.split("-", 1)[1]
        item = {"path": str(path), "name": name, "token": token, "password": request.form.get("password") or None}
        jid = jobs.submit("import", _import_files, cid, [item], request.form.get("account_id", type=int) or None)
        return jsonify({"job": jid})

    @app.get("/jobs/<jid>")
    def job_status(jid):
        job = jobs.get(jid)
        if job is None:
            return jsonify({"status": "missing"}), 404
        return jsonify({k: job[k] for k in ("id", "kind", "status", "progress", "result", "error")})

    # ------------------------------------------------------------------ review API

    def _payload():
        return request.get_json(silent=True) or {}

    def _rows_html(cid, ids):
        mapper = service.mapper_for(conn(), cid)
        ledgers = db.ledgers(conn(), cid)
        accounts = {a["id"]: a for a in db.accounts(conn(), cid)}
        kinds = {r["name"].lower(): r["kind"] for r in ledgers}
        out = {}
        tmpl = app.jinja_env.get_template("_row.html")
        for tid in ids:
            r = db.txn(conn(), tid)
            if r is not None and r["client_id"] == cid:
                out[str(tid)] = tmpl.render(r=r, mapper=mapper, accounts=accounts, ledger_kinds=kinds)
        return out

    def _affected(cid, ledger_set_ids, keys_from):
        """Rows that may have changed: the ones edited plus any row sharing a party key."""
        keys = set()
        for tid in keys_from:
            r = db.txn(conn(), tid)
            if r is not None:
                keys.update(json.loads(r["keys"] or "[]"))
        ids = set(ledger_set_ids)
        if keys:
            for r in conn().execute("SELECT id, keys FROM txns WHERE client_id=? AND status IN ('review','ready')",
                                    (cid,)):
                if keys.intersection(json.loads(r["keys"] or "[]")):
                    ids.add(r["id"])
        return sorted(ids)

    @app.post("/api/c/<int:cid>/ledger")
    def api_ledger(cid):
        client_or_404(cid)
        data = _payload()
        ids = [int(i) for i in data.get("ids", [])]
        try:
            n, similar = service.set_ledger(conn(), cid, ids, data.get("ledger", ""), data.get("similar", True))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        affected = _affected(cid, ids, ids)
        return jsonify({"set": n, "similar": similar, "rows": _rows_html(cid, affected),
                        "counts": db.counts(conn(), cid)})

    @app.post("/api/c/<int:cid>/status")
    def api_status(cid):
        client_or_404(cid)
        data = _payload()
        ids = [int(i) for i in data.get("ids", [])]
        action = data.get("action")
        if action not in ("skip", "approve", "restore"):
            return jsonify({"error": "Unknown action."}), 400
        n = service.set_status(conn(), cid, ids, action)
        return jsonify({"changed": n, "rows": _rows_html(cid, ids), "counts": db.counts(conn(), cid)})

    @app.post("/api/c/<int:cid>/direction")
    def api_direction(cid):
        client_or_404(cid)
        data = _payload()
        try:
            service.set_direction(conn(), cid, int(data.get("id")), data.get("direction", ""))
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"rows": _rows_html(cid, [int(data.get("id"))])})

    # ------------------------------------------------------------------ post / export

    def _post_job(progress, cid):
        c = db.connect(cfg.db_path)
        try:
            out = service.post_to_tally(c, cfg, cid, progress=progress)
            return {"posted": out.posted, "failed": out.failed, "ledgers": out.ledgers_created,
                    "errors": [{"id": i, "message": m} for i, m in out.errors[:30]], "problems": out.problems}
        finally:
            c.close()

    @app.post("/c/<int:cid>/post")
    def post_tally(cid):
        client_or_404(cid)
        return jsonify({"job": jobs.submit("post", _post_job, cid)})

    @app.post("/c/<int:cid>/export")
    def export_xml(cid):
        c = client_or_404(cid)
        try:
            out = service.export_xml(conn(), cfg, cid)
        except (service.NothingFound, service.SetupNeeded) as exc:
            flash(str(exc), "error")
            return redirect(request.referrer or url_for("client_page", cid=cid))
        return render_template("exported.html", c=c, out=out, files=[p.name for p in out.files])

    @app.get("/c/<int:cid>/files/<name>")
    def download_file(cid, name):
        c = client_or_404(cid)
        folder = (cfg.exports_dir / safe_filename(c["name"], "client")).resolve()
        path = (folder / safe_filename(name)).resolve()
        if folder not in path.parents or not path.exists():
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name, mimetype="application/xml")

    @app.post("/c/<int:cid>/batches/<int:bid>/undo")
    def undo_batch(cid, bid):
        client_or_404(cid)
        n = service.undo_batch(conn(), cid, bid)
        flash(f"{n} row(s) are ready to export again.", "ok")
        return redirect(url_for("client_page", cid=cid))

    @app.get("/c/<int:cid>/excel")
    def excel(cid):
        c = client_or_404(cid)
        sid = request.args.get("statement", type=int)
        data = exports.workbook(conn(), cid, statement_id=sid)
        name = safe_filename(f"{c['name']} bank transactions.xlsx")
        tmp = cfg.exports_dir / name
        tmp.write_bytes(data)
        return send_file(tmp, as_attachment=True, download_name=name,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/c/<int:cid>/statements/<int:sid>/delete")
    def delete_statement(cid, sid):
        client_or_404(cid)
        st = db.statement(conn(), sid)
        if st is None or st["client_id"] != cid:
            abort(404)
        posted = conn().execute("SELECT COUNT(*) FROM txns WHERE statement_id=? AND status IN ('posted','exported')",
                                (sid,)).fetchone()[0]
        if posted and request.form.get("confirm") != "yes":
            flash(f"{posted} row(s) of this statement are already in Tally or exported. Tick the box to delete it "
                  "anyway, and remove those vouchers in Tally yourself.", "error")
            return redirect(url_for("client_page", cid=cid))
        if st["stored_path"]:
            Path(st["stored_path"]).unlink(missing_ok=True)
        db.delete_statement(conn(), sid)
        flash(f"Deleted {st['filename']}.", "ok")
        return redirect(url_for("client_page", cid=cid))

    @app.get("/api/tally")
    def api_tally():
        now = time.time()
        if now - tally_cache["at"] > 15 or request.args.get("fresh"):
            try:
                tc = TallyClient(cfg.tally.get("host"), cfg.tally.get("port"), timeout=2)
                tc.ping()
                companies = tc.companies()
                tally_cache["value"] = {"ok": True, "companies": companies}
            except TallyError as exc:
                tally_cache["value"] = {"ok": False, "error": str(exc)}
            tally_cache["at"] = now
        return jsonify(tally_cache["value"])

    @app.errorhandler(400)
    def bad_request(exc):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": getattr(exc, "description", "Bad request")}), 400
        return render_template("error.html", message=getattr(exc, "description", "Bad request")), 400

    @app.errorhandler(404)
    def not_found(_exc):
        return render_template("error.html", message="That page doesn't exist."), 404

    return app


def run(cfg: Config) -> int:
    from waitress import serve

    host = cfg.server.get("host", "127.0.0.1")
    port = int(cfg.server.get("port", 8765))
    if host not in ("127.0.0.1", "localhost") and not cfg.server.get("password"):
        print("Refusing to open Bahi on the network without a password. Set [server] password in "
              f"{cfg.home / 'bahi.toml'} (or the BAHI_PASSWORD environment variable).")
        return 2
    app = create_app(cfg)
    if cfg.watch.get("enabled"):
        from ..watch import start_background as start_watch

        start_watch(cfg)
    shown = "127.0.0.1" if host in ("0.0.0.0", "127.0.0.1", "localhost") else host
    url = f"http://{shown}:{port}/"
    print(f"Bahi is running at {url}  (data: {cfg.home})")
    if host == "0.0.0.0":
        print("Open from other devices with this computer's address, e.g. http://192.168.x.x:%d/ (user: admin)" % port)
    print("Keep this window open. Close it to stop Bahi.")
    if cfg.server.get("open_browser", True):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    serve(app, host=host, port=port, threads=6, channel_timeout=300, ident="Bahi")
    return 0


__all__ = ["create_app", "run"]
