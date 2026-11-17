"""Watched folders: drop statements into inbox/<client name>/ and they are imported.

On a CA firm's PC this lets staff save statements straight from email into a
folder. On your Linux box it pairs with Syncthing for firms that prefer to
send files rather than install anything. Imported files move to done/,
problem files to failed/ with a note saying why.
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from . import db, service
from .config import Config
from .lab import SUPPORTED
from .pdftext import PasswordRequired
from .util import now_iso


def _move(src: Path, folder: Path, note: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / src.name
    n = 2
    while dest.exists():
        dest = folder / f"{src.stem} ({n}){src.suffix}"
        n += 1
    shutil.move(str(src), str(dest))
    if note:
        dest.with_name(dest.name + ".txt").write_text(f"{now_iso()}\n{note}\n", encoding="utf-8")
    return dest


def scan_once(cfg: Config, settle_seconds: float = 5.0) -> list[str]:
    inbox = cfg.inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)
    readme = inbox / "README.txt"
    if not readme.exists():
        readme.write_text("Make one folder per client (named exactly like the client in Bahi) and drop statements "
                          "into it. Imported files move to done/, files with problems to failed/.\n", encoding="utf-8")
    log = []
    conn = db.connect(cfg.db_path)
    try:
        for folder in sorted(p for p in inbox.iterdir() if p.is_dir() and not p.name.startswith(".")):
            files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED]
            if not files:
                continue
            cid = db.add_client(conn, folder.name)
            for f in sorted(files):
                if time.time() - f.stat().st_mtime < settle_seconds:
                    continue  # still being copied
                try:
                    out = service.import_statement(conn, cfg, cid, f)
                    _move(f, folder / "done")
                    log.append(f"{folder.name}/{f.name}: {out.summary}; {out.ready} ready, {out.review} to review")
                except service.AlreadyImported as exc:
                    _move(f, folder / "done", str(exc))
                    log.append(f"{folder.name}/{f.name}: already imported")
                except PasswordRequired:
                    _move(f, folder / "failed", "This PDF is locked. Upload it in Bahi and enter the password once; "
                                                "Bahi remembers it for this account.")
                    log.append(f"{folder.name}/{f.name}: locked")
                except Exception as exc:
                    _move(f, folder / "failed", f"{type(exc).__name__}: {exc}")
                    log.append(f"{folder.name}/{f.name}: failed ({exc})")
    finally:
        conn.close()
    if log:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        with open(cfg.logs_dir / "watch.log", "a", encoding="utf-8") as fh:
            for line in log:
                fh.write(f"{now_iso()} {line}\n")
    return log


def watch_forever(cfg: Config, once: bool = False) -> int:
    interval = max(5, int(cfg.watch.get("interval_seconds", 20)))
    print(f"Watching {cfg.inbox_dir} every {interval}s. Ctrl+C to stop.")
    while True:
        for line in scan_once(cfg, 0 if once else 5):
            print(line)
        if once:
            return 0
        time.sleep(interval)


def start_background(cfg: Config) -> threading.Thread:
    def loop():
        interval = max(5, int(cfg.watch.get("interval_seconds", 20)))
        while True:
            try:
                scan_once(cfg)
            except Exception as exc:  # keep watching
                print(f"watch: {exc}")
            time.sleep(interval)

    t = threading.Thread(target=loop, name="bahi-watch", daemon=True)
    t.start()
    return t
