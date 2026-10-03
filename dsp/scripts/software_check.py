"""Check that every validation report states the running software (architecture §8.14).

A report states the software that produced it in two rows of its section "Software, data
and settings": ``Software`` (package version and source digest) and ``Runtime`` (versions
of Python and of the runtime SOUP). This check compares those rows, in every ``*.md`` file
of the folder of the validation reports, with the identity of the software that runs the
check. Run on a pull request into ``main``, it makes sure that a release carries only
reports produced by the released code. It needs no data and runs no evaluation. A file with
neither row (e.g. the README of the folder) is not a report and is not checked.

This script only parses the arguments, prints the messages and sets the exit status; the
identity is in ``sinus_dsp.version`` and the comparison in ``sinus_dsp.evaluation.report``.

Usage (from ``dsp/``):
  uv run python scripts/software_check.py                # docs/validation/ at the repo root
  uv run python scripts/software_check.py --folder PATH

Exit status: 0 if every report states the running software; 1 otherwise, with one line per
problem on standard error; 2 on a usage error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sinus_dsp.evaluation.report import software_rows, stale_software_rows
from sinus_dsp.version import software_identity

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FOLDER = REPO_ROOT / "docs" / "validation"
REPORT_PATTERN = "*.md"

EXIT_CURRENT = 0
EXIT_STALE = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check that every validation report states the running software: "
        "package version, source digest, and the versions of Python and of the runtime SOUP."
    )
    parser.add_argument(
        "--folder",
        type=Path,
        default=DEFAULT_FOLDER,
        metavar="PATH",
        help="folder of the reports (default: docs/validation/ at the repository root)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return its exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    folder: Path = args.folder
    if not folder.is_dir():
        parser.error(f"not a folder: {folder}")
    software = software_identity()
    software_line = software_rows(software)[0]
    problems: list[str] = []
    reports = 0
    for path in sorted(folder.glob(REPORT_PATTERN), key=lambda path: path.name):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        problems.extend(f"{path}: {entry}" for entry in stale_software_rows(text, software))
        # Without a problem, every Software row of a report is the current one.
        if any(line.removesuffix("\r") == software_line for line in text.split("\n")):
            reports += 1
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return EXIT_STALE
    print(
        f"software check: {reports} reports state sinus-dsp {software.version}, "
        f"source SHA-256 {software.source_sha256}"
    )
    return EXIT_CURRENT


if __name__ == "__main__":
    sys.exit(main())
