"""Download and verify the reference databases (architecture §8.3).

SRS-001: the MIT-BIH Arrhythmia Database 1.0.0. SRS-013: the MIT-BIH Noise Stress Test
Database 1.0.0. Each database is obtained from PhysioNet into the data folder and every file
named in its published SHA-256 checksum list is verified. A database with a missing or
altered file is reported as not verified, with an error naming each such file.

This script only parses the arguments, prints the messages and sets the exit status; the
download and the verification are in ``sinus_dsp.data.physionet``.

Usage (from ``dsp/``):
  uv run python scripts/download_data.py                        # both databases, every file
  uv run python scripts/download_data.py --database mitdb       # one database
  uv run python scripts/download_data.py --database mitdb --records 100 105
  uv run python scripts/download_data.py --data-dir PATH        # another data folder

Running it again resumes an interrupted download: files already verified are not fetched.

Exit status: 0 if every requested database is verified; 1 if one is not verified or its
checksum list is malformed (message on standard error); 2 on a usage error.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from sinus_dsp.data.physionet import (
    MITDB,
    NSTDB,
    Database,
    FetchFunction,
    describe_verification,
    download_database,
    fetch_https,
)
from sinus_dsp.errors import DataVerificationError, MalformedFileError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"

DATABASES: dict[str, Database] = {MITDB.slug: MITDB, NSTDB.slug: NSTDB}
ALL_DATABASES = "all"

EXIT_VERIFIED = 0
EXIT_NOT_VERIFIED = 1

_RECORD_NAME = re.compile(r"[A-Za-z0-9_]+")


def _record_name(value: str) -> str:
    """Argument type of ``--records``: an invalid record name is a usage error."""
    if _RECORD_NAME.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(f"invalid record name: {value!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download the reference databases from PhysioNet and verify every file "
        "against the published SHA-256 checksum list."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="PATH",
        help="data folder; each database goes in a subfolder (default: data/ at the "
        "repository root)",
    )
    parser.add_argument(
        "--database",
        choices=[*DATABASES, ALL_DATABASES],
        default=ALL_DATABASES,
        help="database to download (default: all)",
    )
    parser.add_argument(
        "--records",
        nargs="+",
        type=_record_name,
        metavar="NAME",
        help="download and verify only the files of these records (default: every file); "
        "needs --database mitdb or --database nstdb",
    )
    return parser


def _announcing(fetch: FetchFunction) -> FetchFunction:
    """Wrap a fetch function so that each URL is printed before it is fetched."""

    def fetch_and_announce(url: str) -> bytes:
        print(f"fetching {url}", flush=True)
        return fetch(url)

    return fetch_and_announce


def main(argv: Sequence[str] | None = None, *, fetch: FetchFunction = fetch_https) -> int:
    """Run the command and return its exit status (SRS-001, SRS-013)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.records is not None and args.database == ALL_DATABASES:
        parser.error("--records needs --database mitdb or --database nstdb")
    databases = (
        list(DATABASES.values()) if args.database == ALL_DATABASES else [DATABASES[args.database]]
    )

    status = EXIT_VERIFIED
    for database in databases:
        name = f"{database.title} {database.version}"
        try:
            result = download_database(
                database, args.data_dir, records=args.records, fetch=_announcing(fetch)
            )
        except (DataVerificationError, MalformedFileError) as error:
            print(f"{name}: {error}", file=sys.stderr)
            status = EXIT_NOT_VERIFIED
        else:
            print(f"{name}: {describe_verification(result)}")
    return status


if __name__ == "__main__":
    sys.exit(main())
