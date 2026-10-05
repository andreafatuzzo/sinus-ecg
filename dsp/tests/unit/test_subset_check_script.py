"""Unit tests of the command-line wrapper scripts/subset_check.py. No test uses the network.

The script is loaded as a module. Its ``check_subset_report`` is replaced either by a
recorder of the call, or by the real function bound to the fixture subset database and a
fake detector.
"""

import functools
import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp.data.physionet import Database, database_url, fetch_https
from sinus_dsp.errors import SubsetReportMismatchError
from sinus_dsp.evaluation import subset
from sinus_dsp.evaluation.report import render_subset_report

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "subset_check.py"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORED = REPO_ROOT / "docs" / "validation" / "qrs-ec57-subset-report.md"

Detector = Callable[[npt.NDArray[np.float64], float, int], npt.NDArray[np.int64]]


@pytest.fixture
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("subset_check_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check_subset_report is subset.check_subset_report
    return module


class RecordingCheck:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.error = error

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error


class FixtureFetch:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return b""


def test_defaults(script: ModuleType) -> None:
    args = script.build_parser().parse_args([])
    assert args.data_dir == REPO_ROOT / "data"
    assert args.stored == DEFAULT_STORED
    assert args.write_regenerated is None
    assert args.update is False
    assert args.offline is False
    assert script.main.__kwdefaults__["fetch"] is fetch_https


def test_offline_verifies_only(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    check = RecordingCheck()
    monkeypatch.setattr(script, "check_subset_report", check)
    argv = ["--offline", "--data-dir", str(tmp_path / "d"), "--stored", str(tmp_path / "s.md")]
    assert script.main(argv, fetch=FixtureFetch()) == 0
    assert check.calls == [
        ((tmp_path / "s.md", tmp_path / "d"), {"regenerated_path": None, "fetch": None})
    ]


def test_without_offline_the_fetch_is_announced(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    check = RecordingCheck()
    monkeypatch.setattr(script, "check_subset_report", check)
    fetch = FixtureFetch()
    assert script.main([], fetch=fetch) == 0
    ((args, kwargs),) = check.calls
    assert args == (DEFAULT_STORED, REPO_ROOT / "data")
    assert kwargs["regenerated_path"] is None
    wrapped = kwargs["fetch"]
    assert wrapped is not None and wrapped is not fetch
    assert wrapped("https://example.org/x") == b""
    assert fetch.urls == ["https://example.org/x"]
    assert capsys.readouterr().out.splitlines() == [
        f"subset report equals the stored report: {DEFAULT_STORED}",
        "fetching https://example.org/x",
    ]


def test_update_regenerates_into_the_stored_report(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    check = RecordingCheck()
    monkeypatch.setattr(script, "check_subset_report", check)
    stored = tmp_path / "s.md"
    assert script.main(["--update", "--offline", "--stored", str(stored)]) == 0
    ((args, kwargs),) = check.calls
    assert args[0] == stored
    assert kwargs["regenerated_path"] == stored


@pytest.fixture
def fixture_run(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    write_subset_database: Callable[[Path], Database],
    fake_detector: Detector,
) -> tuple[Path, Database, Path]:
    """The script bound to the fixture subset database, and the path of a stored report."""
    root = tmp_path / "data"
    database = write_subset_database(root)
    check = functools.partial(subset.check_subset_report, database=database, detector=fake_detector)
    monkeypatch.setattr(script, "check_subset_report", check)
    return root, database, tmp_path / "docs" / "stored.md"


def expected_report(root: Path, database: Database, detector: Detector) -> bytes:
    results = subset.run_subset(root, database=database, detector=detector, fetch=None)
    return render_subset_report(results).encode("utf-8")


def test_update_then_check(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    fake_detector: Detector,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, database, stored = fixture_run
    argv = ["--offline", "--data-dir", str(root), "--stored", str(stored)]
    assert script.main([*argv, "--update"]) == 0
    assert capsys.readouterr().out == f"stored report updated: {stored}\n"
    assert stored.read_bytes() == expected_report(root, database, fake_detector)
    assert script.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.out == f"subset report equals the stored report: {stored}\n"
    assert captured.err == ""


def test_update_replaces_a_stored_report_that_differs(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    fake_detector: Detector,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, database, stored = fixture_run
    stored.parent.mkdir()
    stored.write_bytes(b"\xff an old report that is not UTF-8\n")
    regenerated = tmp_path / "out" / "regenerated.md"
    argv = ["--offline", "--data-dir", str(root), "--stored", str(stored)]
    assert script.main([*argv, "--update", "--write-regenerated", str(regenerated)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"regenerated report written: {regenerated}",
        f"stored report updated: {stored}",
    ]
    expected = expected_report(root, database, fake_detector)
    assert stored.read_bytes() == expected
    assert regenerated.read_bytes() == expected


@pytest.mark.parametrize("spelling", ["same", "through-parent"])
def test_update_may_write_the_regenerated_report_over_the_stored_report(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    fake_detector: Detector,
    capsys: pytest.CaptureFixture[str],
    spelling: str,
) -> None:
    """Architecture §8.11 (v0.2.10): the bytes are read, then written; no ``SameFileError``."""
    root, database, stored = fixture_run
    stored.parent.mkdir()
    stored.write_bytes(b"an old report\n")
    regenerated = stored if spelling == "same" else stored.parent / ".." / "docs" / stored.name
    argv = ["--offline", "--data-dir", str(root), "--stored", str(stored), "--update"]
    assert script.main([*argv, "--write-regenerated", str(regenerated)]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        f"regenerated report written: {regenerated}",
        f"stored report updated: {stored}",
    ]
    assert captured.err == ""
    assert stored.read_bytes() == expected_report(root, database, fake_detector)
    assert sorted(path.name for path in stored.parent.iterdir()) == [stored.name]


def test_update_writes_the_regenerated_copy_atomically(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    fake_detector: Detector,
    tmp_path: Path,
) -> None:
    root, database, stored = fixture_run
    regenerated = tmp_path / "new" / "folder" / "regenerated.md"
    regenerated.parent.mkdir(parents=True)
    (regenerated.parent / "regenerated.md.part~").write_bytes(b"stale temporary file\n")
    argv = ["--offline", "--data-dir", str(root), "--stored", str(stored), "--update"]
    assert script.main([*argv, "--write-regenerated", str(regenerated)]) == 0
    expected = expected_report(root, database, fake_detector)
    assert regenerated.read_bytes() == expected
    assert sorted(path.name for path in regenerated.parent.iterdir()) == ["regenerated.md"]


def test_mismatch_gives_status_1_with_the_differences(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    fake_detector: Detector,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, database, stored = fixture_run
    expected = expected_report(root, database, fake_detector)
    stored.parent.mkdir()
    lines = expected.decode("utf-8").split("\n")
    row = next(line for line in lines if line.startswith("| 108 | "))
    changed = row.replace("| 108 | MLII | 1 |", "| 108 | MLII | 2 |")
    stored.write_bytes("\n".join(changed if line == row else line for line in lines).encode())
    regenerated = tmp_path / "regenerated.md"
    argv = ["--offline", "--data-dir", str(root), "--stored", str(stored)]
    assert script.main([*argv, "--write-regenerated", str(regenerated)]) == 1
    captured = capsys.readouterr()
    assert captured.out == f"regenerated report written: {regenerated}\n"
    assert captured.err.splitlines() == [
        f"subset report differs from the stored report {stored}:",
        f"  line {lines.index(row) + 1}: stored {changed}, regenerated {row}",
        script.UPDATE_HINT,
    ]
    assert regenerated.read_bytes() == expected
    assert b"| 108 | MLII | 2 |" in stored.read_bytes()


def test_absent_stored_report_gives_status_1(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _, stored = fixture_run
    assert script.main(["--offline", "--data-dir", str(root), "--stored", str(stored)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines()[:2] == [
        f"subset report differs from the stored report {stored}:",
        f"  no stored report: {stored}",
    ]


def test_stored_report_that_is_not_utf8_gives_status_1(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _, stored = fixture_run
    stored.parent.mkdir()
    stored.write_bytes(b"\xff\n")
    assert script.main(["--offline", "--data-dir", str(root), "--stored", str(stored)]) == 1
    assert capsys.readouterr().err == f"subset check failed: {stored}: not UTF-8 text\n"


@pytest.mark.parametrize("update", [False, True])
def test_not_verified_gives_status_1_and_writes_nothing(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    update: bool,
) -> None:
    root, _, stored = fixture_run
    (root / "mitdb" / "203.dat").write_bytes(b"altered")
    regenerated = tmp_path / "regenerated.md"
    argv = ["--offline", "--data-dir", str(root), "--stored", str(stored)]
    argv += ["--write-regenerated", str(regenerated)] + (["--update"] if update else [])
    assert script.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    prefix = "no report written" if update else "subset check failed"
    assert captured.err == f"{prefix}: mitdb 1.0.0 not verified: checksum mismatch: 203.dat\n"
    assert not stored.exists()
    assert not regenerated.exists()


def test_failed_download_gives_status_1(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, database, stored = fixture_run
    (root / "mitdb" / "100.hea").unlink()

    def failing(url: str) -> bytes:
        raise OSError(f"no network: {url}")

    assert script.main(["--data-dir", str(root), "--stored", str(stored)], fetch=failing) == 1
    captured = capsys.readouterr()
    assert captured.out == f"fetching {database_url(database)}100.hea\n"
    assert captured.err == "subset check failed: mitdb 1.0.0 not verified: missing: 100.hea\n"


def test_mismatch_error_raised_by_the_check(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    error = SubsetReportMismatchError(["line 1: stored a, regenerated b", "… and 3 more"])
    monkeypatch.setattr(script, "check_subset_report", RecordingCheck(error))
    assert script.main(["--offline", "--stored", "s.md"]) == 1
    assert capsys.readouterr().err.splitlines() == [
        "subset report differs from the stored report s.md:",
        "  line 1: stored a, regenerated b",
        "  … and 3 more",
        script.UPDATE_HINT,
    ]


@pytest.mark.parametrize(
    "argv",
    [
        ["--unknown"],
        ["extra"],
        ["--stored"],
        ["--data-dir"],
        ["--write-regenerated"],
        ["--update", "yes"],
        ["--offline", "yes"],
    ],
)
def test_usage_error_gives_status_2(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    check = RecordingCheck()
    monkeypatch.setattr(script, "check_subset_report", check)
    with pytest.raises(SystemExit) as caught:
        script.main(argv, fetch=FixtureFetch())
    assert caught.value.code == 2
    assert check.calls == []
