"""Generate the traceability matrix and enforce the traceability gates (IEC 62304 §5.1.1).

The rules and their rationale are in docs/adr/0004-test-tagging-and-traceability-gates.md, with
the corrections and clarifications of docs/regulatory/architecture.md §8.16. From Milestone 2
the rules apply per software item (docs/adr/0006-verification-per-software-item.md, design in
docs/regulatory/architecture-m2.md §13.12).
IDs in this file are written as SRS-nnn, because this file is itself scanned for citations.

Sources of truth (paths relative to the repository root):
  - Requirements: headings ``### SRS-nnn: Title`` in docs/regulatory/srs.md. Each one has a
                  ``**Milestone:** Mn`` line and a ``**Verification level:**`` line whose first
                  word is ``Requirement`` or ``System``, and a ``**Software item:**`` line:
                  entries separated by ``;``, items joined by `` and ``, a qualifier in
                  parentheses ignored, ``CI workflow`` not an item. The items are ``dsp``,
                  ``desktop``, ``firmware``, ``backend`` and ``libs/<name>``. A requirement
                  marked ``_Deleted_`` needs none of these.
  - Milestones:   rows ``| Mn | Title | Status |`` in docs/regulatory/milestones.md, where Status
                  is ``Planned``, ``In progress`` or ``Released``.
  - Code:         any SRS ID in the Python sources of dsp/sinus_dsp and dsp/scripts, in the
                  Python sources of each C++ item (libs/<name>, firmware, desktop) outside its
                  test folders and its tools folder, and in the C and C++ sources of libs/,
                  firmware/ and desktop/, outside test folders (a folder named tests, test or
                  test_apps).
  - Python tests: ``@pytest.mark.requirement("SRS-nnn", ...)`` on test functions or classes,
                  or in ``pytestmark``, in the test files under dsp/tests and under the tests
                  folder of each C++ item (libs/<name>/tests, ...). Test files, classes and
                  functions are those of pytest's default discovery: files ``test_*.py``
                  or ``*_test.py``, classes ``Test*``, functions ``test*``. A requirement mark
                  in any other file under dsp/tests (a conftest.py, a helper module) fails
                  --check and is never counted. The same holds under the tests folder of a C++ item.
                  A test with a ``skip`` or ``xfail`` mark (decorator or ``pytestmark``), or a
                  GoogleTest suite or test named ``DISABLED_*``, is disabled: it fails --check
                  and never counts.
  - C++ tests:    one or more ``// Verifies: SRS-nnn, SRS-nnn`` lines directly above a
                  GoogleTest ``TEST``, ``TEST_F``, ``TEST_P``, ``TYPED_TEST`` or ``TYPED_TEST_P``,
                  in the sources under libs/, firmware/ and desktop/.
  - Open points:  rows ``| OP-nnn | Open point | Refs | Opened | Target | Status |`` in
                  docs/regulatory/open-points.md; Refs may cite SRS, HAZ and RC IDs (HAZ and RC
                  rows are in risk-analysis.md). The Target of a row of the Open section is
                  ``Mn`` or ``After Mn``, with Mn a milestone of the register.
  - Items:        the item of a file is given by its path: dsp/ is ``dsp``, libs/<name>/ is
                  ``libs/<name>``, and desktop/, firmware/ and backend/ are those items. A test
                  verifies a requirement for the item whose folder holds it, if the requirement
                  names that item; the release gate needs one in each item the requirement names.
  - Version:      ``[project] version`` in dsp/pyproject.toml and the string literal assigned
                  to ``__version__`` in dsp/sinus_dsp/__init__.py. Both are equal and follow
                  the milestone register: ``0.N.0.dev0`` with N the lowest milestone In
                  progress; if none is in progress, ``0.N.P`` with N the highest milestone
                  Released (docs/regulatory/sdp.md §4, architecture.md §8.14). The files are
                  read, not imported. The file ``VERSION`` (one line) of each C++ item folder
                  with a CMakeLists.txt holds the same version.

Test folders: a requirement tag is only accepted in a ``tests/requirements/`` folder (tests for
requirements with Verification level Requirement) or a ``tests/system/`` folder (level System),
e.g. dsp/tests/requirements/, libs/<name>/tests/system/. Unit tests carry no tags. A test
verifies a requirement only in the folder of the requirement's Verification level: a test in
the folder of the other level fails --check and verifies nothing.

The matrix shows each requirement with its citations and verifying tests, each milestone with
the outcome of the release gate for it, the outcome of the release gate as a whole with the
items that make it fail, and the gaps.

Usage (from the repository root or anywhere):
  python dsp/scripts/traceability.py                 # rewrite docs/regulatory/traceability.md
  python dsp/scripts/traceability.py --check         # exit 1 if any check fails, including
                                                     # the version rule (every push)
  python dsp/scripts/traceability.py --release-gate  # exit 1 unless every requirement of a
                                                     # milestone in progress or released has a
                                                     # verifying test, no open point targets
                                                     # it, and the version is not a development
                                                     # version (pull requests into main)
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIREMENT_LEVEL = "Requirement"
SYSTEM_LEVEL = "System"
# Folder directly under a ``tests`` folder -> verification level of the tests it holds.
LEVEL_DIRS = {"requirements": REQUIREMENT_LEVEL, "system": SYSTEM_LEVEL}
LEVEL_FOLDER = {level: f"tests/{name}/" for name, level in LEVEL_DIRS.items()}

PLANNED, IN_PROGRESS, RELEASED = "Planned", "In progress", "Released"
MILESTONE_STATUSES = (PLANNED, IN_PROGRESS, RELEASED)
# The release gate covers every milestone whose work has reached develop, and so main.
GATED_STATUSES = (IN_PROGRESS, RELEASED)
# An open point's Target is a milestone ``Mn`` of the register, or this prefix and one.
AFTER_PREFIX = "After "

CPP_SUFFIXES = (".c", ".cc", ".cpp", ".h", ".hpp")
# Folders holding tests, never scanned as production code (``test``: ESP-IDF component tests).
TEST_DIR_NAMES = frozenset({"tests", "test", "test_apps"})
# Build output and third-party code, never scanned.
SKIPPED_DIR_NAMES = frozenset(
    {"build", "_deps", "managed_components", "third_party", "external", "vendor"}
)
SKIPPED_DIR_PREFIXES = (".", "build-", "cmake-build-")

REQ_ID = re.compile(r"\bSRS-\d{3}\b")
REQ_ID_EXACT = re.compile(r"SRS-\d{3}")
REQ_HEADING = re.compile(r"^#{2,4}\s+(SRS-\d{3})\b[\s:—-]*(.*)$")
ANY_HEADING = re.compile(r"^#{1,6}\s")
MILESTONE_LINE = re.compile(r"^\*\*Milestone:\*\*(.*)$")
LEVEL_LINE = re.compile(r"^\*\*Verification level:\*\*\s*(\w*)")
ITEM_LINE = re.compile(r"^\*\*Software item:\*\*(.*)$")
CI_WORKFLOW = "CI workflow"
# First folders of the software items (the folder of a library is libs/<name>)
ITEM_FOLDERS = frozenset({"dsp", "desktop", "firmware", "backend"})
ITEM_NAME = re.compile(r"dsp|desktop|firmware|backend|libs/[a-z0-9][a-z0-9-]*")
# Marks that disable a test (skipif is allowed)
DISABLING_MARKS = frozenset({"skip", "xfail"})
CPP_DISABLED_PREFIX = "DISABLED_"
VERSION_FILE_NAME = "VERSION"
DELETED_MARK = "_Deleted_"
MILESTONE_ROW = re.compile(r"^\|\s*(M\d+)\s*\|")
RISK_ROW = re.compile(r"^\|\s*((?:HAZ|RC)-\d{3})\s*\|")
OP_ROW = re.compile(r"^\|\s*(OP-\d{3})\s*\|")
SPEC_ID = re.compile(r"\b(?:SRS|HAZ|RC)-\d{3}\b")

VERSION_NAME = "__version__"
# A version containing this is a development version (PEP 440), never released into main.
DEVELOPMENT_MARK = ".dev"

CPP_TAG = re.compile(r"^\s*//\s*Verifies:(.*)$")
# Case-insensitive on purpose: "// verifies: ..." must fail as a malformed tag, not be ignored.
CPP_TAG_KEYWORD = re.compile(r"\bVerifies\s*:", re.IGNORECASE)
_CPP_MACRO = r"(?:TYPED_TEST_P|TYPED_TEST|TEST_F|TEST_P|TEST)"
CPP_TEST_START = re.compile(rf"^\s*{_CPP_MACRO}\s*\(")
CPP_TEST_NAME = re.compile(rf"^\s*{_CPP_MACRO}\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)")
CPP_TEST_LOOKAHEAD = 5  # lines joined to read test macro arguments split over several lines


@dataclass(frozen=True)
class Layout:
    """Paths read and written; a root other than the repository allows tests on a fixture tree."""

    root: Path

    @property
    def regulatory(self) -> Path:
        return self.root / "docs" / "regulatory"

    @property
    def srs(self) -> Path:
        return self.regulatory / "srs.md"

    @property
    def milestones(self) -> Path:
        return self.regulatory / "milestones.md"

    @property
    def risk(self) -> Path:
        return self.regulatory / "risk-analysis.md"

    @property
    def open_points(self) -> Path:
        return self.regulatory / "open-points.md"

    @property
    def output(self) -> Path:
        return self.regulatory / "traceability.md"

    @property
    def pyproject(self) -> Path:
        return self.root / "dsp" / "pyproject.toml"

    @property
    def package_init(self) -> Path:
        return self.root / "dsp" / "sinus_dsp" / "__init__.py"

    @property
    def cpp_item_dirs(self) -> list[Path]:
        """The folders of the C++ software items that exist: ``libs/<name>``, ``desktop``,
        ``firmware`` (architecture-m2.md §13.12)."""
        libs = self.root / "libs"
        dirs = (
            sorted(d for d in libs.iterdir() if d.is_dir() and not _skipped_dir(d.name))
            if libs.is_dir()
            else []
        )
        return dirs + [self.root / n for n in ("desktop", "firmware") if (self.root / n).is_dir()]

    @property
    def python_code_roots(self) -> list[Path]:
        return [self.root / "dsp" / "sinus_dsp", self.root / "dsp" / "scripts", *self.cpp_item_dirs]

    @property
    def python_test_roots(self) -> list[Path]:
        return [self.root / "dsp" / "tests"] + [
            d / "tests" for d in self.cpp_item_dirs if (d / "tests").is_dir()
        ]

    @property
    def version_files(self) -> list[Path]:
        """The ``VERSION`` file of each C++ item folder that holds a ``CMakeLists.txt``."""
        dirs = [d for d in self.cpp_item_dirs if (d / "CMakeLists.txt").is_file()]
        return [d / VERSION_FILE_NAME for d in dirs]

    @property
    def cpp_roots(self) -> list[Path]:
        return [self.root / "libs", self.root / "firmware", self.root / "desktop"]

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    milestone: str | None  # value of the Milestone line; None if the line is missing
    level: str | None  # first word of the Verification level line; None if missing
    deleted: bool
    # SRS-nnn software items of the "Software item" line, in its order, without CI workflow
    items: tuple[str, ...] = ()
    item_errors: tuple[str, ...] = ()  # what is wrong with that line (without the SRS ID)


@dataclass(frozen=True)
class Milestone:
    id: str
    title: str
    status: str


@dataclass(frozen=True)
class TestRef:
    name: str  # path::Class::test (pytest) or path::Suite.Name (GoogleTest)
    level: str  # verification level of the folder the test is in
    disabled: str = ""  # how the test is disabled (rule "Disabled requirement tests"); else ""

    @property
    def item(self) -> str:
        """The software item whose folder holds the test file."""
        return item_of(self.name.split("::", 1)[0])


@dataclass(frozen=True)
class OpenPoint:
    id: str
    is_open: bool
    refs: list[str]
    target: str = ""  # the Target column of an open row (e.g. "M1"); empty for closed rows


@dataclass
class Matrix:
    requirements: dict[str, Requirement]
    milestones: dict[str, Milestone]
    code: dict[str, set[str]]
    tests: dict[str, list[TestRef]]
    risk_ids: set[str]
    open_points: list[OpenPoint]
    register_errors: list[str]  # duplicate requirements, milestones.md format errors
    misplaced_tags: list[str]  # requirement tags outside tests/requirements and tests/system
    # requirement marks in files under dsp/tests that are not test files (conftest.py, helpers)
    marks_outside_test_files: list[str]
    tag_errors: list[str]  # malformed or dangling C++ tags
    versions: dict[str, str]  # file -> package version found in it (pyproject first)
    version_errors: list[str]  # files whose package version cannot be read
    disabled_tests: list[str] = field(default_factory=list)  # tagged tests that are disabled


# --- Sources ---------------------------------------------------------------------------------


def item_of(rel_path: str) -> str:
    """The software item of a file from its path relative to the repository root (``dsp``,
    ``libs/<name>``, ``desktop``, ``firmware``, ``backend``); empty if it belongs to none."""
    parts = rel_path.replace("`", "").split("/")
    if parts[0] == "libs":
        return f"libs/{parts[1]}" if len(parts) > 2 else ""
    return parts[0] if parts[0] in ITEM_FOLDERS and len(parts) > 1 else ""


def parse_software_items(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Software items of a ``**Software item:**`` line (the text after the label) and the
    errors in it. Entries are separated by ``;``, an entry may join items with `` and ``, a
    qualifier in parentheses is ignored, and ``CI workflow`` is not an item."""
    items: list[str] = []
    errors: list[str] = []
    for entry in text.split(";"):
        for part in re.split(r"\s+and\s+", re.sub(r"\([^)]*\)", "", entry).strip()):
            name = part.strip()
            if not name or name == CI_WORKFLOW:
                continue
            if not ITEM_NAME.fullmatch(name):
                errors.append(f"unknown software item '{name}'")
            elif name not in items:
                items.append(name)
    if not items and not errors:
        errors.append(f"no software item other than {CI_WORKFLOW}")
    return tuple(items), tuple(errors)


