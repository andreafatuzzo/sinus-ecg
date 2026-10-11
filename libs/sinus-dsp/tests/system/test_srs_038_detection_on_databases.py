"""System verification of SRS-038 for libs/sinus-dsp: detection by the library on the databases.

For each of the 48 MIT-BIH Arrhythmia records and the 12 noise stress records, with the channel
and mains setting of SRS-007 (first stored signal, 60 Hz), the record is loaded and scored here,
record by record, with the documented evaluation (``evaluate_record``, SRS-008 and SRS-011) once
with the reference ``detect_beats`` and once with the library through the shared library
``sinus_dsp_harness``. The counts must be equal, and so are the detections themselves. This does
not use ``compare_library.py`` or ``compare_detection``; the record names are written out from the
database documentation.

Needs the complete local databases and the shared library of the computer build
(``SINUS_DSP_HARNESS``); skipped otherwise, as in CI. The result is recorded in the verification
report of the milestone.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sinus_dsp.data.records import load_record
from sinus_dsp.evaluation.harness import LibraryHarness, load_harness
from sinus_dsp.evaluation.run import EvaluationSettings, evaluate_record
from sinus_dsp.pipeline import detect_beats

DATA_ROOT = Path(__file__).resolve().parents[4] / "data"
LIBRARY_ROOT = Path(__file__).resolve().parents[2]

SRS_007 = EvaluationSettings(channel=0, mains_hz=60)

MITDB_RECORDS = (
    "100", "101", "102", "103", "104", "105", "106", "107", "108", "109",
    "111", "112", "113", "114", "115", "116", "117", "118", "119",
    "121", "122", "123", "124",
    "200", "201", "202", "203", "205", "207", "208", "209", "210",
    "212", "213", "214", "215", "217", "219",
    "220", "221", "222", "223", "228", "230", "231", "232", "233", "234",
)  # fmt: skip
NSTDB_RECORDS = tuple(
    f"{base}e{snr}" for base in ("118", "119") for snr in ("24", "18", "12", "06", "00", "_6")
)

CASES = [("mitdb", name) for name in MITDB_RECORDS] + [("nstdb", name) for name in NSTDB_RECORDS]

pytestmark = [pytest.mark.needs_data, pytest.mark.needs_nstdb, pytest.mark.needs_harness]


@pytest.fixture(scope="module")
def harness(harness_library: Path) -> LibraryHarness:
    return load_harness(harness_library)


def test_record_lists() -> None:
    assert len(MITDB_RECORDS) == 48 and len(set(MITDB_RECORDS)) == 48
    assert len(NSTDB_RECORDS) == 12 and len(set(NSTDB_RECORDS)) == 12


@pytest.mark.requirement("SRS-038")
def test_library_identity_is_that_of_the_version_file(harness: LibraryHarness) -> None:
    version = (LIBRARY_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    name, digest = harness.identity().split(";")
    assert name == version
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


@pytest.mark.requirement("SRS-038")
@pytest.mark.parametrize(("database", "name"), CASES, ids=[f"{d}-{n}" for d, n in CASES])
def test_counts_equal_to_the_reference(harness: LibraryHarness, database: str, name: str) -> None:
    record = load_record(DATA_ROOT / database / name, SRS_007.channel)
    seen: list[np.ndarray] = []

    def library(signal, fs_hz, mains_hz):  # type: ignore[no-untyped-def]
        out = harness.detect(signal, fs_hz, mains_hz)
        seen.append(np.asarray(out))
        return out

    expected = evaluate_record(record, SRS_007, detect_beats)
    actual = evaluate_record(record, SRS_007, library)
    assert len(seen) == 1
    e, a = expected.counts, actual.counts
    assert (a.tp, a.fn, a.fp) == (e.tp, e.fn, e.fp), (
        f"record {name}: library TP/FN/FP {a.tp}/{a.fn}/{a.fp}, reference {e.tp}/{e.fn}/{e.fp}"
    )
    reference_indices = np.asarray(detect_beats(record.signal_mv, record.fs_hz, SRS_007.mains_hz))
    assert np.array_equal(seen[0], reference_indices)
