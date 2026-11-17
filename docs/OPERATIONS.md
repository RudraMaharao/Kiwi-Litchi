# Operations

## Commands and files

Activate the environment with `source ~/Apps/kiwi-litchi-linux/.venv/bin/activate`.

- `kiwi` starts the combined app. `kiwi clients`, `kiwi ledgers`, `kiwi import`, `kiwi post --dry-run`, `kiwi lab` retain the original Bahi workflows; use each command's `--help` for arguments.
- `litchi` manages books, embeddings, retrieval, audit reports and whole-workspace backups. Use `litchi --help`.
- `bahi` remains a compatibility command and can use a different home. Prefer `kiwi` for this package.

Default data root: `~/.local/share/kiwi-litchi`. Set `KIWI_DATA_DIR` before launching commands/services to choose another location. Original Kiwi settings: `kiwi/bahi.toml`; database: `kiwi/data/bahi.db`. Litchi books/configs: `clients/kiwi-N/`. Legal source database: `law.sqlite3`. No real client records, passwords, downloaded models or runtime databases are included in the release ZIP.

The web service binds only to localhost. Use the laptop's browser, or an SSH tunnel with localhost forwarding for remote access. Changing `[server] host` does not expose the combined service; LAN/Tailscale web hosting is not enabled in this pilot. The separate signal engine in the plan is outside this package.

## Tally connection and import

In `kiwi/bahi.toml`, set `[tally] host` to the machine running Tally and `port` to its XML port, normally 9000. Use a literal private LAN IP if pulling books from another computer. Set the exact company name in Kiwi's client settings. After changing settings restart the web app.

```bash
kiwi tally-check
kiwi ledgers --client 'Exact client name' --fetch
litchi clients
litchi pull-books kiwi-1 --start 2026-04-01 --end 2027-03-31
```

Alternatively import native exported XML using the web app or `litchi import-books kiwi-1 /path/to/books.xml`. Masters and vouchers can be separate files. Each voucher needs a stable GUID/REMOTEID/MASTERID, balanced ledger lines, a date and voucher type. Reimport updates by ID. Missing or deleted vouchers are not inferred from absence: reconcile counts and totals against Tally, and rebuild a separate fresh dataset if a source snapshot has removed vouchers. Only Payment/Receipt types feed current prediction history and book questions; custom voucher types need explicit mapping support before use.

## Night jobs and watch folders

```bash
systemctl --user list-timers
journalctl --user -u kiwi-web -n 80
journalctl --user -u litchi-batch -n 80
litchi batch --embeddings
```

Reports are under `clients/<id>/reports/latest.json`, with timings, items processed, errors, audit flags and Python peak memory. The Python peak excludes Ollama/Docker. Measure whole-system RAM separately (`free -h`, `ollama ps`, `sudo docker stats --no-stream`). The 2 GB systemd application limit excludes the other services. Sleep/suspend prevents overnight jobs; configure the laptop's power settings for its intended server use. Missed timers are not replayed during daytime. Batch timeout is five hours, not a guarantee of finishing before 06:00 if started late manually.

The watcher reads `kiwi/inbox/<exact client name>/`; completed files move to `done`, failed files to `failed` with a reason. Files must settle for five seconds. Locked PDFs should first be uploaded in Kiwi to supply the password. Watched imports only populate the review workflow; they never post automatically.

To disable services:

```bash
systemctl --user disable --now kiwi-web.service kiwi-watch.timer kiwi-backup.timer kiwi-lab.timer litchi-batch.timer
```

## Backup and restore

```bash
litchi backup
litchi backup --qdrant
```

Backups use SQLite's backup API and include both apps' databases, client configs, original uploads/exports, Kiwi config and the law source library. Fourteen successful backup sets are retained. Normal scheduled backups omit the regenerable Qdrant index; `--qdrant` additionally downloads the active collection snapshot. Snapshot downloads currently have a 50 MB response cap; rebuild from the source library for larger indexes. Multi-database backups are individually consistent, not a transactional snapshot across all clients and services. Stop writes for a coordinated firm-wide cutover. Watch inboxes and service definitions should also be copied separately if needed.

Copy completed backup folders to an external drive weekly. Restore into a NEW directory, never over the live database:

```bash
litchi --data-dir "$HOME/kiwi-restore-test" restore /path/to/backup-folder
litchi --data-dir "$HOME/kiwi-restore-test" password
```

Checksums and client database integrity are checked. The restored law index is invalidated: run `law-index` with the restored data root to rebuild. Passwords/sessions are not restored. Inspect totals before changing `KIWI_DATA_DIR` to the restored directory. Keep the original data directory until the restore has been verified.

## Troubleshooting

- Port occupied: stop the existing app/service before running another server. The intended address is localhost:8765.
- Model not downloaded: run the exact `ollama pull` command in AI-SETUP.md.
- Model digest changed: rerun embeddings and calibration; rebuild law-index.
- Wrong UI password: use `kiwi password`, then sign in again. Restart to invalidate existing sessions immediately.
- PDF/scan mismatch: keep the source and expected output, fix the parser/layout, and add the sample to the regression lab. Approval cannot bypass an unresolved row balance check.
- Tally timeout: inspect the target company before any retry. Original Kiwi does not guarantee exactly-once external posting across a timeout/crash. Never retry blindly.

## Configuring review heuristics

A TDS review rule uses these keys (supply independently reviewed values): `ledgers` (list of exact counterparty ledgers), `threshold_paise` (integer), `start` and `end` (ISO dates), `tds_ledgers` (list of exact deduction ledger names), and `source` (applicable source and scope). Add records to the client's `tds_review_rules` list. This looks for missing deduction lines in payment vouchers; separate deduction journals require human reconciliation. It is a review prompt, not a statutory determination.