def _skipped_dir(name: str) -> bool:
    return name in SKIPPED_DIR_NAMES or name.startswith(SKIPPED_DIR_PREFIXES)


def iter_sources(root: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
    """Files under ``root`` ending in one of ``suffixes``, sorted, outside build/vendor folders."""
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skipped_dir(d))
        for name in sorted(filenames):
            if name.endswith(suffixes):
                yield Path(dirpath) / name


def _in_tools_folder(path: Path, layout: Layout) -> bool:
    """Whether the file of a C++ software item is in a folder named ``tools``."""
    rel = layout.rel(path)
    return item_of(rel) != "dsp" and "tools" in rel.split("/")[:-1]


def is_test_path(path: Path, layout: Layout) -> bool:
    return any(part in TEST_DIR_NAMES for part in path.relative_to(layout.root).parts[:-1])


def folder_level(path: Path, layout: Layout) -> str | None:
    """Verification level of a test file from its folder (``tests/requirements|system/``)."""
    parts = path.relative_to(layout.root).parts[:-1]
    for part, child in zip(parts, parts[1:], strict=False):
        if part == "tests" and child in LEVEL_DIRS:
            return LEVEL_DIRS[child]
    return None


def parse_requirements(layout: Layout) -> tuple[dict[str, Requirement], list[str]]:
    """Requirements by ID, and duplicate-ID errors."""
    if not layout.srs.exists():
        return {}, []
    blocks: list[tuple[str, str, list[str]]] = []  # id, title, lines of the entry
    for raw in layout.srs.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if m := REQ_HEADING.match(line):
            blocks.append((m.group(1), m.group(2).strip(), [line]))
        elif ANY_HEADING.match(line):
            blocks.append(("", "", []))  # any other heading ends the current entry
        elif blocks:
            blocks[-1][2].append(line)

    requirements: dict[str, Requirement] = {}
    errors: list[str] = []
    for req_id, title, lines in blocks:
        if not req_id:
            continue
        if req_id in requirements:
            errors.append(f"{req_id}: defined more than once in srs.md")
            continue
        milestone = level = item_text = None
        for line in lines:
            if m := MILESTONE_LINE.match(line):
                milestone = m.group(1).strip()
            elif m := LEVEL_LINE.match(line):
                level = m.group(1)
            elif m := ITEM_LINE.match(line):
                item_text = m.group(1)
        deleted = any(DELETED_MARK in line for line in lines)
        if item_text is None:
            items: tuple[str, ...] = ()
            item_errors: tuple[str, ...] = ("no '**Software item:**' line",)
        else:
            items, item_errors = parse_software_items(item_text)
        requirements[req_id] = Requirement(
            req_id, title, milestone, level, deleted, items, item_errors
        )
    return requirements, errors


