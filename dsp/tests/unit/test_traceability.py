"""Unit tests of scripts/traceability.py on fixture trees: the rules of ``--check``, the release
gate, the matrix and the command line.

The rules and their rationale are in docs/adr/0004-test-tagging-and-traceability-gates.md.
Each test starts from a small repository tree under ``tmp_path`` that passes every rule
(fixture ``tree``), changes it in one way and compares what the script reports with the
expected items, so that each failure is shown to come from that change alone. The script is
loaded as a module and run on the tree through its ``Layout``; the command line runs in-process
with the tree as the repository root, and once as a command from a copy of the script placed in
a tree. The software version rule has its own tests in test_traceability_version.py; here every
tree carries a version that fits its register.

The requirement IDs and tags of the fixture trees are text in this file. The real check reads
IDs only from production code, and counts a requirement tag in this folder only if it is code,
so it sees none of them (``test_the_real_check_reads_nothing_from_this_file``).
"""

import importlib.util
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "traceability.py"
REPO_ROOT = Path(__file__).resolve().parents[3]

OUTPUT = "docs/regulatory/traceability.md"
REGISTER = "docs/regulatory/milestones.md"

# The rules of --check, as the script names them, in the order it reports them.
STALE = f"{OUTPUT} is stale"
FIELDS = "Requirement or milestone register errors"
UNKNOWN = "Unknown requirement IDs referenced in code or tests"
INDEPENDENCE = "Requirement tags outside tests/requirements/ or tests/system/ (independence rule)"
CPP_TAGS = "Malformed or dangling C++ requirement tags"
LEVEL = "Tests in the wrong folder for the requirement's verification level"
UNTESTED = "Implemented requirements without a verifying test"
DANGLING = "Open points citing undefined IDs"
DUPLICATE = "Duplicate open point IDs"
VERSION = "Software version"
RULES = [STALE, FIELDS, UNKNOWN, INDEPENDENCE, CPP_TAGS, LEVEL, UNTESTED, DANGLING, DUPLICATE]

STALE_ITEM = "run: python dsp/scripts/traceability.py"
DEV_ITEM = "dsp/pyproject.toml: version 0.1.0.dev0 is a development version, not a release"
NO_MILESTONE = "no '**Milestone:** Mn' line"
BAD_LEVEL = "the '**Verification level:**' line must start with Requirement or System"
MALFORMED = "malformed tag, expected '// Verifies: SRS-nnn' or '// Verifies: SRS-nnn, SRS-nnn'"
RESERVED = "'Verifies:' is reserved for a '// Verifies: SRS-nnn' comment on its own line"
DANGLING_TAG = (
    "tag not directly followed by a GoogleTest TEST, TEST_F, TEST_P, TYPED_TEST or TYPED_TEST_P"
)

REQ_CPP = "libs/sinus-dsp/tests/requirements/qrs_test.cpp"
SYS_CPP = "libs/sinus-dsp/tests/system/qrs_test.cpp"
CPP_TEST = "TEST(Qrs, Detects) {\n}\n"


# --- fixture texts --------------------------------------------------------------------------


def requirement(
    req_id: str,
    title: str = "",
    *,
    milestone: str | None = "M1",
    level: str | None = "Requirement",
    extra: str = "",
) -> str:
    """An srs.md entry; a field given as ``None`` has no line."""
    heading = title or f"Title of {req_id}"
    lines = [f"### {req_id}: {heading}", "", "The software shall work.", ""]
    if milestone is not None:
        lines.append(f"**Milestone:** {milestone}".rstrip())
    if level is not None:
        lines.append(f"**Verification level:** {level}".rstrip())
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


SRS_HEAD = (
    "# Software requirements specification\n\n## Conventions\n\n"
    "**Milestone:** M9 (a line before the first requirement belongs to no entry)\n\n"
    "## Requirements\n\n"
)


def marked(name: str, *ids: str) -> str:
    """A test function with a requirement marker, the decorator on its first line."""
    args = ", ".join(f'"{i}"' for i in ids)
    return f"@pytest.mark.requirement({args})\ndef {name}() -> None:\n    pass\n"


def python_test_file(*tests: str) -> str:
    """A test module importing pytest; the first test starts on line 4, the next on line 9."""
    return "import pytest\n\n\n" + "\n\n".join(tests)


def cpp_test(*tags: str, test: str = CPP_TEST) -> str:
    """A GoogleTest source: the tag lines, then the test."""
    return "".join(f"{tag}\n" for tag in tags) + test


BASE_STATUSES = {"M0": "Released", "M1": "In progress", "M2": "Planned"}
BASE_REQUIREMENTS = (
    requirement("SRS-001", "Remove baseline wander"),
    requirement("SRS-002", "Detection performance", level="System"),
    requirement("SRS-003", "Later feature", milestone="M2"),
)
BASE_RISK = ("HAZ-001", "RC-001")
BASE_OPEN = (("OP-001", "SRS-003, HAZ-001", "M2"),)
BASE_CLOSED = (("OP-002", "SRS-001, RC-001"),)
BASE_FILES = {
    "dsp/pyproject.toml": '[project]\nname = "sinus-dsp"\nversion = "0.1.0.dev0"\n',
    "dsp/sinus_dsp/__init__.py": '"""Package."""\n\n__version__ = "0.1.0.dev0"\n',
    "dsp/sinus_dsp/filters.py": (
        '"""Filters."""\n\n\n# SRS-001: remove the baseline wander.\ndef remove() -> None:\n'
        "    pass\n"
    ),
    "dsp/scripts/validate.py": '"""Validation run (SRS-002)."""\n',
    "dsp/tests/requirements/test_srs_001.py": python_test_file(
        marked("test_removes_wander", "SRS-001")
    ),
    "dsp/tests/system/test_srs_002.py": python_test_file(marked("test_detects_beats", "SRS-002")),
    "dsp/tests/unit/test_filters.py": "def test_remove() -> None:\n    pass\n",
}
BASE_PY_TEST = "dsp/tests/requirements/test_srs_001.py::test_removes_wander"

# The matrix of the base tree, written out by hand.
BASE_MATRIX = """\
# Traceability matrix

<!-- Generated by dsp/scripts/traceability.py. Do not edit by hand. -->

Rules: [ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md). \
Milestone status: [`milestones.md`](milestones.md).

| Requirement | Title | Milestone | Verification level | Implemented in | Verified by \
| Open points |
|---|---|---|---|---|---|---|
| SRS-001 | Remove baseline wander | M1 | Requirement | `dsp/sinus_dsp/filters.py:4` \
| `dsp/tests/requirements/test_srs_001.py::test_removes_wander` | — |
| SRS-002 | Detection performance | M1 | System | `dsp/scripts/validate.py:1` \
| `dsp/tests/system/test_srs_002.py::test_detects_beats` | — |
| SRS-003 | Later feature | M2 | Requirement | — | **none** | OP-001 |

## Milestones

| Milestone | Title | Status | Requirements | With a verifying test | Release gate |
|---|---|---|---|---|---|
| M0 | Title of M0 | Released | 0 | 0 | pass |
| M1 | Title of M1 | In progress | 2 | 2 | pass |
| M2 | Title of M2 | Planned | 1 | 0 | not applied |

## Gaps

- Requirements without tests: SRS-003
- Implemented requirements without tests: none
- Unknown IDs referenced in code/tests: none
- Open points citing undefined IDs: none
- Open points still open: 1 (see `open-points.md`)
"""


class Tree:
    """A repository tree that passes every rule of ``--check`` until a test changes it."""

    def __init__(self, root: Path, tool: ModuleType) -> None:
        self.root = root
        self.tool = tool
        self.layout: Any = tool.Layout(root)
        for rel, text in BASE_FILES.items():
            self.write(rel, text)
        self.srs(*BASE_REQUIREMENTS)
        self.register(BASE_STATUSES)
        self.risk(*BASE_RISK)
        self.open_points(BASE_OPEN, BASE_CLOSED)

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def srs(self, *entries: str) -> None:
        self.write("docs/regulatory/srs.md", SRS_HEAD + "\n".join(entries))

    def register(self, statuses: dict[str, str], extra_rows: Sequence[str] = ()) -> None:
        rows = [f"| {ms} | Title of {ms} | {status} |" for ms, status in statuses.items()]
        head = "# Milestones\n\n## Register\n\n| Milestone | Title | Status |\n|---|---|---|\n"
        self.write(REGISTER, head + "".join(f"{row}\n" for row in [*rows, *extra_rows]))

    def risk(self, *ids: str) -> None:
        rows = "".join(f"| {i} | Description of {i} |\n" for i in ids)
        self.write(
            "docs/regulatory/risk-analysis.md",
            f"# Risk analysis\n\n| ID | Item |\n|---|---|\n{rows}",
        )

    def open_points(
        self,
        open_rows: Sequence[tuple[str, str, str]],
        closed_rows: Sequence[tuple[str, str]] = (),
    ) -> None:
        """Rows (ID, refs, target) under "## Open" and (ID, refs) under "## Closed"."""
        lines = ["# Open points", "", "## Conventions", "", "- One row per point.", "", "## Open"]
        lines += [
            "",
            "| ID | Open point | Refs | Opened | Target | Status |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {op} | Point {op}. | {refs} | 2026-01-01 | {target} | Open |"
            for op, refs, target in open_rows
        ]
        lines += ["", "## Closed", "", "| ID | Open point | Refs | Opened | Closed | Resolution |"]
        lines += ["|---|---|---|---|---|---|"]
        lines += [
            f"| {op} | Point {op}. | {refs} | 2026-01-01 | 2026-01-02 | Done. |"
            for op, refs in closed_rows
        ]
        self.write("docs/regulatory/open-points.md", "\n".join(lines) + "\n")

    def version(self, version: str) -> None:
        self.write("dsp/pyproject.toml", f'[project]\nname = "sinus-dsp"\nversion = "{version}"\n')
        self.write("dsp/sinus_dsp/__init__.py", f'"""Package."""\n\n__version__ = "{version}"\n')

    def release(self) -> None:
        """Mark M1 Released, with the version of its release."""
        self.register({"M0": "Released", "M1": "Released", "M2": "Planned"})
        self.version("0.1.0")

    def matrix(self) -> Any:
        return self.tool.build(self.layout)

    def render(self) -> str:
        text: str = self.tool.render(self.matrix())
        return text

    def update(self) -> None:
        """Write the matrix, as the script does without options."""
        self.write(OUTPUT, self.render())

    def check(self, *, update: bool = True) -> dict[str, list[str]]:
        """The rules of ``--check`` that fail, with their items; the matrix is written first
        unless ``update`` is false."""
        if update:
            self.update()
        matrix = self.matrix()
        failures = self.tool.check_failures(matrix, self.layout, self.tool.render(matrix))
        return {rule: items for rule, items in failures if items}

    def gate(self) -> list[str]:
        items: list[str] = self.tool.release_gate_failures(self.matrix())
        return items

    def test_names(self, req_id: str) -> list[str]:
        return [test.name for test in self.matrix().tests.get(req_id, [])]


@pytest.fixture(scope="module")
def tool() -> Iterator[ModuleType]:
    name = "traceability_rules_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # the dataclasses of the script look their module up
    spec.loader.exec_module(module)
    yield module
    del sys.modules[name]


