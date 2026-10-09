"""Unit tests of the per-item rules of scripts/traceability.py (docs/adr/0006, architecture-m2.md
§13.12), on fixture trees: the software items of a requirement, the item of a file, the rules
per item, disabled tests, the ``VERSION`` file of a C++ item and the matrix.

Each tree starts with the files that every rule accepts (milestone M1 in progress, the version
0.1.0.dev0) and one change per test shows what the rule reports. The requirement IDs and tags
are text in this file, so the real check reads none of them.
"""

import importlib.util
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "traceability.py"

FIELDS = "Requirement or milestone register errors"
DISABLED = "Disabled requirement tests"
ITEM_TESTS = "Tests in the folder of an item that the requirement does not name"
UNTESTED = "Implemented requirements without a verifying test"
ITEM_CITES = "Requirements cited by an item that they do not name"
VERSION = "Software version"
DEV = "0.1.0.dev0"
PY_TEST = "dsp/tests/requirements/test_a.py"
LIB_PY_TEST = "libs/x/tests/requirements/test_x.py"
CPP_TEST = "libs/x/tests/requirements/qrs_test.cpp"


@pytest.fixture(scope="module")
def tool() -> Iterator[ModuleType]:
    name = "traceability_items_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # the dataclasses of the script look their module up
    spec.loader.exec_module(module)
    yield module
    del sys.modules[name]


def req(req_id: str, item: str | None, *, level: str = "Requirement", extra: str = "") -> str:
    """An srs.md entry of milestone M1; ``item`` None writes no ``Software item`` line."""
    lines = [f"### {req_id}: Title of {req_id}", "", "The software shall work.", ""]
    lines += ["**Milestone:** M1", f"**Verification level:** {level}"]
    if item is not None:
        lines.append(f"**Software item:** {item}")
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


def marked(name: str, *ids: str, decorators: str = "") -> str:
    args = ", ".join(f'"{i}"' for i in ids)
    return f"@pytest.mark.requirement({args})\n{decorators}def {name}() -> None:\n    pass\n"


def py_file(*tests: str, header: str = "") -> str:
    return "import pytest\n\n" + header + "\n\n" + "\n\n".join(tests)


class Repo:
    """A fixture repository under ``root``; every rule of ``--check`` passes until a test
    changes it."""

    def __init__(self, root: Path, tool: ModuleType) -> None:
        self.root = root
        self.tool = tool
        self.layout: Any = tool.Layout(root)
        self.write("dsp/pyproject.toml", f'[project]\nname = "sinus-dsp"\nversion = "{DEV}"\n')
        self.write("dsp/sinus_dsp/__init__.py", f'"""Package."""\n\n__version__ = "{DEV}"\n')
        self.register("In progress")

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def register(self, status: str) -> None:
        rows = f"| M1 | Title of M1 | {status} |\n"
        head = "# Milestones\n\n| Milestone | Title | Status |\n|---|---|---|\n"
        self.write("docs/regulatory/milestones.md", head + rows)

    def srs(self, *entries: str) -> None:
        self.write("docs/regulatory/srs.md", "# SRS\n\n" + "\n".join(entries))

    def matrix(self) -> Any:
        return self.tool.build(self.layout)

    def render(self) -> str:
        text: str = self.tool.render(self.matrix())
        return text

    def check(self) -> dict[str, list[str]]:
        """The failing rules of ``--check`` with their items, the matrix written first."""
        self.write("docs/regulatory/traceability.md", self.render())
        matrix = self.matrix()
        failures = self.tool.check_failures(matrix, self.layout, self.tool.render(matrix))
        return {rule: items for rule, items in failures if items}

    def gate(self) -> list[str]:
        items: list[str] = self.tool.release_gate_failures(self.matrix())
        return items

    def requirement_gate(self) -> list[str]:
        """The items of the release gate about a requirement."""
        return [item for item in self.gate() if item.startswith("SRS-")]


@pytest.fixture
def repo(tmp_path: Path, tool: ModuleType) -> Repo:
    return Repo(tmp_path / "repo", tool)


# --- the software items of a requirement ----------------------------------------------------


