"""Cross-check of the recording writer with the offline loader (architecture-m3.md 17.8, check 4).

The C++ test ``WfdbRecordingWriterCrossCheck.WritesRecords`` writes the records ``xc_test`` and
``xc_replay`` into the folder named by ``SINUS_DESKTOP_WFDB_DIR``, each with ``<name>.source``:
a line ``fs_millihertz=<n>``, then the binary32 source values, one per line, as 8 hexadecimal
digits of their bits. Without the variable the test is skipped (the C++ tests have not written
the records).
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np
import pytest
import wfdb

from sinus_dsp.data.records import load_record

VARIABLE = "SINUS_DESKTOP_WFDB_DIR"

_IDENTITY = (
    "desktop_version=0.3.0.dev0",
    "desktop_source_sha256=" + "ab" * 32,
    "library_version=0.3.0.dev0",
    "library_source_sha256=" + "cd" * 32,
)

#: The comment lines that the C++ test gives each record (architecture-m3.md 17.6).
COMMENTS = {
    "xc_test": [
        "sinus_recording=1",
        "start_utc=2026-10-12T08:00:00.000Z",
        "source=test",
        "source_name=127.0.0.1:45000",
        "mains_hz=60",
        *_IDENTITY,
        "event=gap at_sample=4 missing_samples=36",
        "event=interruption at_sample=9 missing_samples=0 duration_ms=2500",
    ],
    "xc_replay": [
        "sinus_recording=1",
        "start_utc=2026-10-12T08:00:01.500Z",
        "source=replayed",
        "source_name=f212_even",
        "mains_hz=50",
        *_IDENTITY,
    ],
}


def _folder() -> Path:
    value = os.environ.get(VARIABLE)
    if not value:
        pytest.skip(f"{VARIABLE} is not set: the C++ tests did not write recordings to check")
    return Path(value)


def _source(path: Path) -> tuple[int, np.ndarray]:
    lines = path.read_text(encoding="ascii").split("\n")
    assert lines[-1] == ""
    key, fs_millihertz = lines[0].split("=")
    assert key == "fs_millihertz"
    values = [struct.unpack(">f", bytes.fromhex(line))[0] for line in lines[1:-1]]
    return int(fs_millihertz), np.array(values, dtype=np.float32)


def test_cpp_recordings_load_in_offline_loader(fixture_dir: Path) -> None:
    folder = _folder()
    for name, comments in COMMENTS.items():
        fs_millihertz, source = _source(folder / f"{name}.source")
        record = load_record(folder / name, annotator=None)
        assert record.fs_hz == fs_millihertz / 1000.0, name
        assert len(record.signal_mv) == len(source), name
        header = wfdb.rdheader(str(folder / name))
        gain = float(header.adc_gain[0])
        bound = 0.5 / gain * (1.0 + 1e-9)
        difference = np.abs(record.signal_mv - source.astype(np.float64))
        assert float(np.max(difference)) <= bound, name
        assert list(header.comments) == comments, name
    replay = load_record(folder / "xc_replay", annotator=None).signal_mv
    original = load_record(fixture_dir / "f212_even", annotator=None).signal_mv
    assert np.array_equal(replay, original)
    test_values = _source(folder / "xc_test.source")[1]
    assert float(np.max(test_values)) == pytest.approx(32.767)
    assert float(np.min(test_values)) == pytest.approx(-32.767)
