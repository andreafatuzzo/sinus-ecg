"""Unit tests of the validation run and of the writing of the full report.

Two small fixture databases are written in a temporary folder (see the conftest), with
checksum lists and ``Database`` values pinned to them, and evaluated with a fake detector.
Downloads use a fake fetch function that serves the fixture files. No test uses the network
or the real databases.
"""

import dataclasses
import hashlib
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
    NSTDB,
    Database,
    database_url,
    describe_verification,
    fetch_https,
)
from sinus_dsp.data.records import Record, load_record
from sinus_dsp.errors import DataVerificationError, InvalidInputError, MalformedFileError
from sinus_dsp.evaluation import run as run_module
from sinus_dsp.evaluation.metrics import RecordCounts
from sinus_dsp.evaluation.noise_stress import NOISE_STRESS_RECORDS
from sinus_dsp.evaluation.report import render_full_report, software_rows
from sinus_dsp.evaluation.run import (
    DEFAULT_SETTINGS,
    EvaluationSettings,
    ValidationResults,
    run_validation,
    write_validation_report,
)
from sinus_dsp.pipeline import detect_beats
from sinus_dsp.version import SoftwareIdentity, software_identity

Detector = Callable[[npt.NDArray[np.float64], float, int], npt.NDArray[np.int64]]

MITDB_COUNTS = {
    "100": RecordCounts("100", 2, 1, 1),
    "118": RecordCounts("118", 2, 0, 0),
    "119": RecordCounts("119", 3, 1, 0),
    "207": RecordCounts("207", 2, 0, 0),
}


@pytest.mark.parametrize("module", ["run", "noise_stress", "report"])
def test_each_module_can_be_imported_first(module: str) -> None:
    """``run`` imports ``noise_stress`` and ``report`` only when it calls them (no cycle)."""
    code = (
        f"import sys, sinus_dsp.evaluation.{module}; "
        "print(sorted(name for name in sys.modules if name.startswith('sinus_dsp.evaluation.')))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    loaded = completed.stdout.strip()
    if module == "run":
        assert "noise_stress" not in loaded and "report" not in loaded


def nstdb_counts(name: str) -> RecordCounts:
    j = NOISE_STRESS_RECORDS.index(name) % 6
    tp, fn = (2, 0) if j < 3 else (1, 1)
    return RecordCounts(name, tp, fn, 1 if j >= 4 else 0)


@pytest.fixture(scope="module")
def pristine(
    tmp_path_factory: pytest.TempPathFactory,
    write_fixture_databases: Callable[[Path], tuple[Database, Database]],
) -> tuple[Path, Database, Database]:
    root = tmp_path_factory.mktemp("pristine")
    mitdb, nstdb = write_fixture_databases(root)
    return root, mitdb, nstdb


@pytest.fixture
def data(
    pristine: tuple[Path, Database, Database], tmp_path: Path
) -> tuple[Path, Database, Database]:
    """A fresh copy of the fixture databases, which a test may change."""
    root, mitdb, nstdb = pristine
    copy = tmp_path / "data"
    shutil.copytree(root, copy)
    return copy, mitdb, nstdb


class CountingDetector:
    def __init__(self, detector: Detector) -> None:
        self.detector = detector
        self.calls: list[tuple[float, int]] = []

    def __call__(
        self, signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int
    ) -> npt.NDArray[np.int64]:
        self.calls.append((fs_hz, mains_hz))
        return self.detector(signal_mv, fs_hz, mains_hz)


class RecordingLoader:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, int]] = []

    def __call__(self, path: Path, channel: int) -> Record:
        self.calls.append((path, channel))
        return load_record(path, channel)


class ServingFetch:
    """Serves the files of the pristine fixture databases, and remembers the URLs."""

    def __init__(self, root: Path, databases: tuple[Database, ...]) -> None:
        self.urls: list[str] = []
        self.content: dict[str, bytes] = {}
        for database in databases:
            folder = root / database.slug
            for path in folder.rglob("*"):
                if path.is_file():
                    url = database_url(database) + path.relative_to(folder).as_posix()
                    self.content[url] = path.read_bytes()

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if url not in self.content:
            raise OSError(f"not served: {url}")
        return self.content[url]


