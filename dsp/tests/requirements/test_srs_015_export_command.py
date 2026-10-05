"""Requirement tests of SRS-015: the command that writes the golden vectors (RC-012).

SRS-015 (v0.7.1): "A single command shall write one golden-vector file for each input" of
the synthetic set and of the first 60 s of each record of the subset of SRS-016, where the
files of these records are available and verified. Two runs on the same computer and inputs,
with the same software version and source code and the same third-party versions, give
byte-identical files; each file states the software version with an identifier of the source
code that produced it. Verification: "The command is run twice on the synthetic set and on a
fixture record".

The command is `scripts/export_golden.py [--output DIR] [--data-dir PATH]` (architecture,
sections 7.5 and 8.12): defaults `data/golden/` and `data/` at the repository root; it prints
`written: <path>` for each file in the order written, then `skipped: <id>, ...` and
`reason: <reason>` if the record segments were skipped; exit status 0 when the export
completes, whether the segments were written or skipped.

Each run is a separate Python process without network (`write_command_driver`), which may set
the pinned digest of the checksum list of the MIT-BIH Arrhythmia Database to that of a fixture
list, in that process only, so that the command exports the record segments of a fixture
database. The expected files are those of `export_golden_vectors` run in the test process,
whose content is verified in `test_srs_015_golden_vector_files.py`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from sinus_dsp.data.physionet import Database
from sinus_dsp.golden import export_golden_vectors

pytestmark = pytest.mark.usefixtures("forbid_network")

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
EXPORT_SCRIPT = SCRIPTS_DIR / "export_golden.py"
SUFFIX = ".golden.txt"
SUBSET = ("100", "105", "108", "119", "203", "207")
SYNTHETIC_IDS = tuple(
    f"syn-fs{fs}-hr{hr:03d}-{variant}"
    for fs in (250, 360)
    for hr in (40, 75, 180)
    for variant in ("clean", "bw-mains50", "bw-mains60")
)
SEGMENT_IDS = tuple(f"mitdb-{name}-first60s" for name in SUBSET)


def _database(pin: str) -> Database:
    return Database(
        slug="mitdb", version="1.0.0", title="MIT-BIH Arrhythmia Database", checksum_list_sha256=pin
    )


def _files(folder: Path) -> dict[str, bytes]:
    entries = sorted(folder.iterdir())
    assert all(entry.is_file() for entry in entries), entries
    return {entry.name: entry.read_bytes() for entry in entries}


def _run(
    driver: Path,
    pin: str,
    arguments: Sequence[str],
    *,
    cwd: Path,
    script: Path = EXPORT_SCRIPT,
    package_root: Path | None = None,
    hash_seed: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the export command in a separate process without network; ``pin`` replaces the
    pinned digest of the MIT-BIH Arrhythmia checksum list in that process (``-`` keeps the
    real one). With ``package_root``, the process imports the package found there."""
    environment = dict(os.environ)
    if package_root is not None:
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(package_root), *([existing] if existing else [])]
        )
    if hash_seed is not None:
        environment["PYTHONHASHSEED"] = hash_seed
    return subprocess.run(
        [sys.executable, str(driver), pin, "-", str(script), *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )


@pytest.fixture(scope="module")
def synthetic_reference(
    tmp_path_factory: pytest.TempPathFactory, network_forbidden: Callable[[], Any]
) -> dict[str, bytes]:
    """The 18 synthetic files written by `export_golden_vectors` in the test process (data
    folder without the database)."""
    root = tmp_path_factory.mktemp("srs015-synthetic-reference")
    (root / "data").mkdir()
    with network_forbidden():
        export_golden_vectors(root / "golden", data_root=root / "data")
    return _files(root / "golden")


@pytest.fixture(scope="module")
def fixture_reference(
    subset_ecg_fixture: Any,
    tmp_path_factory: pytest.TempPathFactory,
    network_forbidden: Callable[[], Any],
) -> dict[str, bytes]:
    """The 24 files written by `export_golden_vectors` in the test process from the synthetic
    ECG subset fixture."""
    root = tmp_path_factory.mktemp("srs015-fixture-reference")
    with network_forbidden():
        export_golden_vectors(
            root / "golden",
            data_root=subset_ecg_fixture.data_root,
            database=_database(subset_ecg_fixture.checksum_list_sha256),
        )
    return _files(root / "golden")


@pytest.mark.requirement("SRS-015")
def test_command_without_the_database_writes_the_synthetic_files(
    tmp_path: Path,
    synthetic_reference: dict[str, bytes],
    write_command_driver: Callable[[Path], Path],
) -> None:
    """The command with the real pinned checksum list and no database: synthetic files only.

    Input: `export_golden.py --output <folder> --data-dir <empty folder>`, in a separate
    process without network, with the real pinned checksum list.
    Expected: exit status 0, no traceback; the folder holds exactly the 18 synthetic files,
    byte-identical to those of `export_golden_vectors` in the test process; standard output
    gives `written: <folder>/<file>` for the 18 files in the order of the synthetic set,
    then `skipped: ` with the six record-segment identifiers in code-point order of the
    records, and a `reason: ` line that names `SHA256SUMS.txt`.
    """
    output, data = tmp_path / "golden", tmp_path / "empty data"
    data.mkdir()
    driver = write_command_driver(tmp_path)

    completed = _run(driver, "-", ["--output", str(output), "--data-dir", str(data)], cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr
    assert _files(output) == synthetic_reference
    lines = completed.stdout.splitlines()
    assert lines[:18] == [f"written: {output / (i + SUFFIX)}" for i in SYNTHETIC_IDS]
    assert lines[18] == f"skipped: {', '.join(SEGMENT_IDS)}"
    assert lines[19].startswith("reason: ") and "SHA256SUMS.txt" in lines[19]
    assert len(lines) == 20


@pytest.mark.requirement("SRS-015")
def test_command_run_twice_on_fixture_records_gives_identical_files(
    tmp_path: Path,
    subset_ecg_fixture: Any,
    fixture_reference: dict[str, bytes],
    write_command_driver: Callable[[Path], Path],
) -> None:
    """The command run twice on the synthetic set and on fixture records: identical files.

    Input: `export_golden.py --output <folder> --data-dir <fixture>` on the synthetic ECG
    subset fixture (six records named as the subset, verified against the fixture checksum
    list, pinned in the process), run twice in separate processes: from two working folders,
    into two output folders, with two hash seeds.
    Expected: both runs exit with status 0 and write the 24 files (18 synthetic, 6 record
    segments), byte-identical between the two runs and to those of `export_golden_vectors` in
    the test process; standard output names the 24 files and no skipped input.
    """
    driver = write_command_driver(tmp_path)
    pin = subset_ecg_fixture.checksum_list_sha256
    runs = []
    for run, seed in (("first", "1"), ("second", "4242")):
        cwd = tmp_path / f"{run} cwd"
        cwd.mkdir()
        output = tmp_path / f"{run} output"
        arguments = ["--output", str(output), "--data-dir", str(subset_ecg_fixture.data_root)]
        completed = _run(driver, pin, arguments, cwd=cwd, hash_seed=seed)
        assert completed.returncode == 0, completed.stderr
        assert "skipped" not in completed.stdout
        assert len(re.findall(r"^written: ", completed.stdout, flags=re.MULTILINE)) == 24
        runs.append(_files(output))

    assert sorted(runs[0]) == sorted(i + SUFFIX for i in SYNTHETIC_IDS + SEGMENT_IDS)
    assert runs[0] == runs[1]
    assert runs[0] == fixture_reference


@pytest.mark.requirement("SRS-015")
def test_command_default_folders_are_those_of_the_repository(
    tmp_path: Path,
    subset_ecg_fixture: Any,
    fixture_reference: dict[str, bytes],
    copy_subset_fixture: Callable[..., Any],
    write_command_driver: Callable[[Path], Path],
) -> None:
    """Without options, the command reads `data/` and writes `data/golden/` of the repository.

    Input: a copy of the scripts folder in `<repo>/dsp/scripts/`; the files of the six
    records of the synthetic ECG subset fixture and its checksum list in `<repo>/data/mitdb/`
    (as the cache of the build keeps them); `export_golden.py` without options, run from
    another folder, the pinned list set to the fixture list.
    Expected: exit status 0; `<repo>/data/golden/` holds the 24 files, byte-identical to those
    of `export_golden_vectors` on the same records; nothing is written in the working folder.
    """
    repo = tmp_path / "repo"
    shutil.copytree(
        SCRIPTS_DIR, repo / "dsp" / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    copy_subset_fixture(subset_ecg_fixture, repo / "data", only_subset=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    driver = write_command_driver(tmp_path)

    completed = _run(
        driver,
        subset_ecg_fixture.checksum_list_sha256,
        [],
        cwd=elsewhere,
        script=repo / "dsp" / "scripts" / "export_golden.py",
    )

    assert completed.returncode == 0, completed.stderr
    assert _files(repo / "data" / "golden") == fixture_reference
    assert list(elsewhere.iterdir()) == []


def _with_header(data: bytes, key: str, value: str) -> bytes:
    """``data`` with the value of the header line ``key=`` replaced."""
    lines = data.split(b"\n")
    index = next(i for i, line in enumerate(lines) if line.startswith(key.encode() + b"="))
    lines[index] = f"{key}={value}".encode()
    return b"\n".join(lines)


_VERSION_ASSIGNMENT = re.compile(r'^(__version__(?:\s*:\s*str)?\s*=\s*)"[^"]*"', re.MULTILINE)


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("variant", ["same-code-crlf-copy", "comment-added", "version-changed"])
def test_command_states_the_code_that_runs(
    variant: str,
    tmp_path: Path,
    synthetic_reference: dict[str, bytes],
    copy_package: Callable[..., Path],
    expected_software: Callable[[Path], Any],
    running_software: Any,
    write_command_driver: Callable[[Path], Path],
) -> None:
    """Each file states the version and source identifier of the code that wrote it.

    Input: `export_golden.py --output <folder> --data-dir <empty folder>` in a separate
    process that imports a copy of the package under test: the same source code in another
    folder with CR LF line endings; the package with a comment line added at the end of
    `sinus_dsp/golden.py`; or the package with its `__version__` literal set to `0.1.0.dev9`.
    The expected identity of the copy is computed by the test (version literal, and the
    identifier with the six steps of architecture section 8.14).
    Expected: exit status 0. Same source code: the 18 files are byte-identical to those of the
    package under test (same version and source identifier). Comment added: the identifier
    of the copy differs from that of the package under test, and each file equals the file of
    the package under test with `source_sha256` set to the identifier of the copy. Version
    changed: likewise, with `software_version=0.1.0.dev9` as well.
    """
    package = copy_package(tmp_path / "code copy", crlf=variant == "same-code-crlf-copy")
    if variant == "comment-added":
        path = package / "golden.py"
        path.write_bytes(path.read_bytes() + b"\n# A comment line added by a test.\n")
    if variant == "version-changed":
        init = package / "__init__.py"
        text, count = _VERSION_ASSIGNMENT.subn(r'\g<1>"0.1.0.dev9"', init.read_text("utf-8"))
        assert count == 1
        init.write_text(text, encoding="utf-8")
    copy_identity = expected_software(package)
    output, data = tmp_path / "golden", tmp_path / "data"
    data.mkdir()
    driver = write_command_driver(tmp_path)

    completed = _run(
        driver,
        "-",
        ["--output", str(output), "--data-dir", str(data)],
        cwd=tmp_path,
        package_root=package.parent,
    )

    assert completed.returncode == 0, completed.stderr
    files = _files(output)
    if variant == "same-code-crlf-copy":
        assert copy_identity.source_sha256 == running_software.source_sha256
        assert files == synthetic_reference
        return
    assert copy_identity.source_sha256 != running_software.source_sha256
    expected_version = "0.1.0.dev9" if variant == "version-changed" else running_software.version
    assert copy_identity.version == expected_version
    expected = {}
    for name, data_bytes in synthetic_reference.items():
        changed = _with_header(data_bytes, "source_sha256", copy_identity.source_sha256)
        expected[name] = _with_header(changed, "software_version", expected_version)
    assert files == expected
