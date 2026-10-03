"""Unit tests of the release check scripts/software_check.py, on fixture folders.

The script is loaded as a module, and its ``software_identity`` is replaced by a fixed
identity, except in the tests that check the defaults and the real identity.
"""

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from sinus_dsp.evaluation.report import software_rows
from sinus_dsp.version import SoftwareIdentity, software_identity

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "software_check.py"
REPO_ROOT = Path(__file__).resolve().parents[3]

IDENTITY = SoftwareIdentity(
    version="0.1.0.dev0",
    source_sha256="0123456789abcdef" * 4,
    python="3.11",
    runtime=(("numpy", "2.4.6"), ("scipy", "1.17.1"), ("wfdb", "4.3.1")),
)
SOFTWARE_LINE, RUNTIME_LINE = software_rows(IDENTITY)
SUCCESS = (
    "software check: {k} reports state sinus-dsp 0.1.0.dev0, source SHA-256 "
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
)


def report(*rows: str) -> str:
    """A report whose section 2 holds the given rows, from line 7 (after the table header)."""
    return "\n".join(
        [
            "# Report",
            "",
            "## Software, data and settings",
            "",
            "| Item | Value |",
            "|---|---|",
            *rows,
            "| Database | Fixture, version 1.0.0 |",
            "",
        ]
    )


CURRENT = report(SOFTWARE_LINE, RUNTIME_LINE)
README = "# Validation reports\n\nGenerated reports are written here.\n"


@pytest.fixture
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("software_check_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.software_identity is software_identity
    return module


@pytest.fixture
def identity_calls(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[None]:
    """Replace the identity of the running software by IDENTITY; record each call."""
    calls: list[None] = []

    def fixed() -> SoftwareIdentity:
        calls.append(None)
        return IDENTITY

    monkeypatch.setattr(script, "software_identity", fixed)
    return calls


@pytest.fixture
def folder(tmp_path: Path) -> Callable[..., Path]:
    def make(**files: str) -> Path:
        path = tmp_path / "validation"
        path.mkdir(exist_ok=True)
        for name, text in files.items():
            (path / name).write_bytes(text.encode("utf-8"))
        return path

    return make


def test_defaults(script: ModuleType) -> None:
    args = script.build_parser().parse_args([])
    assert args.folder == REPO_ROOT / "docs" / "validation"


def test_current_reports_pass(
    script: ModuleType,
    identity_calls: list[None],
    folder: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = folder(**{"a.md": CURRENT, "b.md": CURRENT, "README.md": README})
    assert script.main(["--folder", str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == SUCCESS.format(k=2)
    assert captured.err == ""
    assert len(identity_calls) == 1


def test_files_that_are_not_markdown_or_in_subfolders_are_not_checked(
    script: ModuleType,
    identity_calls: list[None],
    folder: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale = report("| Software | sinus-dsp 0.0.1 |", RUNTIME_LINE)
    path = folder(**{"report.md": CURRENT, "report.txt": stale, "report.md.part~": stale})
    (path / "old").mkdir()
    (path / "old" / "report.md").write_text(stale, encoding="utf-8")
    (path / "folder.md").mkdir()
    assert script.main(["--folder", str(path)]) == 0
    assert capsys.readouterr().out == SUCCESS.format(k=1)


def test_empty_folder_and_folder_without_reports(
    script: ModuleType,
    identity_calls: list[None],
    folder: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert script.main(["--folder", str(folder())]) == 0
    assert capsys.readouterr().out == SUCCESS.format(k=0)
    assert script.main(["--folder", str(folder(**{"README.md": README}))]) == 0
    assert capsys.readouterr().out == SUCCESS.format(k=0)


def test_stale_reports_fail_with_one_line_per_problem(
    script: ModuleType,
    identity_calls: list[None],
    folder: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    old_software = "| Software | sinus-dsp 0.0.1 |"
    old_runtime = "| Runtime | Python 3.11, numpy 2.4.5, scipy 1.17.1, wfdb 4.3.1 |"
    path = folder(
        **{
            "b.md": report(old_software, old_runtime),
            "_c.md": report(SOFTWARE_LINE),
            "B2.md": report(RUNTIME_LINE),
            "current.md": CURRENT,
            "README.md": README,
        }
    )
    assert script.main(["--folder", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    # Files in code-point order: "B2.md", "README.md", "_c.md", "b.md", "current.md".
    assert captured.err.splitlines() == [
        f"{path / 'B2.md'}: no Software row",
        f"{path / '_c.md'}: no Runtime row",
        f"{path / 'b.md'}: line 7: {old_software}; current: {SOFTWARE_LINE}",
        f"{path / 'b.md'}: line 8: {old_runtime}; current: {RUNTIME_LINE}",
    ]
    assert len(identity_calls) == 1


def test_a_stale_digest_alone_fails(
    script: ModuleType,
    identity_calls: list[None],
    folder: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = SOFTWARE_LINE.replace("0123456789abcdef0123", "ffffffffffffffffffff", 1)
    path = folder(**{"report.md": report(old, RUNTIME_LINE)})
    assert script.main(["--folder", str(path)]) == 1
    assert capsys.readouterr().err == (
        f"{path / 'report.md'}: line 7: {old}; current: {SOFTWARE_LINE}\n"
    )


def test_report_with_carriage_returns_is_counted(
    script: ModuleType,
    identity_calls: list[None],
    folder: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = folder(**{"report.md": CURRENT.replace("\n", "\r\n")})
    assert script.main(["--folder", str(path)]) == 0
    assert capsys.readouterr().out == SUCCESS.format(k=1)


def test_the_real_identity_is_used_by_default(
    script: ModuleType, folder: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    real = software_identity()
    path = folder(**{"report.md": report(*software_rows(real))})
    assert script.main(["--folder", str(path)]) == 0
    assert capsys.readouterr().out == (
        f"software check: 1 reports state sinus-dsp {real.version}, "
        f"source SHA-256 {real.source_sha256}\n"
    )
    (path / "other.md").write_text(CURRENT, encoding="utf-8")
    assert script.main(["--folder", str(path)]) == 1


@pytest.mark.parametrize("argv", [["--unknown"], ["extra"], ["--folder"]])
def test_usage_error_gives_status_2(
    script: ModuleType, identity_calls: list[None], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        script.main(argv)
    assert caught.value.code == 2
    assert identity_calls == []


@pytest.mark.parametrize("kind", ["absent", "file"])
def test_folder_that_is_not_a_folder_gives_status_2(
    script: ModuleType,
    identity_calls: list[None],
    tmp_path: Path,
    kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "report.md"
    if kind == "file":
        path.write_text(CURRENT, encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        script.main(["--folder", str(path)])
    assert caught.value.code == 2
    assert f"not a folder: {path}" in capsys.readouterr().err
    assert identity_calls == []


def test_run_as_a_command(folder: Callable[..., Path]) -> None:
    real = software_identity()
    path = folder(**{"report.md": report(*software_rows(real))})
    command = [sys.executable, str(SCRIPT), "--folder", str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert (completed.returncode, completed.stderr) == (0, "")
    assert completed.stdout.startswith("software check: 1 reports state sinus-dsp ")
    (path / "stale.md").write_text(CURRENT, encoding="utf-8")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "stale.md: line 7: " in completed.stderr
