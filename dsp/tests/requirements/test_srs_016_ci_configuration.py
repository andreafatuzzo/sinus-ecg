"""Requirement tests of SRS-016: inspection of the build configuration (RC-004).

SRS-016 (v0.7): "On every push, the automated build shall obtain records 100, 105, 108, 119,
203 and 207 [...] (a cached copy is allowed), verify [...], and regenerate a subset report.
[...] The build shall fail if the verification fails or if the regenerated subset report
differs from the subset report stored in the repository." Its verification: "Inspection of
the CI configuration confirms that the check runs on every push."

The inspection reads `.github/workflows/ci.yml` and checks the design of architecture section
8.11: the workflow runs on every push (and pull request); its job `dsp` has a step that
restores the cached copy of the records (`actions/cache`, pinned to an exact version, path
`data/mitdb`, a fixed key), then a step that runs `uv run python scripts/subset_check.py
--write-regenerated "${{ runner.temp }}/qrs-ec57-subset-report.md"` with nothing that could
let a failure pass (no `--update`, no condition, no `continue-on-error`), then a step that
publishes the regenerated report as the artifact `subset-report` even when the check failed.

No YAML library is installed, so the module reads the workflow with a small reader for the
part of YAML that the file uses (block mappings and lists, plain and quoted scalars, folded
and literal block scalars, comments). A construct it does not know makes the test fail with
the line concerned, so a change of form is never taken for a pass.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import pytest

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
CHECK_COMMAND = (
    'uv run python scripts/subset_check.py --write-regenerated "${{ runner.temp }}/'
    'qrs-ec57-subset-report.md"'
)
_KEY = re.compile(r"^([A-Za-z0-9_.-]+):(?: (.*))?$")


class _YamlReader:
    """Reader for block-style YAML: mappings, lists, scalars and block scalars.

    Values are dictionaries, lists, strings or None (an empty value). Scalars stay strings
    (`true` is "true"). Flow collections, anchors, tags and multi-line plain scalars are not
    supported and raise `ValueError` naming the line.
    """

    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.position = 0

    @staticmethod
    def _indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _next(self) -> int | None:
        """Index of the next line from ``position`` that is neither empty nor a comment."""
        index = self.position
        while index < len(self.lines):
            stripped = self.lines[index].strip()
            if stripped and not stripped.startswith("#"):
                if "\t" in self.lines[index][: self._indent(self.lines[index]) + 1]:
                    raise ValueError(f"line {index + 1}: tab in indentation")
                return index
            index += 1
        return None

    def read(self) -> Any:
        first = self._next()
        if first is None:
            return None
        value = self._block(self._indent(self.lines[first]))
        rest = self._next()
        if rest is not None:
            raise ValueError(f"line {rest + 1}: not read")
        return value

    def _block(self, indent: int) -> Any:
        index = self._next()
        assert index is not None
        stripped = self.lines[index].strip()
        if stripped == "-" or stripped.startswith("- "):
            return self._list(indent)
        return self._mapping(indent)

    def _mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while (index := self._next()) is not None:
            line = self.lines[index]
            if self._indent(line) < indent:
                break
            if self._indent(line) > indent:
                raise ValueError(f"line {index + 1}: unexpected indentation")
            stripped = line.strip()
            if stripped == "-" or stripped.startswith("- "):
                break
            match = _KEY.match(stripped)
            if match is None:
                raise ValueError(f"line {index + 1}: not a key: {stripped!r}")
            key = match.group(1)
            if key in result:
                raise ValueError(f"line {index + 1}: key {key!r} given twice")
            self.position = index + 1
            result[key] = self._value(match.group(2) or "", indent, index)
        return result

    def _list(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while (index := self._next()) is not None:
            line = self.lines[index]
            stripped = line.strip()
            if self._indent(line) != indent or not (stripped == "-" or stripped.startswith("- ")):
                if self._indent(line) > indent:
                    raise ValueError(f"line {index + 1}: unexpected indentation")
                break
            rest = stripped[2:].strip() if stripped != "-" else ""
            if not rest:
                self.position = index + 1
                following = self._next()
                if following is None or self._indent(self.lines[following]) <= indent:
                    items.append(None)
                else:
                    items.append(self._block(self._indent(self.lines[following])))
            elif _KEY.match(rest):
                self.lines[index] = " " * (indent + 2) + rest
                self.position = index
                items.append(self._mapping(indent + 2))
            else:
                self.position = index + 1
                items.append(self._scalar(rest, index))
        return items

    def _value(self, text: str, indent: int, index: int) -> Any:
        text = text.strip()
        if not text or text.startswith("#"):
            following = self._next()
            if following is None or self._indent(self.lines[following]) <= indent:
                return None
            return self._block(self._indent(self.lines[following]))
        if text[0] in ">|":
            return self._block_scalar(text, indent, index)
        return self._scalar(text, index)

    def _block_scalar(self, header: str, indent: int, index: int) -> str:
        if not re.fullmatch(r"[>|][+-]?", header):
            raise ValueError(f"line {index + 1}: block scalar header {header!r} not supported")
        body: list[str] = []
        position = index + 1
        while position < len(self.lines):
            line = self.lines[position]
            if line.strip() and self._indent(line) <= indent:
                break
            body.append(line)
            position += 1
        while body and not body[-1].strip():
            body.pop()
        self.position = index + 1 + len(body)
        if not body:
            return ""
        margin = min(self._indent(line) for line in body if line.strip())
        lines = [line[margin:] for line in body]
        if header[0] == "|":
            text = "\n".join(lines)
        else:
            paragraphs: list[list[str]] = [[]]
            for line in lines:
                if line.strip():
                    paragraphs[-1].append(line)
                else:
                    paragraphs.append([])
            text = "\n".join(" ".join(p) for p in paragraphs)
        return text if header.endswith("-") else text + "\n"

    @staticmethod
    def _scalar(text: str, index: int) -> str:
        if text[0] in "[{&*!":
            raise ValueError(f"line {index + 1}: {text!r} is not supported by this reader")
        if text[0] in "'\"":
            quote = text[0]
            end = text.find(quote, 1)
            if end < 0 or text[end + 1 :].strip() and not text[end + 1 :].strip().startswith("#"):
                raise ValueError(f"line {index + 1}: quoted scalar not supported: {text!r}")
            return text[1:end]
        comment = re.search(r"\s#", text)
        return (text[: comment.start()] if comment else text).strip()


def _read_yaml(text: str) -> Any:
    return _YamlReader(text).read()


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    """The workflow of the build, `.github/workflows/ci.yml`, as read by the reader above."""
    data = _read_yaml(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def dsp_job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and "dsp" in jobs, "no job dsp"
    job = jobs["dsp"]
    assert isinstance(job, dict)
    return job


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list) and all(isinstance(s, dict) for s in steps)
    return steps


def _check_step(steps: list[dict[str, Any]]) -> int:
    found = [i for i, s in enumerate(steps) if "scripts/subset_check.py" in str(s.get("run", ""))]
    assert len(found) == 1, f"{len(found)} steps run scripts/subset_check.py"
    return found[0]


@pytest.mark.requirement("SRS-016")
def test_workflow_reader_reads_the_forms_used_by_the_workflow() -> None:
    """The reader of the inspection, on a text written by the test.

    Input: a YAML text with comments, a key without value, nested mappings, a list of
    mappings whose first key is on the dash line, plain and double-quoted scalars, a folded
    block scalar `>-` and a literal block scalar `|`, and a flow list.
    Expected: the documented values (None for the key without value, the folded scalar
    joined with spaces without a final line feed, the literal one with its line feeds); the
    flow list raises `ValueError` naming its line.
    """
    text = (
        "# comment\n"
        "on:\n"
        "  push:\n"
        "  pull_request:\n"
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - uses: x/y@v1.2.3\n"
        "        with:\n"
        "          path: data/mitdb\n"
        "      # comment between items\n"
        '      - name: "Quoted: value"\n'
        "        run: >-\n"
        "          one two\n"
        '          --flag "${{ a.b }}/c.md"\n'
        "      - run: |\n"
        "          first\n"
        "          second\n"
    )

    assert _read_yaml(text) == {
        "on": {"push": None, "pull_request": None},
        "jobs": {
            "a": {
                "steps": [
                    {"uses": "x/y@v1.2.3", "with": {"path": "data/mitdb"}},
                    {"name": "Quoted: value", "run": 'one two --flag "${{ a.b }}/c.md"'},
                    {"run": "first\nsecond\n"},
                ]
            }
        },
    }
    with pytest.raises(ValueError, match="line 2"):
        _read_yaml("on:\n  push: [main]\n")


@pytest.mark.requirement("SRS-016")
def test_workflow_runs_on_every_push(workflow: dict[str, Any], dsp_job: dict[str, Any]) -> None:
    """The check runs on every push.

    Input: `.github/workflows/ci.yml`.
    Expected: the workflow is triggered by `push` without any filter (no branches, tags or
    paths, so every push of every branch runs it), and by `pull_request`; no `concurrency`
    setting could cancel the run of a push (at the workflow or the job level); the job `dsp`
    has no condition (`if`) and is not allowed to fail (`continue-on-error`).
    """
    triggers = workflow.get("on")

    assert isinstance(triggers, dict), f"triggers in another form: {triggers!r}"
    assert "push" in triggers and triggers["push"] is None, f"push: {triggers.get('push')!r}"
    assert "pull_request" in triggers
    assert "concurrency" not in workflow and "concurrency" not in dsp_job
    assert "if" not in dsp_job
    assert dsp_job.get("continue-on-error") in (None, "false")


@pytest.mark.requirement("SRS-016")
def test_job_dsp_runs_the_subset_check_so_that_a_failure_fails_the_build(
    dsp_job: dict[str, Any],
) -> None:
    """The step of the job `dsp` that runs the check, and nothing that could hide a failure.

    Input: the job `dsp` of `.github/workflows/ci.yml`.
    Expected: the job runs on `ubuntu-latest` (the environment that is the authority for the
    stored report, architecture 8.11) in the folder `dsp`; exactly one step runs
    `scripts/subset_check.py`, with the command `uv run python scripts/subset_check.py
    --write-regenerated "${{ runner.temp }}/qrs-ec57-subset-report.md"` and nothing else: no
    `--update` (which would replace the stored report instead of comparing), no `--offline`
    (the records must be obtained when the cache is empty), no `--stored` or `--data-dir`
    (the stored report of the repository and the cached data folder are the defaults), no
    other shell command; the step has no condition, is not allowed to fail, and runs in the
    folder of the job.
    """
    steps = _steps(dsp_job)
    step = steps[_check_step(steps)]
    command = str(step["run"]).strip()
    words = shlex.split(command)

    assert dsp_job.get("runs-on") == "ubuntu-latest"
    assert dsp_job.get("defaults") == {"run": {"working-directory": "dsp"}}
    for option in ("--update", "--offline", "--stored", "--data-dir"):
        assert option not in words, f"the check runs with {option}"
    assert not re.search(r"\|\||&&|;|\|", command), f"other shell commands: {command!r}"
    assert command == CHECK_COMMAND
    assert "if" not in step
    assert step.get("continue-on-error") in (None, "false")
    assert step.get("working-directory") in (None, "dsp")
    assert "shell" not in step


@pytest.mark.requirement("SRS-016")
def test_cached_copy_of_the_records_is_restored_before_the_check(dsp_job: dict[str, Any]) -> None:
    """A cached copy of the records is allowed: the cache step comes before the check.

    Input: the job `dsp` of `.github/workflows/ci.yml`.
    Expected: exactly one step uses `actions/cache`, pinned to an exact version (`@vX.Y.Z`),
    before the check step, without a condition; it keeps the folder `data/mitdb` (relative
    to the repository root, where the check looks for the data by default) under a fixed key
    without expressions, so that the copy does not depend on the commit (it is verified at
    every run).
    """
    steps = _steps(dsp_job)
    check = _check_step(steps)
    caches = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/cache")]

    assert len(caches) == 1, f"{len(caches)} cache steps"
    step = steps[caches[0]]
    assert caches[0] < check
    assert re.fullmatch(r"actions/cache@v\d+\.\d+\.\d+", str(step["uses"])), step["uses"]
    assert "if" not in step
    options = step.get("with")
    assert isinstance(options, dict)
    assert options.get("path") == "data/mitdb"
    key = str(options.get("key", ""))
    assert key and "${{" not in key, f"cache key {key!r}"


@pytest.mark.requirement("SRS-016")
def test_regenerated_report_is_published_even_when_the_check_fails(
    dsp_job: dict[str, Any],
) -> None:
    """The report regenerated by the build is always available (architecture 8.11).

    Input: the job `dsp` of `.github/workflows/ci.yml`.
    Expected: after the check step, a step uses `actions/upload-artifact`, pinned to an exact
    version, with the condition `always()` (it runs when the check failed), the artifact name
    `subset-report` and the path given to `--write-regenerated` by the check step.
    """
    steps = _steps(dsp_job)
    check = _check_step(steps)
    words = shlex.split(str(steps[check]["run"]))
    regenerated = words[words.index("--write-regenerated") + 1]
    uploads = [
        i
        for i, s in enumerate(steps)
        if i > check
        and str(s.get("uses", "")).startswith("actions/upload-artifact")
        and isinstance(s.get("with"), dict)
        and s["with"].get("name") == "subset-report"
    ]

    assert len(uploads) == 1, f"{len(uploads)} uploads of subset-report after the check"
    step = steps[uploads[0]]
    assert re.fullmatch(r"actions/upload-artifact@v\d+\.\d+\.\d+", str(step["uses"]))
    assert step.get("if") == "always()"
    assert step["with"].get("path") == regenerated
    assert regenerated == "${{ runner.temp }}/qrs-ec57-subset-report.md"


@pytest.mark.requirement("SRS-016")
def test_check_runs_in_the_locked_environment_after_the_other_checks(
    dsp_job: dict[str, Any],
) -> None:
    """The check runs on the checked-out repository, in the environment of `uv.lock`.

    Input: the job `dsp` of `.github/workflows/ci.yml`.
    Expected: the first step checks out the repository (`actions/checkout`); a step runs
    `uv sync --locked` before the check (the runtime versions that the report states come
    from the lock file); the traceability check runs before the subset check (architecture
    8.11).
    """
    steps = _steps(dsp_job)
    check = _check_step(steps)
    runs = [str(s.get("run", "")).strip() for s in steps]

    assert str(steps[0].get("uses", "")).startswith("actions/checkout@")
    assert "uv sync --locked" in runs[:check]
    assert any("scripts/traceability.py --check" in run for run in runs[:check])