@pytest.fixture
def tree(tmp_path: Path, tool: ModuleType) -> Tree:
    return Tree(tmp_path / "repo", tool)


# --- layout and the base tree ---------------------------------------------------------------


def test_layout_paths(tool: ModuleType, tmp_path: Path) -> None:
    layout = tool.Layout(tmp_path)
    regulatory = tmp_path / "docs" / "regulatory"
    assert layout.regulatory == regulatory
    assert (layout.srs, layout.milestones, layout.risk, layout.open_points, layout.output) == (
        regulatory / "srs.md",
        regulatory / "milestones.md",
        regulatory / "risk-analysis.md",
        regulatory / "open-points.md",
        regulatory / "traceability.md",
    )
    assert layout.python_code_roots == [
        tmp_path / "dsp" / "sinus_dsp",
        tmp_path / "dsp" / "scripts",
    ]
    assert layout.python_test_roots == [tmp_path / "dsp" / "tests"]
    assert layout.cpp_roots == [tmp_path / "libs", tmp_path / "firmware", tmp_path / "desktop"]
    assert layout.rel(tmp_path / "a" / "b.py") == "a/b.py"


def test_repository_root_is_two_folders_above_the_script(tool: ModuleType) -> None:
    assert tool.REPO_ROOT == REPO_ROOT


def test_base_tree_passes_every_rule(tree: Tree) -> None:
    assert tree.check() == {}
    assert tree.render() == BASE_MATRIX


def test_check_lists_its_rules_in_order(tree: Tree, tool: ModuleType) -> None:
    matrix = tree.matrix()
    rules = [rule for rule, _ in tool.check_failures(matrix, tree.layout, tool.render(matrix))]
    assert rules == [*RULES, VERSION]


def test_base_tree_release_gate(tree: Tree) -> None:
    assert tree.gate() == [DEV_ITEM]
    tree.release()
    assert tree.gate() == []
    assert tree.check() == {}


# --- sources: files and folders -------------------------------------------------------------


def test_sources_are_listed_in_sorted_order(tool: ModuleType, tmp_path: Path) -> None:
    for rel in ["b.py", "a.py", "z/c.py", "m/d.py", "m/a.txt", "m/n/e.py", "a.pyc", "f.py.txt"]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    found = [p.relative_to(tmp_path).as_posix() for p in tool.iter_sources(tmp_path, (".py",))]
    assert found == ["a.py", "b.py", "m/d.py", "m/n/e.py", "z/c.py"]


def test_absent_root_has_no_sources(tool: ModuleType, tmp_path: Path) -> None:
    assert list(tool.iter_sources(tmp_path / "absent", (".py",))) == []


@pytest.mark.parametrize(
    "folder",
    [
        "build",
        "_deps",
        "managed_components",
        "third_party",
        "external",
        "vendor",
        ".git",
        ".venv",
        "build-esp32s3",
        "cmake-build-debug",
    ],
)
def test_build_and_third_party_folders_are_not_read(tree: Tree, folder: str) -> None:
    tree.write(f"dsp/sinus_dsp/{folder}/generated.py", "# SRS-099\n")
    tree.write(f"dsp/scripts/{folder}/generated.py", "# SRS-099\n")
    tree.write(f"libs/sinus-dsp/{folder}/generated.cpp", "// SRS-099\n// Verifies: nothing\n")
    tree.write(f"firmware/{folder}/x/generated.h", "// Verifies: SRS-099\n")
    tree.write(
        f"dsp/tests/unit/{folder}/test_generated.py", python_test_file(marked("test_g", "SRS-099"))
    )
    tree.write(
        f"dsp/tests/requirements/{folder}/test_generated.py",
        python_test_file(marked("test_g", "SRS-099")),
    )
    assert tree.check() == {}


@pytest.mark.parametrize(
    "folder", ["builder", "vendors", "rebuild", "external_api", "x.build", "deps"]
)
def test_folders_with_similar_names_are_read(tree: Tree, folder: str) -> None:
    tree.write(f"dsp/sinus_dsp/{folder}/module.py", "# SRS-099\n")
    assert tree.check() == {UNKNOWN: ["SRS-099"]}


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("libs/sinus-dsp/tests/x.cpp", True),
        ("libs/sinus-dsp/tests/requirements/x.cpp", True),
        ("libs/sinus-dsp/test/x.cpp", True),
        ("firmware/test_apps/main/x.c", True),
        ("firmware/components/a/test/x.c", True),
        ("tests/x.cpp", True),
        ("libs/sinus-dsp/src/x.cpp", False),
        ("libs/sinus-dsp/src/tests.cpp", False),
        ("libs/sinus-dsp/src/test.cpp", False),
        ("libs/sinus-dsp/testing/x.cpp", False),
        ("libs/sinus-dsp/unit_tests/x.cpp", False),
        ("libs/sinus-dsp/test_data/x.cpp", False),
    ],
)
def test_test_folders(tool: ModuleType, tmp_path: Path, rel: str, expected: bool) -> None:
    assert tool.is_test_path(tmp_path / rel, tool.Layout(tmp_path)) is expected


@pytest.mark.parametrize(
    ("rel", "level"),
    [
        ("dsp/tests/requirements/test_a.py", "Requirement"),
        ("dsp/tests/system/test_a.py", "System"),
        ("dsp/tests/requirements/sub/test_a.py", "Requirement"),
        ("libs/sinus-dsp/tests/system/a_test.cpp", "System"),
        ("firmware/tests/requirements/a_test.cpp", "Requirement"),
        ("dsp/tests/unit/test_a.py", None),
        ("dsp/tests/test_a.py", None),
        ("dsp/tests/unit/requirements/test_a.py", None),
        ("dsp/tests/integration/system/test_a.py", None),
        ("dsp/requirements/test_a.py", None),
        ("firmware/test/requirements/a_test.c", None),
        ("dsp/tests/requirements.py", None),
        ("dsp/tests/requirements_old/test_a.py", None),
    ],
)
def test_folder_level(tool: ModuleType, tmp_path: Path, rel: str, level: str | None) -> None:
    assert tool.folder_level(tmp_path / rel, tool.Layout(tmp_path)) == level


def test_folder_names_above_the_root_do_not_count(tool: ModuleType, tmp_path: Path) -> None:
    root = tmp_path / "tests"
    layout = tool.Layout(root)
    assert tool.folder_level(root / "requirements" / "test_a.py", layout) is None
    assert tool.is_test_path(root / "src" / "a.cpp", layout) is False


# --- requirements and the milestone register ------------------------------------------------


def test_requirements_are_read_from_their_headings(tree: Tree, tool: ModuleType) -> None:
    tree.srs(
        "## SRS-010 — Two hashes and a dash\n\n**Milestone:** M1\n"
        "**Verification level:** Requirement\n",
        "#### SRS-011:Four hashes\n\n**Milestone:** M2\n"
        "**Verification level:** System (test engineer)\n",
        "##### SRS-012: Five hashes are not a requirement heading\n\n**Milestone:** M1\n",
        "# SRS-013: One hash is not either\n",
        "### SRS-014\n\n  **Milestone:** M1  \n**Verification level:**Requirement, by QA\n",
        "### SRS-015: Removed\n\n_Deleted_: merged into SRS-010.\n",
    )
    requirements, errors = tool.parse_requirements(tree.layout)
    assert errors == []
    found = {r.id: (r.title, r.milestone, r.level, r.deleted) for r in requirements.values()}
    assert found == {
        "SRS-010": ("Two hashes and a dash", "M1", "Requirement", False),
        "SRS-011": ("Four hashes", "M2", "System", False),
        "SRS-014": ("", "M1", "Requirement", False),
        "SRS-015": ("Removed", None, None, True),
    }


def test_an_entry_ends_at_the_next_heading(tree: Tree, tool: ModuleType) -> None:
    tree.srs(
        "### SRS-001: Entry\n\n**Verification level:** Requirement\n\n#### Notes\n\n"
        "**Milestone:** M1\n",
        *BASE_REQUIREMENTS[1:],
    )
    requirements, _ = tool.parse_requirements(tree.layout)
    assert requirements["SRS-001"].milestone is None
    assert tree.check() == {FIELDS: [f"SRS-001: {NO_MILESTONE}"]}


@pytest.mark.parametrize(
    ("entry", "item"),
    [
        (requirement("SRS-004", milestone=None), f"SRS-004: {NO_MILESTONE}"),
        (requirement("SRS-004", milestone=""), f"SRS-004: {NO_MILESTONE}"),
        (requirement("SRS-004", milestone="M9"), "SRS-004: milestone 'M9' is not in milestones.md"),
        (requirement("SRS-004", milestone="m1"), "SRS-004: milestone 'm1' is not in milestones.md"),
        (
            requirement("SRS-004", milestone="M1, M2"),
            "SRS-004: milestone 'M1, M2' is not in milestones.md",
        ),
        (requirement("SRS-004", level=None), f"SRS-004: {BAD_LEVEL}"),
        (requirement("SRS-004", level=""), f"SRS-004: {BAD_LEVEL}"),
        (requirement("SRS-004", level="Inspection"), f"SRS-004: {BAD_LEVEL}"),
        (requirement("SRS-004", level="requirement"), f"SRS-004: {BAD_LEVEL}"),
        (requirement("SRS-004", level="Requirements"), f"SRS-004: {BAD_LEVEL}"),
        (requirement("SRS-004", level="QA Requirement"), f"SRS-004: {BAD_LEVEL}"),
        (requirement("SRS-004", level="(System)"), f"SRS-004: {BAD_LEVEL}"),
    ],
)
def test_requirement_without_a_valid_field(tree: Tree, entry: str, item: str) -> None:
    tree.srs(*BASE_REQUIREMENTS, entry)
    assert tree.check() == {FIELDS: [item]}


def test_requirement_without_both_fields(tree: Tree) -> None:
    tree.srs(
        requirement("SRS-005", level="Unknown"),
        *BASE_REQUIREMENTS,
        requirement("SRS-004", milestone=None, level=None),
    )
    assert tree.check() == {
        FIELDS: [f"SRS-004: {NO_MILESTONE}", f"SRS-004: {BAD_LEVEL}", f"SRS-005: {BAD_LEVEL}"]
    }


@pytest.mark.parametrize(
    "level",
    [
        "Requirement",
        "System",
        "Requirement (QA)",
        "System, on the reference database",
        "Requirement — functional test",
    ],
)
def test_verification_level_is_the_first_word(tree: Tree, level: str) -> None:
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004", level=level))
    assert tree.check() == {}


@pytest.mark.parametrize(
    "entry",
    [
        "### SRS-004: _Deleted_\n",
        "### SRS-004: Old title\n\n_Deleted_ on 2026-01-01: merged into SRS-001.\n",
        requirement("SRS-004", milestone="M9", level="Unknown", extra="_Deleted_"),
        requirement("SRS-004", milestone=None, level=None, extra="Status: _Deleted_"),
    ],
)
def test_deleted_requirement_needs_no_fields(tree: Tree, entry: str) -> None:
    tree.srs(*BASE_REQUIREMENTS, entry)
    assert tree.check() == {}
    tree.release()
    assert tree.gate() == []


