"""Unit tests of the command-line wrapper scripts/validate.py. No test uses the network.

The script is loaded as a module. Its ``write_validation_report`` is replaced either by a
recorder of the call, or by the real function bound to the fixture databases and a fake
detector.
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
from sinus_dsp.evaluation import run

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate.py"
REPO_ROOT = Path(__file__).resolve().parents[3]

Detector = Callable[[npt.NDArray[np.float64], float, int], npt.NDArray[np.int64]]


@pytest.fixture
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.write_validation_report is run.write_validation_report
    return module


class RecordingWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


class FixtureFetch:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return b""


def test_defaults(script: ModuleType) -> None:
    args = script.build_parser().parse_args([])
    assert args.data_dir == REPO_ROOT / "data"
    assert args.output == REPO_ROOT / "docs" / "validation" / "qrs-ec57-report.md"
    assert args.offline is False
    assert script.main.__kwdefaults__["fetch"] is fetch_https


def test_offline_verifies_only(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    writer = RecordingWriter()
    monkeypatch.setattr(script, "write_validation_report", writer)
    fetch = FixtureFetch()
    argv = ["--offline", "--data-dir", str(tmp_path / "d"), "--output", str(tmp_path / "r.md")]
    assert script.main(argv, fetch=fetch) == 0
    assert writer.calls == [((tmp_path / "r.md", tmp_path / "d"), {"fetch": None})]


def test_without_offline_the_fetch_is_announced(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    writer = RecordingWriter()
    monkeypatch.setattr(script, "write_validation_report", writer)
    fetch = FixtureFetch()
    assert script.main([], fetch=fetch) == 0
    ((args, kwargs),) = writer.calls
    assert args == (REPO_ROOT / "docs" / "validation" / "qrs-ec57-report.md", REPO_ROOT / "data")
    wrapped = kwargs["fetch"]
    assert wrapped is not None and wrapped is not fetch
    assert wrapped("https://example.org/x") == b""
    assert fetch.urls == ["https://example.org/x"]
    output = capsys.readouterr().out.splitlines()
    assert output == [
        f"report written: {REPO_ROOT / 'docs' / 'validation' / 'qrs-ec57-report.md'}",
        "fetching https://example.org/x",
    ]


@pytest.fixture
def fixture_run(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    write_fixture_databases: Callable[[Path], tuple[Database, Database]],
    fake_detector: Detector,
) -> tuple[Path, Database, Database]:
    """The script bound to the fixture databases, written under ``tmp_path / "data"``."""
    root = tmp_path / "data"
    mitdb, nstdb = write_fixture_databases(root)
    writer = functools.partial(
        run.write_validation_report, mitdb=mitdb, nstdb=nstdb, detector=fake_detector
    )
    monkeypatch.setattr(script, "write_validation_report", writer)
    return root, mitdb, nstdb


def test_report_written(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Database],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _, _ = fixture_run
    output = tmp_path / "out" / "report.md"
    argv = ["--offline", "--data-dir", str(root), "--output", str(output)]
    assert script.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.out == f"report written: {output}\n"
    assert captured.err == ""
    first = output.read_bytes()
    assert first.startswith(b"# QRS detection: EC57 beat-by-beat evaluation\n")
    assert script.main(argv) == 0
    assert output.read_bytes() == first


def test_report_written_after_downloading_nothing(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Database],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _, _ = fixture_run
    fetch = FixtureFetch()
    output = tmp_path / "report.md"
    assert script.main(["--data-dir", str(root), "--output", str(output)], fetch=fetch) == 0
    assert fetch.urls == []
    assert "fetching" not in capsys.readouterr().out
    assert output.is_file()


def test_not_verified_gives_status_1_and_no_report(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Database],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, mitdb, _ = fixture_run
    (root / "mitdb" / "100.dat").write_bytes(b"altered")
    output = tmp_path / "report.md"
    argv = ["--offline", "--data-dir", str(root), "--output", str(output)]
    assert script.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "no report written: mitdb 1.0.0 not verified: checksum mismatch: 100.dat\n"
    )
    assert not output.exists()


def test_failed_download_gives_status_1_and_no_report(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Database],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, mitdb, _ = fixture_run
    (root / "mitdb" / "100.dat").unlink()

    def failing(url: str) -> bytes:
        raise OSError(f"no network: {url}")

    output = tmp_path / "report.md"
    assert script.main(["--data-dir", str(root), "--output", str(output)], fetch=failing) == 1
    captured = capsys.readouterr()
    assert captured.out == f"fetching {database_url(mitdb)}100.dat\n"
    assert captured.err == "no report written: mitdb 1.0.0 not verified: missing: 100.dat\n"
    assert not output.exists()


def test_malformed_record_list_gives_status_1(
    script: ModuleType,
    fixture_run: tuple[Path, Database, Database],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pin_database: Callable[..., Database],
    fake_detector: Detector,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _, nstdb = fixture_run
    mitdb = pin_database(root / "mitdb", "Fixture", records_file=["100", "../100"])
    writer = functools.partial(
        run.write_validation_report, mitdb=mitdb, nstdb=nstdb, detector=fake_detector
    )
    monkeypatch.setattr(script, "write_validation_report", writer)
    output = tmp_path / "report.md"
    argv = ["--offline", "--data-dir", str(root), "--output", str(output)]
    assert script.main(argv) == 1
    assert "line 2: invalid record name: '../100'" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize(
    "argv", [["--unknown"], ["extra"], ["--output"], ["--data-dir"], ["--offline", "yes"]]
)
def test_usage_error_gives_status_2(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    writer = RecordingWriter()
    monkeypatch.setattr(script, "write_validation_report", writer)
    with pytest.raises(SystemExit) as caught:
        script.main(argv, fetch=FixtureFetch())
    assert caught.value.code == 2
    assert writer.calls == []
