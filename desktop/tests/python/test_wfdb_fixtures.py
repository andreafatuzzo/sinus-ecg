"""Cross-checks of the WFDB fixtures with the Python reference (architecture-m3.md 17.8).

1. The committed fixtures are those that the fixture script writes with the locked ``wfdb``.
2. The ``.expected`` files hold the values of the offline loader.
3. The pinned checksum lists of the desktop application are those of ``sinus_dsp``.
"""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from types import ModuleType

import numpy as np
import wfdb

from sinus_dsp.data.physionet import MITDB, NSTDB
from sinus_dsp.data.records import load_record

REFERENCE_SOURCE = Path(__file__).resolve().parents[2] / "src" / "core" / "reference_databases.cpp"

#: The readable fixture records, each with a ``.expected`` file.
READABLE = (
    "f16_one",
    "f16_two",
    "f212_even",
    "f212_odd",
    "f212_odd3",
    "fs_frac",
    "gain_zero",
    "no_units",
    "replay16",
    "replay212",
    "session_gap",
)


def _files(folder: Path) -> set[str]:
    return {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}


def _expected(path: Path) -> tuple[dict[str, str], list[tuple[int, str, str]]]:
    lines = path.read_bytes().decode("ascii").split("\n")
    assert lines[-1] == "", f"{path.name} does not end with a line feed"
    fields = dict(line.split("=", 1) for line in lines[:5])
    assert list(fields) == ["record", "fs_millihertz", "sample_count", "sha256_binary32", "rows"]
    rows: list[tuple[int, str, str]] = []
    for line in lines[5:-1]:
        adu, bits64, bits32 = line.split(" ")
        rows.append((int(adu), bits64, bits32))
    assert len(rows) == int(fields["rows"])
    return fields, rows


def test_fixture_files_are_reproduced(
    tmp_path: Path, fixture_script: ModuleType, fixture_dir: Path
) -> None:
    written = fixture_script.write_fixtures(tmp_path)
    names = {path.relative_to(tmp_path).as_posix() for path in written}
    assert names == _files(tmp_path)
    assert names == _files(fixture_dir)
    for name in sorted(names):
        assert (tmp_path / name).read_bytes() == (fixture_dir / name).read_bytes(), name


def test_expected_values_are_those_of_the_offline_loader(fixture_dir: Path) -> None:
    assert sorted(path.stem for path in fixture_dir.glob("*.expected")) == sorted(READABLE)
    for name in READABLE:
        fields, rows = _expected(fixture_dir / f"{name}.expected")
        assert fields["record"] == name
        record = load_record(fixture_dir / name, annotator=None)
        values = record.signal_mv
        assert record.fs_hz == int(fields["fs_millihertz"]) / 1000.0, name
        assert len(values) == int(fields["sample_count"]), name
        digest = hashlib.sha256(values.astype("<f4").tobytes()).hexdigest()
        assert digest == fields["sha256_binary32"], name
        digital = wfdb.rdrecord(str(fixture_dir / name), channels=[0], physical=False)
        adu = np.asarray(digital.d_signal)[:, 0]
        for index, (row_adu, bits64, bits32) in enumerate(rows):
            assert int(adu[index]) == row_adu, (name, index)
            assert struct.pack(">d", float(values[index])).hex() == bits64, (name, index)
            assert struct.pack(">f", float(np.float32(values[index]))).hex() == bits32, (
                name,
                index,
            )


def test_reference_digests_equal_those_of_dsp() -> None:
    source = REFERENCE_SOURCE.read_text(encoding="utf-8")
    entries = re.findall(
        r'\{\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*"([0-9a-f]{64})",\s*MainsFrequency::k60Hz\s*\}',
        source,
    )
    assert entries == [
        (database.slug, database.version, database.title, database.checksum_list_sha256)
        for database in (MITDB, NSTDB)
    ]