@pytest.mark.parametrize(
    ("line", "items"),
    [
        ("dsp", ("dsp",)),
        ("dsp (scripts)", ("dsp",)),
        ("dsp (scripts); CI workflow", ("dsp",)),
        ("dsp (scripts); libs/sinus-dsp; CI workflow", ("dsp", "libs/sinus-dsp")),
        ("dsp and libs/sinus-dsp", ("dsp", "libs/sinus-dsp")),
        ("libs/sinus-dsp", ("libs/sinus-dsp",)),
        ("libs/sinus-dsp (build for the ESP32-S3); CI workflow", ("libs/sinus-dsp",)),
        ("libs/sinus-dsp; dsp (scripts)", ("libs/sinus-dsp", "dsp")),
        ("desktop; firmware and backend", ("desktop", "firmware", "backend")),
        ("dsp (scripts and tools) and dsp", ("dsp",)),
    ],
)
def test_software_item_lines_that_parse(
    tool: ModuleType, line: str, items: tuple[str, ...]
) -> None:
    assert tool.parse_software_items(" " + line) == (items, ())


@pytest.mark.parametrize(
    ("line", "errors"),
    [
        ("widget", ("unknown software item 'widget'",)),
        ("dsp; libs/Bad_Name", ("unknown software item 'libs/Bad_Name'",)),
        ("libs/", ("unknown software item 'libs/'",)),
        ("dsp and ci workflow", ("unknown software item 'ci workflow'",)),
        ("CI workflow", ("no software item other than CI workflow",)),
        ("CI workflow (scripts)", ("no software item other than CI workflow",)),
        ("", ("no software item other than CI workflow",)),
    ],
)
def test_software_item_lines_that_do_not_parse(
    tool: ModuleType, line: str, errors: tuple[str, ...]
) -> None:
    assert tool.parse_software_items(line)[1] == errors


