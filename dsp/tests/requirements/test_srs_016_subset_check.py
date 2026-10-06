"""Requirement tests of SRS-016: the subset check of the continuous integration (RC-004).

SRS-016 (v0.7.2): on every push, the build obtains records 100, 105, 108, 119, 203 and 207
of version 1.0.0 of the MIT-BIH Arrhythmia Database (a cached copy is allowed), verifies each
of their files against the checksum list of SRS-001, runs QRS detection with the settings of
SRS-007 and the evaluation of SRS-008 and SRS-011 on them, and regenerates a subset report.
The build fails, and no subset report is written, if the verification fails; it also fails
if the regenerated report differs from the one stored in the repository.

This module tests the check: `check_subset_report` and `compare_reports` of
`sinus_dsp.evaluation.subset`, and the command `scripts/subset_check.py` that the build runs
(architecture, section 8.11). The content of the subset report is tested in
`test_srs_016_subset_report_content.py`, the stored report in
`test_srs_016_stored_subset_report.py`, the build configuration in
`test_srs_016_ci_configuration.py`.

Inputs (`conftest.py`): fixture databases whose records are named as the subset, written at
360 Hz with their checksum list, the `Database` under test pinned to the digest of that list,
`fetch=None` or a fetch function that serves the fixture bytes without network. With the
detector double (the samples above 0.5 mV) every count is known; the command, which uses the
real detector, runs on noise-free synthetic ECGs.

The cases of the verification of SRS-016 and their tests:
- the stored subset report equals the regenerated one: the check passes
  (`test_check_passes_when_the_stored_report_equals_the_regenerated_one` and the command);
- one value of the stored report differs: the check fails and names the difference
  (`test_one_differing_value_fails_and_is_named`, for counts, percentages, rankings, the
  figures not scored, the settings, the database, the verification, the statements, and the
  rows `Software` and `Runtime`: a stored report that differs only in the row `Software`
  fails like any other, architecture section 8.11), and through the command;
- a record file fails verification: the check fails and no report is written
  (`test_failed_verification_stops_the_check_before_any_report_is_written` and the command).

The difference entries are how the check names a difference, so they are compared with the
formats documented in architecture section 8.11 (v0.2.10, and v0.2.11 for an empty stored
report, which has no line): `line <n>: stored <text>, regenerated <text>` with `(empty line)`
and `(no line)`, lines compared by position, the entries for line endings, `no stored
report: <path>`, and the limit of 20 entries followed by `… and <k> more`
(`_documented_differences` works them out from the documented rules). The messages and exit
statuses of the command are compared only where the requirement needs them: the build fails
(a status other than 0) and the difference is named.

The subset report contains the items of SRS-012 (v0.7.2), the licence of the database among
them (row `Database licence`): a stored report whose licence row differs, or that has none,
fails like any other (`test_one_differing_value_fails_and_is_named`,
`test_stored_report_without_the_licence_row_fails`).

Changes of v0.2.10 re-checked here: the shared helper that writes files (no behaviour
change), and `--update` with `--write-regenerated` naming the stored report itself.
"""

from __future__ import annotations

import inspect
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sinus_dsp.data.physionet import MITDB, Database, fetch_https, select_files
from sinus_dsp.data.records import load_record
from sinus_dsp.errors import DataVerificationError, MalformedFileError, SubsetReportMismatchError
from sinus_dsp.evaluation.run import DEFAULT_SETTINGS, EvaluationSettings
from sinus_dsp.evaluation.subset import (
    SUBSET_RECORDS,
    check_subset_report,
    compare_reports,
    run_subset,
)
from sinus_dsp.pipeline import detect_beats

pytestmark = pytest.mark.usefixtures("forbid_network")

MITDB_TITLE = "MIT-BIH Arrhythmia Database"
MITDB_PIN = "b61158a96d5f2ca80edfb354a9a66a6324836c390a84e1966dcee2b907d6be43"
FILES_URL = "https://physionet.org/files/mitdb/1.0.0/"
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
SUBSET_CHECK_SCRIPT = SCRIPTS_DIR / "subset_check.py"
STORED_NAME = "qrs-ec57-subset-report.md"
SPIKE_RECORD_SAMPLES = 151200  # 7 min at 360 Hz


def _database(fixture: Any) -> Database:
    """The `Database` of a fixture: MIT-BIH Arrhythmia 1.0.0 pinned to the fixture list,
    with the fixture licence (`FIXTURE_LICENCES` of `conftest.py`)."""
    return Database(
        slug="mitdb",
        version="1.0.0",
        title=MITDB_TITLE,
        checksum_list_sha256=fixture.checksum_list_sha256,
        licence=fixture.licence,
    )


def _entry(n: int, stored: str, regenerated: str) -> str:
    """The documented difference entry for line ``n`` (architecture, section 8.11)."""
    return f"line {n}: stored {stored}, regenerated {regenerated}"


def _regenerate(
    fixture: Any,
    folder: Path,
    detector: Callable[..., Any] | None = None,
    *,
    database: Database | None = None,
) -> bytes:
    """The subset report that the check regenerates from ``fixture``.

    The check is run against a stored report that does not exist, which is one difference;
    the regenerated report is written to ``folder / regenerated.md`` and returned. The
    `Database` is that of the fixture (``_database``) unless another one is given.
    """
    options: dict[str, Any] = {} if detector is None else {"detector": detector}
    with pytest.raises(SubsetReportMismatchError) as excinfo:
        check_subset_report(
            folder / "absent.md",
            fixture.data_root,
            regenerated_path=folder / "regenerated.md",
            database=_database(fixture) if database is None else database,
            fetch=None,
            **options,
        )
    assert len(excinfo.value.differences) == 1
    return (folder / "regenerated.md").read_bytes()


