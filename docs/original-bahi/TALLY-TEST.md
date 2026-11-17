# Checking Bahi against real TallyPrime

Bahi's Tally XML follows Tally's documented import format and a template used by an established Excel-to-Tally vendor. It was tested against Bahi's own simulator, not real TallyPrime. Run through this once, in the Windows VM with Educational mode ([SERVER.md, section 5](SERVER.md)) or on any PC with TallyPrime, before the first firm relies on it. It takes about half an hour.

Setup:
1. Set `[tally] edu_mode = true` in `bahi.toml`. Educational mode only accepts the 1st, 2nd and 31st of a month, and edu mode moves dates there.
2. Create a company in Tally called **Sharma Traders (Demo)**.
3. In Bahi, click **Load the demo client**, then run **Ledgers > Fetch ledgers from Tally**.

| # | Check | How | If it fails |
|---|---|---|---|
| 1 | Bahi can reach Tally | `bahi tally-check` lists the company | Connectivity: *acts as* Server or Both, port 9000, firewall allows it. In the VM, check the port forward |
| 2 | Ledgers fetch with groups | Ledgers page shows Cash as *Cash* and your bank ledger as *Bank* | Tell me what the page shows |
| 3 | Missing ledgers are created | Post the demo. The bank ledgers, parties, expense and tax ledgers and Suspense A/c that the new company doesn't have yet are created first, each under a sensible group | Use **Download Tally XML** and import the *new-ledgers* file with Alt+O > Masters |
| 4 | Payment, Receipt and Contra vouchers post | Post to Tally. Day Book shows all three types with the right Dr and Cr sides | Note the exact message Tally gives |
| 5 | Bank details are accepted | Open a posted Payment: the bank allocation shows the transaction type, instrument number and bank date | Turn off *Fill in bank details* in Client settings and post again |
| 6 | Entries show as reconciled | Banking > Bank Reconciliation for the bank ledger: posted rows have a bank date | Same as 5. The rest still works without it |
| 7 | Custom voucher types | Set Payment voucher type to an existing custom type (for example "Bank Payment") and post one row | Check the name matches exactly |
| 8 | The right company | With two companies open, rows go to the one set in Client settings | Use the company name exactly as Tally shows it |
| 9 | XML file import | **Download Tally XML**, then in Tally press Alt+O > Transactions and give the file path | Note Tally's message |
| 10 | Importing the same file twice | Import the same vouchers file again | If Tally duplicates them, warn firms to import each file once. Bahi itself never exports a row twice |
| 11 | Bill-wise party ledgers | Post a receipt to a party ledger with bill-wise details on | If Tally insists on bill allocations, tell me and I'll add "On Account" entries |

Afterwards, set `edu_mode = false`. Then send me two things: any check that failed, with Tally's exact message, and the Tally version from F1 > About.
