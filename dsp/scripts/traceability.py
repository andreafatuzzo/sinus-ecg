"""Generate the traceability matrix and enforce the traceability gates (IEC 62304 §5.1.1).

The rules and their rationale are in docs/adr/0004-test-tagging-and-traceability-gates.md.
IDs in this file are written as SRS-nnn, because this file is itself scanned for citations.

Sources of truth (paths relative to the repository root):
  - Requirements: headings ``### SRS-nnn: Title`` in docs/regulatory/srs.md. Each one has a
                  ``**Milestone:** Mn`` line and a ``**Verification level:**`` line whose first
                  word is ``Requirement`` or ``System``. A requirement marked ``_Deleted_`` needs
                  neither.
  - Milestones:   rows ``| Mn | Title | Status |`` in docs/regulatory/milestones.md, where Status
                  is ``Planned``, ``In progress`` or ``Released``.
  - Code:         any SRS ID in the Python sources of dsp/sinus_dsp and dsp/scripts, and in the
                  C and C++ sources of libs/, firmware/ and desktop/ outside their test folders.
  - Python tests: ``@pytest.mark.requirement("SRS-nnn", ...)`` on test functions or classes,
                  or in ``pytestmark``, in the test files under dsp/tests.
  - C++ tests:    one or more ``// Verifies: SRS-nnn, SRS-nnn`` lines directly above a
                  GoogleTest ``TEST``, ``TEST_F``, ``TEST_P``, ``TYPED_TEST`` or ``TYPED_TEST_P``,
                  in the sources under libs/, firmware/ and desktop/.
  - Open points:  ``| OP-nnn | ... | refs | ...`` rows in docs/regulatory/open-points.md; refs
                  may cite SRS, HAZ and RC IDs (HAZ and RC rows are in risk-analysis.md).

Test folders: a requirement tag is only accepted in a ``tests/requirements/`` folder (tests for
requirements with Verification level Requirement) or a ``tests/system/`` folder (level System),
e.g. dsp/tests/requirements/, libs/<name>/tests/system/. Unit tests carry no tags.

Usage (from the repository root or anywhere):
  python dsp/scripts/traceability.py                 # rewrite docs/regulatory/traceability.md
  python dsp/scripts/traceability.py --check         # exit 1 if any check fails (every push)
  python dsp/scripts/traceability.py --release-gate  # exit 1 unless every requirement of a
                                                     # milestone in progress or released has a
                                                     # verifying test and no open point targets
                                                     # it (pull requests into main)
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIREMENT_LEVEL = "Requirement"
SYSTEM_LEVEL = "System"
# Folder directly under a ``tests`` folder -> verification level of the tests it holds.
LEVEL_DIRS = {"requirements": REQUIREMENT_LEVEL, "system": SYSTEM_LEVEL}
LEVEL_FOLDER = {level: f"tests/{name}/" for name, level in LEVEL_DIRS.items()}

MILESTONE_STATUSES = ("Planned", "In progress", "Released")
# The release gate covers every milestone whose work has reached develop, and so main.
GATED_STATUSES = ("In progress", "Released")

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
DELETED_MARK = "_Deleted_"
MILESTONE_ROW = re.compile(r"^\|\s*(M\d+)\s*\|")
RISK_ROW = re.compile(r"^\|\s*((?:HAZ|RC)-\d{3})\s*\|")
OP_ROW = re.compile(r"^\|\s*(OP-\d{3})\s*\|")
SPEC_ID = re.compile(r"\b(?:SRS|HAZ|RC)-\d{3}\b")

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
    def python_code_roots(self) -> list[Path]:
        return [self.root / "dsp" / "sinus_dsp", self.root / "dsp" / "scripts"]

    @property
    def python_test_roots(self) -> list[Path]:
        return [self.root / "dsp" / "tests"]

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


@dataclass(frozen=True)
class Milestone:
    id: str
    title: str
    status: str


@dataclass(frozen=True)
class TestRef:
    name: str  # path::Class::test (pytest) or path::Suite.Name (GoogleTest)
    level: str  # verification level of the folder the test is in


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
    tag_errors: list[str]  # malformed or dangling C++ tags


# --- Sources ---------------------------------------------------------------------------------


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
        milestone = level = None
        for line in lines:
            if m := MILESTONE_LINE.match(line):
                milestone = m.group(1).strip()
            elif m := LEVEL_LINE.match(line):
                level = m.group(1)
        deleted = any(DELETED_MARK in line for line in lines)
        requirements[req_id] = Requirement(req_id, title, milestone, level, deleted)
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
    """Requirement -> ``path:line`` of every citation in production code."""
    files = [p for r in layout.python_code_roots for p in iter_sources(r, (".py",))]
    files += [
        p
        for r in layout.cpp_roots
        for p in iter_sources(r, CPP_SUFFIXES)
        if not is_test_path(p, layout)
    ]
    refs: dict[str, set[str]] = defaultdict(set)
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for req in REQ_ID.findall(line):
                refs[req].add(f"`{layout.rel(path)}:{lineno}`")
    return refs


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


def _pytestmark_ids(body: list[ast.stmt]) -> list[str]:
    """IDs from ``pytestmark = ...`` assignments at module or class level."""
    ids: list[str] = []
    for stmt in body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            ids.extend(_mark_ids(stmt.value))
    return ids


def scan_python_tests(layout: Layout) -> tuple[dict[str, list[TestRef]], list[str]]:
    """Requirement -> verifying tests, and requirement marks outside the verification folders."""
    refs: dict[str, list[TestRef]] = defaultdict(list)
    misplaced: list[str] = []

    def visit(body: list[ast.stmt], prefix: str, inherited: list[str], level: str) -> None:
        inherited = inherited + _pytestmark_ids(body)
        for node in body:
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                ids = inherited + [i for d in node.decorator_list for i in _mark_ids(d)]
                name = f"{prefix}::{node.name}"
                if isinstance(node, ast.ClassDef):
                    visit(node.body, name, ids, level)
                elif node.name.startswith("test"):
                    for req in dict.fromkeys(ids):
                        refs[req].append(TestRef(name, level))

    for root in layout.python_test_roots:
        for path in iter_sources(root, (".py",)):
            # pytest's default discovery patterns
            if not (path.name.startswith("test_") or path.name.endswith("_test.py")):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            level = folder_level(path, layout)
            # A requirement mark outside the verification folders is rejected, however it is
            # applied (decorator, pytestmark, pytest.param(marks=...)), and is not counted.
            if level is None:
                misplaced += [
                    f"{layout.rel(path)}:{n.lineno}"
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and _is_requirement_mark(n)
                ]
                continue
            visit(tree.body, layout.rel(path), [], level)
    return refs, misplaced


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
                    for req in dict.fromkeys(pending):
                        refs[req].append(TestRef(name, level))
                pending = []
            if pending:
                errors.append(f"{where}:{pending_at}: tag not directly followed by {expected}")
    return refs, misplaced, errors


# --- Matrix and checks -----------------------------------------------------------------------


def build(layout: Layout) -> Matrix:
    requirements, req_errors = parse_requirements(layout)
    milestones, ms_errors = parse_milestones(layout)
    py_tests, py_misplaced = scan_python_tests(layout)
    cpp_tests, cpp_misplaced, tag_errors = scan_cpp_tests(layout)
    tests: dict[str, list[TestRef]] = defaultdict(list)
    for source in (py_tests, cpp_tests):
        for req, refs in source.items():
            tests[req] += refs
    return Matrix(
        requirements=requirements,
        milestones=milestones,
        code=scan_code(layout),
        tests=dict(tests),
        risk_ids=parse_risk_ids(layout),
        open_points=parse_open_points(layout),
        register_errors=req_errors + ms_errors,
        misplaced_tags=sorted(py_misplaced + cpp_misplaced),
        tag_errors=sorted(tag_errors),
    )


def _milestone_key(milestone_id: str) -> int:
    return int(milestone_id[1:])


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
    """Requirements cited in production code without any verifying test."""
    return [
        f"{req}: cited in {', '.join(sorted(m.code[req]))}"
        for req in sorted(m.code)
        if req in m.requirements and not m.tests.get(req)
    ]


def dangling_refs(m: Matrix) -> list[str]:
    """Open-point references (open or closed) to SRS/HAZ/RC IDs that are not defined."""
    defined = set(m.requirements) | m.risk_ids
    return sorted(f"{op.id}→{ref}" for op in m.open_points for ref in op.refs if ref not in defined)


def duplicate_open_points(m: Matrix) -> list[str]:
    counts = Counter(op.id for op in m.open_points)
    return sorted(op_id for op_id, n in counts.items() if n > 1)


def gated_milestones(m: Matrix) -> list[str]:
    return sorted(
        (ms.id for ms in m.milestones.values() if ms.status in GATED_STATUSES),
        key=_milestone_key,
    )


def release_gate_failures(m: Matrix) -> list[str]:
    """Requirements of gated milestones without a verifying test or without a valid milestone,
    and open points that still target a gated milestone."""
    gated = set(gated_milestones(m))
    out: list[str] = []
    for req in sorted(m.requirements.values(), key=lambda r: r.id):
        if req.deleted:
            continue
        if req.milestone not in m.milestones:
            out.append(f"{req.id}: no valid milestone, so the gate cannot place it")
        elif req.milestone in gated and not m.tests.get(req.id):
            status = m.milestones[req.milestone].status
            out.append(f"{req.id} ({req.milestone}, {status}): no verifying test")
    for op in sorted(m.open_points, key=lambda o: o.id):
        if op.is_open and op.target in gated:
            out.append(f"{op.id}: open point still targets {op.target}; close or retarget it")
    return out


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
        "| Requirement | Title | Milestone | Verification level | Implemented in | Verified by "
        "| Open points |",
        "|---|---|---|---|---|---|---|",
    ]
    for req_id in sorted(m.requirements):
        req = m.requirements[req_id]
        code = "<br>".join(sorted(m.code.get(req_id, ()))) or "—"
        tests = "<br>".join(sorted(f"`{t.name}`" for t in m.tests.get(req_id, ()))) or "**none**"
        ops = ", ".join(sorted(open_by_req.get(req_id, ()))) or "—"
        lines.append(
            f"| {req_id} | {req.title} | {req.milestone or '—'} | {req.level or '—'} "
            f"| {code} | {tests} | {ops} |"
        )
    if not m.requirements:
        lines.append("| — | _No requirements defined yet in `srs.md`_ | — | — | — | — | — |")

    lines += [
        "",
        "## Milestones",
        "",
        "| Milestone | Title | Status | Requirements | With a verifying test | Release gate |",
        "|---|---|---|---|---|---|",
    ]
    gated = set(gated_milestones(m))
    for ms_id in sorted(m.milestones, key=_milestone_key):
        ms = m.milestones[ms_id]
        reqs = [r for r in m.requirements.values() if r.milestone == ms_id and not r.deleted]
        tested = sum(1 for r in reqs if m.tests.get(r.id))
        if ms_id not in gated:
            gate = "not applied"
        else:
            gate = "pass" if tested == len(reqs) else "**fail**"
        lines.append(f"| {ms_id} | {ms.title} | {ms.status} | {len(reqs)} | {tested} | {gate} |")

    untested = sorted(r for r in m.requirements if not m.tests.get(r))
    implemented = [line.split(":", 1)[0] for line in implemented_untested(m)]
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
        ("Malformed or dangling C++ requirement tags", m.tag_errors),
        ("Tests in the wrong folder for the requirement's verification level", level_mismatches(m)),
        ("Implemented requirements without a verifying test", implemented_untested(m)),
        ("Open points citing undefined IDs", dangling_refs(m)),
        ("Duplicate open point IDs", duplicate_open_points(m)),
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
            "verification level, a C++ tag is malformed, a requirement cited in production "
            "code has no verifying test, or open points cite undefined IDs or repeat an ID"
        ),
    )
    parser.add_argument(
        "--release-gate",
        action="store_true",
        help=(
            "do not write; fail unless every requirement of a milestone that is In progress or "
            "Released in docs/regulatory/milestones.md has a verifying test and no open point "
            "still targets such a milestone (run on pull requests into main)"
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

    gate = f"release gate on milestones {', '.join(gated_milestones(matrix)) or 'none'}"
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
