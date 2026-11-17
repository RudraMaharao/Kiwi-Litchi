# Verified environment

Captured on 17 November 2026 — observations from this Linux laptop, not minimum hardware requirements or a macOS support claim

| Component | Observed value |
|---|---|
| CPU | Intel(R) Core(TM) i3-6006U CPU @ 2.00GHz |
| Logical CPUs visible | 4 |
| RAM reported | 7.645 GiB |
| Swap reported | 2.000 GiB |
| Python | 3.12.3 |
| Platform | Linux-7.0.0-38-generic-x86_64-with-glibc2.39 |
| OCR | tesseract 5.3.4 |
| Ollama | 0.40.13 |
| Qdrant | 1.20.0 |
| TallyPrime | 7.2 Educational |
| Tally Wine runtime | 11.0, isolated prefix |

The available-memory value in [environment.json](verification/environment.json) is a snapshot, not an overnight maximum

## Python package versions

| Package | Version |
|---|---|
| kiwi-litchi | 0.1.0 |
| pytest | 9.2.0 |
| flask | 3.1.3 |
| waitress | 3.0.2 |
| pdfplumber | 0.11.10 |
| pypdfium2 | 5.14.0 |
| openpyxl | 3.1.5 |
| xlrd | 2.0.2 |
| rapidfuzz | 3.14.6 |
| sqlite-vec | 0.1.9 |
| numpy | 2.5.4 |
| Pillow | 12.3.0 |
| pypdf | 6.21.4 |
| reportlab | 4.5.1 |

Dependency ranges remain in pyproject.toml — these versions are observations, not proof that every future dependency combination works

## Resource limits

Model requests use CPU-only inference with two threads, one parallel request and one loaded model

Generated app/batch services use MemoryMax=2G and Nice=10 — separate Qdrant has a 512 MiB cap

These individual limits do not establish a whole-machine 7 GB memory guarantee

## Tally compatibility work

The official TallyPrime 7.2 installer used for this practice run had SHA-256 `55e2668a5f625bd216c5139cdd3aeb5095cf5793f3326bbb1c02e3d69be96627`

Wine 9 showed startup failures — local ODBC libraries resolved one loader issue, and the working launcher was changed to an isolated Wine 11.0 runtime and prefix

This is an observed compatibility setup, not vendor-certified Linux support — no Tally binaries, Wine prefixes, licence state or company data are included