@pytest.fixture(scope="module")
def reference(
    subset_fixture: Any,
    make_spike_detector: Callable[[], Any],
    network_forbidden: Callable[[], Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> bytes:
    """The subset report regenerated from the spike subset fixture, with the detector double."""
    folder = tmp_path_factory.mktemp("srs016-reference")
    with network_forbidden():
        return _regenerate(subset_fixture, folder, make_spike_detector())


@pytest.fixture(scope="module")
def ecg_reference(
    subset_ecg_fixture: Any,
    network_forbidden: Callable[[], Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> bytes:
    """The subset report regenerated from the synthetic ECG subset fixture as the command
    regenerates it: with the default detector, and with the database description of the
    software (`MITDB`) whose pinned digest is replaced by that of the fixture list, as the
    command driver does. Its row `Database licence` is therefore that of version 1.0.0 of the
    MIT-BIH Arrhythmia Database (Open Data Commons Attribution License v1.0)."""
    folder = tmp_path_factory.mktemp("srs016-ecg-reference")
    database = replace(MITDB, checksum_list_sha256=subset_ecg_fixture.checksum_list_sha256)
    with network_forbidden():
        return _regenerate(subset_ecg_fixture, folder, database=database)


def _check(
    fixture: Any,
    stored: Path,
    detector: Callable[..., Any],
    *,
    regenerated: Path | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> None:
    check_subset_report(
        stored,
        fixture.data_root,
        regenerated_path=regenerated,
        database=_database(fixture),
        detector=detector,
        fetch=fetch,
    )


def _lines(data: bytes) -> list[str]:
    """The lines of a report: its text split at line feeds, without the final empty item."""
    lines = data.decode("utf-8").split("\n")
    assert lines[-1] == ""
    return lines[:-1]


def _lines_with_endings(data: bytes) -> list[tuple[str, str]]:
    """(text, ending) of each line of a non-empty report, as architecture section 8.11 splits
    it: at line feeds; a carriage return just before a line feed belongs to the ending
    (`CR LF`); a last line without a line feed has the ending `none (no final line feed)`; a
    report that ends with a line feed has no empty last line."""
    parts = data.decode("utf-8").split("\n")
    lines = []
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            if part:
                lines.append((part, "none (no final line feed)"))
        elif part.endswith("\r"):
            lines.append((part[:-1], "CR LF"))
        else:
            lines.append((part, "LF"))
    return lines


def _documented_differences(stored: bytes, regenerated: bytes) -> tuple[str, ...]:
    """The difference entries that architecture section 8.11 documents, worked out by the test.

    Lines are compared by position. Each position where the texts differ, or where only one
    report has a line, gives `line <n>: stored <text>, regenerated <text>`, a text shown as it
    is, `(empty line)` or `(no line)`. Only if no text differs, each position where the
    endings differ gives `line <n>: same text, line ending stored <e>, regenerated <e>`. The
    first 20 entries, then `… and <k> more`.
    """
    s, r = _lines_with_endings(stored), _lines_with_endings(regenerated)

    def shown(text: str | None) -> str:
        return "(no line)" if text is None else (text or "(empty line)")

    entries = []
    for n in range(1, max(len(s), len(r)) + 1):
        stored_text = s[n - 1][0] if n <= len(s) else None
        regenerated_text = r[n - 1][0] if n <= len(r) else None
        if stored_text != regenerated_text:
            entries.append(
                f"line {n}: stored {shown(stored_text)}, regenerated {shown(regenerated_text)}"
            )
    if not entries:
        for n, ((_, ending), (_, other)) in enumerate(zip(s, r, strict=True), start=1):
            if ending != other:
                entries.append(
                    f"line {n}: same text, line ending stored {ending}, regenerated {other}"
                )
    if len(entries) > 20:
        entries = [*entries[:20], f"… and {len(entries) - 20} more"]
    return tuple(entries)


def _flip_one_bit(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))


# --------------------------------------------------------------------------------------------
# The subset of SRS-016 and the defaults of the check
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-016")
def test_subset_is_the_six_records_of_the_requirement() -> None:
    """The records of the check are those of SRS-016.

    Input: the constant `SUBSET_RECORDS` of the subset check.
    Expected: exactly the records 100, 105, 108, 119, 203 and 207, each once.
    """
    assert tuple(SUBSET_RECORDS) == ("100", "105", "108", "119", "203", "207")


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize("function", [run_subset, check_subset_report], ids=lambda f: f.__name__)
def test_check_uses_the_reference_database_and_the_settings_of_srs_007_by_default(
    function: Callable[..., Any],
) -> None:
    """Without arguments, the check uses the data, settings and detection of the requirement.

    Input: the default arguments of `run_subset` and `check_subset_report`, which the command
    of the build uses.
    Expected: the database is version 1.0.0 of the MIT-BIH Arrhythmia Database with the
    checksum list pinned for SRS-001 (`MITDB`, digest b61158a9…be43); the settings are those
    of SRS-007, the first stored signal (channel 0) and the mains interference filter at
    60 Hz; the detector is the QRS detection of SRS-006 (`detect_beats`), the records are read
    as in SRS-002 (`load_record`), and missing files are downloaded (`fetch_https`).
    """
    parameters = inspect.signature(function).parameters

    assert parameters["database"].default is MITDB
    assert (MITDB.slug, MITDB.version, MITDB.title) == ("mitdb", "1.0.0", MITDB_TITLE)
    assert MITDB.checksum_list_sha256 == MITDB_PIN
    assert parameters["settings"].default == EvaluationSettings(channel=0, mains_hz=60)
    assert parameters["settings"].default == DEFAULT_SETTINGS
    assert parameters["detector"].default is detect_beats
    assert parameters["loader"].default is load_record
    assert parameters["fetch"].default is fetch_https


# --------------------------------------------------------------------------------------------
# Equal reports: the check passes
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-016")
def test_check_passes_when_the_stored_report_equals_the_regenerated_one(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """Verification case 1: the stored subset report equals the regenerated one.

    Input: the spike subset fixture (the six records, record 101 outside the subset, the
    checksum list pinned); a stored report equal to the report that the check regenerated
    from it earlier; a path for the regenerated report.
    Expected: the check returns without error; the regenerated report written is
    byte-identical to the stored one, which is unchanged; the detector double was called
    once for each of the six records, on a 7-min signal at 360 Hz with the 60 Hz setting.
    """
    stored = tmp_path / STORED_NAME
    stored.write_bytes(reference)
    regenerated = tmp_path / "regenerated.md"
    detector = make_spike_detector()

    _check(subset_fixture, stored, detector, regenerated=regenerated)

    assert regenerated.read_bytes() == reference
    assert stored.read_bytes() == reference
    assert detector.calls == [(SPIKE_RECORD_SAMPLES, 360.0, 60)] * 6


@pytest.mark.requirement("SRS-016")
def test_check_passes_on_a_cached_copy_of_the_six_records_only(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
    copy_subset_fixture: Callable[..., Any],
) -> None:
    """A cached copy is allowed: it holds the checksum list and the files of the six records.

    Input: a copy of the spike subset fixture in another folder (its path holds a space),
    with only the checksum list and the 28 files of the six records, as the cache of the
    build keeps them: no `RECORDS` file, no file of record 101, nothing in subfolders; the
    stored report regenerated earlier from the complete fixture.
    Expected: the copy holds 29 files; the check passes, and the report it regenerates is
    byte-identical to the stored one (it does not depend on the folder of the data or on the
    files outside the subset).
    """
    copy = copy_subset_fixture(subset_fixture, tmp_path / "cached data", only_subset=True)
    stored = tmp_path / STORED_NAME
    stored.write_bytes(reference)
    regenerated = tmp_path / "regenerated.md"

    assert len(copy.subset_files) == 28
    assert len([p for p in copy.folder.rglob("*") if p.is_file()]) == 29
    _check(copy, stored, make_spike_detector(), regenerated=regenerated)

    assert regenerated.read_bytes() == reference


@pytest.mark.requirement("SRS-016")
def test_files_outside_the_six_records_are_not_needed(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
    copy_subset_fixture: Callable[..., Any],
) -> None:
    """Only the files of the six records are verified and used.

    Input: a copy of the spike subset fixture in which listed files outside the subset are
    deleted (`RECORDS`, `ANNOTATORS`, `101.dat`, `mitdbdir/intro.htm`) or altered (`101.hea`,
    `x_mitdb/x_108.hea`, whose name contains a subset record name but which lies in a
    subfolder); the stored report regenerated earlier.
    Expected: the check passes; the detector is called for six records only.
    """
    copy = copy_subset_fixture(subset_fixture, tmp_path / "data")
    for name in ("RECORDS", "ANNOTATORS", "101.dat", "mitdbdir/intro.htm"):
        (copy.folder / name).unlink()
    for name in ("101.hea", "x_mitdb/x_108.hea"):
        _flip_one_bit(copy.folder / name)
    stored = tmp_path / STORED_NAME
    stored.write_bytes(reference)
    detector = make_spike_detector()

    _check(copy, stored, detector)

    assert len(detector.calls) == 6


# --------------------------------------------------------------------------------------------
# Any difference: the check fails and names it
# --------------------------------------------------------------------------------------------


def _replace_in_line(
    lines: list[str], select: Callable[[str], bool], old: str, new: str
) -> tuple[int, str, str]:
    """Replace ``old`` by ``new`` in the only line selected; return (line number, stored
    line, regenerated line)."""
    found = [i for i, line in enumerate(lines) if select(line)]
    assert len(found) == 1, f"{len(found)} lines selected"
    original = lines[found[0]]
    assert old in original, f"{old!r} not in {original!r}"
    changed = original.replace(old, new, 1)
    assert changed != original
    lines[found[0]] = changed
    return found[0] + 1, changed, original


def _last_digit_changed(line: str) -> tuple[str, str]:
    """(old, new) that change the last hexadecimal digit of the 64-digit digest of ``line``."""
    digest = re.search(r"[0-9a-f]{64}", line)
    assert digest is not None, line
    old = digest.group(0)
    return old, old[:-1] + ("0" if old[-1] != "0" else "1")


def _python() -> str:
    return f"Python {sys.version_info.major}.{sys.version_info.minor}"


# (id, selector of the line, text replaced, replacement or None for the last digest digit)
ONE_VALUE_CASES: list[tuple[str, Callable[[str], bool], str, str | None]] = [
    ("title", lambda s: s.startswith("# "), "regression checking", "regression tests"),
    ("statement", lambda s: s.startswith("Technical evaluation only."), "validation.", "valid."),
    ("subset-statement", lambda s: s.startswith("This report covers"), "203 and", "203 or"),
    ("software-source-identifier", lambda s: s.startswith("| Software |"), "", None),
    ("software-version", lambda s: s.startswith("| Software |"), "sinus-dsp ", "sinus-dsp 9"),
    ("runtime", lambda s: s.startswith("| Runtime |"), "Python ", "Python 9"),
    ("database-version", lambda s: s.startswith("| Database |"), "1.0.0", "1.0.1"),
    ("licence-name", lambda s: s.startswith("| Database licence |"), "Licence 1.2", "Licence 1.3"),
    ("licence-address", lambda s: s.startswith("| Database licence |"), "/1-2/ |", "/1-3/ |"),
    ("verification-files", lambda s: s.startswith("| Verification |"), "28 files", "27 files"),
    ("verification-records", lambda s: s.startswith("| Verification |"), "100, 105", "100, 106"),
    ("records", lambda s: s.startswith("| Records |"), "| 6 |", "| 7 |"),
    ("channel", lambda s: s.startswith("| Signal |"), "channel 0", "channel 1"),
    ("mains", lambda s: s.startswith("| Mains interference filter |"), "60 Hz", "50 Hz"),
    ("count-of-a-record", lambda s: s.startswith("| 105 |"), "| 118 |", "| 117 |"),
    ("signal-of-a-record", lambda s: s.startswith("| 108 |"), "| V5 |", "| MLII |"),
    ("percentage-of-a-record", lambda s: s.startswith("| 108 |"), "97.01", "97.02"),
    ("gross", lambda s: s.startswith("| Gross |"), "| 713 |", "| 714 |"),
    ("average", lambda s: s.startswith("| Average |"), "98.67", "98.66"),
    ("ranking", lambda s: s.startswith("| 1 | 108 | 97.01 |"), "97.01", "97.00"),
    ("not-scored-duration", lambda s: s.startswith("| 207 | 2 |"), "25.4", "25.5"),
    ("not-scored-detections", lambda s: s.startswith("| 207 | 2 |"), "| 25 | 2 |", "| 25 | 3 |"),
    ("flutter-waves", lambda s: s.startswith("Flutter-wave annotations"), ": 0.", ": 1."),
]


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize(
    ("select", "old", "new"),
    [pytest.param(*case[1:], id=case[0]) for case in ONE_VALUE_CASES],
)
def test_one_differing_value_fails_and_is_named(
    select: Callable[[str], bool],
    old: str,
    new: str | None,
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """Verification case 2: one value in the stored report differs from the regenerated one.

    Input: the spike subset fixture and the report regenerated from it, stored with one
    change in one line: the title, the statement on what the results mean, the statement
    that the report covers a subset, the source identifier (last digit) or the version of
    the row `Software`, the Python version of the row `Runtime`, the database version, the
    name or the address of the licence of the database (row `Database licence`), the
    number of files or a record named by the verification, the number of records, the
    channel, the mains setting, a count, signal or percentage of a record, the gross or
    average values, a ranking value, the duration or the detections not scored of record 207,
    the number of flutter waves.
    Expected: the check raises `SubsetReportMismatchError` whose only difference is
    `line <n>: stored <stored line>, regenerated <regenerated line>` for that line; the
    regenerated report is written, byte-identical to the report regenerated earlier, and the
    stored report is unchanged. A stored report that differs only in the row `Software`
    fails like any other (architecture, section 8.11).
    """
    lines = _lines(reference)
    if new is None:
        selected = next(line for line in lines if select(line))
        old, new = _last_digit_changed(selected)
    n, stored_line, regenerated_line = _replace_in_line(lines, select, old, new)
    stored_data = ("\n".join(lines) + "\n").encode("utf-8")
    stored = tmp_path / STORED_NAME
    stored.write_bytes(stored_data)
    regenerated = tmp_path / "regenerated.md"

    with pytest.raises(SubsetReportMismatchError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector(), regenerated=regenerated)

    assert excinfo.value.differences == (_entry(n, stored_line, regenerated_line),)
    assert regenerated.read_bytes() == reference
    assert stored.read_bytes() == stored_data


@pytest.mark.requirement("SRS-016")
def test_stored_report_that_differs_only_in_the_software_row_fails(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
    running_software: Any,
) -> None:
    """The verification note of architecture 8.11: a stored report from other source code.

    Input: the spike subset fixture; the report regenerated from it, stored with its row
    `Software` stating another source identifier (64 zeros) for the same version, as a
    report produced before a change of the package would.
    Expected: the regenerated report states the identity of the package under test (the row
    computed by the test, architecture 8.14); the check raises `SubsetReportMismatchError`
    with the single difference `line <n>: stored | Software | sinus-dsp <version>, source
    SHA-256 000…000 |, regenerated <the current row>`.
    """
    lines = _lines(reference)
    n = lines.index(running_software.software_row) + 1
    old_row = f"| Software | sinus-dsp {running_software.version}, source SHA-256 {'0' * 64} |"
    lines[n - 1] = old_row
    stored = tmp_path / STORED_NAME
    stored.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))

    with pytest.raises(SubsetReportMismatchError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector())

    assert excinfo.value.differences == (_entry(n, old_row, running_software.software_row),)


@pytest.mark.requirement("SRS-016")
def test_stored_report_without_the_licence_row_fails(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """A stored report written before the licence item (SRS-012 v0.7.2) no longer passes.

    Input: the spike subset fixture; the report regenerated from it, stored without its line
    `| Database licence | … |`, as a subset report of the software before that item would be.
    Expected: the check raises `SubsetReportMismatchError`; the first difference names the
    line of the licence row, `line <n>: stored <the Verification row>, regenerated <the
    licence row>`; the entries are exactly those documented in architecture section 8.11
    (lines compared by position, 20 at most, then `… and <k> more`).
    """
    lines = _lines(reference)
    n = next(i for i, line in enumerate(lines) if line.startswith("| Database licence |")) + 1
    stored_lines = [*lines[: n - 1], *lines[n:]]
    stored = tmp_path / STORED_NAME
    stored.write_bytes(("\n".join(stored_lines) + "\n").encode("utf-8"))

    with pytest.raises(SubsetReportMismatchError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector())

    differences = excinfo.value.differences
    assert lines[n].startswith("| Verification |")
    assert differences[0] == _entry(n, lines[n], lines[n - 1])
    assert differences == _documented_differences(stored.read_bytes(), reference)


def _altered_bytes(data: bytes, case: str) -> tuple[bytes, int | None]:
    """The stored bytes for a case of differing bytes, and the line that must be named."""
    lines = _lines(data)
    software = next(i for i, line in enumerate(lines) if line.startswith("| Software |")) + 1
    if case == "crlf-on-every-line":
        return data.replace(b"\n", b"\r\n"), 1
    if case == "crlf-on-one-line":
        text = "".join(
            line + ("\r\n" if i + 1 == software else "\n") for i, line in enumerate(lines)
        )
        return text.encode("utf-8"), software
    if case == "no-final-line-feed":
        return data[:-1], len(lines)
    if case == "extra-final-line-feed":
        return data + b"\n", len(lines) + 1
    if case == "carriage-return-at-the-end":
        return data + b"\r", len(lines) + 1
    if case == "empty-file":
        return b"", 1
    raise AssertionError(case)


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize(
    "case",
    [
        "crlf-on-every-line",
        "crlf-on-one-line",
        "no-final-line-feed",
        "extra-final-line-feed",
        "carriage-return-at-the-end",
        "empty-file",
    ],
)
def test_stored_report_with_other_bytes_fails(
    case: str,
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """Any byte that differs fails the check, even when every line has the same text.

    Input: the report regenerated from the spike subset fixture, stored with CR LF line
    endings on every line, CR LF on the line `Software` only, without its final line feed,
    with one more line feed at the end, with a carriage return after the final line feed,
    or as an empty file.
    Expected: the check raises `SubsetReportMismatchError`; each difference names a line
    (`line <n>: …`), and the first one names the line where the bytes first differ: line 1,
    the line `Software`, the last line, or the line after the last one. The entries are
    exactly those documented in architecture section 8.11, worked out by the test:
    `line <n>: same text, line ending stored CR LF, regenerated LF` for each line (20
    entries, then `… and <k> more`) or for the line `Software` only;
    `line <n>: same text, line ending stored none (no final line feed), regenerated LF` for
    the last line; `line <n>: stored (empty line), regenerated (no line)` for the extra line
    feed; `line <n>: stored <CR>, regenerated (no line)` for the carriage return at the end;
    for the empty file, which has no line (architecture v0.2.11), `line <n>: stored (no
    line), regenerated <text>` for the first 20 lines, then `… and <k> more`.
    """
    stored_data, first_line = _altered_bytes(reference, case)
    stored = tmp_path / STORED_NAME
    stored.write_bytes(stored_data)

    with pytest.raises(SubsetReportMismatchError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector())

    differences = excinfo.value.differences
    assert differences, "no difference named"
    assert all(
        re.match(r"line \d+: ", entry) or entry.startswith("… and ") for entry in differences
    ), differences
    assert differences[0].startswith(f"line {first_line}: "), differences
    if case in ("crlf-on-one-line", "no-final-line-feed"):
        assert len(differences) == 1, differences
    if case == "empty-file":
        assert differences[0] == _entry(1, "(no line)", _lines(reference)[0])
    assert differences == _documented_differences(stored_data, reference)


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize(
    "case", ["trailing-space", "byte-order-mark", "tab-for-a-space", "non-breaking-space"]
)
def test_stored_report_with_an_invisible_difference_fails(
    case: str,
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """Differences that a reader would not see in the text still fail, and are named.

    Input: the report regenerated from the spike subset fixture, stored with a space at the
    end of the line `Software`, with a UTF-8 byte order mark before the first line, with a
    tab in place of the first space of the row of record 100, or with a non-breaking space
    in place of that space.
    Expected: `SubsetReportMismatchError` with the single difference `line <n>: stored
    <stored line>, regenerated <regenerated line>`.
    """
    lines = _lines(reference)
    if case == "trailing-space":
        n = next(i for i, line in enumerate(lines) if line.startswith("| Software |")) + 1
        stored_line = lines[n - 1] + " "
    elif case == "byte-order-mark":
        n, stored_line = 1, "﻿" + lines[0]
    else:
        n = next(i for i, line in enumerate(lines) if line.startswith("| 100 |")) + 1
        stored_line = lines[n - 1].replace(" ", "\t" if case == "tab-for-a-space" else "\xa0", 1)
    regenerated_line = lines[n - 1]
    lines[n - 1] = stored_line
    stored = tmp_path / STORED_NAME
    stored.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))

    with pytest.raises(SubsetReportMismatchError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector())

    assert excinfo.value.differences == (_entry(n, stored_line, regenerated_line),)


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize("case", ["extra-line-at-the-end", "last-line-missing", "line-inserted"])
def test_lines_present_in_only_one_report_are_named(
    case: str,
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """A line that only one of the two reports has fails the check and is named.

    Input: the report regenerated from the spike subset fixture, stored with one more line
    "An added line." at its end, without its last line, or with the line "An added line."
    inserted after line 3.
    Expected: `SubsetReportMismatchError`; the first difference names the first line that
    differs (the line after the last one, the last line, or line 4) and gives the text of the
    line concerned; with a line added or removed at the end, it is the only difference. The
    entries are exactly those documented in architecture section 8.11 (lines compared by
    position): `line <n>: stored An added line., regenerated (no line)`, `line <n>: stored
    (no line), regenerated <last line>`, and for the inserted line one entry per later
    position whose texts differ, 20 at most, then `… and <k> more`.
    """
    lines = _lines(reference)
    if case == "extra-line-at-the-end":
        stored_lines, n, text = [*lines, "An added line."], len(lines) + 1, "An added line."
    elif case == "last-line-missing":
        stored_lines, n, text = lines[:-1], len(lines), lines[-1]
    else:
        stored_lines, n, text = [*lines[:3], "An added line.", *lines[3:]], 4, "An added line."
    stored = tmp_path / STORED_NAME
    stored.write_bytes(("\n".join(stored_lines) + "\n").encode("utf-8"))

    with pytest.raises(SubsetReportMismatchError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector())

    differences = excinfo.value.differences
    assert differences[0].startswith(f"line {n}: "), differences
    assert text in differences[0], differences
    if case != "line-inserted":
        assert len(differences) == 1, differences
    assert differences == _documented_differences(stored.read_bytes(), reference)


@pytest.mark.requirement("SRS-016")
def test_many_differences_are_named_up_to_twenty_then_counted(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """With many differing lines, the first 20 are named and the others are counted.

    Input: the report regenerated from the spike subset fixture, stored with " (changed)"
    added at the end of each of its first 30 non-empty lines.
    Expected: `SubsetReportMismatchError` with 21 entries: `line <n>: stored <line>
    (changed), regenerated <line>` for the first 20 changed lines, in their order, then
    `… and 10 more` (architecture, section 8.11).
    """
    lines = _lines(reference)
    changed = [i for i, line in enumerate(lines) if line][:30]
    assert len(changed) == 30
    stored_lines = [line + " (changed)" if i in changed else line for i, line in enumerate(lines)]
    stored = tmp_path / STORED_NAME
    stored.write_bytes(("\n".join(stored_lines) + "\n").encode("utf-8"))

    with pytest.raises(SubsetReportMismatchError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector())

    expected = [_entry(i + 1, stored_lines[i], lines[i]) for i in changed[:20]]
    assert excinfo.value.differences == (*expected, "… and 10 more")


@pytest.mark.requirement("SRS-016")
def test_absent_stored_report_fails(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """A stored report that does not exist is a difference.

    Input: the spike subset fixture; a stored report path where no file exists; a path for
    the regenerated report.
    Expected: `SubsetReportMismatchError` with the single difference `no stored report:
    <stored path>` (architecture, section 8.11); the regenerated report is written,
    byte-identical to the report regenerated earlier; no file is created at the stored path.
    """
    stored = tmp_path / "docs" / STORED_NAME
    regenerated = tmp_path / "regenerated.md"

    with pytest.raises(SubsetReportMismatchError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector(), regenerated=regenerated)

    assert excinfo.value.differences == (f"no stored report: {stored}",)
    assert regenerated.read_bytes() == reference
    assert not stored.exists()


@pytest.mark.requirement("SRS-016")
def test_stored_report_that_is_not_utf8_fails(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
) -> None:
    """A stored report that is not UTF-8 text fails the check with an error naming it.

    Input: the report regenerated from the spike subset fixture, stored with the byte 0xFF
    in place of its first character; a path for the regenerated report.
    Expected: `MalformedFileError` naming the stored report (architecture, sections 8.2 and
    8.11); the regenerated report is written all the same (it is written before the
    comparison), byte-identical to the report regenerated earlier.
    """
    stored = tmp_path / STORED_NAME
    stored.write_bytes(b"\xff" + reference[1:])
    regenerated = tmp_path / "regenerated.md"

    with pytest.raises(MalformedFileError) as excinfo:
        _check(subset_fixture, stored, make_spike_detector(), regenerated=regenerated)

    assert STORED_NAME in excinfo.value.path
    assert regenerated.read_bytes() == reference


@pytest.mark.requirement("SRS-016")
def test_compare_reports_names_each_differing_line() -> None:
    """The comparison function, on texts written by the test.

    Input: `compare_reports(stored, regenerated, "stored.md")` with the regenerated text
    "a\\nb\\nc\\n" and the stored bytes b"a\\nb\\nc\\n", b"a\\nB\\nc\\n" and b"x\\nb\\ny\\n".
    Expected: no error for equal bytes; otherwise `SubsetReportMismatchError` with the
    differences ("line 2: stored B, regenerated b",) and ("line 1: stored x, regenerated a",
    "line 3: stored y, regenerated c").
    """
    regenerated = "a\nb\nc\n"

    assert compare_reports(b"a\nb\nc\n", regenerated, "stored.md") is None
    with pytest.raises(SubsetReportMismatchError) as one:
        compare_reports(b"a\nB\nc\n", regenerated, "stored.md")
    with pytest.raises(SubsetReportMismatchError) as two:
        compare_reports(b"x\nb\ny\n", regenerated, "stored.md")

    assert one.value.differences == ("line 2: stored B, regenerated b",)
    assert two.value.differences == (
        "line 1: stored x, regenerated a",
        "line 3: stored y, regenerated c",
    )


# --------------------------------------------------------------------------------------------
# A file that fails verification: the check fails and no report is written
# --------------------------------------------------------------------------------------------


def _damage(folder: Path, kind: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Damage a copy of the subset fixture; return the (missing, mismatched) files expected."""
    if kind == "one-file-altered-one-missing":
        _flip_one_bit(folder / "105.dat")
        (folder / "203.atr").unlink()
        return ("203.atr",), ("105.dat",)
    if kind == "header-altered":
        _flip_one_bit(folder / "100.hea")
        return (), ("100.hea",)
    if kind == "annotation-file-not-read-altered":
        _flip_one_bit(folder / "108.at_")
        return (), ("108.at_",)
    if kind == "calibration-file-missing":
        (folder / "119.xws").unlink()
        return ("119.xws",), ()
    if kind == "every-file-of-a-record-missing":
        for suffix in ("atr", "dat", "hea", "xws"):
            (folder / f"207.{suffix}").unlink()
        return ("207.atr", "207.dat", "207.hea", "207.xws"), ()
    if kind == "checksum-list-missing":
        (folder / "SHA256SUMS.txt").unlink()
        return ("SHA256SUMS.txt",), ()
    if kind == "checksum-list-altered":
        path = folder / "SHA256SUMS.txt"
        path.write_bytes(path.read_bytes() + b"0" * 64 + b" 999.dat\n")
        return (), ("SHA256SUMS.txt",)
    raise AssertionError(kind)


DAMAGES = [
    "one-file-altered-one-missing",
    "header-altered",
    "annotation-file-not-read-altered",
    "calibration-file-missing",
    "every-file-of-a-record-missing",
    "checksum-list-missing",
    "checksum-list-altered",
]


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize("kind", DAMAGES)
def test_failed_verification_stops_the_check_before_any_report_is_written(
    kind: str,
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
    copy_subset_fixture: Callable[..., Any],
) -> None:
    """Verification case 3: a record file fails verification.

    Input: a copy of the spike subset fixture with 105.dat altered by one bit and 203.atr
    deleted (the case of the SRS); or 100.hea altered; or 108.at_ altered (an annotation
    file that the evaluation does not read); or 119.xws deleted; or every file of record 207
    deleted; or the checksum list deleted, or altered so that it is not the pinned one. The
    stored report is the report regenerated earlier from the intact fixture; a path for the
    regenerated report is given; data are not downloaded (`fetch=None`).
    Expected: the check raises `DataVerificationError` for "mitdb 1.0.0" naming each missing
    and each altered file; the regenerated report is not written and nothing else is written
    in its folder; the stored report is unchanged; the detector is never called.
    """
    copy = copy_subset_fixture(subset_fixture, tmp_path / "data")
    missing, mismatched = _damage(copy.folder, kind)
    output = tmp_path / "out"
    output.mkdir()
    stored = output / STORED_NAME
    stored.write_bytes(reference)
    detector = make_spike_detector()

    with pytest.raises(DataVerificationError) as excinfo:
        _check(copy, stored, detector, regenerated=output / "regenerated.md")

    assert excinfo.value.database == "mitdb 1.0.0"
    assert (excinfo.value.missing, excinfo.value.mismatched) == (missing, mismatched)
    for name in (*missing, *mismatched):
        assert name in str(excinfo.value)
    assert [p.name for p in output.iterdir()] == [STORED_NAME]
    assert stored.read_bytes() == reference
    assert detector.calls == []


@pytest.mark.requirement("SRS-016")
def test_files_of_the_six_records_are_selected_by_their_name() -> None:
    """Which listed files are "their files" (architecture, section 8.3).

    Input: `select_files` with the record names of the subset and a checksum list naming
    `100.atr`, `100.dat`, `100.`, `1000.dat`, `100a.hea`, `x_mitdb/100.dat`, `105.at_`,
    `105.hea`, `119.xws`, `203.at-`, `207.dat`, `RECORDS` (digests irrelevant here).
    Expected: every top-level file named `<record>.<extension>` of a subset record, whatever
    the extension, and nothing else: `100.atr`, `100.dat`, `105.at_`, `105.hea`, `119.xws`,
    `203.at-`, `207.dat`; record 108, which has no listed file, appears as the placeholder
    `108.*` (reported missing by the verification); the result is sorted in code-point order.
    """
    names = [
        "100.atr",
        "100.dat",
        "100.",
        "1000.dat",
        "100a.hea",
        "x_mitdb/100.dat",
        "105.at_",
        "105.hea",
        "119.xws",
        "203.at-",
        "207.dat",
        "RECORDS",
    ]
    checksums = {name: "0" * 64 for name in names}

    assert select_files(checksums, SUBSET_RECORDS) == (
        "100.atr",
        "100.dat",
        "105.at_",
        "105.hea",
        "108.*",
        "119.xws",
        "203.at-",
        "207.dat",
    )


@pytest.mark.requirement("SRS-016")
def test_record_without_any_listed_file_fails_verification(
    tmp_path: Path,
    subset_fixture: Any,
    make_spike_detector: Callable[[], Any],
    copy_subset_fixture: Callable[..., Any],
    sha256_hex: Callable[[bytes], str],
) -> None:
    """A subset record that the checksum list does not name cannot be verified.

    Input: a copy of the spike subset fixture whose checksum list is rewritten without the
    lines of record 203 (its files stay on disk), and the `Database` pinned to that list.
    Expected: `DataVerificationError` naming record 203 as missing, as `203.*` (architecture,
    section 8.3), and nothing else; no report is written; the detector is never called.
    """
    copy = copy_subset_fixture(subset_fixture, tmp_path / "data")
    checksum_list = copy.folder / "SHA256SUMS.txt"
    kept = [
        line
        for line in checksum_list.read_bytes().splitlines(keepends=True)
        if not line.split(b" ", 1)[1].startswith(b"203.")
    ]
    checksum_list.write_bytes(b"".join(kept))
    database = Database(
        slug="mitdb",
        version="1.0.0",
        title=MITDB_TITLE,
        checksum_list_sha256=sha256_hex(b"".join(kept)),
        licence=copy.licence,
    )
    detector = make_spike_detector()
    output = tmp_path / "out"
    output.mkdir()

    with pytest.raises(DataVerificationError) as excinfo:
        check_subset_report(
            output / STORED_NAME,
            copy.data_root,
            regenerated_path=output / "regenerated.md",
            database=database,
            detector=detector,
            fetch=None,
        )

    assert (excinfo.value.missing, excinfo.value.mismatched) == (("203.*",), ())
    assert list(output.iterdir()) == []
    assert detector.calls == []


# --------------------------------------------------------------------------------------------
# Obtaining the records: download of what is missing, a cached copy, no network
# --------------------------------------------------------------------------------------------


def _served(fixture: Any, altered: dict[str, bytes] | None = None) -> dict[str, bytes]:
    """Every file of the fixture database and its checksum list, by URL; ``altered`` maps a
    file name to the content served in its place."""
    contents = {f"{FILES_URL}{path}": data for path, data in fixture.database.folder.files.items()}
    contents[f"{FILES_URL}SHA256SUMS.txt"] = fixture.database.folder.checksum_list
    for name, data in (altered or {}).items():
        contents[f"{FILES_URL}{name}"] = data
    return contents


@pytest.mark.requirement("SRS-016")
def test_records_are_downloaded_when_no_copy_is_available(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
    make_fake_fetch: Callable[[dict[str, bytes]], Any],
) -> None:
    """The six records are obtained from PhysioNet when the data folder is empty.

    Input: an empty data folder; a fetch function that serves every file of the fixture
    database and its checksum list at https://physionet.org/files/mitdb/1.0.0/<path>
    (records outside the subset included); the stored report regenerated earlier.
    Expected: the check passes; the files asked for are the checksum list and the 28 files
    of the six records, each once, and nothing else (no file of record 101, no `RECORDS`);
    afterwards the data folder holds exactly these 29 files, with the published contents.
    """
    data_root = tmp_path / "data"
    data_root.mkdir()
    fetch = make_fake_fetch(_served(subset_fixture))
    stored = tmp_path / STORED_NAME
    stored.write_bytes(reference)
    copy = type(subset_fixture)(
        data_root=data_root,
        database=subset_fixture.database,
        subset_files=subset_fixture.subset_files,
        other_files=subset_fixture.other_files,
    )

    _check(copy, stored, make_spike_detector(), fetch=fetch)

    expected = {f"{FILES_URL}SHA256SUMS.txt"} | {
        f"{FILES_URL}{name}" for name in subset_fixture.subset_files
    }
    assert sorted(fetch.calls) == sorted(expected)
    folder = data_root / "mitdb"
    written = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert written == sorted(["SHA256SUMS.txt", *subset_fixture.subset_files])
    for name in subset_fixture.subset_files:
        assert (data_root / "mitdb" / name).read_bytes() == subset_fixture.database.folder.files[
            name
        ]


@pytest.mark.requirement("SRS-016")
def test_damaged_cached_files_are_downloaded_again(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
    make_fake_fetch: Callable[[dict[str, bytes]], Any],
    copy_subset_fixture: Callable[..., Any],
) -> None:
    """A cached copy is only a copy: a damaged or missing file is obtained again.

    Input: a cached copy of the six records with 105.dat altered by one bit and 207.atr
    deleted; a fetch function serving the published files; the stored report regenerated
    earlier.
    Expected: the check passes; 105.dat and 207.atr are asked for, and no intact file; both
    files hold the published contents afterwards.
    """
    copy = copy_subset_fixture(subset_fixture, tmp_path / "data", only_subset=True)
    _flip_one_bit(copy.folder / "105.dat")
    (copy.folder / "207.atr").unlink()
    fetch = make_fake_fetch(_served(subset_fixture))
    stored = tmp_path / STORED_NAME
    stored.write_bytes(reference)

    _check(copy, stored, make_spike_detector(), fetch=fetch)

    assert sorted(fetch.calls) == [f"{FILES_URL}105.dat", f"{FILES_URL}207.atr"]
    for name in ("105.dat", "207.atr"):
        assert (copy.folder / name).read_bytes() == subset_fixture.database.folder.files[name]


@pytest.mark.requirement("SRS-016")
def test_downloaded_file_that_does_not_match_fails_verification(
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
    make_fake_fetch: Callable[[dict[str, bytes]], Any],
) -> None:
    """Data obtained from the network are verified like a cached copy.

    Input: an empty data folder; a fetch function serving the published files, except that
    100.dat is served with one byte changed and 119.hea is not served at all.
    Expected: `DataVerificationError` naming 100.dat as mismatched and 119.hea as missing; no
    report is written; the stored report is unchanged; the detector is never called.
    """
    data_root = tmp_path / "data"
    data_root.mkdir()
    altered = bytearray(subset_fixture.database.folder.files["100.dat"])
    altered[100] ^= 0xFF
    contents = _served(subset_fixture, {"100.dat": bytes(altered)})
    del contents[f"{FILES_URL}119.hea"]
    fetch = make_fake_fetch(contents)
    output = tmp_path / "out"
    output.mkdir()
    stored = output / STORED_NAME
    stored.write_bytes(reference)
    detector = make_spike_detector()
    copy = type(subset_fixture)(
        data_root=data_root,
        database=subset_fixture.database,
        subset_files=subset_fixture.subset_files,
        other_files=subset_fixture.other_files,
    )

    with pytest.raises(DataVerificationError) as excinfo:
        _check(copy, stored, detector, regenerated=output / "regenerated.md", fetch=fetch)

    assert (excinfo.value.missing, excinfo.value.mismatched) == (("119.hea",), ("100.dat",))
    assert [p.name for p in output.iterdir()] == [STORED_NAME]
    assert stored.read_bytes() == reference
    assert detector.calls == []


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize("fetch_kind", ["offline", "network-failing"])
def test_check_fails_when_the_records_cannot_be_obtained(
    fetch_kind: str,
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    make_spike_detector: Callable[[], Any],
    make_fake_fetch: Callable[[dict[str, bytes]], Any],
) -> None:
    """No data and no way to obtain them: the check fails, it does not pass.

    Input: an empty data folder, with `fetch=None` (verification only) or with a fetch
    function that serves nothing.
    Expected: `DataVerificationError` naming the checksum list as missing; no report is
    written; the detector is never called.
    """
    data_root = tmp_path / "data"
    data_root.mkdir()
    fetch = None if fetch_kind == "offline" else make_fake_fetch({})
    output = tmp_path / "out"
    output.mkdir()
    detector = make_spike_detector()
    copy = type(subset_fixture)(
        data_root=data_root,
        database=subset_fixture.database,
        subset_files=subset_fixture.subset_files,
        other_files=subset_fixture.other_files,
    )

    with pytest.raises(DataVerificationError) as excinfo:
        _check(copy, output / STORED_NAME, detector, regenerated=output / "r.md", fetch=fetch)

    assert "SHA256SUMS.txt" in excinfo.value.missing
    assert list(output.iterdir()) == []
    assert detector.calls == []


# --------------------------------------------------------------------------------------------
# The command run by the build: scripts/subset_check.py
# --------------------------------------------------------------------------------------------


def _run_script(
    driver: Path,
    pin: str,
    arguments: Sequence[str],
    *,
    cwd: Path,
    script: Path = SUBSET_CHECK_SCRIPT,
    package_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the subset check command in a separate process without network, with the pinned
    checksum list of the MIT-BIH Arrhythmia Database set to ``pin`` in that process only.
    With ``package_root``, the process imports the package `sinus_dsp` found there."""
    environment = dict(os.environ)
    if package_root is not None:
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(package_root), *([existing] if existing else [])]
        )
    return subprocess.run(
        [sys.executable, str(driver), pin, "-", str(script), *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )


def _differences_named(stderr: str) -> set[int]:
    """The line numbers named by difference entries on standard error."""
    return {int(n) for n in re.findall(r"line (\d+): ", stderr)}


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize("stored_kind", ["equal", "one-value-differs", "absent", "not-utf8"])
def test_command_passes_only_when_the_stored_report_equals_the_regenerated_one(
    stored_kind: str,
    tmp_path: Path,
    subset_ecg_fixture: Any,
    ecg_reference: bytes,
    write_command_driver: Callable[[Path], Path],
) -> None:
    """The command of the build: exit status 0 when the reports are equal, a failure otherwise.

    Input: `subset_check.py --offline --data-dir <fixture> --stored <path>
    --write-regenerated <path>`, run in a separate process without network, on the synthetic
    ECG subset fixture with the real detector (the command's default), with the pinned
    checksum list set to the fixture list for that process only. The stored report is the
    report regenerated earlier by the check with its defaults; or that report with the TP
    of record 105 raised by one; or absent; or that report with the byte 0xFF in place of its
    first character.
    Expected: equal reports: exit status 0. One value differs: exit status 1, and standard
    error gives the documented entry `line <n>: stored <stored line>, regenerated <line>` and
    names no other line. Absent: exit status 1, standard error gives the documented entry
    `no stored report: <stored path>`.
    Not UTF-8: a status other than 0 (the build fails), standard error names the stored
    report. In every case: no traceback; the regenerated report is written, byte-identical to
    the report regenerated earlier (so the build can publish it), and the stored report is
    unchanged.
    """
    fixture = subset_ecg_fixture
    stored = tmp_path / "docs" / STORED_NAME
    stored.parent.mkdir()
    regenerated = tmp_path / "artifact" / STORED_NAME
    regenerated.parent.mkdir()
    lines = _lines(ecg_reference)
    entry = None
    if stored_kind == "equal":
        stored.write_bytes(ecg_reference)
    elif stored_kind == "one-value-differs":
        row = next(line for line in lines if line.startswith("| 105 |"))
        tp = row.split(" | ")[2]
        n, stored_line, regenerated_line = _replace_in_line(
            lines, lambda s: s.startswith("| 105 |"), f"| {tp} |", f"| {int(tp) + 1} |"
        )
        entry = _entry(n, stored_line, regenerated_line)
        stored.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    elif stored_kind == "not-utf8":
        stored.write_bytes(b"\xff" + ecg_reference[1:])
    stored_before = stored.read_bytes() if stored.exists() else None
    driver = write_command_driver(tmp_path)

    completed = _run_script(
        driver,
        fixture.checksum_list_sha256,
        [
            "--offline",
            "--data-dir",
            str(fixture.data_root),
            "--stored",
            str(stored),
            "--write-regenerated",
            str(regenerated),
        ],
        cwd=tmp_path,
    )

    assert "Traceback" not in completed.stderr, completed.stderr
    if stored_kind == "equal":
        assert completed.returncode == 0, completed.stderr
    elif stored_kind == "one-value-differs":
        assert completed.returncode == 1, completed.stderr
        assert entry is not None and entry in completed.stderr
        assert _differences_named(completed.stderr) == {int(entry.split()[1].rstrip(":"))}
    elif stored_kind == "absent":
        assert completed.returncode == 1, completed.stderr
        assert f"no stored report: {stored}" in completed.stderr
    else:
        assert completed.returncode != 0
        assert STORED_NAME in completed.stderr
    assert regenerated.read_bytes() == ecg_reference
    assert (stored.read_bytes() if stored.exists() else None) == stored_before


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize("mode", ["check", "update", "update-same-path"])
def test_command_fails_without_writing_a_report_when_verification_fails(
    mode: str,
    tmp_path: Path,
    subset_fixture: Any,
    reference: bytes,
    copy_subset_fixture: Callable[..., Any],
    write_command_driver: Callable[[Path], Path],
) -> None:
    """The command of the build when a record file fails verification.

    Input: `subset_check.py --offline --data-dir <copy> --stored <path> --write-regenerated
    <path>`; the same with `--update`; and with `--update` and `--write-regenerated` naming
    the stored report itself (allowed since architecture v0.2.10), each run in a separate
    process without network, on a copy of the spike subset fixture with 105.dat altered and
    203.atr deleted, the pinned list set to the fixture list; the stored report holds a
    previous report.
    Expected: exit status 1; standard error says that the database is not verified and names
    105.dat and 203.atr, with no traceback; no regenerated report is written; the stored
    report is unchanged, also with `--update` and when both options name it.
    """
    copy = copy_subset_fixture(subset_fixture, tmp_path / "data")
    _damage(copy.folder, "one-file-altered-one-missing")
    output = tmp_path / "out"
    output.mkdir()
    stored = output / STORED_NAME
    stored.write_bytes(reference)
    driver = write_command_driver(tmp_path)
    regenerated = stored if mode == "update-same-path" else output / "regenerated.md"
    arguments = [
        "--offline",
        "--data-dir",
        str(copy.data_root),
        "--stored",
        str(stored),
        "--write-regenerated",
        str(regenerated),
        *(["--update"] if mode != "check" else []),
    ]

    completed = _run_script(driver, copy.checksum_list_sha256, arguments, cwd=tmp_path)

    assert completed.returncode == 1, completed.stderr
    assert "not verified" in completed.stderr
    assert "105.dat" in completed.stderr and "203.atr" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert [p.name for p in output.iterdir()] == [STORED_NAME]
    assert stored.read_bytes() == reference


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize("regenerated", ["none", "other-path", "same-path"])
def test_command_update_replaces_the_stored_report_with_the_regenerated_one(
    regenerated: str,
    tmp_path: Path,
    subset_ecg_fixture: Any,
    ecg_reference: bytes,
    write_command_driver: Callable[[Path], Path],
) -> None:
    """The documented way of updating the stored report, followed by the check of the build.

    Input: a stored report holding "previous report"; `subset_check.py --offline --data-dir
    <fixture> --stored <path> --update` on the synthetic ECG subset fixture, alone, with
    `--write-regenerated <other path>`, or with `--write-regenerated` naming the stored
    report itself (architecture section 8.11, v0.2.10); then the same command without
    `--update` and `--write-regenerated`; each in a separate process without network.
    Expected: the first run exits with status 0, without a traceback, and the stored report
    becomes byte-identical to the report regenerated earlier by the check (and so does the
    file at the other path); the second run exits with status 0.
    """
    fixture = subset_ecg_fixture
    stored = tmp_path / STORED_NAME
    stored.write_bytes(b"previous report\n")
    other = tmp_path / "artifact" / STORED_NAME
    other.parent.mkdir()
    driver = write_command_driver(tmp_path)
    arguments = ["--offline", "--data-dir", str(fixture.data_root), "--stored", str(stored)]
    extra = {
        "none": [],
        "other-path": ["--write-regenerated", str(other)],
        "same-path": ["--write-regenerated", str(stored)],
    }[regenerated]

    first = _run_script(
        driver, fixture.checksum_list_sha256, [*arguments, "--update", *extra], cwd=tmp_path
    )
    after_update = stored.read_bytes()
    second = _run_script(driver, fixture.checksum_list_sha256, arguments, cwd=tmp_path)

    assert first.returncode == 0, first.stderr
    assert "Traceback" not in first.stderr
    assert after_update == ecg_reference
    if regenerated == "other-path":
        assert other.read_bytes() == ecg_reference
    assert second.returncode == 0, second.stderr


@pytest.mark.requirement("SRS-016")
def test_command_checks_the_stored_report_of_the_repository_with_a_cached_copy(
    tmp_path: Path,
    subset_ecg_fixture: Any,
    ecg_reference: bytes,
    copy_subset_fixture: Callable[..., Any],
    write_command_driver: Callable[[Path], Path],
    parse_report: Callable[[str], Any],
) -> None:
    """The command as the build runs it: default paths, download allowed, cached copy present.

    Input: a copy of the scripts folder in `<repo>/dsp/scripts/`, as in the repository; a
    cached copy of the six records of the synthetic ECG subset fixture in `<repo>/data/mitdb`
    (checksum list and the 28 files only), where the cache step of the build keeps them; the
    pinned list set to the fixture list, network forbidden. First run, from another folder:
    `subset_check.py --update`; second run, from `<repo>/dsp` as in the build:
    `subset_check.py --write-regenerated <path>`, without `--offline`, `--data-dir` or
    `--stored`.
    Expected: both runs exit with status 0 without using the network; the first one writes
    `<repo>/docs/validation/qrs-ec57-subset-report.md`, byte-identical to the report
    regenerated earlier by the check; the report written by the second run is byte-identical
    to it. The counts come from the real detector: for every record, TP equals the beats at
    or after 5:00, FN and FP are 0.
    """
    repo = tmp_path / "repo"
    shutil.copytree(
        SCRIPTS_DIR, repo / "dsp" / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    copy_subset_fixture(subset_ecg_fixture, repo / "data", only_subset=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    script = repo / "dsp" / "scripts" / "subset_check.py"
    driver = write_command_driver(tmp_path)
    pin = subset_ecg_fixture.checksum_list_sha256
    regenerated = tmp_path / "artifact.md"

    first = _run_script(driver, pin, ["--update"], cwd=elsewhere, script=script)
    second = _run_script(
        driver,
        pin,
        ["--write-regenerated", str(regenerated)],
        cwd=repo / "dsp",
        script=script,
    )

    assert first.returncode == 0, first.stderr
    stored = repo / "docs" / "validation" / STORED_NAME
    assert stored.read_bytes() == ecg_reference
    assert second.returncode == 0, second.stderr
    assert regenerated.read_bytes() == ecg_reference
    table = parse_report(ecg_reference.decode("utf-8")).section("results per record")
    rows = table.table_with_row("100")
    for record in subset_ecg_fixture.subset_records():
        assert rows.row(record.name)[2:5] == (str(record.tp), "0", "0"), record.name
        assert record.tp > 0


@pytest.mark.requirement("SRS-016")
@pytest.mark.parametrize("variant", ["same-code-crlf-copy", "comment-added"])
def test_command_fails_when_the_package_changed_and_the_stored_report_did_not(
    variant: str,
    tmp_path: Path,
    subset_ecg_fixture: Any,
    ecg_reference: bytes,
    copy_package: Callable[..., Path],
    expected_software: Callable[[Path], Any],
    running_software: Any,
    write_command_driver: Callable[[Path], Path],
) -> None:
    """A change of the code that is not carried into the stored report fails the build.

    Input: the stored report regenerated earlier by the package under test; the command
    `subset_check.py --offline --data-dir <fixture> --stored <path>` run in a separate
    process that imports a copy of the package: the same source code in another folder with
    CR LF line endings, or the package with a comment line added at the end of
    `sinus_dsp/evaluation/run.py` (no change of any result).
    Expected: same source code: exit status 0. Comment added: exit status 1; standard error
    names only the line `Software`, as `line <n>: stored <row of the package under test>,
    regenerated <row with the identifier computed by the test from the copy>`.
    """
    package = copy_package(tmp_path / "code copy", crlf=variant == "same-code-crlf-copy")
    if variant == "comment-added":
        path = package / "evaluation" / "run.py"
        path.write_bytes(path.read_bytes() + b"\n# A comment line added by a test.\n")
    copy_identity = expected_software(package)
    stored = tmp_path / STORED_NAME
    stored.write_bytes(ecg_reference)
    driver = write_command_driver(tmp_path)
    fixture = subset_ecg_fixture

    completed = _run_script(
        driver,
        fixture.checksum_list_sha256,
        ["--offline", "--data-dir", str(fixture.data_root), "--stored", str(stored)],
        cwd=tmp_path,
        package_root=package.parent,
    )

    if variant == "same-code-crlf-copy":
        assert copy_identity.software_row == running_software.software_row
        assert completed.returncode == 0, completed.stderr
    else:
        n = _lines(ecg_reference).index(running_software.software_row) + 1
        assert copy_identity.source_sha256 != running_software.source_sha256
        assert completed.returncode == 1, completed.stderr
        assert _entry(n, running_software.software_row, copy_identity.software_row) in (
            completed.stderr
        )
        assert _differences_named(completed.stderr) == {n}
    assert stored.read_bytes() == ecg_reference