def parse_milestones(layout: Layout) -> tuple[dict[str, Milestone], list[str]]:
    """Milestones by ID, and format errors of the register."""
    name = layout.rel(layout.milestones)
    if not layout.milestones.exists():
        return {}, [f"{name} not found"]
    milestones: dict[str, Milestone] = {}
    errors: list[str] = []
    for line in layout.milestones.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not MILESTONE_ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            errors.append(f"{name}: row {cells[0]} needs the columns Milestone, Title, Status")
            continue
        ms = Milestone(id=cells[0], title=cells[1], status=cells[2])
        if ms.id in milestones:
            errors.append(f"{name}: milestone {ms.id} listed more than once")
        elif ms.status not in MILESTONE_STATUSES:
            errors.append(
                f"{name}: milestone {ms.id} has status '{ms.status}', "
                f"expected one of: {', '.join(MILESTONE_STATUSES)}"
            )
        else:
            milestones[ms.id] = ms
    return milestones, errors


def parse_risk_ids(layout: Layout) -> set[str]:
    if not layout.risk.exists():
        return set()
    lines = layout.risk.read_text(encoding="utf-8").splitlines()
    return {m.group(1) for line in lines if (m := RISK_ROW.match(line.strip()))}


def parse_open_points(layout: Layout) -> list[OpenPoint]:
    """Rows under the "## Open" heading are open; rows under any other heading are not."""
    points: list[OpenPoint] = []
    if not layout.open_points.exists():
        return points
    section = ""
    for line in layout.open_points.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("## "):
            section = line[3:].strip().lower()
        elif m := OP_ROW.match(line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            refs = SPEC_ID.findall(cells[2]) if len(cells) > 2 else []
            is_open = section == "open"
            target = cells[4] if is_open and len(cells) > 4 else ""
            points.append(OpenPoint(id=m.group(1), is_open=is_open, refs=refs, target=target))
    return points


def scan_code(layout: Layout) -> dict[str, set[str]]:
    """Requirement -> ``path:line`` of every citation in production code: the Python and C/C++
    sources under the code roots, outside test folders."""
    files = [p for r in layout.python_code_roots for p in iter_sources(r, (".py",))]
    files += [p for r in layout.cpp_roots for p in iter_sources(r, CPP_SUFFIXES)]
    files = [p for p in files if not is_test_path(p, layout)]
    # Python files in the tools folder of a C++ item are not production code
    files = [p for p in files if p.suffix != ".py" or not _in_tools_folder(p, layout)]
    refs: dict[str, set[str]] = defaultdict(set)
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for req in REQ_ID.findall(line):
                refs[req].add(f"`{layout.rel(path)}:{lineno}`")
    return refs


def read_pyproject_version(layout: Layout) -> tuple[str | None, str | None]:
    """The ``[project] version`` of dsp/pyproject.toml, or the reason it cannot be read."""
    name = layout.rel(layout.pyproject)
    if not layout.pyproject.exists():
        return None, f"{name} not found"
    try:
        data = tomllib.loads(layout.pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        return None, f"{name}: not valid TOML ({error})"
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str):
        return None, f"{name}: no [project] version given as a string"
    return version, None


def read_package_init_version(layout: Layout) -> tuple[str | None, str | None]:
    """The string literal assigned to ``__version__`` at the top level of the package's
    ``__init__.py``, or the reason it cannot be read."""
    name = layout.rel(layout.package_init)
    if not layout.package_init.exists():
        return None, f"{name} not found"
    try:
        tree = ast.parse(layout.package_init.read_text(encoding="utf-8"), filename=name)
    except SyntaxError as error:
        return None, f"{name}: not valid Python ({error.msg}, line {error.lineno})"
    values: list[ast.expr | None] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == VERSION_NAME for target in stmt.targets
        ):
            values.append(stmt.value)
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == VERSION_NAME
        ):
            values.append(stmt.value)
    if len(values) != 1:
        return None, f"{name}: {VERSION_NAME} assigned {len(values)} times, expected once"
    value = values[0]
    if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
        return None, f"{name}: {VERSION_NAME} is not assigned a string literal"
    return value.value, None


