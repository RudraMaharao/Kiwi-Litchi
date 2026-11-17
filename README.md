# Kiwi + Litchi

A local bookkeeping workspace for Linux Mint — import bank statements, reconcile every row, review ledger choices, prepare Tally vouchers, and trace book answers back to their evidence

Kiwi handles statement review and posting preparation · Litchi adds historical ledger suggestions, audit signals, fixed-SQL book queries and retrieval from a separately supplied law library

**Working pilot, with measured limits** — 214 regression cases passed on Linux, five actual local-stack checks passed and a disposable Tally company was exercised · real-client, legal-quality and broad prediction gates remain open

| Kiwi · statement review | Litchi · book evidence |
|---|---|
| ![Kiwi beige workspace](docs/screenshots/02-kiwi-clients.jpg) | ![Litchi lychee workspace](docs/screenshots/08a-litchi-overview-viewport.jpg) |

## Project guide

- [Full screenshot gallery and stage index](docs/SCREENSHOTS.md)
- [Workflow, architecture and automation maps](docs/WORKFLOW.md)
- [All measured metrics, failed smoke case and unmeasured evaluations](docs/METRICS-AND-EVALUATIONS.md)
- [Exact LLM/embedding specs, request parameters and local tuning](docs/MODEL-SPECS.md)
- [Hardware and installed package versions](docs/ENVIRONMENT.md)
- [Changes from the supplied baseline](docs/CHANGELOG.md)
- [Linux installation and setup](docs/INSTALL-LINUX.md)

## Repository contents

The repository includes the complete application (`bahi/`, `kiwi_litchi/`), synthetic statement samples, practice XML/CSV examples, tests, Linux scripts, local-model benchmark, screenshots, SVG diagrams, environment/model specifications, validation records and original-source documentation. Runtime databases, credentials, model weights and TallyPrime itself are excluded.

After cloning, open `OPEN-KIWI-LITCHI.html` locally for the offline project index. The full gallery is also embedded below.

## What works in the tested workflow

- CSV, Excel, text PDF, scanned PDF and photographed statement parsing
- Running-balance checks, duplicate handling, ledger rules and correction memory
- Payment, Receipt and Contra XML, explicit company targeting and missing-ledger creation
- Native Tally voucher import into Litchi with repeat/amend/cancel handling
- Exact book totals from integer-paise SQL with the supporting vouchers
- Local Ollama embeddings and structured model intents with validation guards
- User services, timed batch jobs and backup/restore

## Measured snapshot

| Check | Observed result |
|---|---|
| Regression suite | 214 passed, zero skips/failures/errors, installed run 59.01 seconds, package run 70.62 seconds |
| Synthetic statement lab | 11/11 passed, OCR narration still needs review |
| Actual AI stack | 5/5 passed against local services |
| Original Tally practice example | 4 vouchers, bank ₹9,600 debit and Cash ₹500 debit |
| Full practice sync | 10 active vouchers, 3 cancelled objects excluded |
| Independent restore | Four databases and 45 tables matched |
| Small raw-model intent smoke | 2/3 exact matches — not a broad accuracy claim |

## Quick Linux run

```bash
sudo apt install git python3-venv python3-pip tesseract-ocr poppler-utils curl
git clone https://github.com/RudraMaharao/kiwi-litchi.git
cd kiwi-litchi
bash scripts/install-linux.sh
bash scripts/run.sh
```

Open `http://127.0.0.1:8765` and set/sign in with your own local password · follow the installation guide for Ollama, model downloads and Qdrant

```bash
.venv/bin/python -m pytest -q
.venv/bin/kiwi lab --report statement-lab.html
.venv/bin/python scripts/check-live-stack.py
.venv/bin/python scripts/benchmark-local-models.py --output model-smoke-benchmark.json
```

The model benchmark requires both installed models and unloads them between phases — run it when other model work is idle

## Automation boundary

Watch jobs import files for review · scheduled jobs back up data, run statement checks, cache suggestions and write audit reports · human approval and explicit posting remain separate

A timeout can occur after Tally has committed a voucher — inspect actual Tally data before retrying, because exactly-once posting is not guaranteed

## Models and data

- `llama3.2:1b-instruct-q4_K_M` — 1,235,814,432 parameters, supplied Q4_K_M artifact, app context 4,096
- `nomic-embed-text` — 136,727,040 parameters, F16, 768-dimensional vectors
- CPU-only application requests, two threads, one parallel Ollama request and one loaded model
- No local fine-tuning or weight changes — the change log describes the actual prompt, guard and configuration work

No client databases, passwords, model weights, Tally installer or Wine prefix are included

The law library starts empty and the screenshots show abstention · a CA-reviewed legal evaluation and independent labelled ledger holdout are not claimed passed

## Provenance

Built on the supplied Bahi 1.0.0 source and combined Kiwi/Litchi bundle · original documentation remains in this package

[Source provenance](docs/PROVENANCE.md) · [Original Bahi README](docs/ORIGINAL-BAHI-README.md) · [Font licence](bahi/web/static/fonts/OFL-atkinson-hyperlegible-next.txt)

No new licence is asserted over the supplied application code · model weights and TallyPrime retain their upstream terms

## Architecture and workflow diagrams

### Statement workflow

![Kiwi and Litchi statement workflow](docs/diagrams/workflow.svg)

### Background automation

![Kiwi and Litchi background automation](docs/diagrams/automation.svg)

## Full screenshot walkthrough

