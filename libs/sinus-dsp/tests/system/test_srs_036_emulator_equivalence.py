"""System verification of SRS-036: equivalence of the library on the ESP32-S3, in the emulator.

The emulator runs only in the CI job ``libs-esp32s3`` (architecture-m2.md 14.13), so the
verification has two parts:

* checks that need nothing from a run: the job in ``ci.yml`` (every push, after ``dsp``, the
  pinned image, the build of the app, QEMU on the pack of the golden vectors, the verdict through
  ``emulator_log.py``), and ``emulator_log.py`` on recorded logs;
* ``test_emulator_run_meets_srs_036``, which judges the files of one run against the requirement.
  It reads them from the folder named by the environment variable ``SINUS_EMULATOR_DIR``, which
  must hold ``qemu.log`` (serial log of the emulator) and ``equivalence-esp32s3.md`` (results
  written by ``emulator_log.py``). If ``SINUS_GOLDEN_DIR`` (the golden vectors of the run) is set,
  the reference identity of the results is also compared with that of the files. The test is
  skipped with a message when ``SINUS_EMULATOR_DIR`` is unset; the job ``libs-esp32s3`` sets it.

The judgement is written here, independently of ``emulator_log.py``: exactly one end line
``SINUS-EQUIVALENCE-END pass``; the target is the ESP32-S3; the library version and source digest
are those computed here by the method of 14.15; all 32 files of the set with the 6 compared
outputs each; every largest difference within the tolerance of SRS-034 and every outcome pass.
Standard library and pytest only.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

LIBRARY_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = LIBRARY_ROOT.parents[1]
EMULATOR_LOG = LIBRARY_ROOT / "verification" / "emulator_log.py"
CI_FILE = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"

EMULATOR_DIR_VARIABLE = "SINUS_EMULATOR_DIR"
GOLDEN_DIR_VARIABLE = "SINUS_GOLDEN_DIR"

#: The set of SRS-035 (architecture-m2.md 14.12): 18 synthetic, 8 event, 6 record segments.
SET = tuple(
    [
        f"syn-fs{fs}-hr{hr}-{kind}"
        for fs in (250, 360)
        for hr in ("040", "075", "180")
        for kind in ("clean", "bw-mains50", "bw-mains60")
    ]
    + [
        f"syn-fs{fs}-event-{kind}"
        for fs in (250, 360)
        for kind in ("artefact", "held", "rate-change", "small-beat")
    ]
    + [f"mitdb-{record}-first60s" for record in ("100", "105", "108", "119", "203", "207")]
)

#: SRS-034: the compared outputs and their tolerances.
TOLERANCES = {
    "baseline_mv": 2e-5,
    "mains_mv": 2e-5,
    "beats": 0.0,
    "beat_reported_at": 0.0,
    "heart_rates": 1e-4,
    "quality_windows": 0.01,
}
TOLERANCE_TEXT = {
    "baseline_mv": "2e-05",
    "mains_mv": "2e-05",
    "beats": "0",
    "beat_reported_at": "0",
    "heart_rates": "1e-04",
    "quality_windows": "0.01",
}
OUTPUTS = tuple(TOLERANCES)

END_PASS = "SINUS-EQUIVALENCE-END pass"
BEGIN = "SINUS-EQUIVALENCE-BEGIN"
SHA = re.compile(r"[0-9a-f]{64}")
ANSI = re.compile("\x1b\\[[0-9;]*[A-Za-z]")


def library_identity() -> tuple[str, str]:
    """Version and source digest of the library, by the method of architecture-m2.md 14.15."""
    version = (LIBRARY_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    libs = LIBRARY_ROOT.parent
    names: list[str] = []
    for folder in ("include", "src"):
        for path in (LIBRARY_ROOT / folder).rglob("*"):
            relative = path.relative_to(libs)
            if path.is_file() and not any(part.startswith(".") for part in relative.parts):
                names.append(relative.as_posix())
    manifest = ""
    for name in sorted(names):
        data = (libs / name).read_bytes().replace(b"\r\n", b"\n")
        manifest += f"{hashlib.sha256(data).hexdigest()}  {name}\n"
    return version, hashlib.sha256(manifest.encode()).hexdigest()


def golden_identity(folder: Path) -> set[tuple[str, str]]:
    """The (software_version, source_sha256) stated by the golden-vector files."""
    found: set[tuple[str, str]] = set()
    for name in SET:
        header: dict[str, str] = {}
        with (folder / f"{name}.golden.txt").open(encoding="utf-8") as stream:
            for line in stream:
                key, _, value = line.rstrip("\n").partition("=")
                if key in ("software_version", "source_sha256"):
                    header[key] = value
                if len(header) == 2:
                    break
        found.add((header["software_version"], header["source_sha256"]))
    return found


def judge(directory: Path, golden_dir: Path | None = None) -> list[str]:
    """Problems of one emulator run against SRS-036 and SRS-034; empty if it meets them."""
    problems: list[str] = []
    try:
        log = (directory / "qemu.log").read_bytes().decode("utf-8", errors="replace")
        results = (directory / "equivalence-esp32s3.md").read_text(encoding="utf-8")
    except OSError as error:
        return [f"file of the run missing: {error}"]

    lines = [ANSI.sub("", x).strip() for x in log.splitlines()]
    ends = [x for x in lines if x.startswith("SINUS-EQUIVALENCE-END")]
    if ends != [END_PASS]:
        problems.append(f"log: end lines {ends!r}, expected exactly [{END_PASS!r}]")
    if lines.count(BEGIN) != 1:
        problems.append(f"log: {lines.count(BEGIN)} lines {BEGIN}, expected 1")

    rows: dict[str, str] = {}
    table: list[list[str]] = []
    for line in results.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("| "):
            continue
        if len(cells) == 2:
            rows[cells[0]] = cells[1]
        elif len(cells) == 6:
            table.append(cells)

    target = rows.get("Build target", "")
    if not target.startswith("ESP32-S3 (emulator"):
        problems.append(f"build target {target!r} is not the ESP32-S3 in the emulator")
    version, digest = library_identity()
    expected_library = f"sinus-dsp {version}, source SHA-256 {digest}"
    if rows.get("Library") != expected_library:
        problems.append(f"library {rows.get('Library')!r}, computed {expected_library!r}")
    reference = rows.get("Reference", "")
    match = re.fullmatch(r"sinus-dsp (\S+), source SHA-256 ([0-9a-f]{64})", reference)
    if match is None:
        problems.append(f"reference {reference!r}: not one reference software")
    elif golden_dir is not None and golden_identity(golden_dir) != {match.groups()}:
        problems.append(f"reference {reference!r} differs from the golden-vector files")
    if rows.get("Golden vectors") != "32 files of 32 expected, format version 2":
        problems.append(f"golden vectors row {rows.get('Golden vectors')!r}")
    size = re.fullmatch(r"(\d+) bytes, limit (\d+)", rows.get("Chain size", ""))
    if size is None or int(size.group(1)) > int(size.group(2)):
        problems.append(f"chain size row {rows.get('Chain size')!r}")
    if rows.get("Outcome") != "pass":
        problems.append(f"outcome row {rows.get('Outcome')!r}")

    seen: dict[tuple[str, str], str] = {}
    for cells in table[1:]:  # the header row first
        name, output, difference, _sample, tolerance, outcome = cells
        key = (name, output)
        if key in seen:
            problems.append(f"{name} {output}: reported twice")
        seen[key] = outcome
        if output not in TOLERANCES:
            problems.append(f"{name}: unexpected output {output}")
            continue
        try:
            value, stated = float(difference), float(tolerance)
        except ValueError:
            problems.append(f"{name} {output}: difference {difference!r}")
            continue
        if stated != TOLERANCES[output]:
            problems.append(f"{name} {output}: tolerance {tolerance}, SRS-034 {TOLERANCES[output]}")
        if not value <= TOLERANCES[output]:
            problems.append(f"{name} {output}: difference {difference} exceeds the tolerance")
        if outcome != "pass":
            problems.append(f"{name} {output}: outcome {outcome}")
    expected_keys = {(n, o) for n in SET for o in OUTPUTS}
    for key in sorted(expected_keys - seen.keys()):
        problems.append(f"{key[0]} {key[1]}: missing from the results")
    for key in sorted(seen.keys() - expected_keys):
        if key[1] in TOLERANCES:
            problems.append(f"{key[0]}: not a file of the set")
    return problems


def synthetic_results(
    *, target: str = "ESP32-S3 (emulator, ESP-IDF 6.1, GNU 15.2.0)", library: str | None = None
) -> str:
    """Results in the format of 14.12, as the emulator would report a perfect run."""
    version, digest = library_identity()
    library_text = library or f"sinus-dsp {version}, source SHA-256 {digest}"
    head = [
        "# Equivalence of the real-time library with the reference",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Build target | {target} |",
        f"| Library | {library_text} |",
        f"| Reference | sinus-dsp {version}, source SHA-256 {'a' * 64} |",
        "| Golden vectors | 32 files of 32 expected, format version 2 |",
        "| Chain size | 51840 bytes, limit 65536 |",
        "| Outcome | pass |",
        "",
        "## Results per file",
        "",
        "| File | Output | Largest difference | At sample | Tolerance | Outcome |",
        "|---|---|---:|---:|---:|---|",
    ]
    body = [
        f"| {name} | {output} | 0 | 1 | {TOLERANCE_TEXT[output]} | pass |"
        for name in SET
        for output in OUTPUTS
    ]
    return "\n".join(head + body) + "\n"


def write_run(folder: Path, results: str, log_end: str = END_PASS) -> Path:
    block = f"boot noise\n{BEGIN}\n{results.strip()}\n{log_end}\n"
    (folder / "qemu.log").write_text(block, encoding="utf-8")
    (folder / "equivalence-esp32s3.md").write_text(results, encoding="utf-8")
    return folder


# ---------------------------------------------------------------------------------------------
# The configuration of the job and the verdict script (no run needed)
# ---------------------------------------------------------------------------------------------


def _job() -> str:
    text = CI_FILE.read_text(encoding="utf-8")
    start = text.index("\n  libs-esp32s3:")
    following = re.search(r"\n  [A-Za-z0-9_-]+:\n", text[start + 1 :])
    return text[start : start + 1 + following.start()] if following else text[start:]


@pytest.mark.requirement("SRS-036")
def test_job_runs_on_every_push_in_the_emulator_on_the_set() -> None:
    text = CI_FILE.read_text(encoding="utf-8")
    on_block = text[: text.index("\njobs:")]
    assert "\n  push:\n" in on_block and "branches" not in on_block
    job = _job()
    assert "needs: dsp" in job
    assert "espressif/idf:v6.1@sha256:" in job
    assert "name: golden-vectors" in job  # the set of SRS-035
    assert "sinus_dsp_golden_pack" in job and "idf.py" in job
    assert "qemu-system-xtensa -machine esp32s3" in job
    assert "-serial file:" in job
    assert "verification/emulator_log.py" in job  # the verdict, which fails the job
    assert "continue-on-error" not in job
    assert "if: always()" in job and "equivalence-esp32s3" in job
    assert job.index("qemu-system-xtensa") < job.index("emulator_log.py")
    assert "test_srs_036_emulator_equivalence.py" in job and EMULATOR_DIR_VARIABLE in job


def _run_log(tmp_path: Path, log: str) -> subprocess.CompletedProcess[str]:
    log_file, results_file = tmp_path / "qemu.log", tmp_path / "r.md"
    log_file.write_text(log, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(EMULATOR_LOG), str(log_file), "--results", str(results_file)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.requirement("SRS-036")
def test_verdict_script_on_recorded_logs(tmp_path: Path) -> None:
    results = synthetic_results()
    good = f"boot\n{BEGIN}\n{results.strip()}\n{END_PASS}\n"
    assert _run_log(tmp_path, good).returncode == 0
    failing = results.replace("| Outcome | pass |", "| Outcome | fail |").replace(
        "| baseline_mv | 0 | 1 | 2e-05 | pass |", "| baseline_mv | 3e-05 | 1 | 2e-05 | fail |", 1
    )
    failed_log = f"{BEGIN}\n{failing.strip()}\nSINUS-EQUIVALENCE-END fail\n"
    assert _run_log(tmp_path, failed_log).returncode == 1
    assert _run_log(tmp_path, f"{BEGIN}\n{results.strip()}\n").returncode == 1  # no end line
    assert _run_log(tmp_path, good + good).returncode == 1  # two end lines
    assert _run_log(tmp_path, "").returncode == 1  # nothing (timeout)


# ---------------------------------------------------------------------------------------------
# The judgement itself, on synthetic runs
# ---------------------------------------------------------------------------------------------


def test_library_identity_has_the_documented_form() -> None:
    version, digest = library_identity()
    assert version == (LIBRARY_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert SHA.fullmatch(digest)


def test_judge_accepts_a_perfect_run(tmp_path: Path) -> None:
    assert judge(write_run(tmp_path, synthetic_results())) == []


def _drop_file(r: str) -> str:
    return "\n".join(x for x in r.splitlines() if "mitdb-207" not in x) + "\n"


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda r: r.replace("ESP32-S3 (emulator", "computer (x86"), "build target"),
        (lambda r: r.replace("source SHA-256 ", "source SHA-256 0", 1), "library"),
        (_drop_file, "missing"),
        (lambda r: r.replace("| beats | 0 | 1 |", "| beats | 1 | 1 |", 1), "exceeds"),
        (lambda r: r.replace("| 2e-05 |", "| 1e-03 |", 1), "tolerance"),
        (lambda r: r.replace("| 2e-05 | pass |", "| 2e-05 | fail |", 1), "outcome fail"),
        (lambda r: r.replace("| Outcome | pass |", "| Outcome | fail |"), "outcome row"),
    ],
)
def test_judge_rejects(tmp_path: Path, mutate: Callable[[str], str], needle: str) -> None:
    problems = judge(write_run(tmp_path, mutate(synthetic_results())))
    assert any(needle in p for p in problems), problems


def test_judge_rejects_a_log_without_the_passing_end_line(tmp_path: Path) -> None:
    run = write_run(tmp_path, synthetic_results(), log_end="SINUS-EQUIVALENCE-END fail")
    assert any("end lines" in p for p in judge(run))
    run = write_run(tmp_path, synthetic_results(), log_end=END_PASS + "\n" + END_PASS)
    assert any("end lines" in p for p in judge(run))


def test_judge_names_a_missing_file_of_the_run(tmp_path: Path) -> None:
    assert any("missing" in p for p in judge(tmp_path))


# ---------------------------------------------------------------------------------------------
# The run of the job
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-036")
def test_emulator_run_meets_srs_036() -> None:
    folder = os.environ.get(EMULATOR_DIR_VARIABLE)
    if not folder:
        pytest.skip(
            f"{EMULATOR_DIR_VARIABLE} is not set: the emulator runs only in the CI job "
            "libs-esp32s3, which sets it to the folder of qemu.log and equivalence-esp32s3.md"
        )
    golden = os.environ.get(GOLDEN_DIR_VARIABLE)
    problems = judge(Path(folder), Path(golden) if golden else None)
    assert problems == [], "\n".join(problems)
