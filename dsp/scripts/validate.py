"""Generate the full validation report of the QRS detection (architecture §8.10).

SRS-009: this single command runs the QRS detection and the EC57 evaluation on every record
of the MIT-BIH Arrhythmia Database, and on the 12 records of the MIT-BIH Noise Stress Test
Database (SRS-014), and writes the report to docs/validation/qrs-ec57-report.md. Two runs on
the same data and software version write byte-identical reports. SRS-012, SRS-014: both
databases are verified first; if a verification fails, no report is written.

This script only parses the arguments, prints the messages and sets the exit status; the
run and the report are in ``sinus_dsp.evaluation``.

Usage (from ``dsp/``):
  uv run python scripts/validate.py                  # download what is missing, then run
  uv run python scripts/validate.py --offline        # verify the local data only, no network
  uv run python scripts/validate.py --data-dir PATH --output PATH

Exit status: 0 when the report is written; 1 if a database is not verified or a data file
is malformed (message on standard error, no report written); 2 on a usage error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sinus_dsp.data.physionet import FetchFunction, fetch_https
from sinus_dsp.errors import DataVerificationError, MalformedFileError
from sinus_dsp.evaluation.run import write_validation_report

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "validation" / "qrs-ec57-report.md"

EXIT_WRITTEN = 0
EXIT_NOT_VERIFIED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the QRS detection and the EC57 evaluation on the reference databases "
        "and write the validation report."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="PATH",
        help="data folder, with one subfolder per database (default: data/ at the repository root)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help="report to write (default: docs/validation/qrs-ec57-report.md at the repository root)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="verify the local data only, without downloading anything",
    )
    return parser


def _announcing(fetch: FetchFunction) -> FetchFunction:
    """Wrap a fetch function so that each URL is printed before it is fetched."""

    def fetch_and_announce(url: str) -> bytes:
        print(f"fetching {url}", flush=True)
        return fetch(url)

    return fetch_and_announce


def main(argv: Sequence[str] | None = None, *, fetch: FetchFunction = fetch_https) -> int:
    """Run the command and return its exit status (SRS-009)."""
    args = build_parser().parse_args(argv)
    try:
        write_validation_report(
            args.output,
            args.data_dir,
            fetch=None if args.offline else _announcing(fetch),
        )
    except (DataVerificationError, MalformedFileError) as error:
        print(f"no report written: {error}", file=sys.stderr)
        return EXIT_NOT_VERIFIED
    print(f"report written: {args.output}")
    return EXIT_WRITTEN


if __name__ == "__main__":
    sys.exit(main())
