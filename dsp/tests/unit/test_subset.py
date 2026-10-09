"""Unit tests of the subset check: run, comparison of the reports, and the check itself.

A fixture arrhythmia database with the six records of the subset, one more record and a few
other files is written in a temporary folder (see ``write_subset_database`` in the conftest),
with a checksum list and a ``Database`` pinned to it, and evaluated with a fake detector.
Downloads use a fake fetch function that serves the fixture files. No test uses the network
or the real databases.
"""

import ast
import inspect
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

import sinus_dsp
from sinus_dsp.data.physionet import (
    CHECKSUM_LIST_NAME,
    MITDB,
    Database,
    database_url,
    describe_verification,
    fetch_https,
)
from sinus_dsp.data.records import Record, load_record
from sinus_dsp.errors import (
    DataVerificationError,
    InvalidInputError,
    MalformedFileError,
    SubsetReportMismatchError,
)
from sinus_dsp.evaluation import subset as subset_module
from sinus_dsp.evaluation.metrics import RecordCounts
from sinus_dsp.evaluation.report import render_subset_report, software_rows
from sinus_dsp.evaluation.run import DEFAULT_SETTINGS, EvaluationSettings, ValidationResults
from sinus_dsp.evaluation.subset import (
    SUBSET_RECORDS,
    check_subset_report,
    compare_reports,
    run_subset,
)
from sinus_dsp.pipeline import detect_beats
from sinus_dsp.version import SoftwareIdentity, software_identity

Detector = Callable[[npt.NDArray[np.float64], float, int], npt.NDArray[np.int64]]

DSP_DIR = Path(__file__).resolve().parents[2]

#: The files that the selection of the six records holds in the fixture database.
SUBSET_FILES = (
    "100.atr",
    "100.dat",
    "100.hea",
    "100.xws",
    "105.atr",
    "105.dat",
    "105.hea",
    "108.at_",
    "108.atr",
    "108.dat",
    "108.hea",
    "119.at_",
    "119.atr",
    "119.dat",
    "119.hea",
    "203.at-",
    "203.at_",
    "203.atr",
    "203.dat",
    "203.hea",
    "207.atr",
    "207.dat",
    "207.hea",
)

COUNTS = {
    "100": RecordCounts("100", 2, 1, 1),
    "105": RecordCounts("105", 2, 0, 2),
    "108": RecordCounts("108", 1, 2, 0),
    "119": RecordCounts("119", 3, 1, 0),
    "203": RecordCounts("203", 2, 0, 0),
    "207": RecordCounts("207", 2, 0, 0),
}


@pytest.fixture(scope="module")
def pristine(
    tmp_path_factory: pytest.TempPathFactory,
    write_subset_database: Callable[[Path], Database],
) -> tuple[Path, Database]:
    root = tmp_path_factory.mktemp("pristine")
    return root, write_subset_database(root)


@pytest.fixture
def data(pristine: tuple[Path, Database], tmp_path: Path) -> tuple[Path, Database]:
    """A fresh copy of the fixture database, which a test may change."""
    root, database = pristine
    copy = tmp_path / "data"
    shutil.copytree(root, copy)
    return copy, database


class CountingDetector:
    def __init__(self, detector: Detector, events: list[str] | None = None) -> None:
        self.detector = detector
        self.calls: list[tuple[float, int]] = []
        self.events = events

    def __call__(
        self, signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int
    ) -> npt.NDArray[np.int64]:
        self.calls.append((fs_hz, mains_hz))
        if self.events is not None:
            self.events.append("detect")
        return self.detector(signal_mv, fs_hz, mains_hz)


class RecordingLoader:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, int]] = []

    def __call__(self, path: Path, channel: int) -> Record:
        self.calls.append((path, channel))
        return load_record(path, channel)


class ServingFetch:
    """Serves the files of the pristine fixture database, and remembers the URLs."""

    def __init__(self, root: Path, database: Database) -> None:
        self.urls: list[str] = []
        self.content: dict[str, bytes] = {}
        folder = root / database.slug
        for path in folder.rglob("*"):
            if path.is_file():
                self.content[database_url(database) + path.relative_to(folder).as_posix()] = (
                    path.read_bytes()
                )

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if url not in self.content:
            raise OSError(f"not served: {url}")
        return self.content[url]


