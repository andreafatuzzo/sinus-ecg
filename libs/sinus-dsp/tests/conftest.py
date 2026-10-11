"""Skip hook and fixture for the tests that need the shared library of the computer build.

``needs_harness`` (architecture-m2.md 14.14): the tests are skipped when ``SINUS_DSP_HARNESS``
is unset or names no file; without the variable, the shared library of the ``release`` build
(``build/release/harness/``) is used if it exists. The hook sees every collected test, so it
also covers the tests of ``dsp/tests`` when pytest runs with the ``testpaths`` of
``dsp/pyproject.toml``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_VARIABLE = "SINUS_DSP_HARNESS"


def _default_harness() -> Path:
    suffix = {"win32": ".dll", "darwin": ".dylib"}.get(sys.platform, ".so")
    name = "sinus_dsp_harness" if suffix == ".dll" else "libsinus_dsp_harness"
    return LIBRARY_ROOT / "build" / "release" / "harness" / f"{name}{suffix}"


def harness_path() -> Path:
    """The shared library to test: ``SINUS_DSP_HARNESS``, else the release build's."""
    value = os.environ.get(ENVIRONMENT_VARIABLE)
    return Path(value) if value else _default_harness()


def harness_unavailable() -> str | None:
    """Why there is no shared library, or ``None``."""
    path = harness_path()
    if path.is_file():
        return None
    return (
        f"shared library sinus_dsp_harness not found at {path}: build libs/sinus-dsp "
        f"with the release preset or set {ENVIRONMENT_VARIABLE}"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    reason = harness_unavailable()
    if reason is None:
        return
    for item in items:
        if item.get_closest_marker("needs_harness"):
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def harness_library() -> Path:
    """Path of the shared library (tests marked ``needs_harness`` only)."""
    return harness_path()
