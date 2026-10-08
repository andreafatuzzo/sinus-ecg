"""Unit tests of the private module ``sinus_dsp._files`` (architecture §8.2, "Writing files").

They also check the rule of architecture §8.1 on private names: the package has one atomic
writer, and no module imports a private name of a module that is not a private module, except
``qrs._trace`` in ``pipeline`` (``qrs._detect`` until architecture v0.3, §13.3).
"""

import ast
import os
from pathlib import Path

import pytest

import sinus_dsp
from sinus_dsp._files import PART_SUFFIX, write_atomically

PACKAGE_DIR = Path(sinus_dsp.__file__).resolve().parent
PRIVATE_MODULES = ("sinus_dsp._files", "sinus_dsp._types", "sinus_dsp._units")


def test_part_suffix() -> None:
    assert PART_SUFFIX == ".part~"


def test_writes_the_bytes_exactly(tmp_path: Path) -> None:
    content = b"first line\r\nsecond line\n\xff\x00no final line feed"
    path = tmp_path / "file.txt"
    write_atomically(path, content)
    assert path.read_bytes() == content
    assert sorted(p.name for p in tmp_path.iterdir()) == ["file.txt"]


def test_writes_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    write_atomically(path, b"")
    assert path.read_bytes() == b""


def test_creates_the_folder_and_its_parents(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "c" / "file.md"
    write_atomically(path, b"text\n")
    assert path.read_bytes() == b"text\n"
    assert sorted(p.name for p in path.parent.iterdir()) == ["file.md"]


def test_replaces_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "file.md"
    path.write_bytes(b"an older and longer content than the new one\n")
    write_atomically(path, b"new\n")
    assert path.read_bytes() == b"new\n"


def test_overwrites_a_part_file_left_by_an_interrupted_run(tmp_path: Path) -> None:
    path = tmp_path / "file.md"
    (tmp_path / "file.md.part~").write_bytes(b"stale and longer than the content written\n")
    write_atomically(path, b"complete\n")
    assert path.read_bytes() == b"complete\n"
    assert not (tmp_path / "file.md.part~").exists()


def test_leaves_other_files_untouched(tmp_path: Path) -> None:
    (tmp_path / "other.md").write_bytes(b"other\n")
    (tmp_path / "other.md.part~").write_bytes(b"other part\n")
    write_atomically(tmp_path / "file.md", b"x")
    assert (tmp_path / "other.md").read_bytes() == b"other\n"
    assert (tmp_path / "other.md.part~").read_bytes() == b"other part\n"


def test_accepts_a_path_given_as_text(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "file.md"
    write_atomically(str(path), b"x")  # type: ignore[arg-type]
    assert path.read_bytes() == b"x"


def test_a_failed_replace_keeps_the_previous_file_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "file.md"
    path.write_bytes(b"previous\n")

    def failing_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_atomically(path, b"new\n")
    assert path.read_bytes() == b"previous\n"
    assert (tmp_path / "file.md.part~").read_bytes() == b"new\n"


def test_the_content_is_written_before_the_final_name_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "file.md"
    seen: list[tuple[str, bytes, bool]] = []
    real_replace = os.replace

    def recording_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        seen.append((Path(source).name, Path(source).read_bytes(), Path(target).exists()))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", recording_replace)
    write_atomically(path, b"content\n")
    assert seen == [("file.md.part~", b"content\n", False)]
    assert path.read_bytes() == b"content\n"


def test_errors_of_the_file_system_propagate(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_bytes(b"a file where a folder is needed\n")
    with pytest.raises(OSError):
        write_atomically(blocker / "file.md", b"x")
    assert blocker.read_bytes() == b"a file where a folder is needed\n"


def test_a_folder_in_place_of_the_file_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "file.md").mkdir()
    with pytest.raises(OSError):
        write_atomically(tmp_path / "file.md", b"x")
    assert (tmp_path / "file.md").is_dir()


# --- package-wide rules -----------------------------------------------------------------------


def _modules() -> list[tuple[str, ast.Module]]:
    """``(dotted name, syntax tree)`` of each module of the package."""
    modules: list[tuple[str, ast.Module]] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        modules.append((name, ast.parse(path.read_text(encoding="utf-8"))))
    return modules


def _absolute(module: str, node: ast.ImportFrom) -> str:
    """The module named by an ``import from``, made absolute."""
    if node.level == 0:
        return str(node.module)
    base = module.split(".")[: -node.level]
    return ".".join([*base, *([node.module] if node.module else [])])


def test_only_the_private_files_module_writes_atomically() -> None:
    """One helper: no other module defines a writer or spells the temporary suffix."""
    found: list[str] = []
    for name, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and "write_atomically" in node.name:
                found.append(f"{name}.{node.name}")
            if isinstance(node, ast.Constant) and node.value == ".part~":
                found.append(f"{name}: '.part~'")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("replace", "rename", "write_bytes", "write_text"):
                    if not _is_str_replace(node):
                        found.append(f"{name}: {node.func.attr}()")
    assert found == [
        "sinus_dsp._files.write_atomically",
        "sinus_dsp._files: '.part~'",
        "sinus_dsp._files: write_bytes()",
        "sinus_dsp._files: replace()",
    ]


def _is_str_replace(node: ast.Call) -> bool:
    """Whether a ``replace`` call is a text or bytes replacement, not ``os.replace``."""
    function = node.func
    assert isinstance(function, ast.Attribute)
    if function.attr != "replace":
        return False
    return not (isinstance(function.value, ast.Name) and function.value.id == "os")


def test_private_names_are_imported_only_from_private_modules() -> None:
    """Architecture §8.1, §13.3: the one exception is ``qrs._trace``, imported by ``pipeline``."""
    found: list[tuple[str, str, str]] = []
    for name, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            source = _absolute(name, node)
            if not source.startswith("sinus_dsp") or source in PRIVATE_MODULES:
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    found.append((name, source, alias.name))
    assert found == [("sinus_dsp.pipeline", "sinus_dsp.qrs", "_trace")]


def test_the_writers_of_files_use_the_helper() -> None:
    """``data.physionet``, ``evaluation.run``, ``evaluation.subset`` and ``golden``."""
    users = sorted(
        name
        for name, tree in _modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and _absolute(name, node) == "sinus_dsp._files"
        and any(alias.name == "write_atomically" for alias in node.names)
    )
    assert users == [
        "sinus_dsp.data.physionet",
        "sinus_dsp.evaluation.run",
        "sinus_dsp.evaluation.subset",
        "sinus_dsp.golden",
    ]
