# Local changes and tuning history

## Supplied baseline

The supplied Linux bundle combines Bahi 1.0.0 bookkeeping with Litchi modules, shared authentication, client bridge, vector retrieval, model adapters, law retrieval and 202 tests

The original 109 Bahi cases remain part of the suite — no local test was removed or weakened to obtain a passing result

## 30 October 2026 — Linux setup and model-intent guard

- Installed the package, OCR tools and actual local AI stack on Linux Mint
- Configured Ollama 0.40.13 with two local models, CPU requests, one loaded model and one parallel request
- Fixed unsupported ledger or reversed date/model drift handling in `model_intent`
- Added schema enums, explicit financial-year context, field/date checks and deterministic consistency rejection
- Added eight focused regression cases, taking the suite from 202 to 210
- Fixed systemd WorkingDirectory generation by using the raw path with systemd percent escaping instead of shell quoting
- Validated generated units, actual live-stack checks, synthetic statements and fresh backup restore

## 16–17 November 2026 — TallyPrime and native export compatibility

- Installed the official TallyPrime 7.2 installer into a separate Wine environment
- Wine 9 startup was unstable, so selected a side-by-side Wine 11.0 runtime and isolated prefix rather than replacing the distro runtime
- Made the normal launcher select that tested runtime and bundled the required local ODBC libraries
- Verified the Educational Mode practice company and localhost XML server
- Posted the original four practice rows and checked native exports, missing masters, bank allocations and reconciliation dates
- Diagnosed Tally XML-invalid control references and the numeric CMPINFO/VOUCHER summary in real exports
- Reused the existing narrow control cleanup and skipped only that summary count in Litchi imports
- Added four native-export regression cases, taking the suite to 214
- Investigated duplicate XML import and an actual committed request with a deliberately withheld response
- Verified amendment and cancellation sync, integer-paise totals and independent backup restore

## Interface changes

- Replaced the shared white/green appearance with beige surfaces, burnt-orange Kiwi and lychee blush/raspberry Litchi
- Added fruit-shaped CSS brand symbols and a clear visual boundary between apps
- Increased body text from 14 px to 17 px, controls to 16–17 px and secondary text generally to 14–15 px
- Removed diagonal navigation arrows and sentence-ending full stops from interface copy
- Finished display-only formatting of generated flash/help text in the repo source
- Retained decimal values, filenames, raw transaction records and exact source quotations

## Repository handoff

- Added this measured metric record, model specifications, prompt/runtime notes, workflow diagrams and staged screenshots
- Included the unsuccessful raw-model smoke case rather than changing the test or hiding it
- Omitted runtime databases, credentials, downloaded weights, installers, Wine prefixes and machine-specific configuration
- Preserved supplied source provenance and the Atkinson font licence without inventing a licence for the supplied application code

## No neural fine-tuning

No local weights, optimizer, training schedule, LoRA adapter or quantization were changed — prompts, validation code, runtime configuration and stored correction memory are the local tuning work
