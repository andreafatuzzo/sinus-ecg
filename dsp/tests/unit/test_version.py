"""Unit tests of the software identity: source files, manifest, digest, runtime versions.

The digest of the fixture package below was also computed with the shell command of the
design (``find pkg -type f -name '*.py' -not -path '*/.*' -print0 | LC_ALL=C sort -z |
xargs -0 sha256sum --text | sha256sum --text``), which gave the same value.
"""

import dataclasses
import hashlib
import importlib.metadata
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import sinus_dsp
from sinus_dsp import version
from sinus_dsp.version import (
    RUNTIME_DISTRIBUTIONS,
    SoftwareIdentity,
    package_dir,
    runtime_versions,
    software_identity,
    source_digest,
    source_files,
    source_manifest,
)

DSP_DIR = Path(__file__).resolve().parents[2]

FILES = {
    "pkg/__init__.py": b'__version__ = "1.2.3"\n',
    "pkg/a.py": b"A = 1\n",
    "pkg/sub/__init__.py": b"",
    "pkg/sub/b.py": b"def b() -> int:\n    return 2\n",
}

# The manifest of FILES, written out: SHA-256 of each file, two spaces, name, line feed.
MANIFEST = (
    "0be0ff596ad59010e64260292dc9b4b16361d82808af059f73cfec079bef53e4  pkg/__init__.py\n"
    "06edbcf4336165a271e6524025a6439c3caa3246fd0796f116772279707a5325  pkg/a.py\n"
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  pkg/sub/__init__.py\n"
    "b2a5709295e66b396ce4018aed7fd49778dccd2c49ba7ba2e7def6be88790d6d  pkg/sub/b.py\n"
)
DIGEST = "f352e925a2684785f4cfab72a0812a57852ef8018521b88e68a7d71fee655120"
EMPTY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

HEX_64 = re.compile(r"[0-9a-f]{64}")


def write_files(root: Path, files: dict[str, bytes]) -> Path:
    """Write the files under ``root`` in the order given; return ``root / "pkg"``."""
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root / "pkg"


def manifest_of(files: dict[str, bytes]) -> str:
    """The manifest of a set of files, computed in the test from its definition."""
    lines = []
    for name in sorted(files):
        content = files[name].replace(b"\r\n", b"\n")
        lines.append(f"{hashlib.sha256(content).hexdigest()}  {name}\n")
    return "".join(lines)


def digest_of(files: dict[str, bytes]) -> str:
    return hashlib.sha256(manifest_of(files).encode("utf-8")).hexdigest()


@pytest.fixture
def package(tmp_path: Path) -> Path:
    return write_files(tmp_path, FILES)


def try_symlink(link: Path, target: Path, *, folder: bool = False) -> None:
    """Create a symbolic link, or skip the test where the platform does not allow it."""
    try:
        link.symlink_to(target, target_is_directory=folder)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symbolic links are not available here: {error}")


# --- the six steps on a fixture package -----------------------------------------------------


def test_manifest_and_digest_written_out() -> None:
    assert hashlib.sha256(MANIFEST.encode("utf-8")).hexdigest() == DIGEST
    assert manifest_of(FILES) == MANIFEST


def test_fixture_package(package: Path) -> None:
    assert source_files(package) == (
        "pkg/__init__.py",
        "pkg/a.py",
        "pkg/sub/__init__.py",
        "pkg/sub/b.py",
    )
    assert source_manifest(package) == MANIFEST
    assert source_digest(package) == DIGEST


def test_names_are_sorted_in_code_point_order(tmp_path: Path) -> None:
    # A walk lists the files of a folder before those of its subfolders; code-point order
    # puts "a/x.py" ("/" is U+002F) before "a0.py" ("0" is U+0030) and after "a.py".
    files = {
        "pkg/a0.py": b"0\n",
        "pkg/é.py": b"e\n",
        "pkg/a.py": b"a\n",
        "pkg/_c.py": b"c\n",
        "pkg/a-b.py": b"ab\n",
        "pkg/B.py": b"B\n",
        "pkg/a/x.py": b"x\n",
        "pkg/Z/y.py": b"y\n",
    }
    package = write_files(tmp_path, files)
    assert source_files(package) == (
        "pkg/B.py",
        "pkg/Z/y.py",
        "pkg/_c.py",
        "pkg/a-b.py",
        "pkg/a.py",
        "pkg/a/x.py",
        "pkg/a0.py",
        "pkg/é.py",
    )
    assert source_manifest(package) == manifest_of(files)
    assert source_digest(package) == digest_of(files)
    # The names are encoded in UTF-8 in the manifest.
    assert "  pkg/é.py\n".encode() in source_manifest(package).encode("utf-8")


