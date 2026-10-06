# Contributing to Sinus

Thanks for your interest. Sinus follows a lightweight version of medical-device software practice (IEC 62304, ISO 14971), so contributions follow a few extra rules on top of the usual ones. The full process is in [`docs/regulatory/sdp.md`](docs/regulatory/sdp.md).

> Sinus is **not a medical device**. Contributions must not add diagnostic claims or alarm features, and must never suggest connecting a worn device to USB or mains power.

## Workflow

1. Branch from `develop` as `feature/<short-name>`.
2. Open a pull request into `develop`. `main` only receives pull requests from `develop` at the end of a milestone.
3. CI must pass: ruff, mypy, pytest, the traceability checks, the subset report check and the vulnerability scan of the SBOM (below). On pull requests into `main`, the release gate also requires a verifying test for every requirement of a milestone that is in progress or released ([`milestones.md`](docs/regulatory/milestones.md)).

## Development setup (Python, `dsp/`)

```sh
cd dsp
uv sync
uv run pytest && uv run mypy && uv run ruff check . && uv run ruff format --check .
```

## Rules for changes that affect behavior

- **Requirements first.** Behavior is specified in [`docs/regulatory/srs.md`](docs/regulatory/srs.md) as `SRS-xxx`. Add or change the requirement in the same pull request as the code. IDs are never reused.
- **Traceability.** Code cites the `SRS-xxx` it implements. Tests that verify a requirement must check its pass criterion and are tagged:
  - Python: `@pytest.mark.requirement("SRS-xxx")` on the test function or class;
  - C++ (GoogleTest): one or more `// Verifies: SRS-xxx, SRS-yyy` lines directly above the `TEST`, `TEST_F`, `TEST_P`, `TYPED_TEST` or `TYPED_TEST_P` line, with no line in between. `Verifies:` is reserved for this use.

  CI fails when a requirement cited in production code has no verifying test. Regenerate the matrix with `uv run python scripts/traceability.py` (from `dsp/`). Rules: [ADR 0004](docs/adr/0004-test-tagging-and-traceability-gates.md).
- **Independent verification.** Whoever implements a requirement does not write the tests that verify it. Each component (`dsp/`, `libs/<library>/`, `desktop/`, `firmware/`) has three test folders:
  - `tests/unit/`: the implementer's unit tests, with no requirement tags;
  - `tests/requirements/`: tests of requirements with Verification level `Requirement`, written by someone else;
  - `tests/system/`: tests of requirements with Verification level `System`, written by someone else.

  CI rejects requirement tags anywhere else, and in the folder of the other level.
- **Risk.** Check the change against [`docs/regulatory/risk-analysis.md`](docs/regulatory/risk-analysis.md) and update it when needed.
- **Dependencies.** Add them with `uv add`, and list every new runtime dependency in [`docs/regulatory/soup.md`](docs/regulatory/soup.md).
- **Open points.** Anything you defer or leave undecided goes in [`docs/regulatory/open-points.md`](docs/regulatory/open-points.md) as a new `OP-xxx` row, tagged with the `SRS`/`HAZ`/`RC` IDs it concerns.
- **Data.** Never commit datasets. Validation reports in `docs/validation/` are generated, never hand-edited.
- **Stored subset report.** On every push, CI regenerates the subset report on records 100, 105, 108, 119, 203 and 207 of the MIT-BIH Arrhythmia Database and fails if it differs in any byte from [`docs/validation/qrs-ec57-subset-report.md`](docs/validation/qrs-ec57-subset-report.md). The report states the software that produced it, so it changes with any change to a file under `dsp/sinus_dsp/` (even a comment), to the package version, or to the Python minor version or a runtime dependency version in `dsp/uv.lock`, as well as with any change of the detection results. Update it in the same pull request:

  ```sh
  cd dsp
  uv run python scripts/subset_check.py --update   # downloads the six records into data/mitdb/ if needed (about 12 MB)
  ```

  and check in the diff which rows changed: only `Software` and `Runtime`, or the counts too. CI is the authority ([`architecture.md`](docs/regulatory/architecture.md) §8.11): if CI still reports a difference after the update, replace the stored report with the `subset-report` artifact of that CI run, so that the pull request shows the change for review.
- **Validation.** QRS detection is scored with EC57 beat-by-beat matching. Beat classification must use an inter-patient split.

## Security

- **Reporting.** Report a vulnerability privately, as described in [`SECURITY.md`](SECURITY.md), never in a public issue.
- **Vulnerability scan.** On every push, CI scans the SBOM of the Python reference with OSV-Scanner and fails on a known vulnerability that has not been triaged. A finding is triaged as described in [`cybersecurity.md`](docs/regulatory/cybersecurity.md) §7.3: a GitHub issue labelled `security`, and an entry in [`dsp/osv-scanner.toml`](dsp/osv-scanner.toml) with the ID, a reason and an expiry date. Never add an entry only to make CI pass.

## Reporting problems

Open a GitHub Issue. For defects, label it `bug`, describe how to reproduce it, and name the affected requirement if you know it.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
