"""Generate the SRS -> code -> tests traceability matrix (IEC 62304 §5.1.1).

Sources of truth:
  - Requirements: headings of the form ``### SRS-001: Title`` in docs/regulatory/srs.md
  - Code:         any ``SRS-xxx`` mention in a comment/docstring under CODE_ROOTS
  - Tests:        ``@pytest.mark.requirement("SRS-xxx", ...)`` on test functions/classes
  - Open points:  ``| OP-xxx | ... | refs | ...`` rows in docs/regulatory/open-points.md;
                  refs may cite SRS-, HAZ- and RC- IDs (hazards and risk controls are
                  defined as table rows in docs/regulatory/risk-analysis.md)

Usage (from the repo root or anywhere):
  python dsp/scripts/traceability.py          # rewrite docs/regulatory/traceability.md
  python dsp/scripts/traceability.py --check  # exit 1 if the file is stale, IDs are unknown,
                                              # or open points cite undefined IDs
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRS_FILE = REPO_ROOT / "docs" / "regulatory" / "srs.md"
RISK_FILE = REPO_ROOT / "docs" / "regulatory" / "risk-analysis.md"
OPEN_POINTS_FILE = REPO_ROOT / "docs" / "regulatory" / "open-points.md"
OUTPUT_FILE = REPO_ROOT / "docs" / "regulatory" / "traceability.md"
CODE_ROOTS: list[tuple[Path, tuple[str, ...]]] = [
    (REPO_ROOT / "dsp" / "sinus_dsp", ("*.py",)),
    (REPO_ROOT / "firmware", ("*.c", "*.h")),
]
TEST_ROOTS = [REPO_ROOT / "dsp" / "tests"]
# Only QA (requirements/) and test-engineer (system/) tests may claim to verify a requirement;
# developer unit tests (unit/) must not, so that no one verifies their own code functionally.
VERIFICATION_DIRS = [
    REPO_ROOT / "dsp" / "tests" / "requirements",
    REPO_ROOT / "dsp" / "tests" / "system",
]

REQ_ID = re.compile(r"\bSRS-\d{3}\b")
REQ_HEADING = re.compile(r"^#{2,4}\s+(SRS-\d{3})\b[\s:—-]*(.*)$")
RISK_ROW = re.compile(r"^\|\s*((?:HAZ|RC)-\d{3})\s*\|")
OP_ROW = re.compile(r"^\|\s*(OP-\d{3})\s*\|")
SPEC_ID = re.compile(r"\b(?:SRS|HAZ|RC)-\d{3}\b")


@dataclass
class OpenPoint:
    id: str
    is_open: bool
    refs: list[str]


@dataclass
class Matrix:
    titles: dict[str, str]
    code: dict[str, set[str]]
    tests: dict[str, set[str]]
    risk_ids: set[str]
    open_points: list[OpenPoint]
    misplaced_tests: list[str]


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def parse_requirements() -> dict[str, str]:
    titles: dict[str, str] = {}
    if not SRS_FILE.exists():
        return titles
    for line in SRS_FILE.read_text(encoding="utf-8").splitlines():
        m = REQ_HEADING.match(line.strip())
        if m:
            titles[m.group(1)] = m.group(2).strip()
    return titles


def parse_risk_ids() -> set[str]:
    if not RISK_FILE.exists():
        return set()
    lines = RISK_FILE.read_text(encoding="utf-8").splitlines()
    return {m.group(1) for line in lines if (m := RISK_ROW.match(line.strip()))}


def parse_open_points() -> list[OpenPoint]:
    """Rows under the "## Open" heading are open; rows under any other heading are not."""
    points: list[OpenPoint] = []
    if not OPEN_POINTS_FILE.exists():
        return points
    section = ""
    for line in OPEN_POINTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("## "):
            section = line[3:].strip().lower()
        elif m := OP_ROW.match(line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            refs = SPEC_ID.findall(cells[2]) if len(cells) > 2 else []
            points.append(OpenPoint(id=m.group(1), is_open=section == "open", refs=refs))
    return points


def scan_code() -> dict[str, set[str]]:
    refs: dict[str, set[str]] = defaultdict(set)
    for root, patterns in CODE_ROOTS:
        if not root.exists():
            continue
        for pattern in patterns:
            for path in sorted(root.rglob(pattern)):
                text = path.read_text(encoding="utf-8")
                for lineno, line in enumerate(text.splitlines(), start=1):
                    for req in REQ_ID.findall(line):
                        refs[req].add(f"`{rel(path)}:{lineno}`")
    return refs


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


def scan_tests() -> tuple[dict[str, set[str]], list[str]]:
    """Return requirement -> verifying tests, and requirement marks outside VERIFICATION_DIRS."""
    refs: dict[str, set[str]] = defaultdict(set)
    misplaced: list[str] = []

    def visit(body: list[ast.stmt], prefix: str, inherited: list[str]) -> None:
        inherited = inherited + _pytestmark_ids(body)
        for node in body:
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                ids = inherited + [i for d in node.decorator_list for i in _mark_ids(d)]
                name = f"{prefix}::{node.name}"
                if isinstance(node, ast.ClassDef):
                    visit(node.body, name, ids)
                elif node.name.startswith("test"):
                    for req in ids:
                        refs[req].add(f"`{name}`")

    for root in TEST_ROOTS:
        # pytest's default discovery patterns
        paths = sorted({*root.rglob("test_*.py"), *root.rglob("*_test.py")})
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            allowed = any(path.is_relative_to(d) for d in VERIFICATION_DIRS)
            # Any requirement mark outside the verification folders is rejected, however it
            # is applied (decorator, pytestmark, pytest.param(marks=...)), and is not counted.
            if not allowed:
                misplaced += [
                    f"{rel(path)}:{n.lineno}"
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and _is_requirement_mark(n)
                ]
                continue
            visit(tree.body, rel(path), [])
    return refs, sorted(misplaced)


def build() -> Matrix:
    tests, misplaced = scan_tests()
    return Matrix(
        titles=parse_requirements(),
        code=scan_code(),
        tests=tests,
        risk_ids=parse_risk_ids(),
        open_points=parse_open_points(),
        misplaced_tests=misplaced,
    )


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
        "| Requirement | Title | Implemented in | Verified by | Open points |",
        "|---|---|---|---|---|",
    ]
    for req in sorted(m.titles):
        code = "<br>".join(sorted(m.code.get(req, ()))) or "—"
        tests = "<br>".join(sorted(m.tests.get(req, ()))) or "**none**"
        ops = ", ".join(sorted(open_by_req.get(req, ()))) or "—"
        lines.append(f"| {req} | {m.titles[req]} | {code} | {tests} | {ops} |")
    if not m.titles:
        lines.append("| — | _No requirements defined yet in `srs.md`_ | — | — | — |")

    untested = sorted(r for r in m.titles if not m.tests.get(r))
    unknown = unknown_ids(m)
    dangling = dangling_refs(m)
    open_count = sum(op.is_open for op in m.open_points)
    lines += ["", "## Gaps", ""]
    lines.append(f"- Requirements without tests: {', '.join(untested) or 'none'}")
    lines.append(f"- Unknown IDs referenced in code/tests: {', '.join(unknown) or 'none'}")
    lines.append(f"- Open points citing undefined IDs: {', '.join(dangling) or 'none'}")
    lines.append(f"- Open points still open: {open_count} (see `open-points.md`)")
    return "\n".join(lines) + "\n"


def unknown_ids(m: Matrix) -> list[str]:
    return sorted((set(m.code) | set(m.tests)) - set(m.titles))


def dangling_refs(m: Matrix) -> list[str]:
    """Open-point references (open or closed) to SRS/HAZ/RC IDs that are not defined."""
    defined = set(m.titles) | m.risk_ids
    return sorted(f"{op.id}→{ref}" for op in m.open_points for ref in op.refs if ref not in defined)


def duplicate_open_points(m: Matrix) -> list[str]:
    counts = Counter(op.id for op in m.open_points)
    return sorted(op_id for op_id, n in counts.items() if n > 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "do not write; fail if the committed matrix is stale, code/tests cite unknown IDs, "
            "open points cite undefined IDs or repeat an ID, or requirement marks appear "
            "outside tests/requirements and tests/system"
        ),
    )
    args = parser.parse_args()

    matrix = build()
    content = render(matrix)

    if args.check:
        ok = True
        current = OUTPUT_FILE.read_text(encoding="utf-8") if OUTPUT_FILE.exists() else ""
        if current != content:
            print(f"{rel(OUTPUT_FILE)} is stale: run python dsp/scripts/traceability.py")
            ok = False
        if unknown := unknown_ids(matrix):
            print(f"Unknown requirement IDs referenced: {', '.join(unknown)}")
            ok = False
        if dangling := dangling_refs(matrix):
            print(f"Open points cite undefined IDs: {', '.join(dangling)}")
            ok = False
        if matrix.misplaced_tests:
            print(
                "Requirement markers outside tests/requirements or tests/system: "
                + ", ".join(matrix.misplaced_tests)
            )
            ok = False
        if duplicates := duplicate_open_points(matrix):
            print(f"Duplicate open point IDs: {', '.join(duplicates)}")
            ok = False
        return 0 if ok else 1

    OUTPUT_FILE.write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {rel(OUTPUT_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
