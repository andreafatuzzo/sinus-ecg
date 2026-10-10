"""Requirement tests of SRS-035: inspection of the build configuration (RC-012).

SRS-035 (`dsp` item and CI workflow): "On every push, the automated build shall export the golden
vectors of SRS-015 and SRS-033 from the commit under test [...] and run the check of SRS-034 on
all of them. The build shall fail if a file of the set is missing or fails the check." Its
verification: "Inspection of the CI configuration confirms that the export and the check run on
every push." (The check on a set with a file missing is tested in C++, SRS-034/035.)

The inspection reads `.github/workflows/ci.yml` with the small YAML reader of the SRS-016 test
(loaded from its file, no YAML library being installed): the job `dsp` exports the vectors and
hands them over as the artifact `golden-vectors`; the job `libs` (needs `dsp`) downloads it and runs
the equivalence executable in a step that can fail the job, then uploads the results also on
failure. No check on the form of version pins: the requirement does not ask for it.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
WORKFLOW = _HERE.parents[2] / ".github" / "workflows" / "ci.yml"


def _load_reader() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_srs_016_reader", _HERE / "test_srs_016_ci_configuration.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._read_yaml


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    """The workflow `.github/workflows/ci.yml` as read by the reader."""
    data = _load_reader()(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _job(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and name in jobs, f"no job {name}"
    job = jobs[name]
    assert isinstance(job, dict)
    return job


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list) and all(isinstance(s, dict) for s in steps)
    return steps


def _only(steps: list[dict[str, Any]], needle: str, field: str = "run") -> int:
    found = [i for i, s in enumerate(steps) if needle in str(s.get(field, ""))]
    assert len(found) == 1, f"{len(found)} steps with {needle!r} in {field}"
    return found[0]


def _plain(step: dict[str, Any]) -> None:
    """The step has no condition and cannot let a failure pass."""
    assert "if" not in step, f"condition: {step['if']!r}"
    assert step.get("continue-on-error") in (None, "false")


@pytest.mark.requirement("SRS-035")
def test_workflow_runs_on_every_push_and_both_jobs_always_run(workflow: dict[str, Any]) -> None:
    """The export and the check run on every push.

    Input: `.github/workflows/ci.yml`.
    Expected: `push` is a trigger without any filter (no branches, tags, paths); no
    `concurrency` setting at workflow or job level could cancel a run; the jobs `dsp` and
    `libs` have no condition and are not allowed to fail.
    """
    triggers = workflow.get("on")

    assert isinstance(triggers, dict), f"triggers in another form: {triggers!r}"
    assert "push" in triggers and triggers["push"] is None, f"push: {triggers.get('push')!r}"
    assert "concurrency" not in workflow
    for name in ("dsp", "libs"):
        job = _job(workflow, name)
        _plain(job)
        assert "concurrency" not in job


@pytest.mark.requirement("SRS-035")
def test_job_dsp_exports_the_golden_vectors_of_the_commit(workflow: dict[str, Any]) -> None:
    """The export runs in the same run, on the commit under test, after the records are verified.

    Input: the job `dsp`.
    Expected: exactly one step runs `scripts/export_golden.py` with `--output` set to a folder
    under `runner.temp`, no condition and no `continue-on-error`, after the checkout and after
    the subset check (which obtains and verifies the records, SRS-016); no `--offline`-like
    escape and no other shell command in the step.
    """
    steps = _steps(_job(workflow, "dsp"))
    export = _only(steps, "scripts/export_golden.py")
    subset = _only(steps, "scripts/subset_check.py")
    command = str(steps[export]["run"]).strip()
    words = shlex.split(command)

    assert str(steps[0].get("uses", "")).startswith("actions/checkout@")
    assert subset < export
    _plain(steps[export])
    assert words[:4] == ["uv", "run", "python", "scripts/export_golden.py"]
    assert words[words.index("--output") + 1].startswith("${{ runner.temp }}/")
    assert not re.search(r"\|\||&&|;|\|", command), f"other shell commands: {command!r}"
    assert "--offline" not in words


@pytest.mark.requirement("SRS-035")
def test_job_dsp_hands_the_whole_folder_over_as_artifact_golden_vectors(
    workflow: dict[str, Any],
) -> None:
    """The set (all files, with the notices) travels to the check as one artifact.

    Input: the job `dsp`.
    Expected: after the export step, a step without condition uses `actions/upload-artifact`
    with the name `golden-vectors`, the path equal to the `--output` folder of the export (the
    folder, not single files), and `if-no-files-found: error`, so that an empty export fails
    the build.
    """
    steps = _steps(_job(workflow, "dsp"))
    export = _only(steps, "scripts/export_golden.py")
    words = shlex.split(str(steps[export]["run"]))
    folder = words[words.index("--output") + 1]
    uploads = [
        i
        for i, s in enumerate(steps)
        if str(s.get("uses", "")).startswith("actions/upload-artifact")
        and isinstance(s.get("with"), dict)
        and s["with"].get("name") == "golden-vectors"
    ]

    assert len(uploads) == 1 and uploads[0] > export
    step = steps[uploads[0]]
    _plain(step)
    assert step["with"].get("path") == folder
    assert step["with"].get("if-no-files-found") == "error"


@pytest.mark.requirement("SRS-035")
def test_job_libs_waits_for_dsp_and_downloads_the_vectors_before_the_check(
    workflow: dict[str, Any],
) -> None:
    """The check runs on the vectors of this run, not on stored ones.

    Input: the job `libs`.
    Expected: `needs` is `dsp` (the job does not start, and the build fails, if the export
    failed); a step uses `actions/download-artifact` with the name `golden-vectors` into a
    folder, before the equivalence step; `SINUS_GOLDEN_DIR` is set at job level to that same
    folder, which the equivalence step reads (`--vectors`).
    """
    libs = _job(workflow, "libs")
    steps = _steps(libs)
    check = _only(steps, "sinus_dsp_equivalence")
    downloads = [
        i
        for i, s in enumerate(steps)
        if str(s.get("uses", "")).startswith("actions/download-artifact")
    ]

    assert libs.get("needs") == "dsp"
    assert len(downloads) == 1 and downloads[0] < check
    download = steps[downloads[0]]
    _plain(download)
    assert download["with"].get("name") == "golden-vectors"
    env = libs.get("env")
    assert isinstance(env, dict)
    assert env.get("SINUS_GOLDEN_DIR") == download["with"].get("path")
    assert shlex.split(str(steps[check]["run"]))[1:3] == ["--vectors", "${SINUS_GOLDEN_DIR}"]


@pytest.mark.requirement("SRS-035")
def test_equivalence_step_fails_the_job_on_a_missing_or_failing_file(
    workflow: dict[str, Any],
) -> None:
    """The step that runs the check of SRS-034 can fail the build, and nothing hides its status.

    Input: the job `libs`.
    Expected: exactly one step runs `build/release/verification/sinus_dsp_equivalence` (after
    the release build and its tests) with `--vectors` and `--results`; the command is a single
    program call (no `||`, `&&`, `;`, pipe), the step has no `if`, no `continue-on-error`
    (neither at step nor at job level) and no `shell` override that would change the exit
    status handling.
    """
    libs = _job(workflow, "libs")
    steps = _steps(libs)
    check = _only(steps, "sinus_dsp_equivalence")
    command = str(steps[check]["run"]).strip()
    words = shlex.split(command)
    build = [i for i, s in enumerate(steps) if "--preset release" in str(s.get("run", ""))]

    assert words[0] == "build/release/verification/sinus_dsp_equivalence"
    assert "--vectors" in words and "--results" in words
    assert not re.search(r"\|\||&&|;|\||\bexit\b|\btrue\b", command), f"status hidden: {command!r}"
    _plain(steps[check])
    _plain(libs)
    assert "shell" not in steps[check]
    assert build and build[0] < check


@pytest.mark.requirement("SRS-035")
def test_equivalence_results_are_uploaded_even_when_the_check_failed(
    workflow: dict[str, Any],
) -> None:
    """The result of the check is kept on failure, after the check step.

    Input: the job `libs`.
    Expected: after the equivalence step, a step uses `actions/upload-artifact` with the
    condition `always()`, the name `equivalence-computer`, and in its path the file given to
    `--results` by the equivalence step.
    """
    steps = _steps(_job(workflow, "libs"))
    check = _only(steps, "sinus_dsp_equivalence")
    words = shlex.split(str(steps[check]["run"]))
    results = words[words.index("--results") + 1].replace("${RUNNER_TEMP}", "${{ runner.temp }}")
    uploads = [
        i
        for i, s in enumerate(steps)
        if i > check
        and str(s.get("uses", "")).startswith("actions/upload-artifact")
        and isinstance(s.get("with"), dict)
        and s["with"].get("name") == "equivalence-computer"
    ]

    assert len(uploads) == 1, f"{len(uploads)} uploads of equivalence-computer after the check"
    step = steps[uploads[0]]
    assert step.get("if") == "always()"
    assert results in str(step["with"].get("path"))