def read_version_file(layout: Layout, path: Path) -> tuple[str | None, str | None]:
    """The version in the one line of the ``VERSION`` file of a C++ item, or the reason it
    cannot be read."""
    name = layout.rel(path)
    if not path.is_file():
        return None, f"{name} not found"
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1 or not lines[0].strip():
        return None, f"{name}: not one line"
    return lines[0].strip(), None


def read_versions(layout: Layout) -> tuple[dict[str, str], list[str]]:
    """Package version by file (dsp/pyproject.toml first, then the ``VERSION`` file of each C++
    item that has a CMakeLists.txt), and the files where none is read."""
    versions: dict[str, str] = {}
    errors: list[str] = []
    for path, read in (
        (layout.pyproject, read_pyproject_version),
        (layout.package_init, read_package_init_version),
    ):
        version, error = read(layout)
        if version is not None:
            versions[layout.rel(path)] = version
        if error is not None:
            errors.append(error)
    for path in layout.version_files:
        version, error = read_version_file(layout, path)
        if version is not None:
            versions[layout.rel(path)] = version
        if error is not None:
            errors.append(error)
    return versions, errors


# --- Python tests (pytest) -------------------------------------------------------------------


def _is_requirement_mark(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "requirement"
    )


def _mark_ids(expr: ast.expr) -> list[str]:
    """IDs from a requirement mark, or from a list/tuple of marks (as in ``pytestmark``)."""
    marks = expr.elts if isinstance(expr, ast.List | ast.Tuple) else [expr]
    return [
        a.value
        for m in marks
        if isinstance(m, ast.Call) and _is_requirement_mark(m)
        for a in m.args
        if isinstance(a, ast.Constant) and isinstance(a.value, str)
    ]


def _pytestmark_exprs(body: list[ast.stmt]) -> list[ast.expr]:
    """Values of ``pytestmark = ...`` assignments, annotated or not, at module or class level."""
    exprs: list[ast.expr] = []
    for stmt in body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            exprs.append(stmt.value)
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == "pytestmark"
            and stmt.value is not None
        ):
            exprs.append(stmt.value)
    return exprs


def _pytestmark_ids(body: list[ast.stmt]) -> list[str]:
    """IDs from ``pytestmark = ...`` assignments at module or class level."""
    return [i for expr in _pytestmark_exprs(body) for i in _mark_ids(expr)]


def _disabling_marks(expr: ast.expr) -> list[str]:
    """The marks ``skip`` and ``xfail`` of a mark or of a list/tuple of marks, as written
    (``pytest.mark.skip``), whether used bare or called; ``skipif`` is not one."""
    marks = expr.elts if isinstance(expr, ast.List | ast.Tuple) else [expr]
    out: list[str] = []
    for mark in marks:
        target = mark.func if isinstance(mark, ast.Call) else mark
        if isinstance(target, ast.Attribute) and target.attr in DISABLING_MARKS:
            out.append(ast.unparse(target))
    return out


