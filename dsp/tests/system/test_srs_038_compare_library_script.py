"""System verification of SRS-038 for dsp (scripts): the command ``compare_library.py``.

The command is run on the real local databases with the shared library of the computer build
(``SINUS_DSP_HARNESS``, or the release build). The test requires exit status 0, the table of 60
records (the 48 of the MIT-BIH Arrhythmia Database and the 12 noise stress records, names written
out from the database documentation) with equal counts, the identities of both sides and the
summary line. The independent recount per record is in
``libs/sinus-dsp/tests/system/test_srs_038_detection_on_databases.py``.

Skipped without the databases or the shared library, as in CI. The ``needs_harness`` hook is in
``libs/sinus-dsp/tests/conftest.py``: run pytest from ``dsp/`` with its default ``testpaths``.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import pytest

DSP_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = DSP_ROOT.parent / "data"

MITDB_RECORDS = (
    "100", "101", "102", "103", "104", "105", "106", "107", "108", "109",
    "111", "112", "113", "114", "115", "116", "117", "118", "119",
    "121", "122", "123", "124",
    "200", "201", "202", "203", "205", "207", "208", "209", "210",
    "212", "213", "214", "215", "217", "219",
    "220", "221", "222", "223", "228", "230", "231", "232", "233", "234",
)  # fmt: skip


def harness_path() -> Path:
    """``SINUS_DSP_HARNESS``, else the shared library of the release build."""
    if os.environ.get("SINUS_DSP_HARNESS"):
        return Path(os.environ["SINUS_DSP_HARNESS"])
    suffix = {"win32": ".dll", "darwin": ".dylib"}.get(sys.platform, ".so")
    name = "sinus_dsp_harness" if suffix == ".dll" else "libsinus_dsp_harness"
    return DSP_ROOT.parent / "libs/sinus-dsp/build/release/harness" / f"{name}{suffix}"


NSTDB_RECORDS = tuple(
    f"{base}e{snr}" for base in ("118", "119") for snr in ("24", "18", "12", "06", "00", "_6")
)


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.needs_harness
@pytest.mark.requirement("SRS-038")
def test_compare_library_script_reports_equal_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = runpy.run_path(str(DSP_ROOT / "scripts" / "compare_library.py"))
    status = script["main"](["--harness", str(harness_path()), "--data-dir", str(DATA_ROOT)])
    out = capsys.readouterr().out
    assert status == 0, out[-2000:]
    rows = [line.split("|")[1:-1] for line in out.splitlines() if line.startswith("| ")]
    rows = [[cell.strip() for cell in row] for row in rows[1:]]  # without the header
    assert [row[0] for row in rows] == list(MITDB_RECORDS + NSTDB_RECORDS)
    assert all(row[7] == "yes" for row in rows)
    assert all(row[1:7] == row[1:4] + row[4:7] and row[1:4] == row[4:7] for row in rows)
    assert "60 records, 60 equal" in out
    assert "Reference (dsp): " in out and "Library (libs/sinus-dsp): " in out