def test_files_in_nested_folders_are_named_with_slashes(tmp_path: Path) -> None:
    package = write_files(tmp_path, {"pkg/one/two/three.py": b"3\n"})
    assert source_files(package) == ("pkg/one/two/three.py",)
    assert "\\" not in source_manifest(package)


def test_names_start_with_the_name_of_the_package_folder(tmp_path: Path) -> None:
    files = {name.replace("pkg/", "other/", 1): content for name, content in FILES.items()}
    other = write_files(tmp_path, files).parent / "other"
    assert source_files(other)[0] == "other/__init__.py"
    assert source_digest(other) == digest_of(files) != DIGEST


def test_same_digest_whatever_the_folder_and_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = write_files(tmp_path / "one", FILES)
    second = write_files(tmp_path / "two" / "deeper", FILES)
    monkeypatch.chdir(tmp_path / "two")
    assert source_digest(first) == source_digest(second) == DIGEST
    # A relative folder gives the same names.
    assert source_digest(Path("deeper") / "pkg") == DIGEST


def test_same_digest_whatever_the_order_of_creation(tmp_path: Path) -> None:
    forward = write_files(tmp_path / "forward", FILES)
    backward = write_files(tmp_path / "backward", dict(reversed(list(FILES.items()))))
    assert source_digest(forward) == source_digest(backward) == DIGEST


