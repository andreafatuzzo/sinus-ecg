"""The C++ reader on the reference databases (architecture-m3.md 17.8, check 5).

The test tool ``sinus_desktop_wfdb_dump <record_path>`` (built with the C++ tests) prints
``fs_millihertz=``, ``sample_count=``, ``sha256_binary64=`` and ``sha256_binary32=`` of signal 0,
or ``error=<status>`` with exit status 1. ``SINUS_DESKTOP_WFDB_DUMP`` names it; without it, or
without the local databases, the test is skipped.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from sinus_dsp.data.records import load_record
from sinus_dsp.evaluation.run import read_record_list

VARIABLE = "SINUS_DESKTOP_WFDB_DUMP"
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
#: The records of each database: 48 and 15 (12 noise stress records and 3 noise records).
RECORD_COUNTS = {"mitdb": 48, "nstdb": 15}


def _dump(tool: str, record_path: Path) -> dict[str, str]:
    completed = subprocess.run(
        [tool, str(record_path)], capture_output=True, text=True, check=False, timeout=120
    )
    assert completed.returncode == 0, (record_path.name, completed.stdout, completed.stderr)
    return dict(line.split("=", 1) for line in completed.stdout.splitlines())


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
def test_cpp_reader_equals_wfdb_on_reference_records() -> None:
    tool = os.environ.get(VARIABLE)
    if not tool:
        pytest.skip(f"{VARIABLE} is not set: no C++ reader to compare")
    for database, count in RECORD_COUNTS.items():
        folder = DATA_DIR / database
        records = read_record_list(folder)
        assert len(records) == count
        for name in records:
            dump = _dump(tool, folder / name)
            record = load_record(folder / name, annotator=None)
            values = record.signal_mv
            assert int(dump["fs_millihertz"]) / 1000.0 == record.fs_hz, name
            assert int(dump["sample_count"]) == len(values), name
            binary64 = hashlib.sha256(values.astype("<f8").tobytes()).hexdigest()
            binary32 = hashlib.sha256(values.astype("<f4").tobytes()).hexdigest()
            assert dump["sha256_binary64"] == binary64, name
            assert dump["sha256_binary32"] == binary32, name
