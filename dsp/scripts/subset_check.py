"""Regenerate the subset report and compare it with the stored one (architecture §8.11).

SRS-016: this command obtains records 100, 105, 108, 119, 203 and 207 of the MIT-BIH
Arrhythmia Database into the data folder (a cached copy is used when it verifies), verifies
each of their files against the pinned checksum list, runs the QRS detection and the EC57
evaluation on them, and compares the regenerated subset report with the one stored in
docs/validation/qrs-ec57-subset-report.md. It runs in continuous integration on every push.

This script only parses the arguments, prints the messages and sets the exit status; the
run, the report and the comparison are in ``sinus_dsp.evaluation``.

Usage (from ``dsp/``):
  uv run python scripts/subset_check.py                 # download what is missing, then check
  uv run python scripts/subset_check.py --offline       # verify the local data only, no network
  uv run python scripts/subset_check.py --update        # replace the stored report
  uv run python scripts/subset_check.py --write-regenerated PATH   # also keep the regenerated one

Exit status: 0 when the regenerated report equals the stored one, or when ``--update`` has
written it; 1 if they differ (the differences on standard error), if the records are not
verified or if a file is malformed (nothing written); 2 on a usage error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sinus_dsp._files import write_atomically
from sinus_dsp.data.physionet import FetchFunction, fetch_https
from sinus_dsp.errors import DataVerificationError, MalformedFileError, SubsetReportMismatchError
from sinus_dsp.evaluation.subset import check_subset_report

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_STORED = REPO_ROOT / "docs" / "validation" / "qrs-ec57-subset-report.md"

EXIT_EQUAL = 0
EXIT_FAILED = 1

UPDATE_HINT = (
    "If the change is intended, update the stored report with "
    "'uv run python scripts/subset_check.py --update' (from dsp/) and review the rows that "
    "changed; if continuous integration still finds a difference, replace it with the "
    "subset-report artifact of that run (CONTRIBUTING.md)."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regenerate the subset report on six records of the MIT-BIH Arrhythmia "
        "Database and compare it with the stored one."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="PATH",
        help="data folder, with one subfolder per database (default: data/ at the repository root)",
    )
    parser.add_argument(
        "--stored",
        type=Path,
        default=DEFAULT_STORED,
        metavar="PATH",
        help="stored subset report "
        "(default: docs/validation/qrs-ec57-subset-report.md at the repository root)",
    )
    parser.add_argument(
        "--write-regenerated",
        type=Path,
        default=None,
        metavar="PATH",
        help="also write the regenerated report to PATH",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="replace the stored report with the regenerated one, after the verification",
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
    """Run the command and return its exit status (SRS-016)."""
    args = build_parser().parse_args(argv)
    stored: Path = args.stored
    regenerated: Path | None = args.write_regenerated
    try:
        # With --update, the regenerated report is written over the stored one, so the
        # comparison that follows passes.
        check_subset_report(
            stored,
            args.data_dir,
            regenerated_path=stored if args.update else regenerated,
            fetch=None if args.offline else _announcing(fetch),
        )
    except (DataVerificationError, MalformedFileError) as error:
        prefix = "no report written" if args.update else "subset check failed"
        print(f"{prefix}: {error}", file=sys.stderr)
        return EXIT_FAILED
    except SubsetReportMismatchError as error:
        if regenerated is not None:
            print(f"regenerated report written: {regenerated}")
        print(f"subset report differs from the stored report {stored}:", file=sys.stderr)
        for difference in error.differences:
            print(f"  {difference}", file=sys.stderr)
        print(UPDATE_HINT, file=sys.stderr)
        return EXIT_FAILED
    if args.update:
        if regenerated is not None:
            # The bytes are read first and then written, so that the path of
            # --write-regenerated may name the stored report itself.
            write_atomically(regenerated, stored.read_bytes())
            print(f"regenerated report written: {regenerated}")
        print(f"stored report updated: {stored}")
    else:
        if regenerated is not None:
            print(f"regenerated report written: {regenerated}")
        print(f"subset report equals the stored report: {stored}")
    return EXIT_EQUAL


if __name__ == "__main__":
    sys.exit(main())