def test_requirement_defined_twice(tree: Tree, tool: ModuleType) -> None:
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-001", "Second definition", milestone=None))
    assert tree.check() == {FIELDS: ["SRS-001: defined more than once in srs.md"]}
    requirements, _ = tool.parse_requirements(tree.layout)
    assert requirements["SRS-001"].title == "Remove baseline wander"


def test_absent_srs(tree: Tree, tool: ModuleType) -> None:
    tree.layout.srs.unlink()
    assert tool.parse_requirements(tree.layout) == ({}, [])
    assert tree.check() == {
        UNKNOWN: ["SRS-001", "SRS-002"],
        DANGLING: ["OP-001→SRS-003", "OP-002→SRS-001"],
    }


@pytest.mark.parametrize(
    ("row", "item"),
    [
        ("| M3 | Title of M3 |", "row M3 needs the columns Milestone, Title, Status"),
        ("| M3 |", "row M3 needs the columns Milestone, Title, Status"),
        ("| M1 | Again | Planned |", "milestone M1 listed more than once"),
        ("| M1 | Again | Done |", "milestone M1 listed more than once"),
        (
            "| M3 | Title | Done |",
            "milestone M3 has status 'Done', expected one of: Planned, In progress, Released",
        ),
        (
            "| M3 | Title | released |",
            "milestone M3 has status 'released', expected one of: Planned, In progress, Released",
        ),
        (
            "| M3 | Title | In Progress |",
            "milestone M3 has status 'In Progress', expected one of: Planned, In progress, "
            "Released",
        ),
        (
            "| M3 | Title | |",
            "milestone M3 has status '', expected one of: Planned, In progress, Released",
        ),
    ],
)
def test_milestone_register_errors(tree: Tree, row: str, item: str) -> None:
    tree.register(BASE_STATUSES, [row])
    assert tree.check() == {FIELDS: [f"{REGISTER}: {item}"]}


def test_register_reads_only_milestone_rows(tree: Tree, tool: ModuleType) -> None:
    tree.register(
        BASE_STATUSES,
        [
            "Text that names | M3 | Planned | in a sentence.",
            "| M | No number | Planned |",
            "| Mx | Letter | Planned |",
            "| m4 | Lower case | Planned |",
            "|M5|Compact|Planned|",
            "   | M6 | Indented | Released |   ",
        ],
    )
    milestones, errors = tool.parse_milestones(tree.layout)
    assert errors == []
    assert {ms.id: (ms.title, ms.status) for ms in milestones.values()} == {
        "M0": ("Title of M0", "Released"),
        "M1": ("Title of M1", "In progress"),
        "M2": ("Title of M2", "Planned"),
        "M5": ("Compact", "Planned"),
        "M6": ("Indented", "Released"),
    }


def test_absent_register(tree: Tree) -> None:
    tree.root.joinpath(REGISTER).unlink()
    assert tree.check() == {
        FIELDS: [
            f"{REGISTER} not found",
            "SRS-001: milestone 'M1' is not in milestones.md",
            "SRS-002: milestone 'M1' is not in milestones.md",
            "SRS-003: milestone 'M2' is not in milestones.md",
        ],
        VERSION: ["milestones.md: no milestone is In progress or Released, so no version fits"],
    }


def test_requirement_of_a_milestone_with_an_invalid_status(tree: Tree) -> None:
    tree.register(BASE_STATUSES, ["| M3 | Title | Done |"])
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004", milestone="M3"))
    assert tree.check() == {
        FIELDS: [
            f"{REGISTER}: milestone M3 has status 'Done', expected one of: Planned, In progress, "
            "Released",
            "SRS-004: milestone 'M3' is not in milestones.md",
        ]
    }


# --- unknown requirement IDs ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("dsp/sinus_dsp/extra.py", "# SRS-099\n"),
        ("dsp/sinus_dsp/sub/extra.py", '"""Implements SRS-099."""\n'),
        ("dsp/scripts/extra.py", "NAME = 'SRS-099'\n"),
        ("libs/sinus-dsp/src/qrs.cpp", "// SRS-099: detection\n"),
        ("libs/sinus-dsp/include/sinus/qrs.h", "/* (SRS-099) */\n"),
        ("libs/sinus-dsp/src/qrs.hpp", "// SRS-099\n"),
        ("firmware/main/main.c", "// SRS-099\n"),
        ("firmware/components/sinus_dsp/glue.cc", "// SRS-099\n"),
        ("desktop/src/view.cpp", "// SRS-099\n"),
    ],
)
def test_unknown_id_cited_in_code(tree: Tree, rel: str, text: str) -> None:
    tree.write(rel, text)
    assert tree.check() == {UNKNOWN: ["SRS-099"]}


def test_unknown_id_tagged_in_a_python_test(tree: Tree) -> None:
    tree.write(
        "dsp/tests/requirements/test_more.py", python_test_file(marked("test_more", "SRS-099"))
    )
    assert tree.check() == {UNKNOWN: ["SRS-099"]}


@pytest.mark.parametrize(
    "value", ["SRS-1", "SRS-0001", "srs-001", "SRS-001, SRS-002", "SRS-001 ", ""]
)
def test_python_tag_must_hold_exact_ids(tree: Tree, value: str) -> None:
    tree.write("dsp/tests/requirements/test_more.py", python_test_file(marked("test_more", value)))
    assert tree.check() == {UNKNOWN: [value]}


def test_unknown_id_tagged_in_a_cpp_test(tree: Tree) -> None:
    tree.write(REQ_CPP, cpp_test("// Verifies: SRS-099"))
    assert tree.check() == {UNKNOWN: ["SRS-099"]}


def test_unknown_ids_are_listed_once_in_order(tree: Tree) -> None:
    tree.write("dsp/sinus_dsp/a.py", "# SRS-098\n# SRS-098\n")
    tree.write("dsp/scripts/b.py", "# SRS-098, SRS-096\n")
    tree.write("dsp/tests/system/test_more.py", python_test_file(marked("test_more", "SRS-097")))
    tree.write(REQ_CPP, cpp_test("// Verifies: SRS-099, SRS-097"))
    assert tree.check() == {UNKNOWN: ["SRS-096", "SRS-097", "SRS-098", "SRS-099"]}


@pytest.mark.parametrize(
    "text",
    ["SRS-0991", "XSRS-099", "SRS-099a", "SRS-099_x", "SRS-99", "SRS_099", "srs-099", "SRS 099"],
)
def test_text_that_is_not_an_id_is_not_a_citation(tree: Tree, text: str) -> None:
    tree.write("dsp/sinus_dsp/extra.py", f"# {text}\n")
    tree.write("libs/sinus-dsp/src/extra.cpp", f"// {text}\n")
    assert tree.check() == {}


@pytest.mark.parametrize(
    "rel",
    [
        "dsp/tests/unit/test_extra.py",
        "dsp/tests/unit/helpers.py",
        "dsp/tests/conftest.py",
        "dsp/tests/requirements/conftest.py",
        "dsp/tests/requirements/test_extra.py",
        "dsp/sinus_dsp/notes.txt",
        "dsp/sinus_dsp/README.md",
        "dsp/other/extra.py",
        "dsp/extra.py",
        "docs/design.md",
        "README.md",
        "libs/sinus-dsp/tests/unit/extra_test.cpp",
        "libs/sinus-dsp/tests/requirements/extra_test.cpp",
        "libs/sinus-dsp/test/extra_test.cpp",
        "firmware/test_apps/main/extra.c",
        "libs/sinus-dsp/CMakeLists.txt",
        "libs/sinus-dsp/src/extra.cxx",
        "libs/sinus-dsp/src/extra.py",
        "backend/app/extra.py",
    ],
)
def test_ids_outside_production_code_are_not_citations(tree: Tree, rel: str) -> None:
    tree.write(rel, "# SRS-099 and SRS-003\n")
    assert tree.check() == {}


# --- independence: requirement tags only in tests/requirements/ and tests/system/ -----------


@pytest.mark.parametrize(
    "folder",
    [
        "dsp/tests/unit",
        "dsp/tests",
        "dsp/tests/integration",
        "dsp/tests/unit/requirements",
        "dsp/tests/unit/system",
        "dsp/tests/requirements_old",
    ],
)
@pytest.mark.parametrize("name", ["test_tagged.py", "tagged_test.py"])
def test_python_tag_outside_the_verification_folders(tree: Tree, folder: str, name: str) -> None:
    tree.write(f"{folder}/{name}", python_test_file(marked("test_a", "SRS-003")))
    assert tree.check() == {INDEPENDENCE: [f"{folder}/{name}:4"]}
    assert tree.test_names("SRS-003") == []


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        (python_test_file(marked("test_a", "SRS-001")), [4]),
        ('import pytest\n\npytestmark = pytest.mark.requirement("SRS-001")\n', [3]),
        (
            "import pytest\n\npytestmark = [pytest.mark.slow, "
            'pytest.mark.requirement("SRS-001")]\n',
            [3],
        ),
        (
            "from typing import Any\n\nimport pytest\n\n"
            'pytestmark: Any = pytest.mark.requirement("SRS-001")\n',
            [5],
        ),
        (
            'import pytest\n\n\nclass TestA:\n    pytestmark = pytest.mark.requirement("SRS-001")\n'
            "\n    def test_a(self) -> None:\n        pass\n",
            [5],
        ),
        (
            'import pytest\n\n\n@pytest.mark.requirement("SRS-001")\nclass TestA:\n'
            "    def test_a(self) -> None:\n        pass\n",
            [4],
        ),
        (
            'import pytest\n\n\n@pytest.mark.parametrize("x", [pytest.param(1, '
            'marks=pytest.mark.requirement("SRS-001"))])\ndef test_a(x: int) -> None:\n'
            "    pass\n",
            [4],
        ),
        (
            'from pytest import mark\n\n\n@mark.requirement("SRS-001")\ndef test_a() -> None:\n'
            "    pass\n",
            [4],
        ),
        (
            'import pytest\n\n\n@pytest.mark.requirement("SRS-001")\n'
            '@pytest.mark.requirement("SRS-002")\ndef test_a() -> None:\n    pass\n',
            [4, 5],
        ),
        ("import pytest\n\n\n@pytest.mark.requirement()\ndef test_a() -> None:\n    pass\n", [4]),
        (
            'import pytest\n\n\ndef helper() -> None:\n    pytest.mark.requirement("SRS-001")\n',
            [5],
        ),
        (python_test_file(marked("test_a", "SRS-099")), [4]),
    ],
)
def test_every_form_of_a_tag_outside_the_folders(tree: Tree, text: str, lines: list[int]) -> None:
    tree.write("dsp/tests/unit/test_tagged.py", text)
    assert tree.check() == {INDEPENDENCE: [f"dsp/tests/unit/test_tagged.py:{n}" for n in lines]}


