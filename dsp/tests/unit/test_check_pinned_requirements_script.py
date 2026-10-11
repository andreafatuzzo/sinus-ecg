"""Unit tests of scripts/check_pinned_requirements.py, on fixture files (OP-077)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_pinned_requirements.py"

LOCK = """
version = 1

[[package]]
name = "pytest"
version = "9.1.1"

[[package]]
name = "Typing_Extensions"
version = "4.0.0"

[[package]]
name = "typing-extensions"
version = "4.1.0"

[[package]]
name = "pluggy"
version = "1.6.0"
"""

REQUIREMENTS = """# comment
pluggy==1.6.0 \\
    --hash=sha256:aa \\
    --hash=sha256:bb
pytest==9.1.1 \\
    --hash=sha256:cc
colorama==0.4.6 ; sys_platform == 'win32' \\
    --hash=sha256:dd
"""


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_pinned_requirements", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_pins_reads_names_versions_and_ignores_markers_and_hashes(script: ModuleType) -> None:
    assert script.parse_pins(REQUIREMENTS) == {
        "pluggy": "1.6.0",
        "pytest": "9.1.1",
        "colorama": "0.4.6",
    }


def test_locked_versions_normalises_names_and_collects_forks(script: ModuleType) -> None:
    locked = script.locked_versions(LOCK)
    assert locked["typing-extensions"] == {"4.0.0", "4.1.0"}
    assert locked["pytest"] == {"9.1.1"}


def test_matching_pins_have_no_problem(script: ModuleType) -> None:
    pins = {"pytest": "9.1.1", "pluggy": "1.6.0"}
    assert script.find_mismatches(pins, script.locked_versions(LOCK)) == []


def test_a_different_pytest_version_is_reported(script: ModuleType) -> None:
    problems = script.find_mismatches({"pytest": "9.0.0"}, script.locked_versions(LOCK))
    assert problems == ["pytest==9.0.0: the lock has 9.1.1"]


def test_a_package_missing_from_the_lock_is_reported(script: ModuleType) -> None:
    pins = {"pytest": "9.1.1", "colorama": "0.4.6"}
    problems = script.find_mismatches(pins, script.locked_versions(LOCK))
    assert problems == ["colorama==0.4.6: the package is not in the lock"]


def test_a_file_without_pytest_is_reported(script: ModuleType) -> None:
    problems = script.find_mismatches({"pluggy": "1.6.0"}, script.locked_versions(LOCK))
    assert problems == ["the requirements file has no pin for pytest"]


def test_main_exit_status(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(LOCK, encoding="utf-8")
    good = tmp_path / "good.txt"
    good.write_text("pytest==9.1.1 \\\n    --hash=sha256:aa\n", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("pytest==9.0.0 \\\n    --hash=sha256:aa\n", encoding="utf-8")
    assert script.main(["--requirements", str(good), "--lock", str(lock)]) == 0
    assert script.main(["--requirements", str(bad), "--lock", str(lock)]) == 1
    assert "pytest==9.0.0" in capsys.readouterr().err
    missing = tmp_path / "missing.txt"
    assert script.main(["--requirements", str(missing), "--lock", str(lock)]) == 2
    assert script.main(["--bogus"]) == 2


def test_the_committed_file_matches_the_committed_lock(script: ModuleType) -> None:
    assert script.main([]) == 0