def test_the_items_of_a_requirement_are_read_from_srs(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp (scripts); libs/x; CI workflow"))
    requirement = repo.matrix().requirements["SRS-001"]
    assert (requirement.items, requirement.item_errors) == (("dsp", "libs/x"), ())


@pytest.mark.parametrize(
    ("item", "error"),
    [
        (None, "no '**Software item:**' line"),
        ("widget", "unknown software item 'widget'"),
        ("CI workflow", "no software item other than CI workflow"),
    ],
)
def test_a_wrong_item_line_fails_the_check(repo: Repo, item: str | None, error: str) -> None:
    repo.srs(req("SRS-001", item))
    assert repo.check()[FIELDS] == [f"SRS-001: {error}"]


def test_a_deleted_requirement_needs_no_item_line(repo: Repo) -> None:
    repo.srs("### SRS-001: _Deleted_\n")
    assert repo.check() == {}


def test_item_of_a_file(tool: ModuleType) -> None:
    for rel, item in [
        ("dsp/sinus_dsp/a.py", "dsp"),
        ("libs/x/src/a.cpp", "libs/x"),
        ("libs/sinus-dsp/tests/unit/a_test.cpp", "libs/sinus-dsp"),
        ("desktop/src/a.cc", "desktop"),
        ("firmware/main/a.c", "firmware"),
        ("backend/app/a.py", "backend"),
        ("docs/design.md", ""),
        ("libs/stray.txt", ""),
        ("README.md", ""),
    ]:
        assert tool.item_of(rel) == item, rel


# --- the layout ------------------------------------------------------------------------------


def test_layout_without_cpp_items(tool: ModuleType, tmp_path: Path) -> None:
    layout = tool.Layout(tmp_path)
    assert layout.cpp_item_dirs == []
    assert layout.python_test_roots == [tmp_path / "dsp" / "tests"]
    assert layout.version_files == []


def test_layout_with_cpp_items(repo: Repo, tmp_path: Path) -> None:
    root = repo.root
    for rel in ["libs/x/tests/a.txt", "libs/y/src/a.txt", "firmware/main/a.txt", "libs/z.txt"]:
        repo.write(rel, "")
    repo.write("libs/x/CMakeLists.txt", "")
    repo.write("firmware/CMakeLists.txt", "")
    layout = repo.layout
    assert layout.cpp_item_dirs == [root / "libs/x", root / "libs/y", root / "firmware"]
    assert layout.python_code_roots[2:] == layout.cpp_item_dirs
    assert layout.python_test_roots == [root / "dsp/tests", root / "libs/x/tests"]
    assert layout.version_files == [root / "libs/x/VERSION", root / "firmware/VERSION"]


def test_build_output_folders_of_an_item_are_not_read(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp and libs/x"))
    repo.write("libs/x/build/gen.py", "# SRS-001\n")
    repo.write("libs/x/build-asan/gen.py", "# SRS-001\n")
    assert repo.matrix().code == {}


# --- rule 1: implemented => tested, per item -------------------------------------------------


def test_citation_in_an_item_needs_a_test_in_that_item(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp and libs/x"))
    repo.write("libs/x/src/a.cpp", "// SRS-001\n")
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001")))
    assert repo.check() == {
        UNTESTED: [
            "SRS-001: implemented in libs/x (cited in `libs/x/src/a.cpp:1`) "
            "without a verifying test in libs/x"
        ]
    }


def test_a_python_test_under_the_tests_folder_of_an_item_counts_for_it(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp and libs/x"))
    repo.write("libs/x/src/a.cpp", "// SRS-001\n")
    repo.write("dsp/sinus_dsp/a.py", "# SRS-001\n")
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001")))
    repo.write(LIB_PY_TEST, py_file(marked("test_x", "SRS-001")))
    assert repo.check() == {}
    names = sorted(t.name for t in repo.matrix().tests["SRS-001"])
    assert names == [f"{PY_TEST}::test_a", f"{LIB_PY_TEST}::test_x"]
    assert [t.item for t in repo.matrix().tests["SRS-001"]] == ["dsp", "libs/x"]
    assert repo.requirement_gate() == []


def test_a_cpp_test_counts_for_its_item(repo: Repo) -> None:
    repo.srs(req("SRS-001", "libs/x"))
    repo.write("libs/x/src/a.cpp", "// SRS-001\n")
    repo.write(CPP_TEST, "// Verifies: SRS-001\nTEST(Qrs, Detects) {\n}\n")
    assert repo.check() == {}


def test_each_citing_item_is_reported_on_its_own(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp; libs/x"))
    repo.write("dsp/sinus_dsp/a.py", "# SRS-001\n")
    repo.write("libs/x/src/a.cpp", "// SRS-001\n")
    repo.write("libs/x/src/b.cpp", "// SRS-001\n")
    assert repo.check()[UNTESTED] == [
        "SRS-001: implemented in dsp (cited in `dsp/sinus_dsp/a.py:1`) "
        "without a verifying test in dsp",
        "SRS-001: implemented in libs/x (cited in `libs/x/src/a.cpp:1`, `libs/x/src/b.cpp:1`) "
        "without a verifying test in libs/x",
    ]


def test_python_code_of_an_item_is_production_code_but_not_its_tools_or_tests(
    repo: Repo,
) -> None:
    repo.srs(req("SRS-001", "libs/x"))
    repo.write("libs/x/verification/emulator_log.py", "# SRS-001\n")
    repo.write("libs/x/tools/pin.py", "# SRS-001\n")
    repo.write("libs/x/tools/sub/pin.py", "# SRS-001\n")
    repo.write("libs/x/tests/unit/helper.py", "# SRS-001\n")
    assert repo.matrix().code == {"SRS-001": {"`libs/x/verification/emulator_log.py:1`"}}


# --- rule 2: cited by an item that the requirement does not name ------------------------------


def test_a_citation_in_an_unnamed_item_fails_the_check(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp; firmware"))
    repo.write("dsp/sinus_dsp/a.py", "# SRS-001\n")
    repo.write("libs/x/src/a.cpp", "// SRS-001\n")
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001")))
    failures = repo.check()
    assert failures[ITEM_CITES] == [
        "SRS-001: cited in libs/x/src/a.cpp:1, but its software items are dsp, firmware"
    ]
    assert list(failures) == [UNTESTED, ITEM_CITES]  # also no test in libs/x


def test_a_citation_in_a_named_item_is_accepted(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp and libs/x"))
    repo.write("dsp/sinus_dsp/a.py", "# SRS-001\n")
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001")))
    assert repo.check() == {}


# --- rule 3: tests in an item that the requirement does not name ------------------------------


def test_a_test_in_an_unnamed_item_does_not_count_and_fails_the_check(repo: Repo) -> None:
    repo.srs(req("SRS-001", "libs/x", level="System"))
    repo.write("dsp/tests/system/test_a.py", py_file(marked("test_a", "SRS-001")))
    failures = repo.check()
    assert failures == {
        ITEM_TESTS: ["SRS-001 names libs/x, but is tagged in dsp/tests/system/test_a.py::test_a"]
    }
    assert repo.matrix().tests["SRS-001"][0].item == "dsp"
    assert repo.tool.verifying(repo.matrix(), "SRS-001") == []
    assert repo.requirement_gate() == ["SRS-001 (M1, In progress): no verifying test in libs/x"]


def test_a_test_in_a_named_item_is_not_reported(repo: Repo) -> None:
    repo.srs(req("SRS-001", "libs/x", level="System"))
    repo.write("libs/x/tests/system/test_a.py", py_file(marked("test_a", "SRS-001")))
    assert repo.check() == {}
    assert repo.requirement_gate() == []


# --- rule 4: the release gate per item --------------------------------------------------------


def test_gate_names_the_item_without_a_test(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp and libs/x"))
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001")))
    assert repo.requirement_gate() == ["SRS-001 (M1, In progress): no verifying test in libs/x"]
    repo.write(LIB_PY_TEST, py_file(marked("test_x", "SRS-001")))
    assert repo.requirement_gate() == []


def test_gate_lists_every_item_without_a_test(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp and libs/x"), req("SRS-002", "dsp"))
    assert repo.requirement_gate() == [
        "SRS-001 (M1, In progress): no verifying test in dsp",
        "SRS-001 (M1, In progress): no verifying test in libs/x",
        "SRS-002 (M1, In progress): no verifying test in dsp",
    ]


def test_a_test_in_the_wrong_folder_of_its_item_does_not_count(repo: Repo) -> None:
    repo.srs(req("SRS-001", "libs/x"))
    repo.write("libs/x/tests/system/test_x.py", py_file(marked("test_x", "SRS-001")))
    assert repo.requirement_gate() == ["SRS-001 (M1, In progress): no verifying test in libs/x"]


# --- rule 5: disabled requirement tests -------------------------------------------------------

SKIP = "@pytest.mark.skip\n"
SKIP_CALL = '@pytest.mark.skip(reason="not now")\n'
XFAIL_CALL = "@pytest.mark.xfail(strict=True)\n"
SKIPIF = '@pytest.mark.skipif(sys.platform == "win32", reason="posix only")\n'


@pytest.mark.parametrize(
    ("text", "how"),
    [
        (py_file(marked("test_a", "SRS-001", decorators=SKIP)), "decorator @pytest.mark.skip"),
        (py_file(marked("test_a", "SRS-001", decorators=SKIP_CALL)), "decorator @pytest.mark.skip"),
        (
            py_file(marked("test_a", "SRS-001", decorators=XFAIL_CALL)),
            "decorator @pytest.mark.xfail",
        ),
        (
            py_file(marked("test_a", "SRS-001"), header="pytestmark = pytest.mark.xfail\n"),
            "pytestmark pytest.mark.xfail",
        ),
        (
            py_file(
                "def test_a() -> None:\n    pass\n",
                header='pytestmark = [pytest.mark.requirement("SRS-001"), pytest.mark.skip()]\n',
            ),
            "pytestmark pytest.mark.skip",
        ),
        (
            py_file(
                "class TestA:\n"
                "    pytestmark = pytest.mark.skip\n\n"
                '    @pytest.mark.requirement("SRS-001")\n'
                "    def test_a(self) -> None:\n        pass\n"
            ),
            "pytestmark pytest.mark.skip",
        ),
        (
            py_file(
                "@pytest.mark.skip\nclass TestA:\n"
                '    @pytest.mark.requirement("SRS-001")\n'
                "    def test_a(self) -> None:\n        pass\n"
            ),
            "decorator @pytest.mark.skip",
        ),
    ],
)
def test_a_skipped_python_requirement_test_is_disabled(repo: Repo, text: str, how: str) -> None:
    repo.srs(req("SRS-001", "dsp"))
    repo.write(PY_TEST, text)
    name = "TestA::test_a" if "TestA" in text else "test_a"
    assert repo.check() == {DISABLED: [f"{PY_TEST}::{name}: requirement test disabled ({how})"]}
    assert "SRS-001" not in repo.matrix().tests  # it does not count
    assert repo.requirement_gate() == ["SRS-001 (M1, In progress): no verifying test in dsp"]


def test_skipif_and_calls_in_the_body_are_allowed(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp"))
    repo.write(
        PY_TEST,
        "import sys\n\nimport pytest\n\n\n"
        + marked("test_a", "SRS-001", decorators=SKIPIF)
        + "\n\n"
        + '@pytest.mark.requirement("SRS-001")\n'
        'def test_b() -> None:\n    pytest.skip("needs the data")\n',
    )
    assert repo.check() == {}
    assert len(repo.matrix().tests["SRS-001"]) == 2


def test_a_skipped_test_without_a_requirement_tag_is_not_reported(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp"))
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001")))
    repo.write(
        "dsp/tests/unit/test_b.py", py_file("@pytest.mark.skip\ndef test_b() -> None:\n    pass")
    )
    assert repo.check() == {}


def test_a_test_with_several_tags_is_reported_once(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp"), req("SRS-002", "dsp"))
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001", "SRS-002", decorators=SKIP)))
    assert repo.check()[DISABLED] == [
        f"{PY_TEST}::test_a: requirement test disabled (decorator @pytest.mark.skip)"
    ]


@pytest.mark.parametrize(
    ("test", "name", "how"),
    [
        ("TEST(DISABLED_Qrs, Detects) {\n}\n", "DISABLED_Qrs.Detects", "suite DISABLED_Qrs"),
        ("TEST(Qrs, DISABLED_Detects) {\n}\n", "Qrs.DISABLED_Detects", "test DISABLED_Detects"),
        (
            "TEST_F(DISABLED_Qrs, DISABLED_Detects) {\n}\n",
            "DISABLED_Qrs.DISABLED_Detects",
            "suite DISABLED_Qrs, test DISABLED_Detects",
        ),
    ],
)
def test_a_disabled_cpp_requirement_test(repo: Repo, test: str, name: str, how: str) -> None:
    repo.srs(req("SRS-001", "libs/x"))
    repo.write(CPP_TEST, f"// Verifies: SRS-001\n{test}")
    assert repo.check() == {DISABLED: [f"{CPP_TEST}::{name}: requirement test disabled ({how})"]}
    assert "SRS-001" not in repo.matrix().tests
    assert repo.requirement_gate() == ["SRS-001 (M1, In progress): no verifying test in libs/x"]


def test_a_cpp_name_that_merely_contains_disabled_is_enabled(repo: Repo) -> None:
    repo.srs(req("SRS-001", "libs/x"))
    repo.write(CPP_TEST, "// Verifies: SRS-001\nTEST(Qrs, NotDISABLED_Detects) {\n}\n")
    assert repo.check() == {}


# --- rule 6: the VERSION file of a C++ item ---------------------------------------------------


def test_an_item_without_cmakelists_needs_no_version_file(repo: Repo) -> None:
    repo.write("libs/x/src/a.cpp", "// no requirement\n")
    assert repo.check() == {}


def test_version_file_equal_to_the_package_version(repo: Repo) -> None:
    repo.write("libs/x/CMakeLists.txt", "")
    repo.write("libs/x/VERSION", f"{DEV}\n")
    assert repo.check() == {}
    assert repo.matrix().versions["libs/x/VERSION"] == DEV


def test_version_file_without_a_final_newline(repo: Repo) -> None:
    repo.write("desktop/CMakeLists.txt", "")
    repo.write("desktop/VERSION", DEV)
    assert repo.check() == {}


def test_version_file_missing(repo: Repo) -> None:
    repo.write("libs/x/CMakeLists.txt", "")
    assert repo.check() == {VERSION: ["libs/x/VERSION not found"]}


@pytest.mark.parametrize("text", ["", "\n", f"{DEV}\n\n", f"{DEV}\n{DEV}\n", f"\n{DEV}\n"])
def test_version_file_not_one_line(repo: Repo, text: str) -> None:
    repo.write("firmware/CMakeLists.txt", "")
    repo.write("firmware/VERSION", text)
    assert repo.check() == {VERSION: ["firmware/VERSION: not one line"]}


def test_version_file_with_another_version(repo: Repo) -> None:
    repo.write("libs/x/CMakeLists.txt", "")
    repo.write("libs/x/VERSION", "0.1.1.dev0\n")
    assert repo.check()[VERSION] == [
        "libs/x/VERSION: version 0.1.1.dev0, expected 0.1.0.dev0 (M1 In progress)",
        "libs/x/VERSION: version 0.1.1.dev0, expected 0.1.0.dev0 (as in dsp/pyproject.toml)",
    ]


def test_gate_lists_a_development_version_of_a_version_file_once_per_version(repo: Repo) -> None:
    repo.write("libs/x/CMakeLists.txt", "")
    repo.write("libs/x/VERSION", f"{DEV}\n")
    assert repo.gate() == [
        f"dsp/pyproject.toml: version {DEV} is a development version, not a release"
    ]
    repo.write("libs/x/VERSION", "0.1.0.dev1\n")
    assert repo.gate() == [
        f"dsp/pyproject.toml: version {DEV} is a development version, not a release",
        "libs/x/VERSION: version 0.1.0.dev1 is a development version, not a release",
    ]


def test_gate_accepts_released_versions_in_every_file(repo: Repo) -> None:
    repo.register("Released")
    repo.write("dsp/pyproject.toml", '[project]\nname = "sinus-dsp"\nversion = "0.1.0"\n')
    repo.write("dsp/sinus_dsp/__init__.py", '__version__ = "0.1.0"\n')
    repo.write("libs/x/CMakeLists.txt", "")
    repo.write("libs/x/VERSION", "0.1.0\n")
    assert repo.gate() == []
    repo.write("libs/x/VERSION", f"{DEV}\n")
    assert repo.gate() == [f"libs/x/VERSION: version {DEV} is a development version, not a release"]


# --- the matrix --------------------------------------------------------------------------------


@pytest.fixture
def mixed(repo: Repo) -> Callable[[], list[str]]:
    """Three requirements: SRS-001 in dsp and libs/x with a test only in dsp, SRS-002 in libs/x
    with its test there, SRS-003 with no test. Returns the lines of the matrix."""
    repo.srs(
        req("SRS-001", "dsp and libs/x"),
        req("SRS-002", "libs/x; CI workflow", level="System"),
        req("SRS-003", "dsp (scripts); CI workflow"),
    )
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001")))
    repo.write("libs/x/tests/system/test_b.py", py_file(marked("test_b", "SRS-002")))
    return lambda: repo.render().splitlines()


def test_matrix_columns_and_cells(mixed: Callable[[], list[str]]) -> None:
    lines = mixed()
    assert (
        "| Requirement | Title | Software items | Milestone | Verification level "
        "| Implemented in | Verified by | Open points |"
    ) in lines
    assert "|---|---|---|---|---|---|---|---|" in lines
    assert (
        f"| SRS-001 | Title of SRS-001 | dsp, libs/x | M1 | Requirement | — "
        f"| `{PY_TEST}::test_a`<br>**none in libs/x** | — |"
    ) in lines
    assert (
        "| SRS-002 | Title of SRS-002 | libs/x | M1 | System | — "
        "| `libs/x/tests/system/test_b.py::test_b` | — |"
    ) in lines
    assert "| SRS-003 | Title of SRS-003 | dsp | M1 | Requirement | — | **none** | — |" in lines


def test_matrix_counts_requirements_verified_in_every_item(mixed: Callable[[], list[str]]) -> None:
    assert "| M1 | Title of M1 | In progress | 3 | 1 | **fail** |" in mixed()


def test_matrix_gaps_name_the_items_without_a_test(mixed: Callable[[], list[str]]) -> None:
    assert "- Requirements without tests: SRS-001 (libs/x), SRS-003" in mixed()


def test_matrix_gap_without_any_test_in_two_items(repo: Repo) -> None:
    repo.srs(req("SRS-001", "dsp and libs/x"))
    lines = repo.render().splitlines()
    assert "- Requirements without tests: SRS-001" in lines
    assert (
        "| SRS-001 | Title of SRS-001 | dsp, libs/x | M1 | Requirement | — "
        "| **none in dsp**<br>**none in libs/x** | — |"
    ) in lines


def test_matrix_shows_a_requirement_without_readable_items(repo: Repo) -> None:
    repo.srs(req("SRS-001", None))
    assert "| SRS-001 | Title of SRS-001 | — | M1 | Requirement | — | **none** | — |" in (
        repo.render().splitlines()
    )


def test_a_milestone_is_not_released_while_an_item_has_no_test(repo: Repo) -> None:
    repo.register("Released")
    repo.srs(req("SRS-001", "dsp and libs/x"))
    repo.write(PY_TEST, py_file(marked("test_a", "SRS-001")))
    assert "| M1 | Title of M1 | Released | 1 | 0 | **fail** |" in repo.render().splitlines()
    repo.write(LIB_PY_TEST, py_file(marked("test_x", "SRS-001")))
    assert "| M1 | Title of M1 | Released | 1 | 1 | pass |" in repo.render().splitlines()