def test_misplaced_python_tags_are_listed_in_order(tree: Tree) -> None:
    tree.write("dsp/tests/unit/test_b.py", python_test_file(marked("test_b", "SRS-001")))
    tree.write(
        "dsp/tests/unit/test_a.py",
        python_test_file(marked("test_a", "SRS-001"), marked("test_c", "SRS-002")),
    )
    tree.write("dsp/tests/test_root.py", python_test_file(marked("test_r", "SRS-001")))
    assert tree.check() == {
        INDEPENDENCE: [
            "dsp/tests/test_root.py:4",
            "dsp/tests/unit/test_a.py:4",
            "dsp/tests/unit/test_a.py:9",
            "dsp/tests/unit/test_b.py:4",
        ]
    }


@pytest.mark.parametrize("name", ["conftest.py", "helpers.py", "tagged_tests.py", "testtagged.py"])
def test_only_pytest_test_files_are_read(tree: Tree, name: str) -> None:
    tree.write(f"dsp/tests/unit/{name}", python_test_file(marked("test_a", "SRS-099")))
    tree.write(f"dsp/tests/requirements/{name}", python_test_file(marked("test_a", "SRS-099")))
    assert tree.check() == {}


@pytest.mark.parametrize(
    ("folder", "code"),
    [
        ("libs/sinus-dsp/tests/unit", False),
        ("libs/sinus-dsp/tests", False),
        ("libs/sinus-dsp/test", False),
        ("firmware/test", False),
        ("firmware/test_apps/main", False),
        ("firmware/tests/integration", False),
        ("desktop/tests/unit/requirements", False),
        ("libs/sinus-dsp/src", True),
        ("desktop/src", True),
    ],
)
def test_cpp_tag_outside_the_verification_folders(tree: Tree, folder: str, code: bool) -> None:
    rel = f"{folder}/qrs_test.cpp"
    tree.write(rel, cpp_test("// Verifies: SRS-003"))
    expected = {INDEPENDENCE: [f"{rel}:1"]}
    if code:  # outside a test folder the tag is also a citation in production code
        expected[UNTESTED] = [f"SRS-003: cited in `{rel}:1`"]
    assert tree.check() == expected
    assert tree.test_names("SRS-003") == []


@pytest.mark.parametrize("root", ["libs/sinus-dsp", "firmware", "desktop"])
def test_cpp_tags_in_the_verification_folders(tree: Tree, root: str) -> None:
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004", level="System"))
    tree.write(f"{root}/tests/requirements/later_test.cpp", cpp_test("// Verifies: SRS-003"))
    tree.write(f"{root}/tests/system/sub/later_test.cpp", cpp_test("// Verifies: SRS-004"))
    assert tree.check() == {}
    matrix = tree.matrix()
    assert matrix.tests["SRS-003"] == [
        tree.tool.TestRef(f"{root}/tests/requirements/later_test.cpp::Qrs.Detects", "Requirement")
    ]
    assert matrix.tests["SRS-004"] == [
        tree.tool.TestRef(f"{root}/tests/system/sub/later_test.cpp::Qrs.Detects", "System")
    ]


# --- Python tests: what counts as a verifying test ------------------------------------------

DETECTOR_TESTS = """\
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.requirement("SRS-001")]


@pytest.mark.requirement("SRS-003")
def test_module_level() -> None:
    pass


@pytest.mark.requirement("SRS-003")
def helper_not_a_test() -> None:
    pass


@pytest.mark.requirement("SRS-004")
class TestDetector:
    pytestmark = pytest.mark.requirement("SRS-005")

    def test_method(self) -> None:
        pass

    @pytest.mark.requirement("SRS-001", "SRS-003")
    async def test_async(self) -> None:
        pass

    def helper(self) -> None:
        pass

    class TestInner:
        def test_inner(self) -> None:
            pass


def testing_prefix() -> None:
    pass
"""


def test_python_tests_are_named_by_path_class_and_function(tree: Tree, tool: ModuleType) -> None:
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004"), requirement("SRS-005"))
    tree.write("dsp/tests/requirements/test_detector.py", DETECTOR_TESTS)
    refs, misplaced = tool.scan_python_tests(tree.layout)
    assert misplaced == []
    path = "dsp/tests/requirements/test_detector.py"
    method, inner = (
        f"{path}::TestDetector::test_method",
        f"{path}::TestDetector::TestInner::test_inner",
    )
    is_async, prefix = f"{path}::TestDetector::test_async", f"{path}::testing_prefix"
    assert {req: [t.name for t in tests] for req, tests in refs.items()} == {
        "SRS-001": [f"{path}::test_module_level", method, is_async, inner, prefix, BASE_PY_TEST],
        "SRS-002": ["dsp/tests/system/test_srs_002.py::test_detects_beats"],
        "SRS-003": [f"{path}::test_module_level", is_async],
        "SRS-004": [method, is_async, inner],
        "SRS-005": [method, is_async, inner],
    }
    assert {t.level for tests in refs.values() for t in tests} == {"Requirement", "System"}
    assert tree.check() == {}


def test_annotated_pytestmark_is_read(tree: Tree) -> None:
    text = (
        "from typing import Any\n\nimport pytest\n\n"
        'pytestmark: list[Any] = [pytest.mark.requirement("SRS-003")]\n\n\n'
        "class TestLater:\n"
        '    pytestmark: Any = pytest.mark.requirement("SRS-001")\n'
        "    other: Any\n\n"
        "    def test_a(self) -> None:\n        pass\n\n\n"
        "def test_b() -> None:\n    pass\n"
    )
    tree.write("dsp/tests/requirements/test_later.py", text)
    path = "dsp/tests/requirements/test_later.py"
    assert tree.test_names("SRS-003") == [f"{path}::TestLater::test_a", f"{path}::test_b"]
    assert tree.test_names("SRS-001") == [f"{path}::TestLater::test_a", BASE_PY_TEST]


def test_annotation_without_a_value_is_not_a_mark(tree: Tree) -> None:
    text = (
        "from typing import Any\n\nimport pytest\n\npytestmark: Any\n\n\n"
        "def test_b() -> None:\n    pass\n"
    )
    tree.write("dsp/tests/requirements/test_later.py", text)
    assert tree.test_names("SRS-003") == []
    assert tree.check() == {}


def test_only_test_classes_are_read(tree: Tree) -> None:
    """pytest collects only classes whose name starts with ``Test`` (nested ones included), so
    a test in any other class never runs and verifies nothing."""
    text = (
        "import pytest\n\n\n"
        '@pytest.mark.requirement("SRS-003")\n'
        "class Checks:\n    def test_a(self) -> None:\n        pass\n\n\n"
        "class Helpers:\n"
        '    pytestmark = pytest.mark.requirement("SRS-003")\n\n'
        '    @pytest.mark.requirement("SRS-003")\n'
        "    def test_b(self) -> None:\n        pass\n\n\n"
        "class TestOuter:\n"
        "    class Inner:\n"
        '        @pytest.mark.requirement("SRS-003")\n'
        "        def test_c(self) -> None:\n            pass\n"
    )
    tree.write("dsp/tests/requirements/test_later.py", text)
    assert tree.test_names("SRS-003") == []
    tree.write("dsp/sinus_dsp/later.py", "# SRS-003\n")
    assert tree.check() == {UNTESTED: ["SRS-003: cited in `dsp/sinus_dsp/later.py:1`"]}


def test_marks_outside_tests_and_test_classes_are_not_read(tree: Tree) -> None:
    text = (
        "import pytest\n\n\n"
        '@pytest.mark.parametrize("x", [pytest.param(1, marks=pytest.mark.requirement("SRS-003")'
        ")])\n"
        "def test_a(x: int) -> None:\n    pass\n\n\n"
        "def test_b() -> None:\n"
        '    @pytest.mark.requirement("SRS-003")\n'
        "    def test_nested() -> None:\n        pass\n"
    )
    tree.write("dsp/tests/requirements/test_later.py", text)
    assert tree.test_names("SRS-003") == []


def test_a_test_tagged_twice_is_listed_once(tree: Tree) -> None:
    text = (
        'import pytest\n\npytestmark = pytest.mark.requirement("SRS-003")\n\n\n'
        '@pytest.mark.requirement("SRS-003", "SRS-003")\n'
        '@pytest.mark.requirement("SRS-003")\n'
        "def test_a() -> None:\n    pass\n"
    )
    tree.write("dsp/tests/requirements/test_later.py", text)
    assert tree.test_names("SRS-003") == ["dsp/tests/requirements/test_later.py::test_a"]


# --- C++ tags -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "name"),
    [
        (cpp_test("// Verifies: SRS-001"), "Qrs.Detects"),
        (cpp_test("// Verifies: SRS-001", test="TEST_F(QrsTest, Detects) {}\n"), "QrsTest.Detects"),
        (
            cpp_test("// Verifies: SRS-001", test="TEST_P(QrsParam, Detects) {}\n"),
            "QrsParam.Detects",
        ),
        (
            cpp_test("// Verifies: SRS-001", test="TYPED_TEST(QrsTyped, Detects) {}\n"),
            "QrsTyped.Detects",
        ),
        (
            cpp_test("// Verifies: SRS-001", test="TYPED_TEST_P(QrsTypedP, Detects) {}\n"),
            "QrsTypedP.Detects",
        ),
        (cpp_test("  //  Verifies:SRS-001", test="  TEST (Qrs , Detects) {}\n"), "Qrs.Detects"),
        (cpp_test("//Verifies: SRS-001", test="TEST(Qrs, Detects) {}\n"), "Qrs.Detects"),
        (cpp_test("\t// Verifies:  SRS-001  ", test="\tTEST(Qrs, Detects) {}\n"), "Qrs.Detects"),
        (
            cpp_test("// Verifies: SRS-001", test="TEST(\n    Qrs,\n    Detects) {}\n"),
            "Qrs.Detects",
        ),
        (cpp_test("// Verifies: SRS-001", test="TEST(Qrs,\n\n\n\nDetects) {}\n"), "Qrs.Detects"),
        (cpp_test("// Verifies: SRS-001", test="TEST(Qrs, Detects)"), "Qrs.Detects"),
    ],
)
def test_cpp_tag_directly_above_a_test(tree: Tree, text: str, name: str) -> None:
    tree.write(REQ_CPP, text)
    assert tree.check() == {}
    assert tree.test_names("SRS-001") == [BASE_PY_TEST, f"{REQ_CPP}::{name}"]


@pytest.mark.parametrize("suffix", [".c", ".cc", ".cpp", ".h", ".hpp"])
def test_cpp_suffixes_that_are_read(tree: Tree, suffix: str) -> None:
    tree.write(
        f"libs/sinus-dsp/tests/requirements/qrs_test{suffix}", cpp_test("// Verifies: SRS-003")
    )
    assert tree.test_names("SRS-003") == [
        f"libs/sinus-dsp/tests/requirements/qrs_test{suffix}::Qrs.Detects"
    ]


@pytest.mark.parametrize(
    "name", ["qrs_test.cxx", "qrs_test.hh", "qrs_test.txt", "CMakeLists.txt", "qrs_test.py"]
)
def test_other_files_under_the_cpp_roots_are_not_read(tree: Tree, name: str) -> None:
    tree.write(f"libs/sinus-dsp/tests/requirements/{name}", cpp_test("// Verifies: nothing"))
    tree.write(f"libs/sinus-dsp/tests/unit/{name}", cpp_test("// Verifies: SRS-003"))
    assert tree.check() == {}


