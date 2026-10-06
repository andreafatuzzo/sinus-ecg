# sinus-dsp: Python reference and validation pipeline

`dsp/` holds the reference implementation of the Sinus signal processing in Python (package `sinus_dsp`) and the pipeline that validates it on the MIT-BIH databases. The portable C++ library is checked against the golden vectors that this package exports. The design is in [`docs/regulatory/architecture.md`](../docs/regulatory/architecture.md), the requirements in [`docs/regulatory/srs.md`](../docs/regulatory/srs.md), and the results in [`docs/validation/`](../docs/validation/).

> Sinus is **not a medical device**. The results are a technical evaluation, not a clinical validation.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.11 (pinned in `.python-version`) and every dependency at the version locked in `uv.lock`.
- For the validation: about 170 MB of disk space for the two databases, and a network connection for their first download.

## Set up

All commands run from `dsp/`.

```sh
uv sync --locked
```

This creates `.venv/` with the package, its runtime dependencies and the development tools.

## Test and check

```sh
uv run pytest                     # all tests
uv run pytest tests/unit          # one folder: tests/unit, tests/requirements or tests/system
uv run pytest tests/unit/test_package.py::test_package_imports   # one test
uv run ruff check .               # lint
uv run ruff format --check .      # formatting
uv run mypy                       # strict type check of sinus_dsp
uv run python scripts/traceability.py --check   # traceability checks, as in CI
```

- `tests/unit/` holds the implementer's unit tests; `tests/requirements/` and `tests/system/` hold the tests that verify the requirements, written by someone else ([`CONTRIBUTING.md`](../CONTRIBUTING.md)).
- Tests marked `needs_data` need the complete MIT-BIH Arrhythmia Database in `data/mitdb/` at the repository root, and tests marked `needs_nstdb` need the MIT-BIH Noise Stress Test Database in `data/nstdb/`. Without them these tests are skipped, as in CI. Download the databases (below) to run them.
- After changing a requirement, requirement-tagged code or a tagged test, regenerate the traceability matrix with `uv run python scripts/traceability.py` and commit [`docs/regulatory/traceability.md`](../docs/regulatory/traceability.md).

## Run

The scripts keep the data in `data/` at the repository root (ignored by git, not in `dsp/`) and write the reports to `docs/validation/`. Each one prints its options with `--help`.

```sh
uv run python scripts/download_data.py              # download and verify both databases into data/
uv run python scripts/validate.py --offline         # full report: docs/validation/qrs-ec57-report.md
uv run python scripts/subset_check.py --offline     # regenerate the subset report and compare it with the stored one
uv run python scripts/export_golden.py              # golden vectors for the C++ library, into data/golden/
uv run python scripts/software_check.py             # the reports state the software that runs this check
```

- **Data.** `download_data.py` downloads the MIT-BIH Arrhythmia Database 1.0.0 and the MIT-BIH Noise Stress Test Database 1.0.0 from PhysioNet and verifies every file against the SHA-256 checksum list of each database, whose own digest is pinned in the code. A file that fails the check is never used. `--database mitdb` or `--database nstdb` downloads one database, `--records` only some records. The databases are never committed; their licence and citations are in [`docs/validation/README.md`](../docs/validation/README.md).
- **Full report.** `validate.py` verifies the data, runs the QRS detection and the EC57 beat-by-beat evaluation on the 48 records, and the noise stress test, then writes the report. Without `--offline` it first downloads any file that is missing. The run takes under a minute on a recent computer.
- **Subset report.** `subset_check.py` needs only records 100, 105, 108, 119, 203 and 207 of the MIT-BIH Arrhythmia Database, and downloads them when they are missing (without `--offline`). CI runs it on every push and fails if the regenerated report differs in any byte from [`docs/validation/qrs-ec57-subset-report.md`](../docs/validation/qrs-ec57-subset-report.md). The report states the software that produced it, so any change under `sinus_dsp/`, to the package version or to a locked runtime version changes it: update it in the same change with `--update` ([`CONTRIBUTING.md`](../CONTRIBUTING.md)).
- **Golden vectors.** `export_golden.py` writes one file for each synthetic input and, when the verified files of the six subset records are present, for the first 60 s of each of them; otherwise it skips the record segments and says why. It never downloads. The files are not stored in the repository.
- **Software check.** `software_check.py` runs on pull requests into `main`: every generated report must state the package version, source digest and runtime versions of the software being released.

## Layout

| Path | Contents |
|---|---|
| `sinus_dsp/filters.py`, `qrs.py`, `pipeline.py` | Baseline wander and mains interference filters, Pan–Tompkins QRS detection, the processing chain |
| `sinus_dsp/input_checks.py`, `errors.py` | Input validation and error types |
| `sinus_dsp/data/` | Download and verification of the databases, loading of records |
| `sinus_dsp/evaluation/` | EC57 matching, statistics, noise stress test, reports, the validation and subset runs |
| `sinus_dsp/synthetic.py`, `golden.py` | Synthetic inputs and the golden-vector format, writer, readers and export |
| `sinus_dsp/version.py` | Software identity: package version and source digest |
| `scripts/` | The command-line scripts above, and the traceability generator |
| `tests/unit/`, `tests/requirements/`, `tests/system/` | Unit, requirement and system tests |
| `osv-scanner.toml` | Triage records of the vulnerability scan in CI ([`docs/regulatory/cybersecurity.md`](../docs/regulatory/cybersecurity.md) §7) |