# --- run_validation -------------------------------------------------------------------------


def test_defaults() -> None:
    assert run_validation.__kwdefaults__ == {
        "mitdb": MITDB,
        "nstdb": NSTDB,
        "settings": EvaluationSettings(),
        "detector": detect_beats,
        "loader": load_record,
        "fetch": fetch_https,
    }
    assert write_validation_report.__kwdefaults__ == run_validation.__kwdefaults__


def test_default_settings_are_the_public_constant() -> None:
    """One frozen instance, the settings of the evaluation, is the default of both functions."""
    assert DEFAULT_SETTINGS == EvaluationSettings(channel=0, mains_hz=60)
    for function in (run_validation, write_validation_report):
        assert inspect.signature(function).parameters["settings"].default is DEFAULT_SETTINGS
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_SETTINGS.mains_hz = 50  # type: ignore[misc]
    assert "_DEFAULT_SETTINGS" not in vars(run_module)


def test_offline_run(data: tuple[Path, Database, Database], fake_detector: Detector) -> None:
    root, mitdb, nstdb = data
    loader = RecordingLoader()
    results = run_validation(
        root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, loader=loader, fetch=None
    )
    assert isinstance(results, ValidationResults)
    assert results.software == software_identity()
    assert results.software.version == sinus_dsp.__version__
    assert results.settings == EvaluationSettings()
    assert results.subset is False
    assert results.mitdb.database == mitdb
    assert results.mitdb.records is None
    assert results.mitdb.files == (
        "100.atr",
        "100.dat",
        "100.hea",
        "118.atr",
        "118.dat",
        "118.hea",
        "119.atr",
        "119.dat",
        "119.hea",
        "207.atr",
        "207.dat",
        "207.hea",
        "RECORDS",
        "mitdbdir/notes.txt",
    )
    assert [record.record for record in results.records] == ["100", "118", "119", "207"]
    assert {record.record: record.counts for record in results.records} == MITDB_COUNTS
    record_207 = results.records[-1]
    assert (record_207.vf_episodes, record_207.vf_episodes_scored) == (2, 1)
    assert record_207.vf_samples_scored == 101
    assert (record_207.reference_excluded, record_207.detections_excluded) == (1, 2)
    # Two "!" outside the episodes: at 300 (before 5:00, not counted) and at 6500 (counted).
    assert record_207.flutter_waves_outside_vf == 1
    # MIT-BIH records in name order, then the noise stress records in their order.
    mitdb_calls = [(root / "mitdb" / name, 0) for name in ("100", "118", "119", "207")]
    nstdb_calls = [(root / "nstdb" / name, 0) for name in NOISE_STRESS_RECORDS]
    assert loader.calls == mitdb_calls + nstdb_calls

    noise = results.noise_stress
    assert noise is not None
    assert noise.nstdb.database == nstdb
    assert "old/readme.txt" in noise.nstdb.files
    assert [record.counts for record in noise.records] == [
        nstdb_counts(name) for name in NOISE_STRESS_RECORDS
    ]
    assert [entry.snr_db for entry in noise.by_snr] == [24, 18, 12, 6, 0, -6]
    assert [
        (entry.statistics.tp, entry.statistics.fn, entry.statistics.fp) for entry in noise.by_snr
    ] == [(4, 0, 0), (4, 0, 0), (4, 0, 0), (2, 2, 0), (2, 2, 2), (2, 2, 2)]
    assert (noise.clean.tp, noise.clean.fn, noise.clean.fp) == (5, 1, 0)
    assert noise.clean.n_records == 2