def test_tag_lines_combine(tree: Tree, tool: ModuleType) -> None:
    tree.write(
        REQ_CPP,
        cpp_test(
            "// Verifies: SRS-001",
            "// Verifies: SRS-003, SRS-001",
            test="TEST_F(QrsTest, Detects) {}\n",
        ),
    )
    matrix = tree.matrix()
    assert matrix.tests["SRS-003"] == [tool.TestRef(f"{REQ_CPP}::QrsTest.Detects", "Requirement")]
    assert tree.test_names("SRS-001") == [BASE_PY_TEST, f"{REQ_CPP}::QrsTest.Detects"]
    assert tree.check() == {}


def test_tag_covers_only_the_test_below_it(tree: Tree) -> None:
    text = (
        "TEST(Qrs, Before) {}\n"
        "// Verifies: SRS-003\n"
        "TEST(Qrs, Tagged) {\n"
        "}\n"
        "TEST(Qrs, After) {}\n"
        "// Verifies: SRS-003\n"
        "TEST_F(QrsTest, Second) {}\n"
    )
    tree.write(REQ_CPP, text)
    assert tree.test_names("SRS-003") == [f"{REQ_CPP}::Qrs.Tagged", f"{REQ_CPP}::QrsTest.Second"]
    assert tree.check() == {}


def test_cpp_file_with_windows_line_endings(tree: Tree) -> None:
    path = tree.root / REQ_CPP
    path.parent.mkdir(parents=True)
    path.write_bytes(
        b"// Verifies: SRS-003\r\nTEST(Qrs, Detects) {\r\n}\r\n// Verifies: SRS-003\r\n"
    )
    assert tree.test_names("SRS-003") == [f"{REQ_CPP}::Qrs.Detects"]
    assert tree.check() == {CPP_TAGS: [f"{REQ_CPP}:4: {DANGLING_TAG}"]}


@pytest.mark.parametrize(
    "tag",
    [
        "// Verifies:",
        "// Verifies:   ",
        "// Verifies: SRS-001,",
        "// Verifies: , SRS-001",
        "// Verifies: SRS-001,, SRS-003",
        "// Verifies: SRS-001 SRS-003",
        "// Verifies: SRS-001;SRS-003",
        "// Verifies: SRS-001 and SRS-003",
        "// Verifies: SRS-1",
        "// Verifies: SRS-0001",
        "// Verifies: srs-001",
        "// Verifies: SRS-001 // detection",
        "// Verifies: SRS-001.",
    ],
)
def test_malformed_cpp_tag(tree: Tree, tag: str) -> None:
    tree.write(REQ_CPP, cpp_test(tag))
    assert tree.check() == {CPP_TAGS: [f"{REQ_CPP}:1: {MALFORMED}"]}


def test_malformed_tag_line_among_valid_ones(tree: Tree) -> None:
    tree.write(
        REQ_CPP, cpp_test("// Verifies: SRS-003", "// Verifies: SRS-1", "// Verifies: SRS-001")
    )
    assert tree.check() == {CPP_TAGS: [f"{REQ_CPP}:2: {MALFORMED}"]}


@pytest.mark.parametrize(
    "line",
    [
        "/* Verifies: SRS-001 */",
        "// verifies: SRS-001",
        "// VERIFIES: SRS-001",
        "// Verifies : SRS-001",
        "/// Verifies: SRS-001",
        "//! Verifies: SRS-001",
        "// Note. Verifies: SRS-001",
        "// The filter verifies: nothing here",
        " * Verifies: SRS-001",
        "int x = 0;  // Verifies: SRS-001",
        'const char* text = "Verifies: SRS-001";',
    ],
)
def test_reserved_word_in_another_form(tree: Tree, line: str) -> None:
    tree.write(REQ_CPP, f"{line}\n{CPP_TEST}")
    assert tree.check() == {CPP_TAGS: [f"{REQ_CPP}:1: {RESERVED}"]}
    assert tree.test_names("SRS-001") == [BASE_PY_TEST]


def test_reserved_word_on_the_test_line(tree: Tree) -> None:
    tree.write(
        REQ_CPP,
        cpp_test("// Verifies: SRS-003", test="TEST(Qrs, Detects) {  // Verifies: SRS-001\n}\n"),
    )
    assert tree.check() == {CPP_TAGS: [f"{REQ_CPP}:2: {RESERVED}"]}
    assert tree.test_names("SRS-003") == [f"{REQ_CPP}::Qrs.Detects"]
    assert tree.test_names("SRS-001") == [BASE_PY_TEST]


def test_reserved_word_in_production_code(tree: Tree) -> None:
    tree.write("desktop/src/view.cpp", "// This view verifies: the input\nvoid draw() {}\n")
    assert tree.check() == {CPP_TAGS: [f"desktop/src/view.cpp:1: {RESERVED}"]}


@pytest.mark.parametrize(
    ("text", "line"),
    [
        (cpp_test("// Verifies: SRS-001", test="\nTEST(Qrs, Detects) {}\n"), 1),
        (cpp_test("// Verifies: SRS-001", test="// The detector finds beats.\n" + CPP_TEST), 1),
        (cpp_test("// Verifies: SRS-001", test="/* note */\n" + CPP_TEST), 1),
        (cpp_test("// Verifies: SRS-001", test=""), 1),
        ("// Verifies: SRS-001", 1),
        (cpp_test("// Verifies: SRS-001", "// Verifies: SRS-003", test=""), 1),
        ("void helper() {}\n// Verifies: SRS-001\nvoid other() {}\n", 2),
        (
            cpp_test(
                "// Verifies: SRS-001",
                test="INSTANTIATE_TEST_SUITE_P(All, QrsParam, ::testing::Values(1));\n",
            ),
            1,
        ),
        (cpp_test("// Verifies: SRS-001", test="TYPED_TEST_SUITE(QrsTyped, Types);\n"), 1),
        (cpp_test("// Verifies: SRS-001", test="TEST_X(Qrs, Detects) {}\n"), 1),
        (cpp_test("// Verifies: SRS-001", test="TESTING(Qrs, Detects) {}\n"), 1),
        (cpp_test("// Verifies: SRS-001", test="MY_TEST(Qrs, Detects) {}\n"), 1),
        (cpp_test("// Verifies: SRS-001", test='TEST_CASE("qrs", "[detects]") {}\n'), 1),
        (cpp_test("// Verifies: SRS-001", test="TEST(Qrs) {}\n"), 1),
        (cpp_test("// Verifies: SRS-001", test="TEST(Qrs, Detects, Extra) {}\n"), 1),
        (cpp_test("// Verifies: SRS-001", test="TEST(Qrs,\n\n\n\n\nDetects) {}\n"), 1),
        (cpp_test("// Verifies: SRS-001", test="#if 1\n" + CPP_TEST + "#endif\n"), 1),
    ],
)
def test_dangling_cpp_tag(tree: Tree, text: str, line: int) -> None:
    tree.write(REQ_CPP, text)
    assert tree.check() == {CPP_TAGS: [f"{REQ_CPP}:{line}: {DANGLING_TAG}"]}
    assert tree.test_names("SRS-001") == [BASE_PY_TEST]


def test_dangling_tag_does_not_reach_the_next_test(tree: Tree) -> None:
    tree.write(REQ_CPP, "// Verifies: SRS-001\nint x;\n// Verifies: SRS-003\n" + CPP_TEST)
    assert tree.check() == {CPP_TAGS: [f"{REQ_CPP}:1: {DANGLING_TAG}"]}
    assert tree.test_names("SRS-001") == [BASE_PY_TEST]
    assert tree.test_names("SRS-003") == [f"{REQ_CPP}::Qrs.Detects"]


def test_tags_do_not_continue_into_the_next_file(tree: Tree) -> None:
    tree.write("libs/sinus-dsp/tests/requirements/a_test.cpp", "// Verifies: SRS-003\n")
    tree.write("libs/sinus-dsp/tests/requirements/b_test.cpp", CPP_TEST)
    assert tree.check() == {
        CPP_TAGS: [f"libs/sinus-dsp/tests/requirements/a_test.cpp:1: {DANGLING_TAG}"]
    }
    assert tree.test_names("SRS-003") == []


def test_tag_errors_of_several_files(tree: Tree) -> None:
    tree.write("libs/sinus-dsp/tests/unit/a_test.cpp", "// Verifies: SRS-001\n")
    tree.write(REQ_CPP, "// Verifies: SRS-1\n" + CPP_TEST + "// verifies: SRS-001\n")
    assert tree.check() == {
        INDEPENDENCE: ["libs/sinus-dsp/tests/unit/a_test.cpp:1"],
        CPP_TAGS: [
            f"{REQ_CPP}:1: {MALFORMED}",
            f"{REQ_CPP}:4: {RESERVED}",
            f"libs/sinus-dsp/tests/unit/a_test.cpp:1: {DANGLING_TAG}",
        ],
    }


# --- verification level against test folder --------------------------------------------------


def test_requirement_level_tested_in_the_system_folder(tree: Tree) -> None:
    tree.write("dsp/tests/system/test_more.py", python_test_file(marked("test_more", "SRS-001")))
    assert tree.check() == {
        LEVEL: [
            "SRS-001 has Verification level Requirement (tests in tests/requirements/), but is "
            "tagged in dsp/tests/system/test_more.py::test_more"
        ]
    }


def test_system_level_tested_in_the_requirements_folder(tree: Tree) -> None:
    tree.write(
        "dsp/tests/requirements/test_more.py", python_test_file(marked("test_more", "SRS-002"))
    )
    assert tree.check() == {
        LEVEL: [
            "SRS-002 has Verification level System (tests in tests/system/), but is tagged in "
            "dsp/tests/requirements/test_more.py::test_more"
        ]
    }


def test_cpp_test_in_the_folder_of_the_other_level(tree: Tree) -> None:
    tree.write(SYS_CPP, cpp_test("// Verifies: SRS-001, SRS-002"))
    tree.write(REQ_CPP, cpp_test("// Verifies: SRS-001, SRS-002"))
    assert tree.check() == {
        LEVEL: [
            "SRS-001 has Verification level Requirement (tests in tests/requirements/), but is "
            f"tagged in {SYS_CPP}::Qrs.Detects",
            "SRS-002 has Verification level System (tests in tests/system/), but is tagged in "
            f"{REQ_CPP}::Qrs.Detects",
        ]
    }


def test_level_mismatches_are_listed_in_order(tree: Tree) -> None:
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004", milestone="M2", level="System"))
    tree.write(
        "dsp/tests/system/test_z.py", python_test_file(marked("test_z", "SRS-003", "SRS-001"))
    )
    tree.write("dsp/tests/system/test_a.py", python_test_file(marked("test_a", "SRS-001")))
    tree.write("dsp/tests/requirements/test_m.py", python_test_file(marked("test_m", "SRS-004")))
    prefix = "has Verification level Requirement (tests in tests/requirements/), but is tagged in"
    assert tree.check() == {
        LEVEL: [
            f"SRS-001 {prefix} dsp/tests/system/test_a.py::test_a",
            f"SRS-001 {prefix} dsp/tests/system/test_z.py::test_z",
            f"SRS-003 {prefix} dsp/tests/system/test_z.py::test_z",
            "SRS-004 has Verification level System (tests in tests/system/), but is tagged in "
            "dsp/tests/requirements/test_m.py::test_m",
        ]
    }