def is_python_test_file(path: Path) -> bool:
    """Whether pytest's default discovery collects the file: ``test_*.py`` or ``*_test.py``."""
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def scan_python_tests(layout: Layout) -> tuple[dict[str, list[TestRef]], list[str], list[str]]:
    """Requirement -> tagged tests, requirement marks in test files outside the verification
    folders, and requirement marks in files that are not test files.

    Every ``.py`` file under the test roots is read; a file that is not valid Python stops the
    script with the parser's error. A mark found in a file that is not a test file is never
    counted, whatever its folder: pytest applies no such mark by itself, and a mark added by a
    hook cannot be read statically.
    """
    refs: dict[str, list[TestRef]] = defaultdict(list)
    misplaced: list[str] = []
    outside: list[str] = []

    def visit(
        body: list[ast.stmt], prefix: str, inherited: list[str], off: list[str], level: str
    ) -> None:
        inherited = inherited + _pytestmark_ids(body)
        marks = [x for e in _pytestmark_exprs(body) for x in _disabling_marks(e)]
        off = off + [f"pytestmark {x}" for x in marks]
        for node in body:
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                ids = inherited + [i for d in node.decorator_list for i in _mark_ids(d)]
                # A skip or xfail mark disables the test (OP-066)
                node_off = off + [
                    f"decorator @{x}" for d in node.decorator_list for x in _disabling_marks(d)
                ]
                name = f"{prefix}::{node.name}"
                if isinstance(node, ast.ClassDef):
                    # pytest's default discovery: tests are only collected in classes Test*
                    if node.name.startswith("Test"):
                        visit(node.body, name, ids, node_off, level)
                elif node.name.startswith("test"):
                    how = ", ".join(dict.fromkeys(node_off))
                    for req in dict.fromkeys(ids):
                        refs[req].append(TestRef(name, level, how))

    for root in layout.python_test_roots:
        for path in iter_sources(root, (".py",)):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            # Every requirement mark call, however it is applied (decorator, pytestmark,
            # pytest.param(marks=...)).
            marks = [
                f"{layout.rel(path)}:{n.lineno}"
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and _is_requirement_mark(n)
            ]
            if not is_python_test_file(path):
                outside += marks
                continue
            level = folder_level(path, layout)
            # A requirement mark outside the verification folders is rejected and not counted.
            if level is None:
                misplaced += marks
                continue
            visit(tree.body, layout.rel(path), [], [], level)
    return refs, misplaced, outside


# --- C++ tests (GoogleTest) ------------------------------------------------------------------


def scan_cpp_tests(layout: Layout) -> tuple[dict[str, list[TestRef]], list[str], list[str]]:
    """Requirement -> verifying tests, misplaced tags, and malformed or dangling tags.

    A tag is one or more consecutive ``// Verifies: SRS-nnn[, SRS-nnn...]`` lines, each on its
    own line, directly followed by the line that opens a GoogleTest test macro.
    """
    refs: dict[str, list[TestRef]] = defaultdict(list)
    misplaced: list[str] = []
    errors: list[str] = []
    expected = "a GoogleTest TEST, TEST_F, TEST_P, TYPED_TEST or TYPED_TEST_P"
    for root in layout.cpp_roots:
        for path in iter_sources(root, CPP_SUFFIXES):
            where = layout.rel(path)
            level = folder_level(path, layout)
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            pending: list[str] = []
            pending_at = 0
            for i, line in enumerate(lines):
                lineno = i + 1
                if tag := CPP_TAG.match(line):
                    ids = [t.strip() for t in tag.group(1).split(",")]
                    if not all(REQ_ID_EXACT.fullmatch(t) for t in ids):
                        errors.append(
                            f"{where}:{lineno}: malformed tag, expected '// Verifies: SRS-nnn' "
                            "or '// Verifies: SRS-nnn, SRS-nnn'"
                        )
                    if level is None:
                        misplaced.append(f"{where}:{lineno}")
                    if not pending:
                        pending_at = lineno
                    pending += [t for t in ids if REQ_ID_EXACT.fullmatch(t)]
                    continue
                if CPP_TAG_KEYWORD.search(line):
                    errors.append(
                        f"{where}:{lineno}: 'Verifies:' is reserved for a "
                        "'// Verifies: SRS-nnn' comment on its own line"
                    )
                if not pending:
                    continue
                test = None
                if CPP_TEST_START.match(line):
                    test = CPP_TEST_NAME.match(" ".join(lines[i : i + CPP_TEST_LOOKAHEAD]))
                if test is None:
                    errors.append(f"{where}:{pending_at}: tag not directly followed by {expected}")
                elif level is not None:
                    name = f"{where}::{test.group(1)}.{test.group(2)}"
                    how = ", ".join(
                        f"{kind} {text}"
                        for kind, text in (("suite", test.group(1)), ("test", test.group(2)))
                        if text.startswith(CPP_DISABLED_PREFIX)
                    )
                    for req in dict.fromkeys(pending):
                        refs[req].append(TestRef(name, level, how))
                pending = []
            if pending:
                errors.append(f"{where}:{pending_at}: tag not directly followed by {expected}")
    return refs, misplaced, errors


# --- Matrix and checks -----------------------------------------------------------------------


def build(layout: Layout) -> Matrix:
    requirements, req_errors = parse_requirements(layout)
    milestones, ms_errors = parse_milestones(layout)
    py_tests, py_misplaced, py_outside = scan_python_tests(layout)
    cpp_tests, cpp_misplaced, tag_errors = scan_cpp_tests(layout)
    versions, version_errors = read_versions(layout)
    tests: dict[str, list[TestRef]] = defaultdict(list)
    disabled: dict[str, str] = {}  # a disabled test does not count (OP-066)
    for source in (py_tests, cpp_tests):
        for req, refs in source.items():
            for ref in refs:
                if ref.disabled:
                    disabled[ref.name] = f"{ref.name}: requirement test disabled ({ref.disabled})"
                else:
                    tests[req].append(ref)
    return Matrix(
        requirements=requirements,
        milestones=milestones,
        code=scan_code(layout),
        tests=dict(tests),
        risk_ids=parse_risk_ids(layout),
        open_points=parse_open_points(layout),
        register_errors=req_errors + ms_errors,
        misplaced_tags=sorted(py_misplaced + cpp_misplaced),
        marks_outside_test_files=sorted(py_outside),
        tag_errors=sorted(tag_errors),
        versions=versions,
        version_errors=version_errors,
        disabled_tests=sorted(disabled.values()),
    )


