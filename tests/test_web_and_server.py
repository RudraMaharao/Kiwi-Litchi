"""The browser app, the format lab, watched folders and the Windows build."""

import io
import json
import re
import shutil
import time
import zipfile

import pytest

from bahi import db, lab, watch, winbuild
from bahi.web import create_app

from .conftest import SAMPLES


def _client(cfg):
    app = create_app(cfg)
    c = app.test_client()
    page = c.get("/")
    token = re.search(rb'name="bahi-token" content="([^"]+)"', page.data).group(1).decode()
    return c, token


def test_pages_render(cfg):
    c, token = _client(cfg)
    assert c.post("/demo", data={"_token": token}).status_code == 302
    for url in ["/", "/c/1", "/c/1/review", "/c/1/review?statement=1&status=all", "/c/1/ledgers", "/c/1/rules",
                "/c/1/settings", "/settings"]:
        r = c.get(url)
        assert r.status_code == 200, url
    assert b"Matches the statement" in c.get("/c/1/review?statement=1").data
    assert c.get("/c/1/excel").status_code == 200
    assert c.get("/c/999").status_code == 404


def test_posts_need_the_page_token(cfg):
    c, token = _client(cfg)
    c.post("/demo", data={"_token": token})
    assert c.post("/api/c/1/status", json={"ids": [1], "action": "skip"}).status_code == 400
    r = c.post("/api/c/1/status", json={"ids": [1], "action": "skip"}, headers={"X-Bahi-Token": token})
    assert r.status_code == 200 and r.get_json()["changed"] == 1


def test_password_required_when_open_to_network(cfg):
    cfg.server["host"] = "0.0.0.0"
    cfg.server["password"] = "s3cret"
    app = create_app(cfg)
    c = app.test_client()
    assert c.get("/").status_code == 401
    import base64

    auth = {"Authorization": "Basic " + base64.b64encode(b"admin:s3cret").decode()}
    assert c.get("/", headers=auth).status_code == 200
    bad = {"Authorization": "Basic " + base64.b64encode(b"admin:wrong").decode()}
    assert c.get("/", headers=bad).status_code == 401


def test_upload_flow_with_password(cfg):
    c, token = _client(cfg)
    c.post("/clients", data={"_token": token, "name": "Upload Co"})
    data = {"_token": token, "files": (open(SAMPLES / "layout_b_locked.pdf", "rb"), "locked.pdf")}
    r = c.post("/c/1/upload", data=data, content_type="multipart/form-data", headers={"X-Bahi-Token": token})
    job = r.get_json()["job"]
    res = _wait(c, job)
    f = res["result"]["files"][0]
    assert f["password"] and f["token"]
    r = c.post("/c/1/upload/retry", data={"_token": token, "token": f["token"], "password": "sharma123"},
               headers={"X-Bahi-Token": token})
    res = _wait(c, r.get_json()["job"])
    f = res["result"]["files"][0]
    assert f["ok"] and f["status"] == "verified"


def _wait(c, job):
    for _ in range(200):
        res = c.get(f"/jobs/{job}").get_json()
        if res["status"] in ("done", "error"):
            return res
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_ledger_api_learns(cfg):
    c, token = _client(cfg)
    c.post("/demo", data={"_token": token})
    conn = db.connect(cfg.db_path)
    jain = [r["id"] for r in db.txns(conn, 1) if r["party"] == "Jain Hardware Stores"]
    r = c.post("/api/c/1/ledger", json={"ids": jain[:1], "ledger": "Jain Hardware Stores"},
               headers={"X-Bahi-Token": token})
    body = r.get_json()
    assert body["set"] == 1 and body["similar"] == len(jain) - 1
    assert len(body["rows"]) == len(jain) and "Set by you" in body["rows"][str(jain[0])]


def test_lab_passes_and_catches_a_regression(cfg, tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "expected").mkdir(parents=True)
    for name in ("layout_a.pdf", "csv_amount_type.csv"):
        shutil.copy(SAMPLES / name, corpus / name)
        stem = name.rsplit(".", 1)[0]
        shutil.copy(SAMPLES / "expected" / f"{stem}.json", corpus / "expected" / f"{stem}.json")
    assert lab.run_lab(corpus, cfg) == 0
    exp = json.loads((corpus / "expected" / "layout_a.json").read_text())
    exp["rows"][3]["amount"] += 100
    (corpus / "expected" / "layout_a.json").write_text(json.dumps(exp))
    assert lab.run_lab(corpus, cfg) == 1


def test_backup(cfg, conn):
    db.add_client(conn, "Backup Co")
    path = lab.backup_db(cfg)
    import sqlite3

    assert sqlite3.connect(path).execute("SELECT name FROM clients").fetchone()[0] == "Backup Co"


def test_watch_folder_imports_and_files_away(cfg):
    folder = cfg.inbox_dir / "Watch Co"
    folder.mkdir(parents=True)
    shutil.copy(SAMPLES / "layout_d.pdf", folder / "april.pdf")
    shutil.copy(SAMPLES / "layout_b_locked.pdf", folder / "locked.pdf")
    log = watch.scan_once(cfg, settle_seconds=0)
    assert any("april.pdf" in line and "verified" in line for line in log)
    assert (folder / "done" / "april.pdf").exists()
    assert (folder / "failed" / "locked.pdf").exists()
    assert "locked" in (folder / "failed" / "locked.pdf.txt").read_text()


def test_windows_build_layout(tmp_path, monkeypatch):
    fake = io.BytesIO()
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("python313._pth", "python313.zip\r\n.\r\n\r\n#import site\r\n")
        z.writestr("python.exe", b"MZ")
    embed = tmp_path / "embed.zip"
    embed.write_bytes(fake.getvalue())
    monkeypatch.setattr(winbuild, "install_wheels", lambda target, *a, **k: target.mkdir(parents=True))
    out = winbuild.build(tmp_path / "dist", embed_zip=embed, include_samples=False)
    names = zipfile.ZipFile(out).namelist()
    assert "Bahi/Start Bahi.bat" in names and "Bahi/app/bahi/__init__.py" in names
    assert "Bahi/app/bahi/web/static/fonts/atkinson-hyperlegible-next-latin-wght-normal.woff2" in names
    pth = (tmp_path / "dist" / "Bahi" / "python" / "python313._pth").read_bytes().decode().split("\r\n")
    assert "Lib\\site-packages" in pth and "..\\app" in pth and "import site" in pth and "#import site" not in pth
    bat = (tmp_path / "dist" / "Bahi" / "Start Bahi.bat").read_bytes()
    assert b"\r\n" in bat and b"-m bahi serve" in bat


def test_cli_parse_and_doctor(cfg, capsys):
    from bahi.cli import main

    assert main(["--home", str(cfg.home), "parse", str(SAMPLES / "layout_c.pdf")]) == 0
    assert "verified" in capsys.readouterr().out
    assert main(["--home", str(cfg.home), "doctor"]) in (0, 1)


@pytest.mark.parametrize("status", ["review", "ready", "all"])
def test_review_tabs(cfg, status):
    c, token = _client(cfg)
    c.post("/demo", data={"_token": token})
    assert c.get(f"/c/1/review?status={status}").status_code == 200