def test_requirement_without_a_valid_level_has_no_mismatch(tree: Tree) -> None:
    tree.srs(
        requirement("SRS-001", "Remove baseline wander", level="Unknown"), *BASE_REQUIREMENTS[1:]
    )
    tree.write("dsp/tests/system/test_more.py", python_test_file(marked("test_more", "SRS-001")))
    assert tree.check() == {FIELDS: [f"SRS-001: {BAD_LEVEL}"]}


def test_only_test_in_the_wrong_folder_fails_the_check(tree: Tree) -> None:
    tree.root.joinpath("dsp/tests/requirements/test_srs_001.py").unlink()
    tree.write(
        "dsp/tests/system/test_srs_001.py",
        python_test_file(marked("test_removes_wander", "SRS-001")),
    )
    failures = tree.check()
    assert failures[LEVEL] == [
        "SRS-001 has Verification level Requirement (tests in tests/requirements/), but is "
        "tagged in dsp/tests/system/test_srs_001.py::test_removes_wander"
    ]
    assert set(failures) <= {LEVEL, UNTESTED}


# --- implemented => tested ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "text", "line"),
    [
        ("dsp/sinus_dsp/later.py", '"""Later feature (SRS-003)."""\n', 1),
        ("dsp/sinus_dsp/sub/later.py", "\n\n# SRS-003\n", 3),
        ("dsp/scripts/later.py", "# See SRS-003.\n", 1),
        ("libs/sinus-dsp/src/later.cpp", "// SRS-003\n", 1),
        ("libs/sinus-dsp/include/sinus/later.hpp", "#pragma once\n// SRS-003\n", 2),
        ("firmware/main/later.c", "/* SRS-003 */\n", 1),
        ("firmware/components/sinus_dsp/later.h", "// SRS-003\n", 1),
        ("desktop/src/later.cc", "// SRS-003\n", 1),
    ],
)
def test_cited_requirement_without_a_test(tree: Tree, rel: str, text: str, line: int) -> None:
    tree.write(rel, text)
    assert tree.check() == {UNTESTED: [f"SRS-003: cited in `{rel}:{line}`"]}


def test_every_citation_is_listed(tree: Tree) -> None:
    tree.write("dsp/sinus_dsp/later.py", "# SRS-003\nx = 1  # SRS-003, SRS-003\n# SRS-003\n")
    tree.write("dsp/scripts/later.py", "# SRS-003\n")
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004"))
    tree.write("libs/sinus-dsp/src/a.cpp", "// SRS-004\n")
    assert tree.check() == {
        UNTESTED: [
            "SRS-003: cited in `dsp/scripts/later.py:1`, `dsp/sinus_dsp/later.py:1`, "
            "`dsp/sinus_dsp/later.py:2`, `dsp/sinus_dsp/later.py:3`",
            "SRS-004: cited in `libs/sinus-dsp/src/a.cpp:1`",
        ]
    }


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("dsp/tests/requirements/test_later.py", python_test_file(marked("test_later", "SRS-003"))),
        (
            "dsp/tests/requirements/sub/later_test.py",
            python_test_file(marked("test_later", "SRS-003")),
        ),
        ("libs/sinus-dsp/tests/requirements/later_test.cpp", cpp_test("// Verifies: SRS-003")),
        ("firmware/tests/requirements/later_test.cpp", cpp_test("// Verifies: SRS-003")),
        ("desktop/tests/requirements/later_test.cc", cpp_test("// Verifies: SRS-003")),
    ],
)
def test_a_verifying_test_clears_the_rule(tree: Tree, rel: str, text: str) -> None:
    tree.write("dsp/sinus_dsp/later.py", "# SRS-003\n")
    tree.write(rel, text)
    assert tree.check() == {}


def test_a_misplaced_test_does_not_verify(tree: Tree) -> None:
    tree.write("dsp/sinus_dsp/later.py", "# SRS-003\n")
    tree.write("dsp/tests/unit/test_later.py", python_test_file(marked("test_later", "SRS-003")))
    tree.write("libs/sinus-dsp/tests/unit/later_test.cpp", cpp_test("// Verifies: SRS-003"))
    assert tree.check() == {
        INDEPENDENCE: [
            "dsp/tests/unit/test_later.py:4",
            "libs/sinus-dsp/tests/unit/later_test.cpp:1",
        ],
        UNTESTED: ["SRS-003: cited in `dsp/sinus_dsp/later.py:1`"],
    }


def test_a_dangling_cpp_tag_does_not_verify(tree: Tree) -> None:
    tree.write("dsp/sinus_dsp/later.py", "# SRS-003\n")
    tree.write(REQ_CPP, "// Verifies: SRS-003\n\n" + CPP_TEST)
    assert tree.check() == {
        CPP_TAGS: [f"{REQ_CPP}:1: {DANGLING_TAG}"],
        UNTESTED: ["SRS-003: cited in `dsp/sinus_dsp/later.py:1`"],
    }


def test_rule_holds_whatever_the_milestone(tree: Tree) -> None:
    tree.register({"M0": "Released", "M1": "In progress", "M2": "Planned", "M3": "Planned"})
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004", milestone="M3"))
    tree.write("dsp/sinus_dsp/later.py", "# SRS-004\n")
    assert tree.check() == {UNTESTED: ["SRS-004: cited in `dsp/sinus_dsp/later.py:1`"]}


def test_cited_deleted_requirement_without_a_test(tree: Tree) -> None:
    tree.srs(*BASE_REQUIREMENTS, "### SRS-004: _Deleted_\n")
    tree.write("dsp/sinus_dsp/old.py", "# SRS-004\n")
    assert tree.check() == {UNTESTED: ["SRS-004: cited in `dsp/sinus_dsp/old.py:1`"]}


# --- open points ----------------------------------------------------------------------------

OPEN_POINTS_SECTIONS = """\
# Open points

| OP-090 | Before any section. | SRS-001 | 2026-01-01 | M1 | Open |

## Open

| ID | Open point | Refs | Opened | Target | Status |
|---|---|---|---|---|---|
| OP-001 | Point. | SRS-003, HAZ-001 | 2026-01-01 | M2 | Open |
| OP-003 | Mentions SRS-099 in its text. | soup.md, RC-001 | 2026-01-01 | M1 | Open |
|OP-004|Compact row.|SRS-001, SRS-001|2026-01-01|M3|Open|
| OP-005 | Short row. | SRS-001 |
| OP-006 | Shorter row. |
| OP-07 | Two digits are not an ID. | SRS-099 | 2026-01-01 | M1 | Open |

### Notes under Open

| OP-008 | Under a subheading. | — | 2026-01-01 | M3 | Closed |

## Closed

| ID | Open point | Refs | Opened | Closed | Resolution |
|---|---|---|---|---|---|
| OP-002 | Closed point. | SRS-001, RC-001 | 2026-01-01 | M1 | Done. |

## Withdrawn

| OP-009 | Withdrawn. | HAZ-001 | 2026-01-01 | M1 | Open |
"""


def test_open_points_are_read_by_section(tree: Tree, tool: ModuleType) -> None:
    tree.write("docs/regulatory/open-points.md", OPEN_POINTS_SECTIONS)
    points = tool.parse_open_points(tree.layout)
    assert [(p.id, p.is_open, p.refs, p.target) for p in points] == [
        ("OP-090", False, ["SRS-001"], ""),
        ("OP-001", True, ["SRS-003", "HAZ-001"], "M2"),
        ("OP-003", True, ["RC-001"], "M1"),
        ("OP-004", True, ["SRS-001", "SRS-001"], "M3"),
        ("OP-005", True, ["SRS-001"], ""),
        ("OP-006", True, [], ""),
        ("OP-008", True, [], "M3"),
        ("OP-002", False, ["SRS-001", "RC-001"], ""),
        ("OP-009", False, ["HAZ-001"], ""),
    ]


def test_absent_open_points(tree: Tree, tool: ModuleType) -> None:
    tree.layout.open_points.unlink()
    assert tool.parse_open_points(tree.layout) == []
    assert "- Open points still open: 0 (see `open-points.md`)" in tree.render()
    assert tree.check() == {}


@pytest.mark.parametrize(
    ("open_rows", "closed_rows", "items"),
    [
        ([("OP-003", "SRS-099", "M2")], [], ["OP-003→SRS-099"]),
        ([], [("OP-003", "HAZ-099")], ["OP-003→HAZ-099"]),
        ([("OP-003", "RC-099, SRS-001, HAZ-001", "M2")], [], ["OP-003→RC-099"]),
        ([("OP-003", "SRS-099, SRS-099", "M2")], [], ["OP-003→SRS-099", "OP-003→SRS-099"]),
        (
            [("OP-004", "SRS-098", "M2"), ("OP-003", "SRS-099, SRS-097", "M3")],
            [("OP-005", "§2, HAZ-002")],
            ["OP-003→SRS-097", "OP-003→SRS-099", "OP-004→SRS-098", "OP-005→HAZ-002"],
        ),
    ],
)
def test_open_point_citing_an_undefined_id(
    tree: Tree,
    open_rows: list[tuple[str, str, str]],
    closed_rows: list[tuple[str, str]],
    items: list[str],
) -> None:
    tree.open_points([*BASE_OPEN, *open_rows], [*BASE_CLOSED, *closed_rows])
    assert tree.check() == {DANGLING: items}


@pytest.mark.parametrize(
    "refs",
    [
        "SRS-001",
        "SRS-001, SRS-002, SRS-003",
        "HAZ-001",
        "RC-001",
        "sdp.md §4",
        "README §License",
        "SRS-0991",
        "XSRS-099",
        "OP-001",
        "—",
        "",
    ],
)
def test_open_point_citing_defined_ids_or_documents(tree: Tree, refs: str) -> None:
    tree.open_points([*BASE_OPEN, ("OP-003", refs, "M3")], [*BASE_CLOSED, ("OP-004", refs)])
    assert tree.check() == {}


def test_deleted_requirement_is_defined(tree: Tree) -> None:
    tree.srs(*BASE_REQUIREMENTS, "### SRS-004: _Deleted_\n")
    tree.open_points([*BASE_OPEN, ("OP-003", "SRS-004", "M3")], BASE_CLOSED)
    assert tree.check() == {}


def test_without_risk_analysis_every_risk_id_is_undefined(tree: Tree) -> None:
    tree.layout.risk.unlink()
    assert tree.check() == {DANGLING: ["OP-001→HAZ-001", "OP-002→RC-001"]}


def test_risk_ids_are_read_from_table_rows(tree: Tree, tool: ModuleType) -> None:
    text = (
        "# Risk analysis\n\nHAZ-004 in a sentence.\n\n| ID | Item |\n|---|---|\n"
        "| HAZ-001 | Hazard. |\n|RC-001|Compact.|\n| HAZ-002, HAZ-003 | Two IDs. |\n"
        "| Item | HAZ-005 |\n| RC-0061 | Four digits. |\n| hAZ-007 | Case. |\n"
    )
    tree.write("docs/regulatory/risk-analysis.md", text)
    assert tool.parse_risk_ids(tree.layout) == {"HAZ-001", "RC-001"}