def _milestone_key(milestone_id: str) -> int:
    return int(milestone_id[1:])


def verifying(m: Matrix, req_id: str) -> list[TestRef]:
    """The tests that verify a requirement: those tagged with it in the folder of its
    Verification level (ADR 0004 §5, §6). If the requirement is not defined, or its level is
    neither Requirement nor System, every test tagged with it counts; both cases fail --check.
    """
    tests = m.tests.get(req_id, [])
    req = m.requirements.get(req_id)
    if req is None:
        return list(tests)
    # A test in an item that the requirement does not name does not count (ADR 0006)
    if req.items:
        tests = [test for test in tests if test.item in req.items]
    if req.level not in LEVEL_FOLDER:
        return list(tests)
    return [test for test in tests if test.level == req.level]


def verifying_in(m: Matrix, req_id: str, item: str) -> list[TestRef]:
    """The verifying tests of a requirement whose file belongs to ``item``."""
    return [test for test in verifying(m, req_id) if test.item == item]


def missing_items(m: Matrix, req_id: str) -> list[str]:
    """The software items of a requirement that have no verifying test, in the order of its
    ``Software item`` line."""
    req = m.requirements.get(req_id)
    return [item for item in req.items if not verifying_in(m, req_id, item)] if req else []


def is_verified(m: Matrix, req_id: str) -> bool:
    """Whether a requirement has a verifying test in each of its software items (in any, if
    its line names none that can be read)."""
    req = m.requirements.get(req_id)
    if req is not None and req.items:
        return not missing_items(m, req_id)
    return bool(verifying(m, req_id))


def requirement_errors(m: Matrix) -> list[str]:
    """Register errors, and requirements without a valid milestone or verification level."""
    errors = list(m.register_errors)
    for req in sorted(m.requirements.values(), key=lambda r: r.id):
        if req.deleted:
            continue
        if not req.milestone:
            errors.append(f"{req.id}: no '**Milestone:** Mn' line")
        elif req.milestone not in m.milestones:
            errors.append(f"{req.id}: milestone '{req.milestone}' is not in milestones.md")
        if req.level not in LEVEL_FOLDER:
            errors.append(
                f"{req.id}: the '**Verification level:**' line must start with "
                f"{REQUIREMENT_LEVEL} or {SYSTEM_LEVEL}"
            )
        errors += [f"{req.id}: {error}" for error in req.item_errors]
    return errors


def unknown_ids(m: Matrix) -> list[str]:
    return sorted((set(m.code) | set(m.tests)) - set(m.requirements))


def level_mismatches(m: Matrix) -> list[str]:
    """Tests located in the folder of the other verification level than their requirement's."""
    out: list[str] = []
    for req_id in sorted(m.tests):
        req = m.requirements.get(req_id)
        if req is None or req.level not in LEVEL_FOLDER:
            continue
        for test in sorted(m.tests[req_id], key=lambda t: t.name):
            if test.level != req.level:
                out.append(
                    f"{req_id} has Verification level {req.level} (tests in "
                    f"{LEVEL_FOLDER[req.level]}), but is tagged in {test.name}"
                )
    return out


def implemented_untested(m: Matrix) -> list[str]:
    """Items whose production code cites a requirement without a verifying test in the item."""
    out: list[str] = []
    for req in sorted(m.code):
        if req not in m.requirements:
            continue
        by_item: dict[str, list[str]] = defaultdict(list)
        for citation in sorted(m.code[req]):
            by_item[item_of(citation.strip("`").rsplit(":", 1)[0])].append(citation)
        for item, citations in sorted(by_item.items()):
            if not verifying_in(m, req, item):
                out.append(
                    f"{req}: implemented in {item} (cited in {', '.join(citations)}) "
                    f"without a verifying test in {item}"
                )
    return out


def cited_outside_items(m: Matrix) -> list[str]:
    """Citations in the production code of an item that the requirement does not name."""
    out: list[str] = []
    for req_id in sorted(m.code):
        req = m.requirements.get(req_id)
        if req is None or not req.items:
            continue
        for citation in sorted(m.code[req_id]):
            where = citation.strip("`")
            if item_of(where.rsplit(":", 1)[0]) not in req.items:
                out.append(
                    f"{req_id}: cited in {where}, but its software items are {', '.join(req.items)}"
                )
    return out


def tagged_outside_items(m: Matrix) -> list[str]:
    """Tests tagged with a requirement that lie in an item that the requirement does not name."""
    out: list[str] = []
    for req_id in sorted(m.tests):
        req = m.requirements.get(req_id)
        if req is None or not req.items:
            continue
        out += [
            f"{req_id} names {', '.join(req.items)}, but is tagged in {test.name}"
            for test in sorted(m.tests[req_id], key=lambda t: t.name)
            if test.item not in req.items
        ]
    return out


def dangling_refs(m: Matrix) -> list[str]:
    """Open-point references (open or closed) to SRS/HAZ/RC IDs that are not defined."""
    defined = set(m.requirements) | m.risk_ids
    return sorted(f"{op.id}→{ref}" for op in m.open_points for ref in op.refs if ref not in defined)


def duplicate_open_points(m: Matrix) -> list[str]:
    counts = Counter(op.id for op in m.open_points)
    return sorted(op_id for op_id, n in counts.items() if n > 1)


def target_errors(m: Matrix) -> list[str]:
    """Open points of the Open section whose Target is not exactly ``Mn`` or ``After Mn``, with
    Mn a milestone of the register; an empty or missing Target included. The release gate
    compares Targets exactly, so any other form would escape it."""
    out: list[str] = []
    for op in m.open_points:
        if not op.is_open:
            continue
        target = op.target
        milestone = target.removeprefix(AFTER_PREFIX)
        if milestone not in m.milestones:
            out.append(
                f"{op.id}: Target '{target}' is not a milestone of milestones.md "
                "(expected 'Mn' or 'After Mn')"
            )
    return sorted(out)


