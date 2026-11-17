> Updated Linux measurements and remaining gates: [Metrics and evaluations](METRICS-AND-EVALUATIONS.md) · The original record below is preserved for provenance

# Validation record

Verified 30 October 2026 on the development Mac: **202 passed, zero failures, errors or skips**, in 17.91 seconds. See [machine-readable results](validation-results.json) and [pytest JUnit report](pytest-results.xml).

The five original test files are byte-for-byte unchanged from the supplied Bahi archive. Their original **109 tests** all pass inside the combined run. There are **93 additional tests** covering Litchi, file adapters, combined login/client workflows, shared rules and ledgers, backups, balance safeguards and calibration gates. Test counts include parametrized cases; they are not 202 independent business capabilities.

Per-file counts: AdapterTests: 8, test_calibration: 8, MoneyTests: 10, ParserTests: 10, WorkflowTests: 29, LawTests: 6, WebTests: 8, test_integration_litchi: 14, test_parse: 19, test_service: 14, test_tally: 10, test_text: 53, test_web_and_server: 13.

The separate original statement lab passed **11/11 synthetic statements**, including real Tesseract OCR of its scan and photograph. See [HTML report](statement-lab.html). Balance/amount correctness does not imply exact OCR narration: the scan had 24/47 exact narrations and the photo 16/24. Human narration review remains necessary.

The Tally integration tests use a real local HTTP simulator, not TallyPrime. The original Windows packaging test checks a mocked layout, not a Windows installation. Litchi model/Qdrant unit tests use deterministic fixtures or mocked adapters; sqlite-vec's installed native extension is exercised. Those checks do not certify model accuracy or real Qdrant compatibility. A first rerun was blocked by the sandbox's network restriction; the final run above had local networking enabled and passed every case.

Browser checks: shared sign-in, original 47-row demo, review screen/balance summary, Litchi navigation, deterministic zero-voucher SQL result and empty-library abstention. Desktop and narrow layouts were inspected. JavaScript syntax and shell syntax checks passed. A Python wheel built successfully. No services or models were installed on the Mac.

Not yet verified: Linux Mint installation/runtime, live Ollama and Qdrant round trips, real bank statements, real TallyPrime, held-out ML quality, legal answer quality, full-system RAM and overnight timing on the i3. Run [acceptance checks](ACCEPTANCE.md) before claiming these targets passed. No fabricated passing results are supplied for them.

To repeat on Linux:

```bash
bash scripts/test.sh
kiwi lab --report statement-lab.html
python scripts/check-live-stack.py
```

The installer runs the software tests before creating the demo. Live-stack checks deliberately fail when a required service is absent; they do not skip or simulate success.