@pytest.mark.parametrize(
    ("open_rows", "closed_rows", "items"),
    [
        ([("OP-001", "SRS-003", "M2")], [], ["OP-001"]),
        ([], [("OP-001", "SRS-003")], ["OP-001"]),
        ([], [("OP-002", "SRS-001"), ("OP-002", "SRS-001")], ["OP-002"]),
        (
            [("OP-003", "", "M2"), ("OP-003", "", "M3"), ("OP-001", "", "M2")],
            [],
            ["OP-001", "OP-003"],
        ),
    ],
)
def test_duplicate_open_point_ids(
    tree: Tree,
    open_rows: list[tuple[str, str, str]],
    closed_rows: list[tuple[str, str]],
    items: list[str],
) -> None:
    tree.open_points([*BASE_OPEN, *open_rows], [*BASE_CLOSED, *closed_rows])
    assert tree.check() == {DUPLICATE: items}


# --- the stale-matrix check -----------------------------------------------------------------


def test_absent_matrix_is_stale(tree: Tree) -> None:
    assert tree.check(update=False) == {STALE: [STALE_ITEM]}


def test_matrix_written_by_the_script_is_current(
    tree: Tree, tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool, "REPO_ROOT", tree.root)
    assert tool.main([]) == 0
    assert tree.check(update=False) == {}


@pytest.mark.parametrize(
    "edit",
    [
        lambda text: text.replace("| M1 |", "| M1  |", 1),
        lambda text: text + "\n",
        lambda text: text.rstrip("\n"),
        lambda text: text.replace("**none**", "none"),
        lambda text: "",
    ],
)
def test_matrix_that_differs_is_stale(tree: Tree, edit: Callable[[str], str]) -> None:
    tree.write(OUTPUT, edit(tree.render()))
    assert tree.check(update=False) == {STALE: [STALE_ITEM]}


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("dsp/sinus_dsp/more.py", "# SRS-001\n"),
        ("dsp/tests/requirements/test_more.py", python_test_file(marked("test_more", "SRS-001"))),
        (REQ_CPP, cpp_test("// Verifies: SRS-001")),
        ("dsp/sinus_dsp/filters.py", "\n" + BASE_FILES["dsp/sinus_dsp/filters.py"]),
    ],
)
def test_change_shown_by_the_matrix_makes_it_stale(tree: Tree, rel: str, text: str) -> None:
    tree.update()
    tree.write(rel, text)
    assert tree.check(update=False) == {STALE: [STALE_ITEM]}


def test_changes_to_the_register_and_open_points_make_it_stale(tree: Tree) -> None:
    tree.update()
    tree.open_points([*BASE_OPEN, ("OP-003", "SRS-001", "M3")], BASE_CLOSED)
    assert tree.check(update=False) == {STALE: [STALE_ITEM]}
    tree.update()
    tree.register({"M0": "Released", "M1": "In progress", "M2": "Planned", "M3": "Planned"})
    assert tree.check(update=False) == {STALE: [STALE_ITEM]}


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("dsp/tests/unit/test_more.py", "def test_more() -> None:\n    pass\n"),
        ("dsp/sinus_dsp/more.py", '"""No citation."""\n'),
        ("libs/sinus-dsp/tests/requirements/plain_test.cpp", CPP_TEST),
    ],
)
def test_change_not_shown_by_the_matrix_leaves_it_current(tree: Tree, rel: str, text: str) -> None:
    tree.update()
    tree.write(rel, text)
    tree.open_points(BASE_OPEN, [*BASE_CLOSED, ("OP-003", "SRS-003")])
    assert tree.check(update=False) == {}


def test_line_endings_of_the_stored_matrix_do_not_matter(tree: Tree) -> None:
    path = tree.root / OUTPUT
    path.write_bytes(tree.render().replace("\n", "\r\n").encode("utf-8"))
    assert tree.check(update=False) == {}


# --- the release gate -----------------------------------------------------------------------


@pytest.mark.parametrize("status", ["In progress", "Released"])
@pytest.mark.parametrize("milestone", ["M0", "M1"])
def test_requirement_of_a_gated_milestone_without_a_test(
    tree: Tree, milestone: str, status: str
) -> None:
    statuses = {"M0": "Released", "M1": status, "M2": "Planned"}
    tree.register(statuses)
    tree.version("0.1.0.dev0" if status == "In progress" else "0.1.0")
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004", milestone=milestone))
    expected = [f"SRS-004 ({milestone}, {statuses[milestone]}): no verifying test"]
    if status == "In progress":
        expected.append(DEV_ITEM)
    assert tree.gate() == expected


def test_requirement_of_a_planned_milestone_is_not_gated(tree: Tree) -> None:
    tree.release()
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004", milestone="M2"))
    assert tree.gate() == []


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("dsp/tests/requirements/test_later.py", python_test_file(marked("test_later", "SRS-004"))),
        ("libs/sinus-dsp/tests/requirements/later_test.cpp", cpp_test("// Verifies: SRS-004")),
        ("firmware/tests/requirements/later_test.c", cpp_test("// Verifies: SRS-004")),
    ],
)
def test_a_verifying_test_opens_the_gate(tree: Tree, rel: str, text: str) -> None:
    tree.release()
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004"))
    tree.write(rel, text)
    assert tree.gate() == []


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("dsp/tests/unit/test_later.py", python_test_file(marked("test_later", "SRS-004"))),
        ("dsp/tests/test_later.py", python_test_file(marked("test_later", "SRS-004"))),
        ("libs/sinus-dsp/tests/unit/later_test.cpp", cpp_test("// Verifies: SRS-004")),
        (REQ_CPP, cpp_test("// Verifies: SRS-004", test="\n" + CPP_TEST)),
        (
            "dsp/tests/requirements/test_later.py",
            "import pytest\n\n\nclass Checks:\n"
            '    @pytest.mark.requirement("SRS-004")\n'
            "    def test_later(self) -> None:\n        pass\n",
        ),
    ],
)
def test_a_test_that_is_not_counted_does_not_open_the_gate(tree: Tree, rel: str, text: str) -> None:
    tree.release()
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004"))
    tree.write(rel, text)
    assert tree.gate() == ["SRS-004 (M1, Released): no verifying test"]


@pytest.mark.parametrize(
    "entry",
    [
        requirement("SRS-004", milestone=None),
        requirement("SRS-004", milestone=""),
        requirement("SRS-004", milestone="M9"),
        requirement("SRS-004", milestone="M3"),
    ],
)
def test_requirement_without_a_valid_milestone_holds_the_gate(tree: Tree, entry: str) -> None:
    tree.release()
    tree.register({"M0": "Released", "M1": "Released", "M2": "Planned"}, ["| M3 | Title | Done |"])
    tree.srs(*BASE_REQUIREMENTS, entry)
    tree.write(
        "dsp/tests/requirements/test_later.py", python_test_file(marked("test_later", "SRS-004"))
    )
    assert tree.gate() == ["SRS-004: no valid milestone, so the gate cannot place it"]


def test_deleted_requirement_is_not_gated(tree: Tree) -> None:
    tree.release()
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004", extra="_Deleted_"))
    assert tree.gate() == []


@pytest.mark.parametrize(
    ("target", "held"),
    [
        ("M1", True),
        ("M0", True),
        ("M2", False),
        ("M9", False),
        ("", False),
        ("After M6", False),
        ("M1 ", True),
    ],
)
def test_open_point_targeting_a_gated_milestone(tree: Tree, target: str, held: bool) -> None:
    tree.release()
    tree.open_points([*BASE_OPEN, ("OP-003", "", target)], BASE_CLOSED)
    expected = [f"OP-003: open point still targets {target.strip()}; close or retarget it"]
    assert tree.gate() == (expected if held else [])


def test_closed_open_point_does_not_hold_the_gate(tree: Tree) -> None:
    tree.release()
    tree.write("docs/regulatory/open-points.md", OPEN_POINTS_SECTIONS)
    # OP-090, OP-002 and OP-009 name M1 in their fifth column, but are outside "## Open".
    # OP-004 and OP-008 target M3, which is not in the register.
    assert tree.gate() == ["OP-003: open point still targets M1; close or retarget it"]


def test_gate_ignores_a_closed_point_whatever_its_target(tree: Tree, tool: ModuleType) -> None:
    tree.release()
    matrix = tree.matrix()
    matrix.open_points = [
        tool.OpenPoint(id="OP-003", is_open=False, refs=[], target="M1"),
        tool.OpenPoint(id="OP-004", is_open=True, refs=[], target="M1"),
    ]
    assert tool.release_gate_failures(matrix) == [
        "OP-004: open point still targets M1; close or retarget it"
    ]


def test_open_section_decides_whether_a_point_is_open(tree: Tree) -> None:
    tree.release()
    tree.register({"M0": "Released", "M1": "Released", "M2": "Planned", "M3": "Released"})
    tree.version("0.3.0")
    tree.write("docs/regulatory/open-points.md", OPEN_POINTS_SECTIONS)
    assert tree.gate() == [
        "OP-003: open point still targets M1; close or retarget it",
        "OP-004: open point still targets M3; close or retarget it",
        "OP-008: open point still targets M3; close or retarget it",
    ]


def test_release_gate_items_in_order(tree: Tree) -> None:
    tree.srs(
        requirement("SRS-005"),
        *BASE_REQUIREMENTS,
        requirement("SRS-004", milestone=None),
        requirement("SRS-006", milestone="M0"),
    )
    tree.open_points([("OP-004", "", "M1"), *BASE_OPEN, ("OP-003", "", "M0")], BASE_CLOSED)
    assert tree.gate() == [
        "SRS-004: no valid milestone, so the gate cannot place it",
        "SRS-005 (M1, In progress): no verifying test",
        "SRS-006 (M0, Released): no verifying test",
        "OP-003: open point still targets M0; close or retarget it",
        "OP-004: open point still targets M1; close or retarget it",
        DEV_ITEM,
    ]


def test_gated_milestones_in_numeric_order(tree: Tree, tool: ModuleType) -> None:
    tree.register(
        {
            "M10": "Released",
            "M2": "Released",
            "M9": "Planned",
            "M1": "Released",
            "M11": "In progress",
        }
    )
    assert tool.gated_milestones(tree.matrix()) == ["M1", "M2", "M10", "M11"]


def test_no_gated_milestone(tree: Tree, tool: ModuleType) -> None:
    tree.register({"M0": "Planned", "M1": "Planned", "M2": "Planned"})
    tree.version("0.0.1")
    assert tool.gated_milestones(tree.matrix()) == []
    assert tree.gate() == []


# --- the matrix -----------------------------------------------------------------------------


def table_rows(text: str, first: str) -> dict[str, list[str]]:
    """Cells of the table rows whose first cell matches the pattern ``first``, by first cell."""
    rows = [[c.strip() for c in line.strip("|").split("|")] for line in text.splitlines()]
    return {cells[0]: cells[1:] for cells in rows if re.fullmatch(first, cells[0])}