def failing_fetch(url: str) -> bytes:
    raise AssertionError(f"the network must not be used: {url}")


def report_lines(text: str) -> list[str]:
    return text.split("\n")


# --- constants, defaults, imports -----------------------------------------------------------


def test_subset_records() -> None:
    assert SUBSET_RECORDS == ("100", "105", "108", "119", "203", "207")
    assert list(SUBSET_RECORDS) == sorted(SUBSET_RECORDS)


def test_defaults() -> None:
    defaults = {
        "database": MITDB,
        "settings": EvaluationSettings(),
        "detector": detect_beats,
        "loader": load_record,
        "fetch": fetch_https,
    }
    assert run_subset.__kwdefaults__ == defaults
    assert check_subset_report.__kwdefaults__ == {"regenerated_path": None, **defaults}
    for function in (run_subset, check_subset_report):
        assert inspect.signature(function).parameters["settings"].default is DEFAULT_SETTINGS


def test_subset_module_can_be_imported_first() -> None:
    """``subset`` imports ``run`` and ``report`` at the top; ``run`` does not import it."""
    code = (
        "import sys, sinus_dsp.evaluation.subset, sinus_dsp.evaluation.run; "
        "print('sinus_dsp.evaluation.report' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True, cwd=DSP_DIR
    )
    assert completed.stdout.strip() == "True"
    code = (
        "import sys, sinus_dsp.evaluation.run; print('sinus_dsp.evaluation.subset' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True, cwd=DSP_DIR
    )
    assert completed.stdout.strip() == "False"


def test_imports_inside_functions_are_only_those_of_the_design() -> None:
    """Architecture §8.13 and §13.7.4: the imports ``run`` makes inside its two functions."""
    found: list[tuple[str, str, str]] = []
    package = Path(sinus_dsp.__file__).resolve().parent
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.ImportFrom):
                    found.append((path.name, function.name, str(node.module)))
                elif isinstance(node, ast.Import):
                    found.append((path.name, function.name, node.names[0].name))
    assert sorted(found) == [
        ("quality.py", "quality_windows", "sinus_dsp.pipeline"),
        ("run.py", "run_validation", "sinus_dsp.evaluation.noise_stress"),
        ("run.py", "run_validation", "sinus_dsp.evaluation.signal_quality"),
        ("run.py", "run_validation", "sinus_dsp.evaluation.start_of_stream"),
        ("run.py", "write_validation_report", "sinus_dsp.evaluation.report"),
    ]


# --- run_subset -----------------------------------------------------------------------------


def test_offline_run(data: tuple[Path, Database], fake_detector: Detector) -> None:
    root, database = data
    detector = CountingDetector(fake_detector)
    loader = RecordingLoader()
    results = run_subset(root, database=database, detector=detector, loader=loader, fetch=None)
    assert isinstance(results, ValidationResults)
    assert results.subset is True
    assert results.noise_stress is None
    assert results.settings is DEFAULT_SETTINGS
    assert results.software == software_identity()
    assert results.mitdb.database == database
    assert results.mitdb.records == SUBSET_RECORDS
    assert results.mitdb.files == SUBSET_FILES
    assert [record.record for record in results.records] == list(SUBSET_RECORDS)
    assert {record.record: record.counts for record in results.records} == COUNTS
    record_207 = results.records[-1]
    assert (record_207.vf_episodes, record_207.vf_episodes_scored) == (2, 1)
    assert record_207.vf_samples_scored == 101
    assert (record_207.reference_excluded, record_207.detections_excluded) == (1, 2)
    assert record_207.flutter_waves_outside_vf == 1
    assert loader.calls == [(root / "mitdb" / name, 0) for name in SUBSET_RECORDS]
    assert detector.calls == [(20.0, 60)] * 6


