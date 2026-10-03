"""Unit tests of the software version rule of scripts/traceability.py, on fixture trees.

Each tree holds only the files the rule reads: the milestone register, dsp/pyproject.toml
and dsp/sinus_dsp/__init__.py. The script is loaded as a module and run on the tree through
its ``Layout``.
"""

import importlib.util
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "traceability.py"
PYPROJECT = "dsp/pyproject.toml"
INIT = "dsp/sinus_dsp/__init__.py"
IN_PROGRESS = "In progress"


@pytest.fixture(scope="module")
def tool() -> Iterator[ModuleType]:
    name = "traceability_script_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # the dataclasses of the script look their module up
    spec.loader.exec_module(module)
    yield module
    del sys.modules[name]


def pyproject_text(version: str) -> str:
    return f'[project]\nname = "sinus-dsp"\nversion = "{version}"\n'


def init_text(version: str) -> str:
    return f'"""Package."""\n\n__version__ = "{version}"\n'


@pytest.fixture
def tree(tmp_path: Path, tool: ModuleType) -> Callable[..., Any]:
    """Write a fixture tree; return its matrix.

    Both files state ``version`` unless their text is given; a file named in ``absent``, or
    without a text and a version, is not written.
    """

    def make(
        statuses: dict[str, str],
        version: str | None = None,
        *,
        pyproject: str | None = None,
        init: str | None = None,
        absent: tuple[str, ...] = (),
    ) -> Any:
        regulatory = tmp_path / "docs" / "regulatory"
        regulatory.mkdir(parents=True, exist_ok=True)
        rows = [f"| {ms} | Title of {ms} | {status} |" for ms, status in statuses.items()]
        register = "# Milestones\n\n| Milestone | Title | Status |\n|---|---|---|\n"
        (regulatory / "milestones.md").write_text(register + "\n".join(rows) + "\n", "utf-8")
        package = tmp_path / "dsp" / "sinus_dsp"
        package.mkdir(parents=True, exist_ok=True)
        if pyproject is None and version is not None:
            pyproject = pyproject_text(version)
        if init is None and version is not None:
            init = init_text(version)
        for name, text in ((PYPROJECT, pyproject), (INIT, init)):
            path = tmp_path / name
            if text is None or name in absent:
                path.unlink(missing_ok=True)
            else:
                path.write_text(text, encoding="utf-8")
        return tool.build(tool.Layout(tmp_path))

    return make


M1_IN_PROGRESS = {"M0": "Released", "M1": IN_PROGRESS, "M2": "Planned"}
M1_RELEASED = {"M0": "Released", "M1": "Released", "M2": "Planned"}


def expected_dev(version: str, form: str) -> list[str]:
    return [f"{name}: version {version}, expected {form}" for name in (PYPROJECT, INIT)]


# --- layout and reading ---------------------------------------------------------------------


def test_layout_paths(tool: ModuleType, tmp_path: Path) -> None:
    layout = tool.Layout(tmp_path)
    assert layout.pyproject == tmp_path / "dsp" / "pyproject.toml"
    assert layout.package_init == tmp_path / "dsp" / "sinus_dsp" / "__init__.py"


def test_versions_are_read_from_both_files(tree: Callable[..., Any]) -> None:
    matrix = tree(M1_IN_PROGRESS, "0.1.0.dev0")
    assert matrix.versions == {PYPROJECT: "0.1.0.dev0", INIT: "0.1.0.dev0"}
    assert list(matrix.versions) == [PYPROJECT, INIT]
    assert matrix.version_errors == []


def test_package_init_is_read_not_imported(tree: Callable[..., Any], tool: ModuleType) -> None:
    init = 'import no_such_module_anywhere\n__version__: str = "0.1.0.dev0"\nraise SystemExit(3)\n'
    matrix = tree(M1_IN_PROGRESS, "0.1.0.dev0", init=init)
    assert matrix.versions[INIT] == "0.1.0.dev0"
    assert tool.version_failures(matrix) == []