def gated_milestones(m: Matrix) -> list[str]:
    return sorted(
        (ms.id for ms in m.milestones.values() if ms.status in GATED_STATUSES),
        key=_milestone_key,
    )


def expected_version(m: Matrix) -> tuple[re.Pattern[str], str] | None:
    """The version that the milestone register gives, as (pattern, text naming the form).

    ``0.N.0.dev0`` exactly, with N the lowest milestone In progress; if none is in progress,
    ``0.N.P`` with N the highest milestone Released and P a whole number without leading
    zeros. ``None`` if no milestone is In progress or Released.
    """
    by_status: dict[str, list[Milestone]] = defaultdict(list)
    for ms in m.milestones.values():
        by_status[ms.status].append(ms)
    if in_progress := by_status["In progress"]:
        ms = min(in_progress, key=lambda ms: _milestone_key(ms.id))
        version = f"0.{_milestone_key(ms.id)}.0.dev0"
        return re.compile(re.escape(version)), f"{version} ({ms.id} In progress)"
    if released := by_status["Released"]:
        ms = max(released, key=lambda ms: _milestone_key(ms.id))
        n = _milestone_key(ms.id)
        return (
            re.compile(rf"0\.{n}\.(0|[1-9][0-9]*)"),
            f"0.{n}.P with P = 0, 1, 2, ... ({ms.id} Released, none In progress)",
        )
    return None


def version_failures(m: Matrix) -> list[str]:
    """Package versions that cannot be read, that differ between the two files, or that do not
    follow the milestone register."""
    out = list(m.version_errors)
    rule = expected_version(m)
    if rule is None:
        out.append("milestones.md: no milestone is In progress or Released, so no version fits")
    else:
        pattern, form = rule
        out += [
            f"{name}: version {version}, expected {form}"
            for name, version in m.versions.items()
            if not pattern.fullmatch(version)
        ]
    found = list(m.versions.items())
    for name, version in found[1:]:
        first, first_version = found[0]
        if version != first_version:
            out.append(f"{name}: version {version}, expected {first_version} (as in {first})")
    return out


def development_versions(m: Matrix) -> list[str]:
    """Package versions that are development versions, which a release cannot carry, and
    files where no version can be read."""
    out = list(m.version_errors)
    reported: set[str] = set()
    for name, version in m.versions.items():
        if DEVELOPMENT_MARK in version and version not in reported:
            reported.add(version)
            out.append(f"{name}: version {version} is a development version, not a release")
    return out


def release_gate_failures(m: Matrix) -> list[str]:
    """Requirements of gated milestones without a verifying test or without a valid milestone,
    open points that still target a gated milestone, and a development version."""
    gated = set(gated_milestones(m))
    out: list[str] = []
    for req in sorted(m.requirements.values(), key=lambda r: r.id):
        if req.deleted:
            continue
        if req.milestone not in m.milestones:
            out.append(f"{req.id}: no valid milestone, so the gate cannot place it")
        elif req.milestone in gated and not is_verified(m, req.id):
            status = m.milestones[req.milestone].status
            where = missing_items(m, req.id) or [""]
            out += [
                f"{req.id} ({req.milestone}, {status}): no verifying test"
                + (f" in {item}" if item else "")
                for item in where
            ]
    for op in sorted(m.open_points, key=lambda o: o.id):
        if op.is_open and op.target in gated:
            out.append(f"{op.id}: open point still targets {op.target}; close or retarget it")
    out += development_versions(m)
    return out


def gated_milestones_text(m: Matrix) -> str:
    """The milestones the release gate covers, as the matrix and the command line name them."""
    return ", ".join(gated_milestones(m)) or "none"


def milestone_gate(m: Matrix, ms: Milestone) -> str:
    """The cell ``Release gate`` of a milestone in the matrix.

    ``not applied`` for a Planned milestone; ``pass`` for a Released milestone whose
    requirements that are not deleted all have a verifying test and that no open point of the
    Open section targets; ``**fail**`` otherwise, so always for a milestone In progress, whose
    development version the gate rejects (architecture.md §8.14, §8.16).
    """
    if ms.status == PLANNED:
        return "not applied"
    reqs = [r for r in m.requirements.values() if r.milestone == ms.id and not r.deleted]
    verified = all(is_verified(m, r.id) for r in reqs)
    targeted = any(op.is_open and op.target == ms.id for op in m.open_points)
    return "pass" if ms.status == RELEASED and verified and not targeted else "**fail**"


