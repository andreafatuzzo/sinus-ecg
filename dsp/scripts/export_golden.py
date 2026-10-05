"""Write the golden vectors of the reference (architecture §7.5, §8.12).

SRS-015: this single command writes one golden-vector file for each input of the set: the 18
synthetic ECGs, and the first 60 s of records 100, 105, 108, 119, 203 and 207 of the MIT-BIH
Arrhythmia Database where the files of these records are available in the data folder and
verified against the pinned checksum list. It never downloads: obtain the records first with
scripts/download_data.py or the subset check. If they are missing or not verified, the record
segments are skipped with the reason, and the synthetic files are still written. The files go
to data/golden/, which git ignores; they are regenerated on demand and are not stored.

This script only parses the arguments, prints the messages and sets the exit status; the
export is in ``sinus_dsp.golden``.

Usage (from ``dsp/``):
  uv run python scripts/export_golden.py
  uv run python scripts/export_golden.py --output DIR --data-dir PATH

Exit status: 0 when the export completes, whether the record segments were written or
skipped; 1 if an input is rejected, a file is malformed or an output is not finite (message
on standard error; the files written before stay); 2 on a usage error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sinus_dsp.errors import InvalidInputError, MalformedFileError, NonFiniteOutputError
from sinus_dsp.golden import export_golden_vectors

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "golden"

EXIT_COMPLETED = 0
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write one golden-vector file for each synthetic input and for the first "
        "60 s of each record of the subset, where its verified files are available."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="DIR",
        help="folder of the files (default: data/golden/ at the repository root)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="PATH",
        help="data folder, with one subfolder per database (default: data/ at the repository root)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command and return its exit status (SRS-015)."""
    args = build_parser().parse_args(argv)
    output: Path = args.output
    try:
        summary = export_golden_vectors(output, data_root=args.data_dir)
    except (InvalidInputError, MalformedFileError, NonFiniteOutputError) as error:
        print(f"export failed: {error}", file=sys.stderr)
        return EXIT_FAILED
    for name in summary.written:
        print(f"written: {output / name}")
    if summary.skipped:
        print(f"skipped: {', '.join(summary.skipped)}")
        print(f"reason: {summary.skip_reason}")
    return EXIT_COMPLETED


if __name__ == "__main__":
    sys.exit(main())