def test_the_report_of_the_results(data: tuple[Path, Database], fake_detector: Detector) -> None:
    root, database = data
    results = run_subset(root, database=database, detector=fake_detector, fetch=None)
    lines = report_lines(render_subset_report(results))
    assert (
        "This report covers records 100, 105, 108, 119, 203 and 207 of the Fixture Arrhythmia "
        "Database. It is a regression check run on every change, not the performance "
        "evaluation against the targets, which uses all 48 records (qrs-ec57-report.md)."
    ) in lines
    verification = describe_verification(results.mitdb)
    assert verification.startswith("verified: 23 files match")
    assert verification.endswith("; records 100, 105, 108, 119, 203, 207")
    assert f"| Verification | {verification} |" in lines
    database_row = lines.index("| Database | Fixture Arrhythmia Database, version 1.0.0 |")
    assert lines[database_row + 1] == (
        "| Database licence | Fixture Licence of mitdb 1.0, https://licences.example/mitdb/ |"
    )
    assert sum(line.startswith("| Database licence |") for line in lines) == 1
    assert "| Records | 6 |" in lines
    assert "| Gross |  | 12 | 4 | 3 | 75.00 | 80.00 |" in lines
    assert all(row in lines for row in software_rows(software_identity()))


def test_files_outside_the_subset_are_neither_verified_nor_evaluated(
    pristine: tuple[Path, Database], data: tuple[Path, Database], fake_detector: Detector
) -> None:
    root, database = data
    folder = root / "mitdb"
    for name in ("118.dat", "RECORDS", "1001.dat", "mitdbdir/notes.txt"):
        (folder / name).write_bytes(b"altered")
    (folder / "x_mitdb" / "x_108.hea").unlink()
    (folder / "999.hea").write_bytes(b"not listed")
    loader = RecordingLoader()
    results = run_subset(root, database=database, detector=fake_detector, loader=loader, fetch=None)
    expected = run_subset(pristine[0], database=database, detector=fake_detector, fetch=None)
    assert results == expected
    assert [path.name for path, _ in loader.calls] == list(SUBSET_RECORDS)


