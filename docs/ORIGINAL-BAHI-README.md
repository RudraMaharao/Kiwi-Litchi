# Bahi

Bahi turns bank statements into Tally vouchers. It takes PDFs (including locked ones), Excel and CSV downloads, scans and phone photos, and checks every row against the running balance. It also suggests the ledger for each line and learns the firm's choices. Then it posts straight into TallyPrime or writes an XML file to import. It runs on the firm's own PC, so client data never leaves the office.

It is built for one job: the hours small CA firms spend every month typing client bank statements into Tally.

## What it does

- **Reads any statement layout** by finding the column headings (Date, Narration, Withdrawal, Deposit, Balance and their many spellings), not with one template per bank. It handles:
  - two-line headings and narrations that wrap mid-word;
  - newest-first statements;
  - overdraft balances marked Dr;
  - a single Amount column with a Dr/Cr flag;
  - Excel downloads that are really HTML pages.
- **Proves every row.** Each balance must equal the previous balance plus the credit or minus the debit.
  - When it does, the row was read correctly, and the balance also settles whether the money went in or out.
  - When it doesn't, the row is flagged, because a row was missed or misread.
  - For scans, a misread amount is repaired from the balances, and a misread date from the rows around it.
- **Suggests ledgers**, most certain first:
  1. your rules;
  2. what you chose last time for the same UPI ID or party;
  3. transfers between the client's own accounts (Contra);
  4. standard entries (cash, charges, interest, GST, TDS, EMIs, salary);
  5. Tally party ledgers with a matching name;
  6. otherwise Suspense, flagged for review.
- **Learns.** Set a ledger once and every other row for that party fills in, this month and next.
- **Posts to Tally** over its port 9000:
  - it creates missing ledgers first;
  - it fills in the bank details, so entries show as reconciled in Tally's bank reconciliation;
  - each voucher is posted separately, so one bad row doesn't block the rest.
  - Or it writes XML files for **Alt+O > Import** in TallyPrime.
- **Never imports twice.** The same file is refused, and rows repeated across overlapping statements are marked.

TallyPrime 6 can import Excel and CSV statements from its list of supported banks itself, but not PDFs, scans or photos, and it doesn't learn ledgers. That's where Bahi earns its place.

## Try it in two minutes

On your Linux box, from this folder:

```bash
bash deploy/install-linux.sh        # Python environment, `bahi` command, services
source ~/.bashrc
bahi mock-tally &                   # a Tally simulator, so you can post without TallyPrime
bahi serve                          # opens http://127.0.0.1:8765/
```

Click **Load the demo client**. You get a sample April statement with 47 rows, every one matched to the balance, and 31 already mapped to ledgers.
1. Fix one of the 16 that need review: type a ledger and press Enter. The other rows for that party fill in.
2. Click **Post to Tally**.
3. Then try **Add statements** with the files in `samples/`. The locked PDF's password is `sharma123`.

## Install at a CA firm (Windows)

On your Linux box:

```bash
bahi build-windows --out dist      # downloads Python for Windows and builds dist/Bahi-1.0.0-Windows.zip
```

At the firm:
1. Unzip to `C:\Bahi` and double-click **Start Bahi.bat**. The browser opens Bahi.
2. In TallyPrime, press **F1 (Help) > Settings > Connectivity**. Under Client/Server configuration:
   - set *TallyPrime acts as* to **Server** or **Both**, and the port to **9000**;
   - if there is an *Enable ODBC* option, set it to **Yes**.
3. Run **Check setup.bat** to confirm Bahi can see Tally.