All 31 supplied workflow captures are embedded here, including nine native TallyPrime screenshots from the disposable practice company. Earlier upload/approval clicks were not photographed and have not been reconstructed. Click an image to inspect it at full resolution.

### Kiwi: sign-in, clients, statements and review

**Shared sign-in with a blank password field**

![Shared sign-in with a blank password field](docs/screenshots/01-sign-in.jpg)

**Kiwi client overview, beige and burnt orange**

![Kiwi client overview, beige and burnt orange](docs/screenshots/02-kiwi-clients.jpg)

**Statement import controls and test posting history**

![Statement import controls and test posting history](docs/screenshots/03-kiwi-statements.jpg)

**The four original practice rows after posting**

![The four original practice rows after posting](docs/screenshots/04-kiwi-review-posted.jpg)

**Ledger cache before final refresh**

![Ledger cache before final refresh](docs/screenshots/05-kiwi-ledgers.jpg)

**Ten masters fetched from the actual Tally company**

![Ten masters fetched from the actual Tally company](docs/screenshots/05b-kiwi-ledgers-refreshed.jpg)

**Rules and saved correction memory**

![Rules and saved correction memory](docs/screenshots/06-kiwi-rules-memory.jpg)

**Exact Tally company, bank mappings and voucher settings**

![Exact Tally company, bank mappings and voucher settings](docs/screenshots/07-kiwi-client-settings.jpg)

### Litchi: predictions, questions, audit and law

**Litchi overview, 8 statement rows and 10 active Tally vouchers**

![Litchi overview, 8 statement rows and 10 active Tally vouchers](docs/screenshots/08-litchi-overview.jpg)

**Litchi viewport and distinct lychee palette**

![Litchi viewport and distinct lychee palette](docs/screenshots/08a-litchi-overview-viewport.jpg)

**No remaining eligible review rows, no fabricated prediction**

![No remaining eligible review rows, no fabricated prediction](docs/screenshots/09-litchi-ledger-predictions.jpg)

**Exact query, model-intent option and Tally XML import**

![Exact query, model-intent option and Tally XML import](docs/screenshots/10-litchi-book-query-form.jpg)

**₹102.25 exact Payment total and its three vouchers**

![₹102.25 exact Payment total and its three vouchers](docs/screenshots/11-litchi-exact-total-evidence.jpg)

**Local model enabled before requesting a payment query**

![Local model enabled before requesting a payment query](docs/screenshots/12-litchi-local-model-query.jpg)

**Payment result panel after the model request**

![Payment result panel after the model request](docs/screenshots/13-litchi-local-model-result.jpg)

**Audit screen before execution**

![Audit screen before execution](docs/screenshots/14-litchi-audit-before.jpg)

**Audit signals and explicit unconfigured-rule skips**

![Audit signals and explicit unconfigured-rule skips](docs/screenshots/15-litchi-audit-results.jpg)

**Dated law search configuration**

![Dated law search configuration](docs/screenshots/16-litchi-law-search.jpg)

**Empty-library abstention, no invented legal answer**

![Empty-library abstention, no invented legal answer](docs/screenshots/17-litchi-empty-law-abstention.jpg)

**Litchi ledger and rule controls**

![Litchi ledger and rule controls](docs/screenshots/18-litchi-ledgers-rules.jpg)

**Actual model-assisted receipt query, ₹200.00 and one voucher**

![Actual model-assisted receipt query, ₹200.00 and one voucher](docs/screenshots/19-litchi-model-receipt-result.jpg)

### Historical practice capture

**first four posted before theme update**

![first four posted before theme update](docs/screenshots/history/first-four-posted-before-theme-update.jpg)

### TallyPrime: native company, vouchers and reconciliation

**Tally company and Educational Mode, initial April-only view**

![Tally company and Educational Mode, initial April-only view](docs/screenshots/tallyprime/01-company.png)

**Tally dashboard through 2 November, bank and cash balances**

![Tally dashboard through 2 November, bank and cash balances](docs/screenshots/tallyprime/02-dashboard-with-balances.png)

**Tally bank, capital and supplier master groups**

![Tally bank, capital and supplier master groups](docs/screenshots/tallyprime/03-chart-of-accounts-assets.png)

**Tally expense/income groups, 28 groups and 10 ledgers**

![Tally expense/income groups, 28 groups and 10 ledgers](docs/screenshots/tallyprime/04-chart-of-accounts-expenses.png)

**Tally Day Book for 1–2 November, including 3 cancellations**

![Tally Day Book for 1–2 November, including 3 cancellations](docs/screenshots/tallyprime/05-day-book-with-cancellations.png)

**Native ₹100 Payment voucher and its expense ledger**

![Native ₹100 Payment voucher and its expense ledger](docs/screenshots/tallyprime/06-payment-voucher-100.png)

**Bank reconciliation summary, books and expected bank balance both ₹9,600**

![Bank reconciliation summary, books and expected bank balance both ₹9,600](docs/screenshots/tallyprime/07-bank-reconciliation-summary.png)

**Native bill-wise supplier ledger with the ₹2 test Payment**

![Native bill-wise supplier ledger with the ₹2 test Payment](docs/screenshots/tallyprime/08-billwise-supplier-payment.png)

**Client/server settings, Both mode, ODBC enabled and port 9000**

![Client/server settings, Both mode, ODBC enabled and port 9000](docs/screenshots/tallyprime/09-connectivity-port-9000.png)
