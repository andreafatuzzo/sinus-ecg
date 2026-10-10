"""Developer's unit tests of verification/emulator_log.py (log reader of the job libs-esp32s3).

They run the script on constructed logs. No requirement marker: the verification of the CI job is
the test engineer's.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "verification" / "emulator_log.py"

REPORT = (
    "# Equivalence of the real-time library with the reference\n"
    "\n"
    "| Item | Value |\n"
    "|---|---|\n"
    "| Outcome | {outcome} |\n"
    "\n"
    "## Results per file\n"
)

BOOT = "ESP-ROM:esp32s3-20210327\r\nBuild:Mar 27 2021\r\nI (123) cpu_start: Starting scheduler.\r\n"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("emulator_log_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


emulator_log = _load()


def _log(outcome: str = "pass", end: str | None = "pass", eol: str = "\r\n") -> str:
    block = REPORT.format(outcome=outcome).replace("\n", eol)
    text = BOOT + "SINUS-EQUIVALENCE-BEGIN" + eol + block
    if end is not None:
        text += f"SINUS-EQUIVALENCE-END {end}" + eol
    return text + "I (999) main_task: Returned from app_main()" + eol


def test_a_passing_log_passes_and_yields_the_block() -> None:
    analysis = emulator_log.analyse(_log())
    assert analysis.passed
    assert analysis.message == ""
    assert analysis.results is not None
    assert analysis.results.startswith("# Equivalence of the real-time library")
    assert "| Outcome | pass |" in analysis.results
    assert "\r" not in analysis.results
    assert "SINUS-EQUIVALENCE" not in analysis.results


@pytest.mark.parametrize("eol", ["\n", "\r\n", "\r"])
def test_line_endings_do_not_matter(eol: str) -> None:
    assert emulator_log.analyse(_log(eol=eol)).passed


def test_colour_codes_around_the_markers_are_ignored() -> None:
    text = _log().replace("SINUS-EQUIVALENCE-END pass", "\x1b[0mSINUS-EQUIVALENCE-END pass\x1b[0m")
    assert emulator_log.analyse(text).passed


def test_a_failing_end_line_fails_and_keeps_the_block() -> None:
    analysis = emulator_log.analyse(_log(outcome="fail", end="fail"))
    assert not analysis.passed
    assert "'fail'" in analysis.message
    assert analysis.results is not None
    assert "| Outcome | fail |" in analysis.results


@pytest.mark.parametrize("word", ["", "PASS", "passed", "pass2"])
def test_only_the_word_pass_passes(word: str) -> None:
    assert not emulator_log.analyse(_log(end=word)).passed


def test_a_log_without_an_end_line_fails() -> None:
    analysis = emulator_log.analyse(_log(end=None))
    assert not analysis.passed
    assert "no 'SINUS-EQUIVALENCE-END' line" in analysis.message
    assert analysis.results is None


def test_a_crash_before_the_markers_fails() -> None:
    analysis = emulator_log.analyse(BOOT + "Guru Meditation Error: Core 0 panic'ed\r\n")
    assert not analysis.passed
    assert analysis.results is None


def test_an_empty_log_fails() -> None:
    assert not emulator_log.analyse("").passed


def test_two_pass_lines_fail() -> None:
    analysis = emulator_log.analyse(_log() + "SINUS-EQUIVALENCE-END pass\r\n")
    assert not analysis.passed
    assert "2 'SINUS-EQUIVALENCE-END' lines" in analysis.message


def test_a_pass_line_and_a_fail_line_fail() -> None:
    assert not emulator_log.analyse(_log() + "SINUS-EQUIVALENCE-END fail\r\n").passed
    assert not emulator_log.analyse("SINUS-EQUIVALENCE-END fail\r\n" + _log()).passed


def test_a_pass_line_without_begin_fails() -> None:
    text = _log().replace("SINUS-EQUIVALENCE-BEGIN", "")
    analysis = emulator_log.analyse(text)
    assert not analysis.passed
    assert "BEGIN" in analysis.message


def test_two_begin_lines_fail() -> None:
    text = _log().replace("# Equivalence", "SINUS-EQUIVALENCE-BEGIN\r\n# Equivalence", 1)
    assert not emulator_log.analyse(text).passed


def test_a_pass_line_over_results_that_say_fail_fails() -> None:
    analysis = emulator_log.analyse(_log(outcome="fail", end="pass"))
    assert not analysis.passed
    assert "Outcome" in analysis.message


def test_the_marker_text_inside_a_longer_line_is_not_an_end_line() -> None:
    text = _log(end=None) + "see SINUS-EQUIVALENCE-END pass above\r\n"
    assert not emulator_log.analyse(text).passed


def _run(log: Path, results: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(log), "--results", str(results)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_exits_0_and_writes_the_results(tmp_path: Path) -> None:
    log = tmp_path / "qemu.log"
    log.write_text(_log(), encoding="utf-8", newline="")
    results = tmp_path / "equivalence-esp32s3.md"
    done = _run(log, results)
    assert done.returncode == 0, done.stderr
    assert "| Outcome | pass |" in results.read_text(encoding="utf-8")


def test_the_script_exits_1_with_a_message_when_the_check_fails(tmp_path: Path) -> None:
    log = tmp_path / "qemu.log"
    log.write_text(_log(end=None), encoding="utf-8", newline="")
    done = _run(log, tmp_path / "r.md")
    assert done.returncode == 1
    assert "FAIL" in done.stderr
    assert not (tmp_path / "r.md").exists()


def test_the_script_exits_2_on_a_usage_error_or_a_missing_log(tmp_path: Path) -> None:
    assert (
        subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, check=False).returncode
        == 2
    )
    assert _run(tmp_path / "missing.log", tmp_path / "r.md").returncode == 2


def test_binary_noise_in_the_log_does_not_stop_the_reading(tmp_path: Path) -> None:
    log = tmp_path / "qemu.log"
    log.write_bytes(b"\xff\xfe\x00junk\r\n" + _log().encode("utf-8"))
    assert _run(log, tmp_path / "r.md").returncode == 0