@pytest.mark.parametrize(
    ("pyproject", "error"),
    [
        (None, f"{PYPROJECT} not found"),
        ("[project\n", f"{PYPROJECT}: not valid TOML ("),
        ('[project]\nname = "x"\ndynamic = ["version"]\n', f"{PYPROJECT}: no [project] version"),
        ('[tool]\nversion = "0.1.0.dev0"\n', f"{PYPROJECT}: no [project] version"),
        ("[project]\nversion = 1\n", f"{PYPROJECT}: no [project] version given as a string"),
    ],
)
def test_pyproject_without_a_readable_version(
    tree: Callable[..., Any], tool: ModuleType, pyproject: str | None, error: str
) -> None:
    if pyproject is None:
        matrix = tree(M1_IN_PROGRESS, "0.1.0.dev0", absent=(PYPROJECT,))
    else:
        matrix = tree(M1_IN_PROGRESS, "0.1.0.dev0", pyproject=pyproject)
    assert matrix.versions == {INIT: "0.1.0.dev0"}
    (found,) = matrix.version_errors
    assert found.startswith(error)
    assert tool.version_failures(matrix) == [found]
    assert found in tool.release_gate_failures(matrix)


@pytest.mark.parametrize(
    ("init", "error"),
    [
        (None, f"{INIT} not found"),
        ('"""No version."""\n', f"{INIT}: __version__ assigned 0 times, expected once"),
        (
            'if True:\n    __version__ = "0.1.0.dev0"\n',
            f"{INIT}: __version__ assigned 0 times, expected once",
        ),
        (
            '__version__ = "0.1.0.dev0"\n__version__ = "0.1.0.dev0"\n',
            f"{INIT}: __version__ assigned 2 times, expected once",
        ),
        ("__version__ = VERSION\n", f"{INIT}: __version__ is not assigned a string literal"),
        ("__version__ = 1\n", f"{INIT}: __version__ is not assigned a string literal"),
        ("__version__: str\n", f"{INIT}: __version__ is not assigned a string literal"),
        ("__version__ = (\n", f"{INIT}: not valid Python ("),
    ],
)
def test_package_init_without_a_readable_version(
    tree: Callable[..., Any], tool: ModuleType, init: str | None, error: str
) -> None:
    if init is None:
        matrix = tree(M1_IN_PROGRESS, "0.1.0.dev0", absent=(INIT,))
    else:
        matrix = tree(M1_IN_PROGRESS, "0.1.0.dev0", init=init)
    assert matrix.versions == {PYPROJECT: "0.1.0.dev0"}
    (found,) = matrix.version_errors
    assert found.startswith(error)
    assert tool.version_failures(matrix) == [found]


def test_both_files_unreadable(tree: Callable[..., Any], tool: ModuleType) -> None:
    matrix = tree(M1_IN_PROGRESS)
    assert matrix.versions == {}
    assert tool.version_failures(matrix) == [f"{PYPROJECT} not found", f"{INIT} not found"]


# --- the version rule (--check) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "version"),
    [
        (M1_IN_PROGRESS, "0.1.0.dev0"),
        ({"M0": IN_PROGRESS}, "0.0.0.dev0"),
        ({"M0": "Released", "M1": IN_PROGRESS, "M2": IN_PROGRESS}, "0.1.0.dev0"),
        ({"M2": IN_PROGRESS, "M0": "Released", "M1": IN_PROGRESS}, "0.1.0.dev0"),
        ({"M0": "Released", "M1": "Released", "M2": IN_PROGRESS}, "0.2.0.dev0"),
        ({"M9": "Released", "M10": IN_PROGRESS}, "0.10.0.dev0"),
        ({"M0": "Released", "M1": "Planned"}, "0.0.1"),
        ({"M0": "Released"}, "0.0.0"),
        (M1_RELEASED, "0.1.0"),
        (M1_RELEASED, "0.1.1"),
        (M1_RELEASED, "0.1.12"),
        ({"M1": "Released", "M0": "Released", "M2": "Planned"}, "0.1.3"),
        ({"M9": "Released", "M10": "Released"}, "0.10.0"),
    ],
)
def test_version_following_the_register(
    tree: Callable[..., Any],
    tool: ModuleType,
    tmp_path: Path,
    statuses: dict[str, str],
    version: str,
) -> None:
    matrix = tree(statuses, version)
    assert tool.version_failures(matrix) == []
    assert ("Software version", []) in tool.check_failures(
        matrix, tool.Layout(tmp_path), tool.render(matrix)
    )


@pytest.mark.parametrize(
    "version",
    ["0.0.1", "0.1.0", "0.1.0.dev1", "0.2.0.dev0", "0.1.0dev0", "v0.1.0.dev0", "0.1.0.dev0 ", ""],
)
def test_version_not_following_a_milestone_in_progress(
    tree: Callable[..., Any], tool: ModuleType, version: str
) -> None:
    matrix = tree(M1_IN_PROGRESS, version)
    assert tool.version_failures(matrix) == expected_dev(version, "0.1.0.dev0 (M1 In progress)")


