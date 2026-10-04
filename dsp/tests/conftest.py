"""Markers for the tests that need the local reference databases (architecture §8.11).

- ``needs_data``: the complete MIT-BIH Arrhythmia Database in ``data/mitdb``: its ``RECORDS``
  file, and the ``.hea``, ``.dat`` and ``.atr`` files of every record it lists. The six
  records that the subset check keeps in ``data/mitdb`` (without ``RECORDS``) do not
  satisfy it.
- ``needs_nstdb``: the MIT-BIH Noise Stress Test Database in ``data/nstdb``: the ``.hea``,
  ``.dat`` and ``.atr`` files of each of its 12 noise stress records.

A marked test is skipped when its database is not complete, e.g. in CI. The files are only
looked for here; the tests verify the data they use.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from sinus_dsp.errors import MalformedFileError
from sinus_dsp.evaluation.noise_stress import NOISE_STRESS_RECORDS
from sinus_dsp.evaluation.run import read_record_list

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

#: The files of a record that the evaluation reads.
RECORD_FILE_SUFFIXES = (".hea", ".dat", ".atr")


def first_missing_record_file(database_dir: Path, records: Sequence[str]) -> Path | None:
    """The first ``.hea``, ``.dat`` or ``.atr`` file of the records that is not a file."""
    for record in records:
        for suffix in RECORD_FILE_SUFFIXES:
            path = database_dir / f"{record}{suffix}"
            if not path.is_file():
                return path
    return None


def mitdb_unavailable(data_dir: Path) -> str | None:
    """Why the complete MIT-BIH Arrhythmia Database is not in ``data_dir``, or ``None``."""
    folder = data_dir / "mitdb"
    try:
        records = read_record_list(folder)
    except (OSError, MalformedFileError) as error:
        return f"MIT-BIH Arrhythmia Database not complete: no usable record list: {error}"
    missing = first_missing_record_file(folder, records)
    if missing is not None:
        return f"MIT-BIH Arrhythmia Database not complete: {missing} not found"
    return None


def nstdb_unavailable(data_dir: Path) -> str | None:
    """Why the 12 noise stress records are not in ``data_dir``, or ``None``."""
    missing = first_missing_record_file(data_dir / "nstdb", NOISE_STRESS_RECORDS)
    if missing is not None:
        return f"MIT-BIH Noise Stress Test Database not complete: {missing} not found"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    reasons = {
        "needs_data": mitdb_unavailable(DATA_DIR),
        "needs_nstdb": nstdb_unavailable(DATA_DIR),
    }
    for item in items:
        for marker, reason in reasons.items():
            if reason is not None and item.get_closest_marker(marker):
                item.add_marker(pytest.mark.skip(reason=reason))
