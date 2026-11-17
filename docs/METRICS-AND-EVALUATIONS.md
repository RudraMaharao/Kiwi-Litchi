# Metrics and evaluation record

Numbers below distinguish software regression results, small synthetic runtime checks and unmeasured release gates

## Measured results

| Metric | Result | Scope |
|---|---|---|
| Latest regression run | 214 passed, 0 failed, 0 errors, 0 skipped | Linux Mint, 17 November 2026 |
| Latest wall-clock test time | 59.01 seconds | JUnit suite time 58.974 seconds |
| Packaged source regression | 214 passed, zero skips/failures/errors in 70.62 seconds | Independent run from the handoff folder |
| Preserved original Bahi tests | 109 | Five original test files remain unchanged |
| Added local guard cases | 8 intent cases and 4 native-export cases | Remaining cases came with the supplied combined source |
| Statement lab | 11/11 synthetic layouts passed | Linux run on 30 October 2026 |
| Scan OCR narration exactness | 24/47 = 51.06% | Amount/balance pass does not establish narration exactness |
| Photo OCR narration exactness | 16/24 = 66.67% | One photographed sample |
| Actual live-stack checks | 5/5 passed | Linux, sqlite-vec, Ollama embeddings, structured intent, Qdrant |
| Raw-model intent smoke | 2/3 exact matches | Two English cases correct, one Hinglish direction wrong, N=3 |
| Original Tally practice rows | 4/4 posted and reconciled | Receipt, Payment, Contra, date/amount/sign checks |
| Original practice bank balance | ₹9,600 debit | Separate acceptance bank protects this simple example |
| Original practice cash balance | ₹500 debit | Cash withdrawal Contra |
| Latest practice-book sync | 10 active vouchers, 3 cancelled objects excluded | Disposable company only |
| Expense query evidence | ₹102.25 across 3 Payment vouchers | ₹100 original + ₹1.50 amended probe + ₹0.75 timeout probe |
| Backup restore | 4 databases, 45 tables matched | Fresh destination, live data not overwritten |
| Earlier synthetic Mehta query | ₹17,500 over 7 vouchers | Separate demo client with 39 vouchers |
| Earlier small workflow time | 27.688 seconds | Cached/small synthetic run, not overnight throughput |
| Earlier sampled whole-machine used RAM | Peak 4,080.1 MiB | Total minus MemAvailable, periodic samples, not a continuous peak profiler |
| Earlier sampled swap used | Peak 1,144.0 MiB | Same small run |
| Earlier Python peak | 48.6 MiB | Python process only, excludes Ollama/Docker |
| Manual batch without new embeddings | 0.183 seconds, 3 clients, 0 errors | Small synthetic audit/report pass |
| Practice embeddings | 9 newly embedded eligible historical lines | CPU, real Nomic model |
| Audit output | 1 informational review flag, 1 possible misposting, 2 skipped rule families | Outputs, not validated true positives |

[Machine-readable summary](verification/metrics.json) · [JUnit](verification/pytest-linux.xml) · [Statement report](verification/statement-lab-linux.html) · [Live-stack report](verification/live-stack-results.json) · [Backup proof](verification/backup-restore-verification.json)

The actual application model-assisted English receipt query returned ₹200.00 with one voucher — this single UI check is separate from the three-prompt raw-model smoke test

The native Tally dashboard shows bank accounts ₹10,580.75, Cash ₹500, net flow ₹11,080.75 and synthetic net profit ₹97.75, consistent with the recorded test entries

## Raw-model smoke cases

| Question | Expected measure | Returned measure | Result |
|---|---|---|---|
| Payments to Kiwi Test Expense in FY 2026-27 | payments | payments | Exact intent matched |
| Receipts from Kiwi Test Income in FY 2026-27 | receipts | receipts | Exact intent matched |
| Kiwi Test Capital se FY 2026-27 kitna aaya? | receipts | payments | Failed direction |

All three returned the expected ledger and date range, but one wrong measure makes the whole intent incorrect

The benchmark used a small fixed ledger list and the app's request options — it did not invoke the application consistency guard, change weights or tune against the three results

[Raw responses and token timings](verification/model-smoke-benchmark.json)

## Gates with no honest passing score yet

| Evaluation | Required design / target | Current status |
|---|---|---|
| Ledger prediction | Chronological history, separate calibration month and untouched later test month | No independent real labelled corpus supplied |
| Ready recommendations | At least 30 selected test rows, ≥97% empirical ready accuracy, ≥70% coverage, and beat Kiwi baseline | Not demonstrated, no automatic approval |
| Embedding speed | Actual i3, representative 1,000 new entries | Tiny 8-text benchmark only, do not extrapolate as a passed target |
| Book intent quality | Frozen 100 English/Hinglish questions, ≥90% exact intents | Not run, N=3 smoke is not a substitute |
| Book arithmetic | Independently reconciled expected paise for every returned answer | Synthetic examples checked, broad 100-question corpus not supplied |
| Law retrieval | Frozen 50-question CA-labelled corpus, ≥90% correct section in top 5 | Verified law library empty |
| Law answer quality | ≥80% independently judged correctness and zero confidently wrong answers | Not evaluated |
| Audit quality | Frozen planted errors and reviewer labels, report precision@k and recall@k | No labelled planted-error corpus |
| Overnight acceptance | Representative work completes by 06:00 with total machine RAM below 7 GB | Not measured |
| Native Tally isolation | Two companies simultaneously open | Not run |
| Native file import UI | Company selection and import-screen workflow | HTTP payload import passed, desktop selection still partial |

Finding 60% of 50 planted errors in 20 one-error flags is impossible — recall@20 has a ceiling of 40%, so choose a feasible reviewer-agreed target rather than fabricating a pass

## Metric definitions and denominators

- Exact intent accuracy = fully correct ledger, measure, start and end / all frozen questions, including unanswered questions
- Ledger top-1 accuracy = correct first ledger / all test rows
- Ready accuracy = correct ready recommendations / selected ready rows
- Ready coverage = selected ready rows / all test rows
- Recall@k = distinct labelled errors found in the first k flags / all planted errors
- Precision@k = relevant flags among the first k / k inspected flags
- Generation tokens/second = eval_count / (eval_duration / 1e9), excluding prompt evaluation and model loading
- Wall time includes HTTP and application overhead, so it is not interchangeable with generation time
- Model digest, split dates, dataset size and exclusions belong beside every score

## Test character and limits

The 214 regression cases include parametrized cases and mocks — they are not 214 independent production capabilities or 214 real-model evaluations

The live-stack and disposable-Tally runs are separate evidence using actual local services

The controlled timeout test intentionally records a failed HTTP posting response even though Tally committed the payment — the matching voucher was checked before the local row was marked posted and no blind retry was attempted

Repeated unidentified voucher XML can create duplicates — exactly-once posting is not guaranteed

[Tally checklist with individual status](TALLY-ACCEPTANCE-RESULTS.md) · [Full acceptance design](ACCEPTANCE.md)
