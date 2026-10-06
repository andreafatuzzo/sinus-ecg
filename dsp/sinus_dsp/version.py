"""Software identity stated by the reports and the golden vectors (architecture §8.14).

SRS-009, SRS-012: a report states the software that produced it. The identity has two parts:
the package version, which names the milestone (``sinus_dsp.__version__``, rule of
``docs/regulatory/sdp.md`` §4), and the SHA-256 digest of the package source, which
identifies the exact code of the package without depending on git. The same version and
digest mean the same source code. The identity also holds the versions of Python and of the
runtime SOUP packages, because the versions of NumPy and SciPy installed from ``dsp/uv.lock``
depend on the Python version, and the digest covers only the package.

This module imports only the package itself and the standard library.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import sinus_dsp

#: The runtime SOUP packages of ``dsp`` (``docs/regulatory/soup.md``): the names of the
#: ``[project] dependencies`` of ``dsp/pyproject.toml``, in this order.
RUNTIME_DISTRIBUTIONS: Final = ("numpy", "scipy", "wfdb")

_SOURCE_SUFFIX: Final = ".py"
_HIDDEN_PREFIX: Final = "."
_BYTECODE_DIR: Final = "__pycache__"


@dataclass(frozen=True)
class SoftwareIdentity:
    """The software that produced a report or a golden vector (SRS-009, SRS-012).

    Attributes:
        version: The package version, ``sinus_dsp.__version__``, e.g. ``0.1.0.dev0``.
        source_sha256: SHA-256 digest of the package source (:func:`source_digest`), 64
            lowercase hexadecimal digits.
        python: Version of Python, ``<major>.<minor>``, e.g. ``3.11``.
        runtime: ``(distribution, version)`` of each runtime SOUP package, in the order of
            :data:`RUNTIME_DISTRIBUTIONS`.
    """

    version: str
    source_sha256: str
    python: str
    runtime: tuple[tuple[str, str], ...]


def package_dir() -> Path:
    """Return the folder of the running package: the folder of this module.

    In the editable install of ``uv sync``, that is the ``sinus_dsp`` folder of the checkout.
    """
    return Path(__file__).resolve().parent


def source_files(package_dir: Path) -> tuple[str, ...]:
    """Return the names of the source files of a package folder, sorted.

    The folder is walked without following symbolic links. Folders whose name starts with
    ``.`` or is ``__pycache__`` are skipped. A file is kept if it is a regular file, not a
    symbolic link, and its name ends with ``.py`` and does not start with ``.``. Each file is
    named by its path relative to the parent of ``package_dir``, with ``/`` as separator
    (e.g. ``sinus_dsp/evaluation/run.py``), and the names are sorted in code-point order.

    Args:
        package_dir: Folder of the package, e.g. ``dsp/sinus_dsp``.

    Returns:
        The names, sorted.

    Raises:
        OSError: If the folder, or a folder inside it, cannot be listed.
    """
    top = Path(package_dir)
    parent = top.parent
    names: list[str] = []
    for dirpath, dirnames, filenames in os.walk(top, onerror=_raise, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(_HIDDEN_PREFIX) and name != _BYTECODE_DIR
        ]
        folder = Path(dirpath)
        for name in filenames:
            if name.startswith(_HIDDEN_PREFIX) or not name.endswith(_SOURCE_SUFFIX):
                continue
            path = folder / name
            if path.is_symlink() or not path.is_file():
                continue
            names.append(path.relative_to(parent).as_posix())
    return tuple(sorted(names))


def source_manifest(package_dir: Path) -> str:
    """Return the manifest of the package source, from which :func:`source_digest` is computed.

    One line per file of :func:`source_files`, in that order:
    ``<SHA-256 of the file><two spaces><name><line feed>``, where the SHA-256 (64 lowercase
    hexadecimal digits) is that of the bytes of the file with every CR LF replaced by LF.
    This is the format of ``sha256sum`` in text mode.

    Args:
        package_dir: Folder of the package.

    Returns:
        The manifest.

    Raises:
        OSError: If a folder cannot be listed or a file cannot be read.
    """
    top = Path(package_dir)
    parent = top.parent
    lines: list[str] = []
    for name in source_files(top):
        content = (parent / name).read_bytes().replace(b"\r\n", b"\n")
        lines.append(f"{hashlib.sha256(content).hexdigest()}  {name}\n")
    return "".join(lines)


def source_digest(package_dir: Path) -> str:
    """Return the SHA-256 digest of the package source (SRS-009, SRS-012).

    The digest is the SHA-256 of the UTF-8 encoding of :func:`source_manifest`. It covers
    every ``.py`` file of the package, ``__init__.py`` (and so the version) included. It
    does not depend on git, on the folder of the checkout or on its line endings. From
    ``dsp/``, on a checkout with line feeds, the same digest is given by::

        find sinus_dsp -type f -name '*.py' -not -path '*/.*' -print0 | LC_ALL=C sort -z \\
          | xargs -0 sha256sum --text | sha256sum --text

    Args:
        package_dir: Folder of the package.

    Returns:
        The digest, 64 lowercase hexadecimal digits.

    Raises:
        OSError: If a folder cannot be listed or a file cannot be read.
    """
    return hashlib.sha256(source_manifest(package_dir).encode("utf-8")).hexdigest()


def runtime_versions() -> tuple[tuple[str, str], ...]:
    """Return ``(distribution, version)`` of each runtime SOUP package, as installed.

    Returns:
        One pair per name of :data:`RUNTIME_DISTRIBUTIONS`, in that order.

    Raises:
        importlib.metadata.PackageNotFoundError: If a package is not installed.
    """
    return tuple((name, importlib.metadata.version(name)) for name in RUNTIME_DISTRIBUTIONS)


def software_identity() -> SoftwareIdentity:
    """Return the identity of the running software (SRS-009, SRS-012).

    The version is the literal ``__version__`` of ``sinus_dsp/__init__.py``, not the
    installed metadata, which is stale after an edit until the next install. The digest is
    that of :func:`package_dir`. The Python version has no patch number, which is not pinned.

    Raises:
        OSError: If a file of the package cannot be read.
        importlib.metadata.PackageNotFoundError: If a runtime SOUP package is not installed.
    """
    return SoftwareIdentity(
        version=sinus_dsp.__version__,
        source_sha256=source_digest(package_dir()),
        python=f"{sys.version_info.major}.{sys.version_info.minor}",
        runtime=runtime_versions(),
    )


def _raise(error: OSError) -> None:
    """``onerror`` of :func:`os.walk`: a folder that cannot be listed is an error."""
    raise error