The zip contains its own Python, so nothing is installed system-wide and the firm's IT doesn't need to be involved. Scanned statements also need [Tesseract for Windows](https://github.com/UB-Mannheim/tesseract/wiki) in its default folder. Text PDFs and Excel files don't.

## Using it

1. **Add a client.** Use the Tally company name exactly as it appears in Tally.
2. **Ledgers > Fetch ledgers from Tally.** Matching and Contra detection get much better with the real list.
3. **Client settings:**
   - pick the Tally bank ledger for each account;
   - fill in the standard entries: bank charges, interest, GST, TDS, EMIs, salary;
   - change the voucher type names if the firm uses its own (for example "HDFC Payment").
4. **Add statements.** Drop them on the page. Locked PDFs ask for the password once, and Bahi remembers it for that account.
5. **Review.**
   - The balance proof at the top shows whether the statement adds up.
   - *Needs review* lists only the rows Bahi wasn't sure about.
   - Keyboard: ↑↓ to move, Enter to edit the ledger, A to approve, S to skip, X to select.
6. **Post to Tally**, or **Download Tally XML**, or **Download Excel** for the firm's working papers.

Next month the same client's statement arrives mostly mapped already.

## Getting the most from your Linux box

[docs/SERVER.md](original-bahi/SERVER.md) covers running the laptop 24/7:
- Bahi on your network and phone (with a password);
- a nightly re-check of every sample statement plus a database backup;
- watched inbox folders;
- building the Windows zip;
- a Windows virtual machine with TallyPrime for testing.

It also has a RAM budget for 8 GB.

## Before you sell it

- [docs/TALLY-TEST.md](original-bahi/TALLY-TEST.md): what to check against real TallyPrime (Educational mode is fine) before the first firm uses it. Bahi was tested here against a simulator, not real Tally.
- [docs/CA-VISIT.md](original-bahi/CA-VISIT.md): a ten-minute demo script, the offer, and answers to the usual objections.
- **Test on real statements.** Run `bahi parse your-statement.pdf` on your own statements from every bank you can get. Then put them in a private corpus folder and run `bahi lab --corpus that-folder --update` once they read correctly. From then on `bahi lab` catches any change that breaks them.

## Commands

| Command | What it does |
|---|---|
| `bahi serve` | Open the app (`--lan` to allow other devices; needs a password) |
| `bahi parse FILE` | Read one statement and print what was found, without saving anything |
| `bahi import FILE... --client NAME` | Import from the command line |
| `bahi post --client NAME` | Post ready rows to Tally (`--xml` to write files, `--dry-run` to preview) |
| `bahi ledgers --client NAME --fetch` | Fetch the client's ledgers from Tally |
| `bahi export --client NAME` | Excel workbook of the client's rows |
| `bahi tally-check` | Is Tally reachable, and which companies are open? |
| `bahi mock-tally` | Tally simulator for demos (`--edu` to act like Educational mode) |
| `bahi lab` | Check every statement in the corpus against its known answer |
| `bahi watch` | Import files dropped into `inbox/<client name>/` |
| `bahi backup` | Copy the database to `data/backups` |
| `bahi build-windows` | Build the Windows zip |
| `bahi demo`, `bahi doctor`, `bahi clients` | Demo client, setup check, client list |

Settings live in `bahi.toml` in the data folder (`~/bahi-data` on Linux, the Bahi folder on Windows): Tally address, network access and password, OCR, watched folders, backups. `edu_mode = true` moves voucher dates to the 1st, 2nd or 31st so you can test against TallyPrime's Educational mode. Never leave it on for real books.

## Not done yet

- **Narrations printed vertically centred** on the amount line, with text above the date, get split across the wrong rows. The amounts stay correct. Top-aligned and bottom-aligned layouts are handled.
- **Password-protected Excel files** need an unlocked copy first.
- **Bill-wise details** (allocating receipts against specific invoices) aren't filled in. Party entries go in as plain ledger entries.
- **GSTR-2B against the purchase register**, the second job CA firms asked for, is not built yet.
- **Scans and photos** read reliably for the money, because the balance check proves it. Read the narrations by eye: OCR can still confuse O and 0 inside them.

## Privacy and security

- By default the app listens on this computer only (127.0.0.1).
- Opening it to the network requires a password (user `admin`), and every change needs a per-session token.
- Statements, saved PDF passwords and the learned ledger choices stay in the data folder.
- Nothing is sent anywhere except to the Tally address you configure.
- Under India's DPDP Act, a firm's client data is personal data. Keeping it on the firm's PC is the simplest way to stay on the right side of that. If you ever process statements on your own machine for a firm, agree that in writing first.

## Tests

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # 108 tests: every sample layout, scans, Tally XML, the web app
python tools/make_samples.py           # regenerate the synthetic statements in samples/
```

The statements in `samples/` are synthetic. They belong to a fictional business ("Sharma Traders") at a fictional "Sample Bank", in column layouts like those Indian banks print.