def test_failed_verification_stops_before_any_evaluation(
    data: tuple[Path, Database], fake_detector: Detector, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = data
    (root / "mitdb" / "105.dat").write_bytes(b"altered")
    (root / "mitdb" / "203.at-").unlink()
    detector = CountingDetector(fake_detector)
    loader = RecordingLoader()
    identities: list[None] = []
    monkeypatch.setattr(subset_module, "software_identity", lambda: identities.append(None))
    with pytest.raises(DataVerificationError) as caught:
        run_subset(root, database=database, detector=detector, loader=loader, fetch=None)
    assert str(caught.value) == (
        "mitdb 1.0.0 not verified: missing: 203.at-; checksum mismatch: 105.dat"
    )
    assert (caught.value.missing, caught.value.mismatched) == (("203.at-",), ("105.dat",))
    assert detector.calls == []
    assert loader.calls == []
    assert identities == []


def test_altered_checksum_list_is_not_verified(
    data: tuple[Path, Database], fake_detector: Detector
) -> None:
    root, database = data
    with (root / "mitdb" / CHECKSUM_LIST_NAME).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(DataVerificationError) as caught:
        run_subset(root, database=database, detector=fake_detector, fetch=None)
    assert caught.value.mismatched == (CHECKSUM_LIST_NAME,)


def test_absent_data_folder_is_not_verified_and_not_created(
    tmp_path: Path, fake_detector: Detector
) -> None:
    root = tmp_path / "absent"
    with pytest.raises(DataVerificationError) as caught:
        run_subset(root, detector=fake_detector, fetch=None)
    assert caught.value.database == "mitdb 1.0.0"
    assert caught.value.missing == (CHECKSUM_LIST_NAME,)
    assert not root.exists()


def test_download_fetches_only_the_files_of_the_subset(
    pristine: tuple[Path, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    source, database = pristine
    fetch = ServingFetch(source, database)
    root = tmp_path / "downloaded"
    results = run_subset(root, database=database, detector=fake_detector, fetch=fetch)
    base = database_url(database)
    assert fetch.urls == [base + CHECKSUM_LIST_NAME, *(base + name for name in SUBSET_FILES)]
    stored = sorted(
        path.relative_to(root / "mitdb").as_posix()
        for path in (root / "mitdb").rglob("*")
        if path.is_file()
    )
    assert stored == sorted([CHECKSUM_LIST_NAME, *SUBSET_FILES])
    offline = run_subset(root, database=database, detector=fake_detector, fetch=None)
    assert results == offline
    # A complete copy (e.g. the CI cache) is used as it is: nothing is fetched.
    again = ServingFetch(source, database)
    assert run_subset(root, database=database, detector=fake_detector, fetch=again) == results
    assert again.urls == []


def test_an_altered_file_of_a_cached_copy_is_downloaded_again(
    pristine: tuple[Path, Database], data: tuple[Path, Database], fake_detector: Detector
) -> None:
    source, database = pristine
    root, _ = data
    (root / "mitdb" / "207.dat").write_bytes(b"corrupted cache")
    fetch = ServingFetch(source, database)
    results = run_subset(root, database=database, detector=fake_detector, fetch=fetch)
    assert fetch.urls == [database_url(database) + "207.dat"]
    assert results == run_subset(source, database=database, detector=fake_detector, fetch=None)


def test_failed_download_stops_before_any_evaluation(
    pristine: tuple[Path, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    source, database = pristine
    fetch = ServingFetch(source, database)
    del fetch.content[database_url(database) + "108.at_"]
    detector = CountingDetector(fake_detector)
    with pytest.raises(DataVerificationError) as caught:
        run_subset(tmp_path, database=database, detector=detector, fetch=fetch)
    assert caught.value.missing == ("108.at_",)
    assert detector.calls == []


def test_software_identity_is_taken_once_after_the_evaluation(
    data: tuple[Path, Database], fake_detector: Detector, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = data
    identity = SoftwareIdentity("7.7.7.dev0", "e" * 64, "3.99", (("numpy", "0.1"),))
    events: list[str] = []

    def fixed_identity() -> SoftwareIdentity:
        events.append("identity")
        return identity

    monkeypatch.setattr(subset_module, "software_identity", fixed_identity)
    detector = CountingDetector(fake_detector, events)
    results = run_subset(root, database=database, detector=detector, fetch=None)
    assert results.software is identity
    assert events == ["detect"] * 6 + ["identity"]


def test_settings_reach_the_detector_and_the_loader(
    data: tuple[Path, Database], fake_detector: Detector
) -> None:
    root, database = data
    detector = CountingDetector(fake_detector)
    loader = RecordingLoader()
    settings = EvaluationSettings(channel=1, mains_hz=50)
    results = run_subset(
        root, database=database, settings=settings, detector=detector, loader=loader, fetch=None
    )
    assert results.settings is settings
    assert detector.calls == [(20.0, 50)] * 6
    assert {channel for _, channel in loader.calls} == {1}


def test_evaluation_errors_propagate(data: tuple[Path, Database]) -> None:
    root, database = data

    def failing(
        signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int
    ) -> npt.NDArray[np.int64]:
        return np.array([5, 3], dtype=np.int64)

    with pytest.raises(InvalidInputError, match="strictly increasing"):
        run_subset(root, database=database, detector=failing, fetch=None)


# --- compare_reports ------------------------------------------------------------------------


def mismatch(stored: bytes, regenerated: str) -> tuple[str, ...]:
    """The differences that ``compare_reports`` names."""
    with pytest.raises(SubsetReportMismatchError) as caught:
        compare_reports(stored, regenerated, "stored.md")
    return caught.value.differences


@pytest.mark.parametrize("text", ["", "a\n", "# Title\n\n| a | ≥ b |\n", "no final line feed"])
def test_equal_reports(text: str) -> None:
    compare_reports(text.encode("utf-8"), text, "stored.md")  # raises nothing


def test_one_line_differs() -> None:
    assert mismatch(b"a\nb\nc\n", "a\nx\nc\n") == ("line 2: stored b, regenerated x",)


def test_message_of_the_error() -> None:
    with pytest.raises(SubsetReportMismatchError) as caught:
        compare_reports(b"a\nb\nc\nd\n", "a\nx\nc\ny\n", "stored.md")
    assert str(caught.value) == (
        "subset report differs from the stored report:\n"
        "line 2: stored b, regenerated x\n"
        "line 4: stored d, regenerated y"
    )


def test_lines_only_in_one_of_the_two_are_named() -> None:
    assert mismatch(b"a\nb\nc\n", "a\n") == (
        "line 2: stored b, regenerated (no line)",
        "line 3: stored c, regenerated (no line)",
    )
    assert mismatch(b"a\n", "a\nb\n") == ("line 2: stored (no line), regenerated b",)
    assert mismatch(b"", "a\n") == ("line 1: stored (no line), regenerated a",)


def test_empty_lines_are_shown() -> None:
    assert mismatch(b"a\n\nb\n", "a\nx\nb\n") == ("line 2: stored (empty line), regenerated x",)
    assert mismatch(b"a\n\n", "a\n") == ("line 2: stored (empty line), regenerated (no line)",)


def test_lines_are_compared_by_their_number() -> None:
    assert mismatch(b"a\nb\nc\n", "a\nx\nb\nc\n") == (
        "line 2: stored b, regenerated x",
        "line 3: stored c, regenerated b",
        "line 4: stored (no line), regenerated c",
    )


def test_text_is_shown_as_it_is() -> None:
    assert mismatch("﻿a\n".encode(), "a\n") == ("line 1: stored ﻿a, regenerated a",)
    assert mismatch(b"a\rb\n", "ab\n") == ("line 1: stored a\rb, regenerated ab",)
    assert mismatch("| x | ≥ 1 |\n".encode(), "| x | ≥ 2 |\n") == (
        "line 1: stored | x | ≥ 1 |, regenerated | x | ≥ 2 |",
    )


@pytest.mark.parametrize(("n_differences", "more"), [(19, None), (20, None), (21, 1), (45, 25)])
def test_at_most_20_differences_are_named(n_differences: int, more: int | None) -> None:
    stored = "".join(f"s{index}\n" for index in range(n_differences)) + "same\n"
    regenerated = "".join(f"r{index}\n" for index in range(n_differences)) + "same\n"
    differences = mismatch(stored.encode(), regenerated)
    named = [f"line {index + 1}: stored s{index}, regenerated r{index}" for index in range(20)]
    if more is None:
        assert differences == tuple(named[:n_differences])
    else:
        assert differences == (*named, f"… and {more} more")


def test_carriage_returns_with_the_same_text_are_named() -> None:
    assert mismatch(b"a\r\nb\r\nc\r\n", "a\nb\nc\n") == (
        "line 1: same text, line ending stored CR LF, regenerated LF",
        "line 2: same text, line ending stored CR LF, regenerated LF",
        "line 3: same text, line ending stored CR LF, regenerated LF",
    )
    assert mismatch(b"a\nb\r\nc\n", "a\nb\nc\n") == (
        "line 2: same text, line ending stored CR LF, regenerated LF",
    )
    assert mismatch(b"a\nb\n", "a\r\nb\n") == (
        "line 1: same text, line ending stored LF, regenerated CR LF",
    )


def test_final_line_feed_is_named() -> None:
    assert mismatch(b"a\nb", "a\nb\n") == (
        "line 2: same text, line ending stored none (no final line feed), regenerated LF",
    )
    assert mismatch(b"a\nb\n", "a\nb") == (
        "line 2: same text, line ending stored LF, regenerated none (no final line feed)",
    )
    assert mismatch(b"a\r\nb", "a\nb\n") == (
        "line 1: same text, line ending stored CR LF, regenerated LF",
        "line 2: same text, line ending stored none (no final line feed), regenerated LF",
    )


def test_line_endings_are_named_only_when_the_texts_are_equal() -> None:
    assert mismatch(b"a\r\nb\r\nc\r\n", "a\nx\nc\n") == ("line 2: stored b, regenerated x",)


def test_line_ending_differences_are_limited_too() -> None:
    stored = "".join(f"{index}\r\n" for index in range(30))
    regenerated = "".join(f"{index}\n" for index in range(30))
    differences = mismatch(stored.encode(), regenerated)
    assert len(differences) == 21
    assert differences[0] == "line 1: same text, line ending stored CR LF, regenerated LF"
    assert differences[-1] == "… and 10 more"


def test_stored_report_that_is_not_utf8() -> None:
    with pytest.raises(MalformedFileError) as caught:
        compare_reports(b"a\n\xff\n", "a\nb\n", "docs/validation/stored.md")
    assert (caught.value.path, caught.value.line) == ("docs/validation/stored.md", None)
    assert caught.value.reason == "not UTF-8 text"
    assert str(caught.value) == "docs/validation/stored.md: not UTF-8 text"


def test_only_the_software_row_differs(
    data: tuple[Path, Database], fake_detector: Detector
) -> None:
    root, database = data
    results = run_subset(root, database=database, detector=fake_detector, fetch=None)
    current = render_subset_report(results)
    old_identity = SoftwareIdentity(
        results.software.version, "0" * 64, results.software.python, results.software.runtime
    )
    stored = current.replace(software_rows(results.software)[0], software_rows(old_identity)[0])
    number = report_lines(current).index(software_rows(results.software)[0]) + 1
    assert mismatch(stored.encode(), current) == (
        f"line {number}: stored {software_rows(old_identity)[0]}, "
        f"regenerated {software_rows(results.software)[0]}",
    )


# --- check_subset_report --------------------------------------------------------------------


@pytest.fixture
def stored_report(data: tuple[Path, Database], tmp_path: Path, fake_detector: Detector) -> Path:
    """A stored subset report equal to the one the fixture database gives."""
    root, database = data
    path = tmp_path / "docs" / "validation" / "qrs-ec57-subset-report.md"
    path.parent.mkdir(parents=True)
    results = run_subset(root, database=database, detector=fake_detector, fetch=None)
    path.write_bytes(render_subset_report(results).encode("utf-8"))
    return path


def test_check_passes_when_the_reports_are_equal(
    data: tuple[Path, Database], stored_report: Path, fake_detector: Detector
) -> None:
    root, database = data
    before = stored_report.read_bytes()
    check_subset_report(stored_report, root, database=database, detector=fake_detector, fetch=None)
    # With a complete local copy, as with a complete CI cache, the network is not used.
    check_subset_report(
        stored_report, root, database=database, detector=fake_detector, fetch=failing_fetch
    )
    assert stored_report.read_bytes() == before
    assert sorted(path.name for path in stored_report.parent.iterdir()) == [stored_report.name]


def test_check_with_a_download(
    pristine: tuple[Path, Database], stored_report: Path, tmp_path: Path, fake_detector: Detector
) -> None:
    source, database = pristine
    fetch = ServingFetch(source, database)
    root = tmp_path / "fresh"
    check_subset_report(stored_report, root, database=database, detector=fake_detector, fetch=fetch)
    assert len(fetch.urls) == 1 + len(SUBSET_FILES)


def test_regenerated_report_is_written_in_utf8_with_line_feeds(
    data: tuple[Path, Database], stored_report: Path, tmp_path: Path, fake_detector: Detector
) -> None:
    root, database = data
    regenerated = tmp_path / "new" / "folder" / "regenerated.md"
    check_subset_report(
        stored_report,
        root,
        regenerated_path=regenerated,
        database=database,
        detector=fake_detector,
        fetch=None,
    )
    content = regenerated.read_bytes()
    assert content == stored_report.read_bytes()
    assert b"\r" not in content
    assert content.endswith(b"\n") and not content.endswith(b"\n\n")
    assert sorted(path.name for path in regenerated.parent.iterdir()) == ["regenerated.md"]


def test_two_checks_regenerate_byte_identical_reports(
    data: tuple[Path, Database], stored_report: Path, tmp_path: Path, fake_detector: Detector
) -> None:
    root, database = data
    first, second = tmp_path / "first.md", tmp_path / "second.md"
    for output in (first, second):
        check_subset_report(
            stored_report,
            root,
            regenerated_path=output,
            database=database,
            detector=fake_detector,
            fetch=None,
        )
    assert first.read_bytes() == second.read_bytes()


def test_one_changed_count_fails_the_check_and_is_named(
    data: tuple[Path, Database], stored_report: Path, tmp_path: Path, fake_detector: Detector
) -> None:
    root, database = data
    text = stored_report.read_text(encoding="utf-8")
    row = "| 105 | MLII | 2 | 0 | 2 | 100.00 | 50.00 |"
    changed = "| 105 | MLII | 2 | 0 | 1 | 100.00 | 50.00 |"
    assert row in report_lines(text)
    stored_report.write_bytes(text.replace(row, changed).encode("utf-8"))
    regenerated = tmp_path / "regenerated.md"
    with pytest.raises(SubsetReportMismatchError) as caught:
        check_subset_report(
            stored_report,
            root,
            regenerated_path=regenerated,
            database=database,
            detector=fake_detector,
            fetch=None,
        )
    number = report_lines(text).index(row) + 1
    assert caught.value.differences == (f"line {number}: stored {changed}, regenerated {row}",)
    # The regenerated report is written before the comparison, for the CI artifact.
    assert regenerated.read_bytes() == text.encode("utf-8")


def test_stale_software_row_fails_the_check(
    data: tuple[Path, Database],
    stored_report: Path,
    fake_detector: Detector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, database = data
    identity = SoftwareIdentity("7.7.7.dev0", "e" * 64, "3.99", (("numpy", "0.1"),))
    monkeypatch.setattr(subset_module, "software_identity", lambda: identity)
    with pytest.raises(SubsetReportMismatchError) as caught:
        check_subset_report(
            stored_report, root, database=database, detector=fake_detector, fetch=None
        )
    current = software_rows(software_identity())
    new = software_rows(identity)
    lines = report_lines(stored_report.read_text(encoding="utf-8"))
    assert caught.value.differences == (
        f"line {lines.index(current[0]) + 1}: stored {current[0]}, regenerated {new[0]}",
        f"line {lines.index(current[1]) + 1}: stored {current[1]}, regenerated {new[1]}",
    )


def test_absent_stored_report_is_one_difference(
    data: tuple[Path, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    root, database = data
    stored = tmp_path / "absent" / "stored.md"
    regenerated = tmp_path / "regenerated.md"
    with pytest.raises(SubsetReportMismatchError) as caught:
        check_subset_report(
            stored,
            root,
            regenerated_path=regenerated,
            database=database,
            detector=fake_detector,
            fetch=None,
        )
    assert caught.value.differences == (f"no stored report: {stored}",)
    assert regenerated.is_file()
    assert not stored.parent.exists()


def test_stored_report_that_is_not_utf8_is_malformed(
    data: tuple[Path, Database], stored_report: Path, fake_detector: Detector
) -> None:
    root, database = data
    stored_report.write_bytes(b"\xff\xfe report\n")
    with pytest.raises(MalformedFileError) as caught:
        check_subset_report(
            stored_report, root, database=database, detector=fake_detector, fetch=None
        )
    assert caught.value.path == str(stored_report)


def test_stored_report_that_cannot_be_read(
    data: tuple[Path, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    root, database = data
    folder = tmp_path / "a folder"
    folder.mkdir()
    with pytest.raises(OSError) as caught:
        check_subset_report(folder, root, database=database, detector=fake_detector, fetch=None)
    assert not isinstance(caught.value, FileNotFoundError)


def test_failed_verification_writes_nothing(
    data: tuple[Path, Database], stored_report: Path, tmp_path: Path, fake_detector: Detector
) -> None:
    root, database = data
    (root / "mitdb" / "119.atr").unlink()
    before = stored_report.read_bytes()
    regenerated = tmp_path / "new" / "regenerated.md"
    for target in (regenerated, stored_report):
        with pytest.raises(DataVerificationError, match="missing: 119.atr"):
            check_subset_report(
                stored_report,
                root,
                regenerated_path=target,
                database=database,
                detector=fake_detector,
                fetch=None,
            )
    assert not regenerated.parent.exists()
    assert stored_report.read_bytes() == before
    assert sorted(path.name for path in stored_report.parent.iterdir()) == [stored_report.name]


@pytest.mark.parametrize("before", [None, b"an older report\n", b"\xff not UTF-8\n"])
def test_regenerated_path_equal_to_the_stored_path_updates_it(
    data: tuple[Path, Database],
    tmp_path: Path,
    fake_detector: Detector,
    before: bytes | None,
) -> None:
    root, database = data
    stored = tmp_path / "docs" / "stored.md"
    if before is not None:
        stored.parent.mkdir()
        stored.write_bytes(before)
    check_subset_report(
        stored,
        root,
        regenerated_path=stored,
        database=database,
        detector=fake_detector,
        fetch=None,
    )
    results = run_subset(root, database=database, detector=fake_detector, fetch=None)
    assert stored.read_bytes() == render_subset_report(results).encode("utf-8")
    assert sorted(path.name for path in stored.parent.iterdir()) == ["stored.md"]


def test_settings_reach_the_regenerated_report(
    data: tuple[Path, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    root, database = data
    stored = tmp_path / "stored.md"
    settings = EvaluationSettings(channel=0, mains_hz=50)
    check_subset_report(
        stored,
        root,
        regenerated_path=stored,
        database=database,
        settings=settings,
        detector=fake_detector,
        fetch=None,
    )
    assert "| Mains interference filter | 50 Hz |" in report_lines(
        stored.read_text(encoding="utf-8")
    )