def test_example_message_of_the_design(tree: Callable[..., Any], tool: ModuleType) -> None:
    matrix = tree(M1_IN_PROGRESS, "0.0.1")
    assert tool.version_failures(matrix)[0] == (
        "dsp/pyproject.toml: version 0.0.1, expected 0.1.0.dev0 (M1 In progress)"
    )


@pytest.mark.parametrize(
    "version",
    ["0.1.01", "0.1.00", "0.1", "0.1.0.dev0", "0.1.0.post1", "0.1.0rc1", "0.0.1", "0.2.0", "1.1.0"],
)
def test_version_not_following_the_last_release(
    tree: Callable[..., Any], tool: ModuleType, version: str
) -> None:
    matrix = tree(M1_RELEASED, version)
    form = "0.1.P with P = 0, 1, 2, ... (M1 Released, none In progress)"
    assert tool.version_failures(matrix) == expected_dev(version, form)


def test_register_without_a_milestone_in_progress_or_released(
    tree: Callable[..., Any], tool: ModuleType
) -> None:
    matrix = tree({"M0": "Planned", "M1": "Planned"}, "0.0.1")
    assert tool.version_failures(matrix) == [
        "milestones.md: no milestone is In progress or Released, so no version fits"
    ]


def test_the_two_files_disagree(tree: Callable[..., Any], tool: ModuleType) -> None:
    matrix = tree(M1_RELEASED, pyproject=pyproject_text("0.1.0"), init=init_text("0.1.1"))
    assert tool.version_failures(matrix) == [
        f"{INIT}: version 0.1.1, expected 0.1.0 (as in {PYPROJECT})"
    ]
    matrix = tree(M1_IN_PROGRESS, pyproject=pyproject_text("0.1.0.dev0"), init=init_text("0.0.1"))
    assert tool.version_failures(matrix) == [
        f"{INIT}: version 0.0.1, expected 0.1.0.dev0 (M1 In progress)",
        f"{INIT}: version 0.0.1, expected 0.1.0.dev0 (as in {PYPROJECT})",
    ]


def test_rule_is_part_of_check(tree: Callable[..., Any], tool: ModuleType, tmp_path: Path) -> None:
    matrix = tree(M1_IN_PROGRESS, "0.0.1")
    failures = dict(tool.check_failures(matrix, tool.Layout(tmp_path), tool.render(matrix)))
    assert failures["Software version"] == expected_dev("0.0.1", "0.1.0.dev0 (M1 In progress)")


def test_rule_does_not_change_the_matrix(tree: Callable[..., Any], tool: ModuleType) -> None:
    assert tool.render(tree(M1_IN_PROGRESS, "0.1.0.dev0")) == tool.render(
        tree(M1_IN_PROGRESS, "0.0.1")
    )


# --- the release gate -----------------------------------------------------------------------


def test_release_gate_rejects_a_development_version(
    tree: Callable[..., Any], tool: ModuleType
) -> None:
    matrix = tree(M1_IN_PROGRESS, "0.1.0.dev0")
    assert tool.release_gate_failures(matrix) == [
        f"{PYPROJECT}: version 0.1.0.dev0 is a development version, not a release"
    ]


def test_release_gate_names_each_development_version(
    tree: Callable[..., Any], tool: ModuleType
) -> None:
    matrix = tree(
        M1_IN_PROGRESS, pyproject=pyproject_text("0.1.0.dev0"), init=init_text("0.1.dev3")
    )
    assert tool.release_gate_failures(matrix) == [
        f"{PYPROJECT}: version 0.1.0.dev0 is a development version, not a release",
        f"{INIT}: version 0.1.dev3 is a development version, not a release",
    ]


@pytest.mark.parametrize("version", ["0.1.0", "0.1.1"])
def test_release_gate_accepts_a_release_version(
    tree: Callable[..., Any], tool: ModuleType, version: str
) -> None:
    matrix = tree(M1_RELEASED, version)
    assert tool.release_gate_failures(matrix) == []
    assert tool.version_failures(matrix) == []


def test_release_gate_without_a_readable_version(
    tree: Callable[..., Any], tool: ModuleType
) -> None:
    matrix = tree(M1_RELEASED, pyproject=pyproject_text("0.1.0"), init='"""No version."""\n')
    assert tool.release_gate_failures(matrix) == [
        f"{INIT}: __version__ assigned 0 times, expected once"
    ]
