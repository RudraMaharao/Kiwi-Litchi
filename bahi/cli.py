"""Command line: `bahi serve`, `bahi parse`, `bahi lab`, `bahi build-windows`, ..."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__, config, db
from .util import rupees


def _cfg(args) -> config.Config:
    home = Path(args.home).expanduser() if getattr(args, "home", None) else config.default_home()
    cfg = config.load(home)
    cfg.ensure_dirs()
    return cfg


def _client_id(conn, name: str) -> int:
    row = db.client_by_name(conn, name)
    if row is None:
        raise SystemExit(f"No client called '{name}'. Clients: " + ", ".join(c["name"] for c in db.clients(conn)))
    return row["id"]


def cmd_init(args):
    home = Path(args.home).expanduser() if args.home else config.default_home()
    toml = config.init_home(home)
    cfg = config.load(home)
    cfg.ensure_dirs()
    db.connect(cfg.db_path).close()
    print(f"Bahi home: {home}\nSettings:  {toml}\nDatabase:  {cfg.db_path}")
    print("Next: `bahi serve` and open the address it prints.")


def cmd_serve(args):
    cfg = _cfg(args)
    if args.lan:
        cfg.server["host"] = "0.0.0.0"
    if args.port:
        cfg.server["port"] = args.port
    if args.no_browser:
        cfg.server["open_browser"] = False
    from .web import run

    return run(cfg)


def cmd_parse(args):
    from .narration import parse as parse_narration
    from .statement import parse_file

    cfg = _cfg(args)
    t0 = time.time()
    st = parse_file(Path(args.file), args.password, ocr_settings=cfg.ocr)
    if args.json:
        out = {
            "source": st.source, "bank": st.bank, "account": st.account_no, "status": st.status,
            "period": [str(st.period_from), str(st.period_to)], "opening": st.opening, "closing": st.closing,
            "warnings": st.warnings,
            "rows": [{"date": str(t.date), "narration": t.narration, "amount": t.amount, "direction": t.direction,
                      "balance": t.balance, "check": t.check, "ref": t.ref} for t in st.txns],
        }
        print(json.dumps(out, indent=1))
        return 0
    print(f"{args.file}: {st.source}, {st.pages} page(s), {time.time() - t0:.1f}s")
    print(f"Bank: {st.bank or '?'}  Account: {st.account_no or '?'}  Period: {st.period_from} to {st.period_to}")
    print(st.summary())
    for w in st.warnings:
        print("  !", w)
    for t in st.txns[: args.rows]:
        info = parse_narration(t.narration)
        mark = "OK" if t.check in ("ok", "flipped", "corrected") else t.check.upper()
        print(f"  {t.date} {('DR' if t.direction == 'debit' else 'CR' if t.direction else '??')} "
              f"{rupees(t.amount):>14} {rupees(t.balance):>15} {mark:9} {info.party[:22]:22} {t.narration[:60]}")
    if len(st.txns) > args.rows:
        print(f"  ... {len(st.txns) - args.rows} more")
    return 0 if st.status in ("verified", "unverified") else 1


def cmd_import(args):
    from . import service

    cfg = _cfg(args)
    conn = db.connect(cfg.db_path)
    cid = db.add_client(conn, args.client)
    account_id = None
    if args.account:
        acc = [a for a in db.accounts(conn, cid) if a["label"].lower() == args.account.lower()]
        account_id = acc[0]["id"] if acc else db.add_account(conn, cid, args.account)
    for f in args.files:
        try:
            out = service.import_statement(conn, cfg, cid, Path(f), account_id=account_id, password=args.password)
            print(f"{f}: {out.summary}. Ready {out.ready}, to review {out.review}, duplicates {out.duplicates} "
                  f"-> {out.account_label}")
            for w in out.warnings:
                print("  !", w)
        except Exception as exc:  # report and continue with the next file
            print(f"{f}: {type(exc).__name__}: {exc}")
    return 0


def cmd_clients(args):
    cfg = _cfg(args)
    conn = db.connect(cfg.db_path)
    for c in db.clients(conn):
        counts = db.counts(conn, c["id"])
        accs = ", ".join(a["label"] + (f" -> {a['tally_ledger']}" if a["tally_ledger"] else "")
                         for a in db.accounts(conn, c["id"]))
        print(f"{c['name']}  [Tally: {c['tally_company'] or '-'}]  {accs}")
        print("   " + "  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return 0


def cmd_post(args):
    from . import service

    cfg = _cfg(args)
    conn = db.connect(cfg.db_path)
    cid = _client_id(conn, args.client)
    if args.xml:
        out = service.export_xml(conn, cfg, cid)
        print(f"{out.vouchers} vouchers written:")
        for f in out.files:
            print("  ", f)
        print("In TallyPrime: Alt+O (Import) > Masters for the ledgers file (if any), then Transactions for the "
              "vouchers file.")
        return 0
    plan = service.plan_vouchers(conn, cfg, cid)
    if args.dry_run:
        print(f"{len(plan.specs)} vouchers ready; new ledgers: {plan.new_ledgers or 'none'}")
        for p in plan.problems:
            print("  !", p)
        return 0
    out = service.post_to_tally(conn, cfg, cid,
                                progress=lambda i, n, msg: print(f"\r{msg}: {i}/{n}", end="", flush=True))
    print(f"\nPosted {out.posted}, failed {out.failed}. New ledgers: {', '.join(out.ledgers_created) or 'none'}")
    for tid, msg in out.errors[:20]:
        print(f"  row {tid}: {msg}")
    return 0 if not out.failed else 1


def cmd_export(args):
    from . import exports

    cfg = _cfg(args)
    conn = db.connect(cfg.db_path)
    cid = _client_id(conn, args.client)
    data = exports.workbook(conn, cid)
    out = Path(args.out or (cfg.exports_dir / f"{args.client}.xlsx"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(out)
    return 0


def cmd_ledgers(args):
    from . import service

    cfg = _cfg(args)
    conn = db.connect(cfg.db_path)
    cid = _client_id(conn, args.client)
    if args.fetch:
        n = service.fetch_ledgers(conn, cfg, cid)
        print(f"Fetched {n} ledgers from Tally.")
    if args.add:
        n = service.add_ledgers_text(conn, cid, "\n".join(args.add))
        print(f"Added {n} ledger(s).")
    for r in db.ledgers(conn, cid):
        print(f"  {r['name']:40} {r['parent']:28} {r['kind']}")
    return 0


def cmd_tally_check(args):
    from .tally import TallyClient, TallyError

    cfg = _cfg(args)
    host = args.host or cfg.tally.get("host", "localhost")
    port = args.port or cfg.tally.get("port", 9000)
    tc = TallyClient(host, port)
    try:
        print(tc.ping())
        print("Companies open in Tally:", ", ".join(tc.companies()) or "none")
    except TallyError as exc:
        print(exc)
        return 1
    return 0


def cmd_mock_tally(args):
    from .tallymock import serve

    server, mock = serve(args.host, args.port, edu_mode=args.edu)
    print(f"Tally simulator on http://{args.host}:{args.port}/ (company: "
          f"{', '.join(mock.companies)}){' in Educational mode' if args.edu else ''}. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_lab(args):
    from .lab import run_lab

    cfg = _cfg(args)
    corpus = Path(args.corpus) if args.corpus else cfg.corpus_dir
    return run_lab(corpus, cfg, update=args.update, report=args.report)


def cmd_watch(args):
    from .watch import watch_forever

    cfg = _cfg(args)
    return watch_forever(cfg, once=args.once)


def cmd_backup(args):
    from .lab import backup_db

    cfg = _cfg(args)
    print(backup_db(cfg))
    return 0


def cmd_build_windows(args):
    from .winbuild import build

    out = build(Path(args.out), python_version=args.python, include_samples=not args.no_samples,
                cache=Path(args.cache) if args.cache else None,
                embed_zip=Path(args.embed_zip) if args.embed_zip else None)
    print(out)
    return 0


def cmd_demo(args):
    from . import service

    cfg = _cfg(args)
    conn = db.connect(cfg.db_path)
    cid = service.load_demo(conn, cfg)
    print(f"Demo client ready: {db.client(conn, cid)['name']}. Run `bahi serve` and open it.")
    return 0


def cmd_doctor(args):
    from .ocr import OCR
    from .tally import TallyClient, TallyError

    cfg = _cfg(args)
    ok = True
    print(f"Bahi {__version__} on Python {sys.version.split()[0]} ({sys.platform})")
    print(f"Home: {cfg.home}  (set BAHI_HOME to change)")
    for mod in ("pdfplumber", "pypdfium2", "openpyxl", "xlrd", "flask", "waitress", "rapidfuzz"):
        try:
            __import__(mod)
            print(f"  ok  {mod}")
        except ImportError:
            ok = False
            print(f"  --  {mod} missing: pip install {mod}")
    engine = OCR(cfg.ocr)
    print(f"  {'ok' if engine.available() else '--'}  OCR: {engine.version() or 'Tesseract not found (only needed for scans and photos)'}")
    conn = db.connect(cfg.db_path)
    print(f"  ok  database: {cfg.db_path} ({len(db.clients(conn))} clients)")
    host = cfg.server.get("host", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost") and not cfg.server.get("password"):
        ok = False
        print("  --  server is open to the network without a password: set [server] password in bahi.toml")
    try:
        print(f"  ok  Tally: {TallyClient(cfg.tally.get('host'), cfg.tally.get('port'), timeout=4).ping()}")
    except TallyError as exc:
        print(f"  --  Tally not reachable at {cfg.tally.get('host')}:{cfg.tally.get('port')} "
              f"(fine if Tally is on another PC or closed). {str(exc)[:80]}")
    if cfg.tally.get("edu_mode"):
        print("  !!  edu_mode is ON: voucher dates are moved to the 1st/2nd/31st. Turn it off for real books.")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bahi", description="Bank statements into Tally, checked against the balance.")
    p.add_argument("--home", help="data folder (default: BAHI_HOME or ~/bahi-data)")
    p.add_argument("--version", action="version", version=f"bahi {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="create the data folder and settings file")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("serve", help="open the app in your browser")
    s.add_argument("--lan", action="store_true", help="allow other devices on your network (needs a password)")
    s.add_argument("--port", type=int)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("parse", help="read one statement and print what was found (nothing is saved)")
    s.add_argument("file")
    s.add_argument("--password")
    s.add_argument("--rows", type=int, default=15)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_parse)

    s = sub.add_parser("import", help="import statements for a client")
    s.add_argument("files", nargs="+")
    s.add_argument("--client", required=True)
    s.add_argument("--account")
    s.add_argument("--password")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("clients", help="list clients and how many rows are ready")
    s.set_defaults(fn=cmd_clients)

    s = sub.add_parser("post", help="post ready rows to Tally (or write XML with --xml)")
    s.add_argument("--client", required=True)
    s.add_argument("--xml", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_post)

    s = sub.add_parser("export", help="Excel workbook of a client's transactions")
    s.add_argument("--client", required=True)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("ledgers", help="show, fetch or add a client's Tally ledgers")
    s.add_argument("--client", required=True)
    s.add_argument("--fetch", action="store_true")
    s.add_argument("--add", nargs="*", help='"Ledger name, Group"')
    s.set_defaults(fn=cmd_ledgers)

    s = sub.add_parser("tally-check", help="check the connection to TallyPrime")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.set_defaults(fn=cmd_tally_check)

    s = sub.add_parser("mock-tally", help="run the Tally simulator (for demos and tests)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=9000)
    s.add_argument("--edu", action="store_true", help="behave like Educational mode (dates 1, 2, 31 only)")
    s.set_defaults(fn=cmd_mock_tally)

    s = sub.add_parser("lab", help="check every statement in the sample folder against its known answer")
    s.add_argument("--corpus")
    s.add_argument("--update", action="store_true", help="accept the current results as the new answers")
    s.add_argument("--report", help="also write an HTML report here")
    s.set_defaults(fn=cmd_lab)

    s = sub.add_parser("watch", help="import files dropped into inbox/<client>/")
    s.add_argument("--once", action="store_true")
    s.set_defaults(fn=cmd_watch)

    s = sub.add_parser("backup", help="copy the database to data/backups")
    s.set_defaults(fn=cmd_backup)

    s = sub.add_parser("build-windows", help="build the zip you install on a CA firm's Windows PC")
    s.add_argument("--out", default="dist")
    s.add_argument("--python", default="3.13.16")
    s.add_argument("--cache", help="folder to keep downloads between builds")
    s.add_argument("--no-samples", action="store_true")
    s.add_argument("--embed-zip", help="a python-3.x.y-embed-amd64.zip you downloaded already")
    s.set_defaults(fn=cmd_build_windows)

    s = sub.add_parser("demo", help="add a demo client with sample data")
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("doctor", help="check the setup")
    s.set_defaults(fn=cmd_doctor)

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    return args.fn(args) or 0
