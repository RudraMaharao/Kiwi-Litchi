#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo 'Run this on your Linux laptop.' >&2; exit 1; }
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo 'First run: bash scripts/install-linux.sh' >&2
  exit 1
fi
exec .venv/bin/python -m kiwi_litchi serve "$@"
