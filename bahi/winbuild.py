"""Build the zip you install on a CA firm's Windows PC, from your Linux box.

It needs no Windows machine: it takes the official 'embeddable' Python for
Windows from python.org, installs Bahi's dependencies as Windows wheels with
pip's --platform option, and adds a Start Bahi.bat. The firm unzips it to
C:\\Bahi and double-clicks. Nothing is installed system-wide.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import __version__
from .config import DEFAULT_TOML

DEPENDENCIES = ["pdfplumber>=0.11", "pypdfium2", "openpyxl", "xlrd>=2", "flask>=3", "waitress>=3", "rapidfuzz"]
ROOT = Path(__file__).resolve().parents[1]

START_BAT = r"""@echo off
setlocal
cd /d "%~dp0"
set "BAHI_HOME=%~dp0"
set "PYTHONUTF8=1"
title Bahi
echo Starting Bahi... keep this window open while you work. Close it to stop Bahi.
"%~dp0python\python.exe" -m bahi serve
if errorlevel 1 pause
"""

CHECK_BAT = r"""@echo off
cd /d "%~dp0"
set "BAHI_HOME=%~dp0"
"%~dp0python\python.exe" -m bahi doctor
echo.
"%~dp0python\python.exe" -m bahi tally-check
pause
"""

README_TXT = """Bahi {version}: bank statements into Tally

1. Unzip this folder to C:\\Bahi (not inside Program Files).
2. Double-click "Start Bahi.bat". Your browser opens Bahi. Keep the black window open while you work.
3. In TallyPrime, press F1 (Help) > Settings > Connectivity and set "TallyPrime acts as" to Server
   (or Both), port 9000. Keep the client's company open when you post.
4. To check everything, double-click "Check setup.bat".

Everything Bahi stores is in this folder (data\\). Back it up with the rest of your office files.
Scanned statements and photos need Tesseract OCR: install it from
https://github.com/UB-Mannheim/tesseract/wiki (default folder). Text PDFs and Excel files don't need it.
"""


def _download(url: str, cache: Path | None) -> bytes:
    if cache is not None:
        cached = cache / url.rsplit("/", 1)[-1]
        if cached.exists():
            return cached.read_bytes()
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / url.rsplit("/", 1)[-1]).write_bytes(data)
    return data


def patch_pth(python_dir: Path) -> Path:
    """Let the embedded Python find site-packages and the app folder."""
    pths = list(python_dir.glob("python3*._pth"))
    if not pths:
        raise RuntimeError("No python3XX._pth file in the embeddable Python.")
    pth = pths[0]
    lines = [ln for ln in pth.read_text().splitlines() if ln.strip()]
    out = []
    for ln in lines:
        if ln.strip().lstrip("#").strip() == "import site":
            continue
        out.append(ln)
    for extra in ("Lib\\site-packages", "..\\app"):
        if extra not in out:
            out.append(extra)
    out.append("import site")
    pth.write_text("\r\n".join(out) + "\r\n")
    return pth


def install_wheels(target: Path, python_version: str, deps: list[str] | None = None, wheel_cache: Path | None = None):
    major_minor = ".".join(python_version.split(".")[:2])
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-compile",
           "--target", str(target), "--platform", "win_amd64", "--python-version", major_minor,
           "--implementation", "cp", "--only-binary=:all:", *(deps or DEPENDENCIES)]
    if wheel_cache is not None:
        cmd[4:4] = ["--cache-dir", str(wheel_cache)]
    subprocess.run(cmd, check=True)


def build(out_dir: Path, python_version: str = "3.13.16", include_samples: bool = True, cache: Path | None = None,
          embed_zip: Path | None = None) -> Path:
    out_dir = Path(out_dir)
    stage = out_dir / "Bahi"
    if stage.exists():
        shutil.rmtree(stage)
    py_dir = stage / "python"
    py_dir.mkdir(parents=True)
    url = f"https://www.python.org/ftp/python/{python_version}/python-{python_version}-embed-amd64.zip"
    try:
        data = embed_zip.read_bytes() if embed_zip else _download(url, cache)
    except OSError as exc:
        raise SystemExit(f"Couldn't download Python for Windows ({exc}). Check the internet connection, or download "
                         f"{url} yourself and pass it with --embed-zip.") from exc
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(py_dir)
    patch_pth(py_dir)
    install_wheels(py_dir / "Lib" / "site-packages", python_version,
                   wheel_cache=(cache / "pip") if cache else None)
    shutil.copytree(ROOT / "bahi", stage / "app" / "bahi",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if include_samples and (ROOT / "samples").exists():
        shutil.copytree(ROOT / "samples", stage / "samples")
    (stage / "bahi.toml").write_text(DEFAULT_TOML.replace("\n", "\r\n"), encoding="utf-8")
    (stage / "Start Bahi.bat").write_text(START_BAT.replace("\n", "\r\n"), encoding="ascii")
    (stage / "Check setup.bat").write_text(CHECK_BAT.replace("\n", "\r\n"), encoding="ascii")
    (stage / "README.txt").write_text(README_TXT.format(version=__version__).replace("\n", "\r\n"), encoding="utf-8")
    zip_path = out_dir / f"Bahi-{__version__}-Windows.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                zf.write(p, Path("Bahi") / p.relative_to(stage))
    return zip_path