def test_same_digest_whatever_the_order_of_the_walk(
    package: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_walk = os.walk
    walked: list[str] = []

    def reversed_walk(top: Path, **kwargs: Any) -> Iterator[tuple[str, list[str], list[str]]]:
        for dirpath, dirnames, filenames in real_walk(top, **kwargs):
            walked.append(dirpath)
            dirnames.reverse()
            filenames.reverse()
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(os, "walk", reversed_walk)
    assert source_files(package) == tuple(sorted(FILES))
    assert source_digest(package) == DIGEST
    assert walked


def test_crlf_copy_gives_the_same_digest(tmp_path: Path) -> None:
    files = {name: content.replace(b"\n", b"\r\n") for name, content in FILES.items()}
    package = write_files(tmp_path, files)
    assert source_manifest(package) == MANIFEST
    assert source_digest(package) == DIGEST


def test_only_cr_lf_pairs_are_replaced(tmp_path: Path) -> None:
    # A carriage return that is not followed by a line feed is kept.
    files = dict(FILES)
    files["pkg/a.py"] = b"A = 1\r\r\n"
    package = write_files(tmp_path, files)
    expected = hashlib.sha256(b"A = 1\r\n").hexdigest()
    assert f"{expected}  pkg/a.py\n" in source_manifest(package)
    assert source_digest(package) != DIGEST


@pytest.mark.parametrize(
    "extra",
    [
        "pkg/__pycache__/a.cpython-311.pyc",
        "pkg/__pycache__/cached.py",
        "pkg/sub/__pycache__/cached.py",
        "pkg/.hidden.py",
        "pkg/sub/.hidden.py",
        "pkg/.hidden/visible.py",
        "pkg/sub/.git/hook.py",
        "pkg/notes.txt",
        "pkg/a.pyc",
        "pkg/a.pyi",
        "pkg/a.py~",
        "pkg/a.py.orig",
        "pkg/README",
        "outside.py",
    ],
)
def test_files_that_are_not_sources_leave_the_digest_unchanged(package: Path, extra: str) -> None:
    path = package.parent / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a source of the package\n")
    assert source_files(package) == tuple(sorted(FILES))
    assert source_digest(package) == DIGEST


def test_empty_folders_leave_the_digest_unchanged(package: Path) -> None:
    (package / "empty").mkdir()
    (package / "sub" / "empty.py").mkdir()  # a folder whose name ends with .py
    assert source_digest(package) == DIGEST


def test_symbolic_link_to_a_file_is_not_a_source(package: Path) -> None:
    try_symlink(package / "link.py", package / "a.py")
    assert (package / "link.py").is_file()
    assert source_files(package) == tuple(sorted(FILES))
    assert source_digest(package) == DIGEST


def test_symbolic_link_to_a_folder_is_not_followed(package: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "elsewhere.py").write_bytes(b"x = 1\n")
    try_symlink(package / "linked", outside, folder=True)
    try_symlink(package / "sub_again", package / "sub", folder=True)
    assert (package / "linked" / "elsewhere.py").is_file()
    assert source_files(package) == tuple(sorted(FILES))
    assert source_digest(package) == DIGEST


@pytest.mark.parametrize(
    "change",
    ["one byte", "renamed", "added", "added empty", "removed", "moved", "line feed added"],
)
def test_a_change_of_the_sources_changes_the_digest(package: Path, change: str) -> None:
    a = package / "a.py"
    if change == "one byte":
        a.write_bytes(b"A = 2\n")
    elif change == "renamed":
        a.rename(package / "a2.py")
    elif change == "added":
        (package / "c.py").write_bytes(b"C = 3\n")
    elif change == "added empty":
        (package / "sub" / "empty.py").write_bytes(b"")
    elif change == "removed":
        (package / "sub" / "b.py").unlink()
    elif change == "moved":
        a.rename(package / "sub" / "a.py")
    else:
        a.write_bytes(b"A = 1\n\n")
    assert source_digest(package) != DIGEST
    assert HEX_64.fullmatch(source_digest(package))


def test_package_without_sources(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    assert source_files(tmp_path / "pkg") == ()
    assert source_manifest(tmp_path / "pkg") == ""
    assert source_digest(tmp_path / "pkg") == EMPTY_DIGEST


def test_absent_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        source_files(tmp_path / "absent")
    with pytest.raises(OSError):
        source_digest(tmp_path / "absent")


def test_unreadable_file_raises(package: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_read_bytes = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self.name == "b.py":
            raise PermissionError(f"cannot read {self}")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(PermissionError, match="b.py"):
        source_digest(package)


# --- runtime versions and the identity of the running software ------------------------------


def dependency_names(pyproject: Path) -> list[str]:
    """Names of the ``[project] dependencies``, normalised as in PEP 503."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    names = []
    for requirement in data["project"]["dependencies"]:
        match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
        assert match is not None, requirement
        names.append(re.sub(r"[-_.]+", "-", match.group(0)).lower())
    return names


def pyproject_version() -> str:
    data = tomllib.loads((DSP_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    value = data["project"]["version"]
    assert isinstance(value, str)
    return value


def test_runtime_distributions_are_the_dependencies_of_pyproject() -> None:
    assert list(RUNTIME_DISTRIBUTIONS) == dependency_names(DSP_DIR / "pyproject.toml")


def test_runtime_versions_in_order() -> None:
    assert runtime_versions() == tuple(
        (name, importlib.metadata.version(name)) for name in RUNTIME_DISTRIBUTIONS
    )
    assert [name for name, _ in runtime_versions()] == list(RUNTIME_DISTRIBUTIONS)


def test_runtime_package_not_installed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version, "RUNTIME_DISTRIBUTIONS", ("numpy", "no-such-distribution-x"))
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        runtime_versions()
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        software_identity()


def test_package_dir_is_the_folder_of_the_running_package() -> None:
    assert package_dir() == Path(sinus_dsp.__file__).resolve().parent
    assert package_dir() == Path(version.__file__).resolve().parent
    assert "sinus_dsp/version.py" in source_files(package_dir())


def test_identity_of_the_running_software() -> None:
    identity = software_identity()
    assert identity.version == sinus_dsp.__version__ == pyproject_version()
    assert HEX_64.fullmatch(identity.source_sha256)
    assert identity.source_sha256 == source_digest(package_dir())
    assert identity.python == f"{sys.version_info.major}.{sys.version_info.minor}"
    assert re.fullmatch(r"3\.\d+", identity.python)
    assert identity.runtime == runtime_versions()
    assert software_identity() == identity


def test_digest_of_the_package_covers_init_and_version() -> None:
    names = source_files(package_dir())
    assert "sinus_dsp/__init__.py" in names
    assert "sinus_dsp/evaluation/run.py" in names
    assert all(name.startswith("sinus_dsp/") and name.endswith(".py") for name in names)


def test_version_is_the_literal_of_the_package_not_the_installed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_version = importlib.metadata.version

    def metadata_version(name: str) -> str:
        if name == "sinus-dsp":
            raise AssertionError("the installed metadata of sinus-dsp must not be read")
        return real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", metadata_version)
    monkeypatch.setattr(sinus_dsp, "__version__", "9.8.7.dev0")
    assert software_identity().version == "9.8.7.dev0"


def test_identity_is_frozen() -> None:
    identity = SoftwareIdentity("1.0.0", "0" * 64, "3.11", (("numpy", "2.0.0"),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.version = "2.0.0"  # type: ignore[misc]


def test_version_imports_only_the_package_and_the_standard_library() -> None:
    code = (
        "import sys, sinus_dsp.version; "
        "print(sorted(name for name in sys.modules "
        "if name.split('.')[0] in ('sinus_dsp', 'numpy', 'scipy', 'wfdb')))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True, cwd=DSP_DIR
    )
    assert completed.stdout.strip() == "['sinus_dsp', 'sinus_dsp.version']"
