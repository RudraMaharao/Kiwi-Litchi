"""The format lab: every statement in the corpus is parsed and compared with its known answer.

Run it after every change to the parser (and nightly on the Linux box) so a
fix for one bank never quietly breaks another. Add a real statement (with
the client's permission, or your own) by dropping it in the corpus folder and
running `bahi lab --update` once you've checked the result by eye.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import sqlite3
import time
from pathlib import Path

from .config import Config
from .statement import CHECK_OK, parse_file
from .util import rupees, write_atomic

SUPPORTED = {".pdf", ".xls", ".xlsx", ".csv", ".txt", ".htm", ".html", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def _expected_from(st, password=None) -> dict:
    data = {
        "opening": st.opening, "closing": st.closing,
        "rows": [{"date": t.date.isoformat(), "amount": t.amount, "direction": t.direction, "balance": t.balance,
                  "narration": t.narration} for t in st.txns],
    }
    if password:
        data["password"] = password
    return data


def check_file(path: Path, expected: dict | None, cfg: Config) -> dict:
    t0 = time.time()
    res = {"file": path.name, "seconds": 0.0, "status": "", "detail": "", "rows": 0, "money_ok": 0,
           "narration_ok": 0, "expected_rows": 0, "source": ""}
    try:
        st = parse_file(path, (expected or {}).get("password"), ocr_settings=cfg.ocr)
    except Exception as exc:
        res.update(status="error", detail=f"{type(exc).__name__}: {exc}", seconds=round(time.time() - t0, 1))
        return res
    res["seconds"] = round(time.time() - t0, 1)
    res["rows"] = len(st.txns)
    res["source"] = st.source
    res["check"] = st.status
    res["_statement"] = st
    if expected is None:
        res["status"] = "new"
        res["detail"] = f"No answer file yet. {st.summary()}"
        return res
    rows = expected.get("rows", [])
    res["expected_rows"] = len(rows)
    money = sum(1 for e, t in zip(rows, st.txns)
                if e["date"] == t.date.isoformat() and e["amount"] == t.amount and e["direction"] == t.direction
                and e.get("balance") == t.balance)
    narr = sum(1 for e, t in zip(rows, st.txns) if e.get("narration", "") == t.narration)
    res["money_ok"], res["narration_ok"] = money, narr
    problems = []
    if len(st.txns) != len(rows):
        problems.append(f"{len(st.txns)} rows, expected {len(rows)}")
    if money != len(rows):
        problems.append(f"{len(rows) - money} row(s) with a wrong date, amount, direction or balance")
    if not expected.get("no_opening") and expected.get("opening") is not None and st.opening != expected["opening"]:
        problems.append(f"opening {rupees(st.opening)}, expected {rupees(expected['opening'])}")
    bad_checks = sum(1 for t in st.txns if t.check not in CHECK_OK)
    if bad_checks:
        problems.append(f"{bad_checks} row(s) fail the balance check")
    ocr = st.source.endswith("ocr")
    if not ocr and rows and narr < 0.95 * len(rows):
        problems.append(f"narrations: {narr}/{len(rows)} exact")
    res["status"] = "fail" if problems else "pass"
    res["detail"] = "; ".join(problems) or (f"narrations {narr}/{len(rows)} exact (OCR)" if ocr else "")
    return res


def run_lab(corpus: Path, cfg: Config, update: bool = False, report: str | None = None) -> int:
    corpus = Path(corpus)
    expected_dir = corpus / "expected"
    files = sorted(p for p in corpus.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
    if not files:
        print(f"No statements in {corpus}.")
        return 0
    results = []
    for f in files:
        exp_path = expected_dir / f"{f.stem}.json"
        expected = json.loads(exp_path.read_text()) if exp_path.exists() else None
        res = check_file(f, None if update else expected, cfg)
        st = res.pop("_statement", None)
        if update and st is not None:
            expected_dir.mkdir(parents=True, exist_ok=True)
            write_atomic(exp_path, json.dumps(_expected_from(st, (expected or {}).get("password")), indent=1))
            res["status"], res["detail"] = "updated", st.summary()
        results.append(res)
        mark = {"pass": "PASS", "fail": "FAIL", "error": "ERR ", "new": "NEW ", "updated": "SAVE"}[res["status"]]
        print(f"{mark} {res['file']:34} {res['source']:9} {res['rows']:4} rows {res['seconds']:5.1f}s  {res['detail']}")
    failed = [r for r in results if r["status"] in ("fail", "error")]
    print(f"\n{len(results) - len(failed)}/{len(results)} statements OK.")
    if report:
        write_report(Path(report), results)
        print(f"Report: {report}")
    log = cfg.logs_dir / "lab.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "ok": len(results) - len(failed),
                             "total": len(results), "failed": [r["file"] for r in failed]}) + "\n")
    return 1 if failed else 0


def write_report(path: Path, results: list[dict]):
    rows = "".join(
        f"<tr class='{r['status']}'><td>{html.escape(r['file'])}</td><td>{r['status']}</td><td>{r['source']}</td>"
        f"<td>{r['rows']}</td><td>{r['seconds']}</td><td>{html.escape(r['detail'])}</td></tr>" for r in results)
    page = f"""<!doctype html><meta charset="utf-8"><title>Bahi lab</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;color:#1d2a44}}table{{border-collapse:collapse}}
td,th{{padding:6px 10px;border-bottom:1px solid #d3e3ce;text-align:left}}.fail td,.error td{{background:#fcebe9}}
.pass td:nth-child(2){{color:#2b6a3c;font-weight:700}}</style>
<h1>Bahi lab, {dt.datetime.now():%d %b %Y %H:%M}</h1>
<table><tr><th>File</th><th>Result</th><th>Read as</th><th>Rows</th><th>Seconds</th><th>Detail</th></tr>{rows}</table>"""
    write_atomic(path, page)


def backup_db(cfg: Config) -> Path:
    """Consistent copy of the database (safe while Bahi is running), keeping the last N."""
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)
    dest = cfg.backups_dir / f"bahi-{dt.datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(str(cfg.db_path))
    out = sqlite3.connect(str(dest))
    with out:
        src.backup(out)
    out.close()
    src.close()
    keep = int(cfg.backup.get("keep", 14))
    old = sorted(cfg.backups_dir.glob("bahi-*.db"))[:-keep] if keep > 0 else []
    for p in old:
        p.unlink(missing_ok=True)
    return dest