def test_open_points_of_each_requirement(tree: Tree) -> None:
    tree.open_points(
        [
            ("OP-010", "SRS-001, SRS-003, SRS-001", "M3"),
            *BASE_OPEN,
            ("OP-004", "SRS-003", "M2"),
            ("OP-007", "HAZ-001, RC-001", "M4"),
            ("OP-008", "sdp.md §4, SRS-003", "M4"),
        ],
        [*BASE_CLOSED, ("OP-005", "SRS-002"), ("OP-006", "SRS-003")],
    )
    text = tree.render()
    open_points = {req: cells[-1] for req, cells in table_rows(text, r"SRS-\d+").items()}
    assert open_points == {
        "SRS-001": "OP-010",
        "SRS-002": "—",
        "SRS-003": "OP-001, OP-004, OP-008, OP-010",
    }
    assert "- Open points still open: 5 (see `open-points.md`)" in text.splitlines()


def test_requirement_rows(tree: Tree) -> None:
    tree.srs(
        requirement("SRS-004", "Without fields", milestone=None, level=None),
        *BASE_REQUIREMENTS,
        "### SRS-005: _Deleted_\n",
    )
    tree.write("dsp/sinus_dsp/more.py", "\n# SRS-001\n")
    tree.write("libs/sinus-dsp/src/qrs.cpp", "// SRS-001\n")
    tree.write("dsp/tests/requirements/test_a.py", python_test_file(marked("test_a", "SRS-001")))
    tree.write(REQ_CPP, cpp_test("// Verifies: SRS-001"))
    rows = table_rows(tree.render(), r"SRS-\d+")
    assert list(rows) == ["SRS-001", "SRS-002", "SRS-003", "SRS-004", "SRS-005"]
    assert rows["SRS-001"] == [
        "Remove baseline wander",
        "M1",
        "Requirement",
        "`dsp/sinus_dsp/filters.py:4`<br>`dsp/sinus_dsp/more.py:2`<br>`libs/sinus-dsp/src/qrs.cpp:1`",
        "`dsp/tests/requirements/test_a.py::test_a`<br>`"
        + BASE_PY_TEST
        + "`<br>`"
        + REQ_CPP
        + "::Qrs.Detects`",
        "—",
    ]
    assert rows["SRS-004"] == ["Without fields", "—", "—", "—", "**none**", "—"]
    assert rows["SRS-005"] == ["_Deleted_", "—", "—", "—", "**none**", "—"]


def test_milestone_table(tree: Tree) -> None:
    tree.register(
        {"M10": "Released", "M0": "Released", "M1": "In progress", "M2": "Planned", "M9": "Planned"}
    )
    tree.srs(
        *BASE_REQUIREMENTS,
        requirement("SRS-004"),
        requirement("SRS-005", extra="_Deleted_"),
        requirement("SRS-006", milestone="M10"),
        requirement("SRS-007", milestone="M9"),
        requirement("SRS-008", milestone="M4"),
    )
    tree.write(
        "dsp/tests/requirements/test_m10.py", python_test_file(marked("test_m10", "SRS-006"))
    )
    rows = table_rows(tree.render(), r"M\d+")
    assert rows == {
        "M0": ["Title of M0", "Released", "0", "0", "pass"],
        "M1": ["Title of M1", "In progress", "3", "2", "**fail**"],
        "M2": ["Title of M2", "Planned", "1", "0", "not applied"],
        "M9": ["Title of M9", "Planned", "1", "0", "not applied"],
        "M10": ["Title of M10", "Released", "1", "1", "pass"],
    }


def test_gaps(tree: Tree) -> None:
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004"))
    tree.write("dsp/sinus_dsp/more.py", "# SRS-004, SRS-099\n")
    tree.write(
        "dsp/tests/requirements/test_more.py", python_test_file(marked("test_more", "SRS-098"))
    )
    tree.open_points(
        [*BASE_OPEN, ("OP-003", "SRS-097, HAZ-001", "M2")], [*BASE_CLOSED, ("OP-004", "RC-099")]
    )
    gaps = tree.render().split("## Gaps\n\n", 1)[1]
    assert gaps == (
        "- Requirements without tests: SRS-003, SRS-004\n"
        "- Implemented requirements without tests: SRS-004\n"
        "- Unknown IDs referenced in code/tests: SRS-098, SRS-099\n"
        "- Open points citing undefined IDs: OP-003→SRS-097, OP-004→RC-099\n"
        "- Open points still open: 2 (see `open-points.md`)\n"
    )


def test_matrix_without_requirements(tree: Tree) -> None:
    tree.srs()
    text = tree.render()
    assert (
        "| — | _No requirements defined yet in `srs.md`_ | — | — | — | — | — |" in text.splitlines()
    )
    assert "| M1 | Title of M1 | In progress | 0 | 0 | pass |" in text.splitlines()


def test_matrix_shows_every_requirement_whatever_the_check(tree: Tree) -> None:
    tree.write("dsp/tests/unit/test_more.py", python_test_file(marked("test_more", "SRS-003")))
    tree.write(SYS_CPP, cpp_test("// Verifies: SRS-001"))
    rows = table_rows(tree.render(), r"SRS-\d+")
    assert rows["SRS-003"][4] == "**none**"
    assert rows["SRS-001"][4] == f"`{BASE_PY_TEST}`<br>`{SYS_CPP}::Qrs.Detects`"


# --- the command line -----------------------------------------------------------------------


@pytest.fixture
def run(
    tree: Tree,
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Callable[..., tuple[int, str]]:
    """Run ``main`` with the tree as the repository root; return the exit status and output."""
    monkeypatch.setattr(tool, "REPO_ROOT", tree.root)

    def call(*args: str) -> tuple[int, str]:
        status = tool.main(list(args))
        captured = capsys.readouterr()
        assert captured.err == ""
        return status, captured.out

    return call


def test_without_options_the_matrix_is_written(
    tree: Tree, run: Callable[..., tuple[int, str]]
) -> None:
    assert run() == (0, f"Wrote {OUTPUT}\n")
    assert (tree.root / OUTPUT).read_bytes() == BASE_MATRIX.encode("utf-8")


def test_matrix_is_written_even_when_a_check_fails(
    tree: Tree, run: Callable[..., tuple[int, str]]
) -> None:
    tree.write("dsp/sinus_dsp/more.py", "# SRS-099\n")
    tree.write(OUTPUT, "old\r\n")
    assert run() == (0, f"Wrote {OUTPUT}\n")
    written = (tree.root / OUTPUT).read_bytes()
    assert b"\r" not in written
    assert "- Unknown IDs referenced in code/tests: SRS-099\n" in written.decode("utf-8")


def test_check_passes(tree: Tree, run: Callable[..., tuple[int, str]]) -> None:
    run()
    assert run("--check") == (0, "Traceability: passed (checks)\n")


def test_check_lists_each_failing_rule_and_does_not_write(
    tree: Tree, run: Callable[..., tuple[int, str]]
) -> None:
    tree.write("dsp/sinus_dsp/more.py", "# SRS-099\n# SRS-003\n")
    tree.write("dsp/tests/unit/test_more.py", python_test_file(marked("test_more", "SRS-001")))
    assert run("--check") == (
        1,
        f"FAIL: {STALE}\n"
        f"  - {STALE_ITEM}\n"
        f"FAIL: {UNKNOWN}\n"
        "  - SRS-099\n"
        f"FAIL: {INDEPENDENCE}\n"
        "  - dsp/tests/unit/test_more.py:4\n"
        f"FAIL: {UNTESTED}\n"
        "  - SRS-003: cited in `dsp/sinus_dsp/more.py:2`\n",
    )
    assert not (tree.root / OUTPUT).exists()


def test_release_gate_alone(tree: Tree, run: Callable[..., tuple[int, str]]) -> None:
    # The matrix is absent: the release gate alone does not check it.
    assert run("--release-gate") == (
        1,
        f"FAIL: Release gate on milestones M0, M1\n  - {DEV_ITEM}\n",
    )
    tree.release()
    assert run("--release-gate") == (
        0,
        "Traceability: passed (release gate on milestones M0, M1)\n",
    )
    assert not (tree.root / OUTPUT).exists()


def test_check_and_release_gate(tree: Tree, run: Callable[..., tuple[int, str]]) -> None:
    tree.release()
    run()
    assert run("--check", "--release-gate") == (
        0,
        "Traceability: passed (checks and release gate on milestones M0, M1)\n",
    )
    tree.srs(*BASE_REQUIREMENTS, requirement("SRS-004"))
    assert run("--release-gate", "--check") == (
        1,
        f"FAIL: {STALE}\n  - {STALE_ITEM}\n"
        "FAIL: Release gate on milestones M0, M1\n  - SRS-004 (M1, Released): no verifying test\n",
    )


def test_release_gate_without_gated_milestones(
    tree: Tree, run: Callable[..., tuple[int, str]]
) -> None:
    tree.register({"M0": "Planned", "M1": "Planned", "M2": "Planned"})
    tree.version("0.0.1")
    assert run("--release-gate") == (0, "Traceability: passed (release gate on milestones none)\n")


def test_unknown_option(tool: ModuleType, run: Callable[..., tuple[int, str]]) -> None:
    with pytest.raises(SystemExit) as caught:
        tool.main(["--gate"])
    assert caught.value.code == 2


def test_run_as_a_command(tree: Tree, tmp_path: Path) -> None:
    """A copy of the script finds the tree from its own location, whatever the working folder."""
    copy = tree.root / "dsp" / "scripts" / "traceability.py"
    shutil.copyfile(SCRIPT, copy)

    def command(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(copy), *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp_path,
        )

    completed = command()
    assert (completed.returncode, completed.stdout, completed.stderr) == (
        0,
        f"Wrote {OUTPUT}\n",
        "",
    )
    assert (tree.root / OUTPUT).read_text(encoding="utf-8") == BASE_MATRIX
    completed = command("--check")
    assert (completed.returncode, completed.stdout, completed.stderr) == (
        0,
        "Traceability: passed (checks)\n",
        "",
    )
    tree.write("libs/sinus-dsp/tests/unit/qrs_test.cpp", cpp_test("// Verifies: SRS-001"))
    completed = command("--check")
    assert (completed.returncode, completed.stderr) == (1, "")
    assert (
        completed.stdout == f"FAIL: {INDEPENDENCE}\n  - libs/sinus-dsp/tests/unit/qrs_test.cpp:1\n"
    )
    completed = command("--release-gate")
    assert (completed.returncode, completed.stdout) == (
        1,
        f"FAIL: Release gate on milestones M0, M1\n  - {DEV_ITEM}\n",
    )


# --- the real repository ----------------------------------------------------------------------


def test_script_cites_no_requirement(tool: ModuleType) -> None:
    """The script is itself production code that the check reads (dsp/scripts)."""
    assert tool.REQ_ID.findall(SCRIPT.read_text(encoding="utf-8")) == []


def test_the_real_check_reads_nothing_from_this_file(tool: ModuleType) -> None:
    layout = tool.Layout(REPO_ROOT)
    here = layout.rel(Path(__file__).resolve())
    _, misplaced = tool.scan_python_tests(layout)
    assert [item for item in misplaced if item.startswith(f"{here}:")] == []
    citations = [where for places in tool.scan_code(layout).values() for where in places]
    assert [where for where in citations if "dsp/tests/" in where] == []
