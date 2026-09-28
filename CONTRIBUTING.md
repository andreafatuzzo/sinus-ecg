# Contributing to Sinus

Thanks for your interest. Sinus follows a lightweight version of medical-device software practice (IEC 62304, ISO 14971), so contributions follow a few extra rules on top of the usual ones. The full process is in [`docs/regulatory/sdp.md`](docs/regulatory/sdp.md).

> Sinus is **not a medical device**. Contributions must not add diagnostic claims or alarm features, and must never suggest connecting a worn device to USB or mains power.

## Workflow

1. Branch from `develop` as `feature/<short-name>`.
2. Open a pull request into `develop`. `main` only receives pull requests from `develop` at the end of a milestone.
3. CI must pass: ruff, mypy, pytest and the traceability check.

## Development setup (Python, `dsp/`)

```sh
cd dsp
uv sync
uv run pytest && uv run mypy && uv run ruff check . && uv run ruff format --check .
```

## Rules for changes that affect behavior

- **Requirements first.** Behavior is specified in [`docs/regulatory/srs.md`](docs/regulatory/srs.md) as `SRS-xxx`. Add or change the requirement in the same pull request as the code. IDs are never reused.
- **Traceability.** Code cites the `SRS-xxx` it implements. Tests that verify a requirement use `@pytest.mark.requirement("SRS-xxx")` and must check the requirement's pass criterion.
- **Independent verification.** Whoever implements a requirement does not write the tests that verify it. Implementers write unit tests in `dsp/tests/unit/` (no requirement markers). Requirement tests go in `dsp/tests/requirements/` and system tests in `dsp/tests/system/`, written by someone else. CI rejects requirement markers anywhere else. Regenerate the matrix with `uv run python scripts/traceability.py`.
- **Risk.** Check the change against [`docs/regulatory/risk-analysis.md`](docs/regulatory/risk-analysis.md) and update it when needed.
- **Dependencies.** Add them with `uv add`, and list every new runtime dependency in [`docs/regulatory/soup.md`](docs/regulatory/soup.md).
- **Open points.** Anything you defer or leave undecided goes in [`docs/regulatory/open-points.md`](docs/regulatory/open-points.md) as a new `OP-xxx` row, tagged with the `SRS`/`HAZ`/`RC` IDs it concerns.
- **Data.** Never commit datasets. Validation reports in `docs/validation/` are generated, never hand-edited.
- **Validation.** QRS detection is scored with EC57 beat-by-beat matching. Beat classification must use an inter-patient split.

## Reporting problems

Open a GitHub Issue. For defects, label it `bug`, describe how to reproduce it, and name the affected requirement if you know it.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
