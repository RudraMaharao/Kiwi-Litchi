# Kiwi and Litchi verification — 16–17 November 2026

All live writes were limited to the disposable Tally company `Kiwi Linux Test` and Kiwi client 2

## Completed

- Automated suite: 214 passed in 76.26 seconds, with no skips or failures
- Actual Linux AI stack: all 5 checks passed, covering sqlite-vec, Ollama embeddings, Ollama structured intent and Qdrant
- Four original practice rows posted through the browser and independently exported from Tally
- Payment, Receipt and Contra dates, amounts and accounting signs matched the CSV
- Bank references KIWI-PRACTICE-001 through 004, bank dates, instrument type and native Reconciled status matched
- Kiwi Test Bank remains ₹9,600 debit and Cash ₹500 debit
- Missing acceptance bank and supplier ledgers were created under Bank Accounts and Sundry Creditors
- Reuploading the same CSV and reposting already-posted rows were blocked by Kiwi
- Exported masters and voucher payloads were accepted by the real Tally importer over HTTP
- A bill-wise supplier accepted the unchanged Kiwi payment XML as On Account
- A complete November export reconciled with Litchi by voucher count and every ledger total before the interruption probe
- Repeated imports updated existing Litchi vouchers without double counting
- An actual Tally amendment updated the existing Litchi voucher to ₹1.50 and cancelled objects disappeared from its active books
- The final controlled interruption probe produced exactly one ₹0.75 payment in Tally despite a client timeout, which was reconciled before recording the Kiwi row as posted
- Latest sync imported 10 active vouchers and excluded 3 cancelled objects
- Real practice-book embeddings, audit and a manual batch completed

## Actual importer bug fixed

TallyPrime 7.2 exports XML-invalid control references such as `&#4;` and a numeric `CMPINFO/VOUCHER` summary that is not a voucher object

Litchi now uses the existing narrow connector cleanup and ignores only the summary field while continuing to reject malformed accounting objects and DTD/entity declarations

Four meaningful regression cases were added, including UTF-8, UTF-16, missing identities and entity rejection

## Tally acceptance checklist

| Check | Result | Evidence or remaining limit |
|---|---|---|
| 1 Connection and company | Passed | Intended disposable company listed |
| 2 Masters and bank/cash classes | Passed | Native ledger/group export |
| 3 Missing ledger creation | Passed | Two new ledgers in expected groups |
| 4 Payment/Receipt/Contra | Passed | Four CSV rows versus native voucher export |
| 5 Bank allocation | Passed | References, dates and type preserved |
| 6 Bank reconciliation | Passed through native export and UI summary | Original four bank allocations report Reconciled with expected dates, and native summary shows both balances ₹9,600 |
| 7 Custom voucher types | Outside verified scope | Litchi totals explicitly support standard Payment/Receipt only, custom Kiwi mapping not exercised |
| 8 Two simultaneously open companies | Not run | Desktop Tally UI unavailable through browser tools |
| 9 Native XML import screen | Partial | Payload import passed over HTTP and prior manual master import was verified, native company selector not observed |
| 10 Repeat import/interruption | Investigated, limitation confirmed | Duplicate XML creates duplicates, a timed-out request can already be committed |
| 11 Bill-wise ledgers | Passed for On Account | Automatic invoice-reference matching is not offered |

## Retry limitation

Kiwi currently leaves a timed-out row ready, even when Tally already committed it — never blindly retry it

The test deliberately withheld one real Tally response, checked the native export, found exactly one matching payment and marked only that reconciled test row as posted

This is not an exactly-once posting guarantee

## Test construction correction

An initial test selector used `Master ID` instead of `MasterID`, creating extra disposable objects rather than altering the intended object

The selector was corrected, the final amount and narration were independently exported and checked, and the unintended payment object was cancelled

Raw requests and responses are retained in this directory and no live company was touched

## Remaining release gates

Two-company routing and the native import screen still need desktop verification

Real client statement acceptance, held-out prediction accuracy/coverage, a CA-reviewed legal corpus and representative overnight performance are not proven by these synthetic tests

The law library is still empty
