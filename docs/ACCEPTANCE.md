> Updated Linux measurements and remaining gates: [Metrics and evaluations](METRICS-AND-EVALUATIONS.md) · The original record below is preserved for provenance

# Acceptance gates and remaining evidence

The software implementation and automated regression suite are included. Targets from the build plan that depend on real hardware, client history, verified legal text or a CA's judgments have not been measured here. They are release gates, not current claims.

| Area | Implemented | Evidence still needed |
|---|---|---|
| Kiwi parsing | Original multi-format parser, OCR, balance repair/proof, duplicates, learning, review, XML, Excel | Your actual bank layouts; unsupported layouts must stop for correction |
| Kiwi posting | Original Tally XML workflows, simulator, missing ledgers, bank dates | All 11 real-Tally checks in TALLY-TEST.md |
| Linux stack | Mint installer, Waitress, sqlite-vec, Ollama adapter, Qdrant adapter | Run installer/tests and check-live-stack.py on the laptop |
| Ledger ML | Historical cosine neighbours, similarity/recency voting, top three, separate calibration/test months | A real labelled history, honest baseline comparison and model speed benchmark |
| Audit | Duplicate candidates, round sums, weekends/holidays, related parties, configurable cash/TDS signals, centroid anomalies | CA-reviewed rule configuration and planted-error evaluation |
| Law | Dated section chunks, BM25 plus Qdrant, citations, exact quote extraction | Reviewed legal corpus and frozen 50-question CA evaluation |
| Book questions | English/Hinglish parser, optional local-model intent, fixed SQL and voucher evidence | Frozen 100-question evaluation, including actual model intents |
| Overnight work | User timers, bounded batch, reports and backup/restore | Finish by 06:00 with total machine RAM below 7 GB on the i3 |
| Firm pilot | Local workflow and demo | A firm actually using it, with permission and verified results |

## Ledger prediction

Use at least three months of labelled historical postings, then a separate calibration month and later untouched test month. A year of data gives a more useful evaluation. Never use a random row split. Embedding inputs exclude the target ledger. Neighbour queries exclude entries on/after the query date. Compare each embedding candidate on the same frozen periods.

```bash
source .venv/bin/activate
litchi embed kiwi-1
litchi evaluate kiwi-1 --month 2026-09 --output evaluation-september.json
litchi calibrate kiwi-1 --calibration-month 2026-08 --test-month 2026-09 --output calibration.json
```

Replace periods/client with the actual data. The evaluator reconstructs Kiwi correction memory from earlier labelled postings and uses its real mapper/rules/fuzzy implementation. It cannot recreate historical ledger-master/config changes that were not recorded; freeze those inputs and record their provenance. Future-created firm rules are excluded from the baseline. This is an evaluation against a reconstructed baseline, not a claim to have replayed an unavailable historical configuration.

Thresholds are selected from a fixed grid using only calibration results. The independent test must achieve ≥97% empirical ready accuracy, ≥70% coverage, at least 30 selected rows and better top-one accuracy than the Kiwi baseline. Otherwise the gate stays disabled. Passing permits a *ready recommendation* for later dates with the same model digest; it never posts or approves automatically. Report sample sizes and uncertainty; 30 examples do not statistically guarantee a future 97% accuracy rate.

Run `embed`/`evaluate --model <candidate>` separately for each locally installed embedding model, keeping the reports. Measure elapsed time per 1,000 new entries on the actual i3; the plan's under-two-minute target is unverified. Only nomic is configured by default; alternatives are not claimed benchmarked.

## Audit rules

Client `config.json` contains `holidays`, `related_parties`, `cash_review_limit_paise`, `cash_rule_source`, and `tds_review_rules`. Tax checks are explicitly reported skipped until supplied with reviewed, applicable rules. No default statutory thresholds are asserted. Inspect the configuration fields used in `kiwi_litchi/intelligence.py` before setting them; use the applicable current source and ask the CA to approve scope/exceptions.

Plant errors in a copy of books, never the original. Freeze changed voucher/line IDs and labels before evaluating. Report precision@20 and recall@20 separately. **The plan's target of finding 60% of 50 errors in 20 flags is mathematically impossible**: recall@20 cannot exceed 40%. Choose recall@50 or a precision@20 target with the reviewer before running the evaluation. This package does not silently change that requirement or claim it passed.

## Law and book evaluations

For 50 law questions record expected act/section, applicability date, source version, and whether the answer is present in the library. Save full top-five results for BM25-only and hybrid retrieval. Count the fraction with a correct section in the top five; target ≥90%. Have the CA independently label cited answer correctness and appropriate abstention; target ≥80% correct and zero confidently wrong. Exact quotation validation alone cannot establish that result. No such dataset or verdicts were supplied.

For 100 English/Hinglish book questions record expected intent and a separately reconciled Tally/SQL amount in paise. Include ambiguous ledger names, mixed directions, period boundaries, cancelled vouchers and unanswerable requests. Evaluate both deterministic and actual local-model intent paths. Target ≥90% exact intents and 100% arithmetic correctness for returned answers. Do not relabel failures or drop unanswered questions from the intent denominator.

## Hardware and deployment

Run `python scripts/check-live-stack.py`, the full pytest suite, the statement lab, and an overnight representative batch on Linux. Record CPU/storage, package/model versions, corpus size, time, system RAM and swap, Ollama memory and Docker memory. System-wide RAM must include the desktop and other services; Python's reported peak alone is insufficient. Verify a backup restored to a fresh data directory and reconcile its totals. Real-Tally failure details and legal-data gaps remain outstanding until those checks supply evidence.
