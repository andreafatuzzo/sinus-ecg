"""Install the pinned Qt build with aqtinstall and check its archives (architecture-m3.md 15.14).

Run from the repository root with the tools project, which pins aqtinstall:

    uv run --project tools/cpp python desktop/qt/install_qt.py --dest <folder>

The Qt version is the one line of ``desktop/qt/version.txt``. aqtinstall checks every archive
against the checksums of the Qt repository; this script keeps the archives it downloads and then
checks them against the committed list ``desktop/qt/<version>-<host>-<arch>.sha256`` (one line
``<sha256>  <archive name>`` per archive): a missing, extra or changed archive fails the install.
On Windows the list also covers the archive of the Qt toolchain.

``<folder>`` must be outside the repository or in a gitignored folder; aqtinstall writes its log
there. After a successful check the script writes ``installed-<version>-<host>-<arch>.sha256``
(a copy of the list) into it; a later run with the same list checks the kept archives again and
does not download anything. It prints ``qt-prefix=<path>`` and, on Windows,
``toolchain-bin=<path>``; ``--github-output <file>`` appends the same lines to that file.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

QT_DIR = Path(__file__).resolve().parent
CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class HostSpec:
    """What is installed on one host: the Qt architecture, the aqtinstall commands, the
    folders they create (relative to the destination)."""

    host: str
    arch: str
    commands: tuple[tuple[str, ...], ...]
    prefix: str
    toolchain_bin: str | None


def host_spec(host: str, version: str) -> HostSpec:
    """The installation of ``version`` on ``host`` (``linux`` or ``windows``)."""
    if host == "linux":
        # qtbase holds Core, Gui, Widgets, Network, Test and the offscreen platform plugin;
        # icu holds the ICU libraries that Qt Core links.
        return HostSpec(
            host=host,
            arch="linux_gcc_64",
            commands=(
                ("install-qt", "linux", "desktop", version, "linux_gcc_64")
                + ("--archives", "qtbase", "icu"),
            ),
            prefix=f"{version}/gcc_64",
            toolchain_bin=None,
        )
    if host == "windows":
        # Qt's LLVM-MinGW build and the toolchain it names (LLVM-MinGW 22.1.7 for Qt 6.12.0);
        # "llvm" selects the runtime libraries (libc++, libunwind) that Qt places next to its DLLs.
        return HostSpec(
            host=host,
            arch="win64_llvm_mingw",
            commands=(
                ("install-qt", "windows", "desktop", version, "win64_llvm_mingw")
                + ("--archives", "qtbase", "llvm"),
                ("install-tool", "windows", "desktop", "tools_llvm_mingw2217")
                + ("qt.tools.win64_llvm_mingw2217",),
            ),
            prefix=f"{version}/llvm-mingw_64",
            toolchain_bin="Tools/llvm-mingw2217_64/bin",
        )
    raise SystemExit(f"install_qt.py: unsupported host {host!r}")


def read_version() -> str:
    """The exact Qt version of ``version.txt``."""
    return (QT_DIR / "version.txt").read_text(encoding="utf-8").strip()


def read_list(path: Path) -> dict[str, str]:
    """The committed list: archive name -> SHA-256 (lowercase hexadecimal)."""
    expected: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        digest, sep, name = line.partition("  ")
        if not sep or len(digest) != 64 or not name or name in expected:
            raise SystemExit(f"install_qt.py: {path.name} line {number} is not '<sha256>  <name>'")
        expected[name] = digest.lower()
    if not expected:
        raise SystemExit(f"install_qt.py: {path.name} lists no archive")
    return expected


def sha256_of(path: Path) -> str:
    """SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def check_archives(folder: Path, expected: dict[str, str]) -> list[str]:
    """Differences between the archives in ``folder`` and the list; empty if they agree."""
    found = {p.name: p for p in folder.iterdir() if p.is_file()} if folder.is_dir() else {}
    problems = [f"missing archive {name}" for name in sorted(expected.keys() - found.keys())]
    problems += [f"archive not in the list {name}" for name in sorted(found.keys() - expected)]
    for name in sorted(expected.keys() & found.keys()):
        actual = sha256_of(found[name])
        if actual != expected[name]:
            problems.append(f"changed archive {name}: SHA-256 {actual}, listed {expected[name]}")
    return problems


def run_aqt(command: tuple[str, ...], dest: Path, archives: Path) -> None:
    """One aqtinstall command, keeping its archives; the working folder (and log) is ``dest``."""
    full = [sys.executable, "-m", "aqt", *command, "--outputdir", str(dest)]
    full += ["--keep", "--archive-dest", str(archives)]
    print("+", " ".join(full), flush=True)
    result = subprocess.run(full, cwd=dest, check=False)  # noqa: S603 (fixed argument list)
    if result.returncode != 0:
        raise SystemExit(f"install_qt.py: aqtinstall failed with status {result.returncode}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dest", type=Path, required=True, help="installation folder")
    parser.add_argument("--host", choices=("linux", "windows"), default=None)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args(argv)

    host = args.host or ("windows" if sys.platform == "win32" else "linux")
    version = read_version()
    spec = host_spec(host, version)
    list_path = QT_DIR / f"{version}-{host}-{spec.arch}.sha256"
    expected = read_list(list_path)
    list_text = list_path.read_text(encoding="utf-8")

    dest: Path = args.dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    archives = dest / "archives" / f"{version}-{host}-{spec.arch}"
    marker = dest / f"installed-{version}-{host}-{spec.arch}.sha256"
    installed = marker.is_file() and marker.read_text(encoding="utf-8") == list_text
    if not installed or not (dest / spec.prefix).is_dir():
        marker.unlink(missing_ok=True)
        if archives.is_dir():
            for old in archives.iterdir():
                if old.is_file():
                    old.unlink()
        archives.mkdir(parents=True, exist_ok=True)
        for command in spec.commands:
            run_aqt(command, dest, archives)

    problems = check_archives(archives, expected)
    if problems:
        marker.unlink(missing_ok=True)
        for problem in problems:
            print(f"install_qt.py: {problem}", file=sys.stderr)
        print(f"install_qt.py: the archives do not match {list_path.name}", file=sys.stderr)
        return 1
    marker.write_text(list_text, encoding="utf-8")
    print(f"install_qt.py: {len(expected)} archives match {list_path.name}")

    lines = [f"qt-prefix={(dest / spec.prefix).as_posix()}"]
    if spec.toolchain_bin is not None:
        lines.append(f"toolchain-bin={(dest / spec.toolchain_bin).as_posix()}")
    for line in lines:
        print(line)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.writelines(f"{line}\n" for line in lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
