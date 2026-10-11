"""Compare the detection of the real-time library with the reference (architecture-m2.md 14.14).

SRS-038: the 48 records of the MIT-BIH Arrhythmia Database and the 12 records of the MIT-BIH
Noise Stress Test Database are evaluated twice with the settings of SRS-007 (channel 0, mains
60 Hz), as specified in SRS-008 and SRS-011: once with the reference and once with the shared
library ``sinus_dsp_harness`` of ``libs/sinus-dsp``. The script prints a Markdown table with
the counts of both for each record, and the identity of both.

Usage (from ``dsp/``), with the shared library of the ``release`` build of ``libs/sinus-dsp``:
  uv run python scripts/compare_library.py --harness <path to sinus_dsp_harness.dll or .so>
  uv run python scripts/compare_library.py --harness <path> --data-dir <data folder>

Exit status: 0 when every record has the same counts for both; 1 when a record differs, when a
database is not verified or when a file is malformed; 2 on a usage error (including a harness
library that cannot be loaded).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from sinus_dsp.data.physionet import MITDB, NSTDB, Database, verify_database
from sinus_dsp.data.records import load_record
from sinus_dsp.errors import DataVerificationError, InvalidInputError, MalformedFileError
from sinus_dsp.evaluation.harness import (
    DetectionComparison,
    LibraryHarness,
    compare_detection,
    load_harness,
)
from sinus_dsp.evaluation.noise_stress import NOISE_STRESS_RECORDS
from sinus_dsp.evaluation.run import (
    DEFAULT_SETTINGS,
    RecordLoader,
    read_record_list,
)
from sinus_dsp.version import software_identity

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"

EXIT_EQUAL = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare the detection of the real-time library with the reference on "
        "the MIT-BIH Arrhythmia Database and the Noise Stress Test Database."
    )
    parser.add_argument(
        "--harness",
        type=Path,
        required=True,
        metavar="PATH",
        help="the shared library sinus_dsp_harness of the release build of libs/sinus-dsp",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="PATH",
        help="data folder, with one subfolder per database (default: data/ at the repository root)",
    )
    return parser


def render_table(rows: Sequence[DetectionComparison]) -> str:
    """Return the Markdown table of the comparisons: the counts of both, and whether equal."""
    lines = [
        "| Record | Reference TP | FN | FP | Library TP | FN | FP | Equal |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        r, c = row.reference, row.candidate
        lines.append(
            f"| {row.record} | {r.tp} | {r.fn} | {r.fp} | {c.tp} | {c.fn} | {c.fp} "
            f"| {'yes' if row.equal else 'NO'} |"
        )
    return "\n".join(lines)


def _compare_database(
    database: Database,
    records: Sequence[str],
    data_dir: Path,
    harness: LibraryHarness,
    loader: RecordLoader,
) -> tuple[DetectionComparison, ...]:
    return compare_detection(
        data_dir / database.slug,
        records,
        DEFAULT_SETTINGS,
        harness.detect,
        loader=loader,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    harness_loader: Callable[[Path], LibraryHarness] = load_harness,
    loader: RecordLoader = load_record,
    mitdb: Database = MITDB,
    nstdb: Database = NSTDB,
    noise_records: Sequence[str] = NOISE_STRESS_RECORDS,
) -> int:
    """Run the command and return its exit status (SRS-038)."""
    args = build_parser().parse_args(argv)
    data_dir: Path = args.data_dir
    try:
        harness = harness_loader(args.harness)
    except InvalidInputError as error:
        print(f"usage error: {error}", file=sys.stderr)
        return EXIT_USAGE
    started = time.perf_counter()
    try:
        verify_database(mitdb, data_dir)
        verify_database(nstdb, data_dir)
        rows = _compare_database(
            mitdb, read_record_list(data_dir / mitdb.slug), data_dir, harness, loader
        ) + _compare_database(nstdb, noise_records, data_dir, harness, loader)
    except (DataVerificationError, MalformedFileError, InvalidInputError) as error:
        print(f"comparison failed: {error}", file=sys.stderr)
        return EXIT_FAILED
    elapsed = time.perf_counter() - started
    reference = software_identity()
    print(f"Reference (dsp): {reference.version};{reference.source_sha256}")
    print(f"Library (libs/sinus-dsp): {harness.identity()}")
    print()
    print(render_table(rows))
    print()
    different = [row.record for row in rows if not row.equal]
    print(f"{len(rows)} records, {len(rows) - len(different)} equal, {elapsed:.1f} s")
    if different:
        print(f"records with different counts: {', '.join(different)}", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_EQUAL


if __name__ == "__main__":
    sys.exit(main())
