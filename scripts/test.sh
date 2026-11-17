#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m pytest -q --junitxml=test-results.xml
fi
exec python3 -m pytest -q --junitxml=test-results.xml
