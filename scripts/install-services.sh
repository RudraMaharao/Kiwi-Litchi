#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo 'Linux only.' >&2; exit 1; }
[[ "$EUID" -ne 0 ]] || { echo 'Run as your regular user, without sudo.' >&2; exit 1; }
cd "$(dirname "${BASH_SOURCE[0]}")/.."
.venv/bin/python scripts/write-services.py "$@"
systemctl --user daemon-reload
systemctl --user enable --now kiwi-web.service kiwi-backup.timer kiwi-lab.timer litchi-batch.timer kiwi-watch.timer
echo 'Services enabled for this user. Check: systemctl --user status kiwi-web'
echo 'To run at boot without logging in, separately run: sudo loginctl enable-linger "$USER"'