def test_software_identity_is_taken_once(
    data: tuple[Path, Database, Database],
    fake_detector: Detector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, mitdb, nstdb = data
    identity = SoftwareIdentity("7.7.7.dev0", "e" * 64, "3.99", (("numpy", "0.1"),))
    calls: list[None] = []

    def fixed_identity() -> SoftwareIdentity:
        calls.append(None)
        return identity

    monkeypatch.setattr(run_module, "software_identity", fixed_identity)
    results = run_validation(root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None)
    assert results.software is identity
    assert len(calls) == 1
    output = root.parent / "report.md"
    write_validation_report(
        output, root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None
    )
    assert len(calls) == 2
    lines = output.read_text(encoding="utf-8").split("\n")
    assert all(row in lines for row in software_rows(identity))


def test_no_software_identity_without_verified_data(
    data: tuple[Path, Database, Database],
    fake_detector: Detector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, mitdb, nstdb = data
    (root / "mitdb" / "100.dat").unlink()
    calls: list[None] = []
    monkeypatch.setattr(run_module, "software_identity", lambda: calls.append(None))
    with pytest.raises(DataVerificationError):
        run_validation(root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None)
    assert calls == []


def test_settings_reach_the_detector_and_the_loader(
    data: tuple[Path, Database, Database], fake_detector: Detector
) -> None:
    root, mitdb, nstdb = data
    detector = CountingDetector(fake_detector)
    loader = RecordingLoader()
    settings = EvaluationSettings(channel=1, mains_hz=50)
    results = run_validation(
        root,
        mitdb=mitdb,
        nstdb=nstdb,
        settings=settings,
        detector=detector,
        loader=loader,
        fetch=None,
    )
    assert results.settings is settings
    assert detector.calls == [(20.0, 50)] * 16
    assert {channel for _, channel in loader.calls} == {1}


@pytest.mark.parametrize(
    ("slug", "documentation"), [("mitdb", "mitdbdir/notes.txt"), ("nstdb", "old/readme.txt")]
)
def test_failed_verification_stops_before_any_evaluation(
    data: tuple[Path, Database, Database], fake_detector: Detector, slug: str, documentation: str
) -> None:
    root, mitdb, nstdb = data
    (root / slug / "RECORDS").write_bytes(b"altered\n")
    (root / slug / documentation).unlink()
    detector = CountingDetector(fake_detector)
    loader = RecordingLoader()
    with pytest.raises(DataVerificationError) as caught:
        run_validation(root, mitdb=mitdb, nstdb=nstdb, detector=detector, loader=loader, fetch=None)
    assert caught.value.database == f"{slug} 1.0.0"
    assert caught.value.mismatched == ("RECORDS",)
    assert caught.value.missing == (documentation,)
    assert detector.calls == []
    assert loader.calls == []


def test_absent_data_folder_is_not_verified_and_not_created(
    tmp_path: Path, fake_detector: Detector
) -> None:
    root = tmp_path / "absent"
    with pytest.raises(DataVerificationError) as caught:
        run_validation(root, detector=fake_detector, fetch=None)
    assert caught.value.database == "mitdb 1.0.0"
    assert caught.value.missing == (CHECKSUM_LIST_NAME,)
    assert not root.exists()


def test_download_then_run(
    pristine: tuple[Path, Database, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    source, mitdb, nstdb = pristine
    fetch = ServingFetch(source, (mitdb, nstdb))
    root = tmp_path / "downloaded"
    results = run_validation(root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=fetch)
    assert fetch.urls[0] == database_url(mitdb) + CHECKSUM_LIST_NAME
    assert sorted(fetch.urls) == sorted(fetch.content)
    offline = run_validation(root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None)
    assert results == offline
    # A second run with the network fetches nothing: every file is verified.
    again = ServingFetch(source, (mitdb, nstdb))
    run_validation(root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=again)
    assert again.urls == []


def test_download_that_fails_raises_before_any_evaluation(
    pristine: tuple[Path, Database, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    source, mitdb, nstdb = pristine
    fetch = ServingFetch(source, (mitdb, nstdb))
    del fetch.content[database_url(nstdb) + "119e_6.dat"]
    detector = CountingDetector(fake_detector)
    with pytest.raises(DataVerificationError) as caught:
        run_validation(tmp_path, mitdb=mitdb, nstdb=nstdb, detector=detector, fetch=fetch)
    assert caught.value.database == "nstdb 1.0.0"
    assert caught.value.missing == ("119e_6.dat",)
    assert detector.calls == []


def test_malformed_record_list_is_raised(
    tmp_path: Path,
    write_fixture_databases: Callable[[Path], tuple[Database, Database]],
    pin_database: Callable[..., Database],
    fake_detector: Detector,
) -> None:
    _, nstdb = write_fixture_databases(tmp_path)
    (tmp_path / "mitdb" / "RECORDS").write_bytes(b"100\n100\n")
    mitdb = pin_database(tmp_path / "mitdb", "Fixture Arrhythmia Database")
    with pytest.raises(MalformedFileError, match="record listed twice: 100"):
        run_validation(tmp_path, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None)


def test_clean_records_missing_from_the_arrhythmia_database(
    tmp_path: Path,
    write_fixture_databases: Callable[[Path], tuple[Database, Database]],
    pin_database: Callable[..., Database],
    fake_detector: Detector,
) -> None:
    _, nstdb = write_fixture_databases(tmp_path)
    mitdb = pin_database(tmp_path / "mitdb", "Fixture", records_file=["100", "118", "207"])
    loader = RecordingLoader()
    with pytest.raises(InvalidInputError, match="needs record 119"):
        run_validation(
            tmp_path, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, loader=loader, fetch=None
        )
    assert all(path.parent.name == "mitdb" for path, _ in loader.calls)


# --- write_validation_report ----------------------------------------------------------------


def test_report_is_written_in_utf8_with_line_feeds(
    data: tuple[Path, Database, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    root, mitdb, nstdb = data
    output = tmp_path / "docs" / "validation" / "report.md"
    write_validation_report(
        output, root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None
    )
    content = output.read_bytes()
    expected = render_full_report(
        run_validation(root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None)
    )
    assert content == expected.encode("utf-8")
    assert b"\r" not in content
    lines = content.decode("utf-8").split("\n")
    assert all(row in lines for row in software_rows(software_identity()))
    assert "≥ 99.50".encode() in content
    assert (
        describe_verification(
            run_validation(root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None).mitdb
        ).encode()
        in content
    )
    assert sorted(path.name for path in output.parent.iterdir()) == ["report.md"]


def test_two_runs_give_byte_identical_reports(
    data: tuple[Path, Database, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    root, mitdb, nstdb = data
    first, second = tmp_path / "first.md", tmp_path / "second.md"
    for output in (first, second):
        write_validation_report(
            output, root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None
        )
    assert first.read_bytes() == second.read_bytes()
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    )


def test_existing_report_is_replaced(
    data: tuple[Path, Database, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    root, mitdb, nstdb = data
    output = tmp_path / "report.md"
    output.write_bytes(b"old report\n")
    (tmp_path / "report.md.part~").write_bytes(b"stale temporary file")
    write_validation_report(
        output, root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None
    )
    assert output.read_bytes().startswith(b"# QRS detection: EC57 beat-by-beat evaluation\n")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["data", "report.md"]


def test_nothing_is_written_when_a_verification_fails(
    data: tuple[Path, Database, Database], tmp_path: Path, fake_detector: Detector
) -> None:
    root, mitdb, nstdb = data
    (root / "nstdb" / "118e24.dat").unlink()
    output = tmp_path / "new" / "report.md"
    with pytest.raises(
        DataVerificationError, match="nstdb 1.0.0 not verified: missing: 118e24.dat"
    ):
        write_validation_report(
            output, root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None
        )
    assert not output.parent.exists()
    existing = tmp_path / "existing.md"
    existing.write_bytes(b"old report\n")
    with pytest.raises(DataVerificationError):
        write_validation_report(
            existing, root, mitdb=mitdb, nstdb=nstdb, detector=fake_detector, fetch=None
        )
    assert existing.read_bytes() == b"old report\n"
    assert not (tmp_path / "existing.md.part~").exists()


def test_nothing_is_written_when_the_evaluation_fails(
    data: tuple[Path, Database, Database], tmp_path: Path
) -> None:
    root, mitdb, nstdb = data

    def failing(
        signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int
    ) -> npt.NDArray[np.int64]:
        return np.array([5, 3], dtype=np.int64)

    output = tmp_path / "report.md"
    with pytest.raises(InvalidInputError, match="strictly increasing"):
        write_validation_report(
            output, root, mitdb=mitdb, nstdb=nstdb, detector=failing, fetch=None
        )
    assert not output.exists()