def render(m: Matrix) -> str:
    open_by_req: dict[str, list[str]] = defaultdict(list)
    for op in m.open_points:
        if op.is_open:
            for ref in dict.fromkeys(op.refs):
                open_by_req[ref].append(op.id)

    lines = [
        "# Traceability matrix",
        "",
        "<!-- Generated by dsp/scripts/traceability.py. Do not edit by hand. -->",
        "",
        "Rules: [ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md). "
        "Milestone status: [`milestones.md`](milestones.md).",
        "",
        "| Requirement | Title | Software items | Milestone | Verification level "
        "| Implemented in | Verified by | Open points |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for req_id in sorted(m.requirements):
        req = m.requirements[req_id]
        code = "<br>".join(sorted(m.code.get(req_id, ()))) or "—"
        cells = sorted(f"`{t.name}`" for t in verifying(m, req_id))
        if len(req.items) > 1 and not req.deleted:
            cells += [f"**none in {item}**" for item in missing_items(m, req_id)]
        tests = "<br>".join(cells) or ("deleted" if req.deleted else "**none**")
        ops = ", ".join(sorted(open_by_req.get(req_id, ()))) or "—"
        items = ", ".join(req.items) or "—"
        lines.append(
            f"| {req_id} | {req.title} | {items} | {req.milestone or '—'} | {req.level or '—'} "
            f"| {code} | {tests} | {ops} |"
        )
    if not m.requirements:
        lines.append("| — | _No requirements defined yet in `srs.md`_ | — | — | — | — | — | — |")

    lines += [
        "",
        "## Milestones",
        "",
        "| Milestone | Title | Status | Requirements | With a verifying test | Release gate |",
        "|---|---|---|---|---|---|",
    ]
    for ms_id in sorted(m.milestones, key=_milestone_key):
        ms = m.milestones[ms_id]
        reqs = [r for r in m.requirements.values() if r.milestone == ms_id and not r.deleted]
        tested = sum(1 for r in reqs if is_verified(m, r.id))
        gate = milestone_gate(m, ms)
        lines.append(f"| {ms_id} | {ms.title} | {ms.status} | {len(reqs)} | {tested} | {gate} |")

    # The outcome of the gate as a whole: the version items belong to no single milestone.
    gate_items = release_gate_failures(m)
    outcome = "**fail**" if gate_items else "pass"
    lines += [
        "",
        "## Release gate",
        "",
        f"Outcome of `--release-gate` on milestones {gated_milestones_text(m)}: {outcome}",
    ]
    if gate_items:
        lines += ["", *(f"- {item}" for item in gate_items)]

    untested: list[str] = []
    for r in sorted(m.requirements):
        if m.requirements[r].deleted:
            continue
        if not verifying(m, r):
            untested.append(r)
        elif missing := missing_items(m, r):
            untested.append(f"{r} ({', '.join(missing)})")
    implemented = list(dict.fromkeys(line.split(":", 1)[0] for line in implemented_untested(m)))
    open_count = sum(op.is_open for op in m.open_points)
    lines += ["", "## Gaps", ""]
    lines.append(f"- Requirements without tests: {', '.join(untested) or 'none'}")
    lines.append(f"- Implemented requirements without tests: {', '.join(implemented) or 'none'}")
    lines.append(f"- Unknown IDs referenced in code/tests: {', '.join(unknown_ids(m)) or 'none'}")
    lines.append(f"- Open points citing undefined IDs: {', '.join(dangling_refs(m)) or 'none'}")
    lines.append(f"- Open points still open: {open_count} (see `open-points.md`)")
    return "\n".join(lines) + "\n"


def check_failures(m: Matrix, layout: Layout, content: str) -> list[tuple[str, list[str]]]:
    """Every failure of ``--check``, as (rule, items) pairs."""
    current = layout.output.read_text(encoding="utf-8") if layout.output.exists() else ""
    stale = [] if current == content else ["run: python dsp/scripts/traceability.py"]
    return [
        (f"{layout.rel(layout.output)} is stale", stale),
        ("Requirement or milestone register errors", requirement_errors(m)),
        ("Unknown requirement IDs referenced in code or tests", unknown_ids(m)),
        (
            "Requirement tags outside tests/requirements/ or tests/system/ (independence rule)",
            m.misplaced_tags,
        ),
        ("Requirement marks outside test files", m.marks_outside_test_files),
        ("Malformed or dangling C++ requirement tags", m.tag_errors),
        ("Disabled requirement tests", m.disabled_tests),
        ("Tests in the wrong folder for the requirement's verification level", level_mismatches(m)),
        (
            "Tests in the folder of an item that the requirement does not name",
            tagged_outside_items(m),
        ),
        ("Implemented requirements without a verifying test", implemented_untested(m)),
        ("Requirements cited by an item that they do not name", cited_outside_items(m)),
        ("Open points citing undefined IDs", dangling_refs(m)),
        ("Duplicate open point IDs", duplicate_open_points(m)),
        ("Open points with a Target that is not a milestone", target_errors(m)),
        ("Software version", version_failures(m)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "do not write; fail if the committed matrix is stale, a requirement lacks a valid "
            "milestone or verification level, code or tests cite unknown IDs, a requirement tag "
            "is outside tests/requirements/ and tests/system/ or in the folder of the other "
            "verification level, a requirement mark is in a file under dsp/tests that is not a "
            "test file, a C++ tag is malformed, a requirement cited in production code has no "
            "verifying test in the item that cites it, an item cites a requirement that does not "
            "name it, a test is tagged in an item that the requirement does not name, a "
            "requirement test is disabled (skip, xfail, DISABLED_), a requirement has no valid "
            "'**Software item:**' line, open points cite undefined IDs, repeat an ID or have a "
            "Target that is not 'Mn' or 'After Mn' with Mn in the milestone register, or the "
            "package version differs between dsp/pyproject.toml, sinus_dsp/__init__.py and the "
            "VERSION files of the C++ items, or does not follow the milestone register"
        ),
    )
    parser.add_argument(
        "--release-gate",
        action="store_true",
        help=(
            "do not write; fail unless every requirement of a milestone that is In progress or "
            "Released in docs/regulatory/milestones.md has a verifying test, in the folder of "
            "its verification level, in each of its software items, no open point still "
            "targets such a milestone, and the package version is not a development version "
            "(run on pull requests into main)"
        ),
    )
    args = parser.parse_args(argv)

    layout = Layout(REPO_ROOT)
    matrix = build(layout)
    content = render(matrix)

    if not (args.check or args.release_gate):
        layout.output.write_text(content, encoding="utf-8", newline="\n")
        print(f"Wrote {layout.rel(layout.output)}")
        return 0

    gate = f"release gate on milestones {gated_milestones_text(matrix)}"
    failures: list[tuple[str, list[str]]] = []
    if args.check:
        failures += check_failures(matrix, layout, content)
    if args.release_gate:
        failures.append((gate[:1].upper() + gate[1:], release_gate_failures(matrix)))
    failed = [(rule, items) for rule, items in failures if items]
    for rule, items in failed:
        print(f"FAIL: {rule}")
        for item in items:
            print(f"  - {item}")
    if failed:
        return 1
    done = [name for name, flag in (("checks", args.check), (gate, args.release_gate)) if flag]
    print(f"Traceability: passed ({' and '.join(done)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
