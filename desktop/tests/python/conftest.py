"""Shared fixtures of the WFDB cross-checks with the Python reference (architecture-m3.md 17.8).

The tests run with the environment of ``dsp`` (its ``wfdb`` and ``sinus_dsp``); they carry no
requirement marker: they are the developer's checks of the WFDB reader and writer.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

DESKTOP_TESTS = Path(__file__).resolve().parents[1]
FIXTURE_SCRIPT = DESKTOP_TESTS / "fixtures" / "make_wfdb_fixtures.py"


@pytest.fixture(scope="session")
def fixture_script() -> ModuleType:
    """The fixture script, loaded from its file (it is not a package module)."""
    spec = importlib.util.spec_from_file_location("make_wfdb_fixtures", FIXTURE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: its dataclasses look their module up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    """The committed fixtures."""
    return DESKTOP_TESTS / "fixtures" / "wfdb"
