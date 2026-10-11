"""Check that a requirements file with hashes names the versions of ``dsp/uv.lock``.

The CI job ``libs-esp32s3`` installs pytest, for the system test of the emulator run, from
``libs/sinus-dsp/tests/system/esp32s3_equivalence/requirements-pytest.txt`` with
``pip install --require-hashes``. The file is derived from ``uv.lock``; this check fails when a
package of the file has a version that the lock does not contain, so the two cannot drift apart
(OP-077).

Usage (from ``dsp/``):
  uv run python scripts/check_pinned_requirements.py
  uv run python scripts/check_pinned_requirements.py --requirements <file> --lock <uv.lock>

Exit status: 0 when every package of the file is pinned to a version of the lock, and pytest is
among them; 1 when a package differs, is missing from the lock or the file has no ``pytest``
pin; 2 on a usage error or an unreadable file.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REQUIREMENTS = (
    REPO_ROOT / "libs/sinus-dsp/tests/system/esp32s3_equivalence/requirements-pytest.txt"
)
DEFAULT_LOCK = REPO_ROOT / "dsp/uv.lock"

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")


def _normal(name: str) -> str:
    """Name normalised as in PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(text: str) -> dict[str, str]:
    """Return ``{normalised name: version}`` of the ``name==version`` lines of a file."""
    pins: dict[str, str] = {}
    for line in text.splitlines():
        match = _PIN.match(line)
        if match is not None:
            pins[_normal(match.group(1))] = match.group(2)
    return pins


def locked_versions(lock_text: str) -> dict[str, set[str]]:
    """Return ``{normalised name: versions}`` of the packages of a ``uv.lock`` text."""
    versions: dict[str, set[str]] = {}
    for package in tomllib.loads(lock_text).get("package", []):
        version = package.get("version")
        if isinstance(version, str):
            versions.setdefault(_normal(str(package["name"])), set()).add(version)
    return versions


def find_mismatches(pins: dict[str, str], locked: dict[str, set[str]]) -> list[str]:
    """Return one message for each pin that the lock does not confirm, and for a missing pytest."""
    problems = []
    if "pytest" not in pins:
        problems.append("the requirements file has no pin for pytest")
    for name, version in sorted(pins.items()):
        if name not in locked:
            problems.append(f"{name}=={version}: the package is not in the lock")
        elif version not in locked[name]:
            known = ", ".join(sorted(locked[name]))
            problems.append(f"{name}=={version}: the lock has {known}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_OK if exit_.code == 0 else EXIT_USAGE
    try:
        pins = parse_pins(args.requirements.read_text(encoding="utf-8"))
        locked = locked_versions(args.lock.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"cannot read the inputs: {error}", file=sys.stderr)
        return EXIT_USAGE
    problems = find_mismatches(pins, locked)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return EXIT_MISMATCH
    print(f"pinned requirements: {len(pins)} packages match {args.lock.name}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
