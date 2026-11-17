#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
  echo 'This installer is for your Linux laptop. Copy the folder there first.' >&2
  exit 1
fi
if [[ "$EUID" -eq 0 ]]; then
  echo 'Run this script as your normal Linux user, without sudo.' >&2
  exit 1
fi
cd "$(dirname "${BASH_SOURCE[0]}")/.."
umask 077
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required (Linux Mint 21/22)"'
if ! python3 -m venv .venv; then
  echo 'Install prerequisites: sudo apt install python3-venv python3-pip tesseract-ocr poppler-utils' >&2
  exit 1
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[files,vectors,server,tests]'
.venv/bin/python -m pytest -q
.venv/bin/python -m kiwi_litchi.launcher init
.venv/bin/python -m kiwi_litchi.launcher demo
if [[ ! -f "${KIWI_DATA_DIR:-$HOME/.local/share/kiwi-litchi}/auth.json" ]]; then
  .venv/bin/python -m kiwi_litchi password
fi
.venv/bin/python -m pip freeze > installed-versions.txt
echo 'Installed. Start with: bash scripts/run.sh'
echo 'Open http://127.0.0.1:8765 on the Linux laptop.'
