# Visiting a CA firm

The goal of a first visit is one free month on one of the firm's clients, processed on their PC. You're not trying to close a sale on the spot.

## Before you go

- **A real example.** Run your own bank statement through Bahi first, so you can say "this is my own account" while you show it.
- **A Windows build.** Run `bahi build-windows` and put the zip on a USB stick.
- **The demo on your MacBook or phone.** Either run Bahi with the Tally simulator on the MacBook (`bahi mock-tally &` then `bahi serve`), or open your Linux box over Tailscale. Load the demo client.
- **Timing.** Avoid filing crunches. Within a month, go after the 20th, once GST returns are filed.

## The ten minutes

1. **Ask before you show** (2 minutes).
   - "How do bank statements get into Tally here?"
   - "How many clients send PDFs? Locked ones? Scans or WhatsApp photos?"
   - "Roughly how long does one client's month take?"

   Write down the answers. You'll use their own numbers when you price.
2. **Show the proof** (3 minutes). Drop a locked PDF on the page and type the password.
   - Point at the balance proof: opening plus credits minus debits equals the bank's closing balance, and every row checks against the running balance.
   - "If anything is misread or missing, it shows up here. You don't have to check rows one by one."
3. **Show the learning** (2 minutes). On *Needs review*, type a ledger for one party and press Enter. The other rows for that party fill in. "Next month this client's statement arrives mostly done."
4. **Show it landing in Tally** (2 minutes). Click **Post to Tally**:
   - the vouchers appear in the Day Book;
   - new ledgers are created;
   - the bank details are filled in for reconciliation.
5. **Make the offer** (1 minute). "Pick one client. I'll install it on this PC and do their last month with you, free. If it saves you time, it's ₹X to set up for all your clients."

## What to say about privacy

- "It runs on this PC. Nothing is uploaded anywhere; it doesn't need the internet."
- "Your clients' statements stay in a folder on this machine. You can back it up like any other office file."

## Prices to test

These are guesses from the market research, not market data:

| Item | Price |
|---|---|
| Setup for the firm (its banks, its ledgers, one client done with them) | ₹15,000 to 30,000 once |
| Support, including fixing a bank format when a bank changes it | ₹1,500 to 3,000 a month |
| Each new bank format or report | ₹3,000 to 5,000 |

Price from their own answers in step 1. Four hours a month saved at an article assistant's cost is the number to beat.

## Objections

- **"Tally already imports bank statements."**
  - TallyPrime imports Excel and CSV downloads from the banks it supports.
  - It doesn't read PDFs, locked PDFs, scans or photos, which is most of what clients send.
  - It doesn't learn which ledger each party goes to.
  - Bahi does those, and posts into the same Tally.
- **"What if it reads something wrong?"** Every row is checked against the bank's running balance, and anything that doesn't match is flagged before it reaches Tally. Nothing posts until someone approves it.
- **"What if the bank changes its statement format?"** That's what the support fee covers. Most format changes need no fix, because Bahi reads column headings rather than fixed positions.
- **"We don't want software on our PC."** It's one folder: no installer, no admin rights, and deleting the folder removes it.
- **"Our data is sensitive."** That's why it works offline on their PC.

## Installing at the firm

1. Unzip to `C:\Bahi` and double-click **Start Bahi.bat**.
2. In TallyPrime, press F1 (Help) > Settings > Connectivity, set *acts as* to Server or Both, port 9000. Then run **Check setup.bat**.
3. Set up the client:
   1. Add the client with the Tally company name.
   2. Run **Fetch ledgers from Tally**.
   3. In Client settings, set the bank ledger and the standard entries.
4. Process one month with the CA watching. Approve, post, and open the Day Book together.
5. Show them **Download Excel** for the client's working papers.

## After the visit

- Write down what they do today and how long it takes. That's your before-and-after story for the next firm.
- If they agree, ask for an introduction to two other firms.
