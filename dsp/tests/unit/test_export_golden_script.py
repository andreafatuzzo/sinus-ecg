"""Unit tests of the command-line wrapper scripts/export_golden.py (architecture §8.12).

The script is loaded as a module. Its ``export_golden_vectors`` is replaced by a recorder of
the call, except in the test that runs the real export without a database.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from sinus_dsp import golden
from sinus_dsp.errors import InvalidInputError, MalformedFileError, NonFiniteOutputError
from sinus_dsp.golden import ExportSummary
from sinus_dsp.synthetic import synthetic_event_set, synthetic_set

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_golden.py"
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_golden_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.export_golden_vectors is golden.export_golden_vectors
    return module


class RecordingExport:
    def __init__(self, summary: ExportSummary | None = None, error: Exception | None = None):
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.summary = summary or ExportSummary(written=(), skipped=(), skip_reason=None)
        self.error = error

    def __call__(self, *args: Any, **kwargs: Any) -> ExportSummary:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.summary


def test_defaults(script: ModuleType) -> None:
    args = script.build_parser().parse_args([])
    assert args.output == REPO_ROOT / "data" / "golden"
    assert args.data_dir == REPO_ROOT / "data"


def test_the_export_is_called_with_the_folders(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    export = RecordingExport()
    monkeypatch.setattr(script, "export_golden_vectors", export)
    argv = ["--output", str(tmp_path / "out"), "--data-dir", str(tmp_path / "data")]
    assert script.main(argv) == 0
    assert export.calls == [((tmp_path / "out",), {"data_root": tmp_path / "data"})]


def test_default_call(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    export = RecordingExport()
    monkeypatch.setattr(script, "export_golden_vectors", export)
    assert script.main([]) == 0
    assert export.calls == [((REPO_ROOT / "data" / "golden",), {"data_root": REPO_ROOT / "data"})]


def test_written_files_are_printed_in_order(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = ExportSummary(written=("b.golden.txt", "a.golden.txt"), skipped=(), skip_reason=None)
    monkeypatch.setattr(script, "export_golden_vectors", RecordingExport(summary))
    assert script.main(["--output", "out"]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        f"written: {Path('out') / 'b.golden.txt'}",
        f"written: {Path('out') / 'a.golden.txt'}",
    ]
    assert captured.err == ""


def test_skipped_segments_are_printed_with_the_reason(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = ExportSummary(
        written=("s.golden.txt",),
        skipped=("mitdb-100-first60s", "mitdb-105-first60s"),
        skip_reason="mitdb 1.0.0 not verified: missing: SHA256SUMS.txt",
    )
    monkeypatch.setattr(script, "export_golden_vectors", RecordingExport(summary))
    assert script.main(["--output", "out"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"written: {Path('out') / 's.golden.txt'}",
        "skipped: mitdb-100-first60s, mitdb-105-first60s",
        "reason: mitdb 1.0.0 not verified: missing: SHA256SUMS.txt",
    ]


@pytest.mark.parametrize(
    "error",
    [
        InvalidInputError("record 105 is shorter than its 60 s segment"),
        MalformedFileError("data/mitdb/SHA256SUMS.txt", 3, "not a checksum entry"),
        NonFiniteOutputError("mitdb-108-first60s"),
    ],
)
def test_errors_give_status_1_with_the_message(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    monkeypatch.setattr(script, "export_golden_vectors", RecordingExport(error=error))
    assert script.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"export failed: {error}\n"


def test_other_errors_propagate(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    error = PermissionError("cannot write")
    monkeypatch.setattr(script, "export_golden_vectors", RecordingExport(error=error))
    with pytest.raises(PermissionError):
        script.main([])


@pytest.mark.parametrize(
    "argv", [["--unknown"], ["extra"], ["--output"], ["--data-dir"], ["--offline"]]
)
def test_usage_error_gives_status_2(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    export = RecordingExport()
    monkeypatch.setattr(script, "export_golden_vectors", export)
    with pytest.raises(SystemExit) as caught:
        script.main(argv)
    assert caught.value.code == 2
    assert export.calls == []


def test_real_export_without_the_database(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "golden"
    argv = ["--output", str(output), "--data-dir", str(tmp_path / "no-data")]
    assert script.main(argv) == 0
    names = [f"{ecg.input_id}.golden.txt" for ecg in (*synthetic_set(), *synthetic_event_set())]
    assert capsys.readouterr().out.splitlines() == [
        *(f"written: {output / name}" for name in names),
        "skipped: mitdb-100-first60s, mitdb-105-first60s, mitdb-108-first60s, "
        "mitdb-119-first60s, mitdb-203-first60s, mitdb-207-first60s",
        "reason: mitdb 1.0.0 not verified: missing: SHA256SUMS.txt",
    ]
    assert sorted(path.name for path in output.iterdir()) == sorted(names)
