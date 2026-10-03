"""Requirement tests of SRS-012: validation report content (RC-004, RC-005, RC-011).

The report is generated from fixture databases written by the tests (`conftest.py`): a
MIT-BIH Arrhythmia fixture of 14 records of 7 minutes at 360 Hz and a Noise Stress Test
fixture of 12 ECG records and 3 noise records, each with its checksum list, the `Database`
under test pinned to the digest of that list, and no network. Channel 0 of every record is
flat except for 1 mV spikes, and the detector is a double that returns the spike samples, so
the detections, and therefore every count, are known (SRS-008 decides them; the expected
values are worked out in the docstring of each record builder of `conftest.py`). The command
tests run the script of the software in a separate process, without network.

What the tests check, from the statement of SRS-012 (v0.7):
- the per-record and aggregate statistics of SRS-011, with values matching the fixture;
- the five records with the lowest Se and with the lowest +P, among the records whose value
  is defined (fewer if fewer are defined), ties ordered by record name;
- the pass or fail of each SRS-007 threshold (99.50%), decided on the exact counts; a
  threshold whose value is not defined is reported as fail;
- the database name and version and the outcome of its verification (SRS-001);
- the software version, with the identifier of the source code that produced the report,
  and the settings used (channel, mains frequency). The test computes the identifier itself
  from the source files of the package under test, with the six steps of architecture
  section 8.14 (`conftest.py`, not the function of the software), and compares it with the
  row `| Software | sinus-dsp <version>, source SHA-256 <identifier> |`; copies of the
  package, changed or not, run in a separate process show that the identifier and the
  version are those of the code that runs;
- the versions of the third-party software used at run time: the row `| Runtime | Python
  <major>.<minor>, numpy <version>, scipy <version>, wfdb <version> |`, compared with the
  environment that runs the test (`sys.version_info`, `importlib.metadata`), and naming
  every runtime dependency of `dsp/pyproject.toml`;
- what was not scored because of ventricular flutter or fibrillation episodes: the episodes
  in the record, over the whole record; from 5:00 to the end of the record, the episodes that
  reach 5:00 or later, their duration from 5:00 with the onset and offset samples (a sample
  shared by two episodes counted once), the reference beats and the unpaired detections
  inside them, without the detection dropped by the rule at 5:00; a statement when no record
  has an episode;
- the statement that the results are a technical evaluation only;
- no report, and an error, when the verification of the database fails.

The cases of the verification of SRS-012 and their tests:
- the report contains each listed item, with values matching the fixture, the worst records
  in the expected order: the tests on the standard fixture below;
- the software version and the identifier of the source code are those of the software
  under test, the identifier computed by the test:
  `test_report_states_the_software_version_and_the_source_identifier`, and for the code that
  runs, `test_report_states_the_identity_of_the_code_that_runs` and
  `test_command_report_states_the_software_and_the_runtime_versions`;
- the versions of the third-party software are those of the environment that runs the test,
  in the documented form: `test_report_states_the_runtime_versions_of_the_environment`;
- two episodes, one that ends before 5:00 and one after it: record 207 of the standard
  fixture (`test_episode_before_5_minutes_counts_only_in_the_episodes_of_the_record`) and
  the case `one-before-and-one-after-5min` of the figures of one record;
- an episode that contains 5:00, with beats and unpaired detections before and after 5:00:
  record 209 (`test_episode_that_contains_5_minutes_counts_from_5_minutes`) and the case
  `contains-5min`;
- a detection left unscored by the rule at 5:00 inside an episode: record 209
  (`test_detection_dropped_by_the_rule_at_5_minutes_is_not_counted`) and the cases
  `dropped-at-5min-inside-an-episode` and `dropped-at-5min-no-scored-beat`;
- two episodes that share a sample: `test_sample_shared_by_two_episodes_is_counted_once` and
  the case `two-episodes-sharing-a-sample`;
- fewer than five records whose Se or +P is defined:
  `test_ranking_lists_only_the_records_whose_value_is_defined` and
  `test_ranking_is_empty_when_no_record_has_a_defined_value`;
- a gross Se or +P that is not defined: the cases `no-detection` and `nothing` of
  `test_threshold_outcome_is_decided_on_the_exact_counts`;
- fixtures without episodes: `test_report_says_so_when_no_record_has_an_episode`;
- a fixture database that fails verification: the tests of the last group.

The text formats (headings, table columns, sentences) are those of the documented report
format (architecture, section 8.10). The count of flutter-wave annotations outside the
episodes is a design figure of the same section of the report (architecture, sections 8.8
and 8.10), tested here with it.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.metadata
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sinus_dsp.data.physionet import Database, VerificationResult
from sinus_dsp.data.records import Annotation, Record
from sinus_dsp.errors import DataVerificationError
from sinus_dsp.evaluation.metrics import RecordCounts, aggregate_statistics
from sinus_dsp.evaluation.noise_stress import NoiseStressResults, SnrStatistics
from sinus_dsp.evaluation.report import render_full_report
from sinus_dsp.evaluation.run import (
    EvaluationSettings,
    RecordEvaluation,
    ValidationResults,
    evaluate_record,
    meets_target,
    run_validation,
    write_validation_report,
)
from sinus_dsp.version import SoftwareIdentity

pytestmark = pytest.mark.usefixtures("forbid_network")

STATEMENT = (
    "Technical evaluation only. Sinus is not a medical device; these results are not a "
    "clinical validation."
)
MITDB_TITLE = "MIT-BIH Arrhythmia Database"
NSTDB_TITLE = "MIT-BIH Noise Stress Test Database"
NOT_SCORED_SENTENCE = (
    "The first 5 min of each record are not scored. Ventricular flutter and fibrillation "
    "episodes are not scored either. The durations and counts below cover the part of each "
    "record from 5:00 to its end, except the episodes in the record, which are counted over "
    "the whole record."
)
NO_EPISODE_SENTENCE = (
    "No ventricular flutter or fibrillation episode is annotated in these records."
)
FLUTTER_SENTENCE = (
    "Flutter-wave annotations outside ventricular flutter and fibrillation episodes, "
    "in all records: {n}."
)
VALIDATE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate.py"
VF_RECORDS = ("207", "208", "209", "210", "211")


def _databases(fixture: Any, *, mitdb_title: str = MITDB_TITLE, mitdb_version: str = "1.0.0"):
    """The two `Database` values of a fixture, pinned to the digests of its checksum lists."""
    mitdb = Database(
        slug="mitdb",
        version=mitdb_version,
        title=mitdb_title,
        checksum_list_sha256=fixture.mitdb.checksum_list_sha256,
    )
    nstdb = Database(
        slug="nstdb",
        version="1.0.0",
        title=NSTDB_TITLE,
        checksum_list_sha256=fixture.nstdb.checksum_list_sha256,
    )
    return mitdb, nstdb


def _verified_text(database: Any) -> str:
    """The documented verification outcome of a whole fixture database."""
    return (
        f"verified: {database.n_listed_files} files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {database.checksum_list_sha256})"
    )


@dataclass(frozen=True)
class Run:
    """A report generated from a fixture: the evaluation results and the text written."""

    results: Any
    text: str
    calls: tuple[tuple[int, float, int], ...]


def _generate(
    fixture: Any,
    output: Path,
    detector_class: Callable[[], Any],
    settings: EvaluationSettings | None = None,
    **database_options: str,
) -> Run:
    """Write the report of ``fixture`` to ``output`` and run the evaluation once more."""
    mitdb, nstdb = _databases(fixture, **database_options)
    options: dict[str, Any] = {} if settings is None else {"settings": settings}
    detector = detector_class()
    write_validation_report(
        output,
        fixture.data_root,
        mitdb=mitdb,
        nstdb=nstdb,
        detector=detector,
        fetch=None,
        **options,
    )
    results = run_validation(
        fixture.data_root,
        mitdb=mitdb,
        nstdb=nstdb,
        detector=detector_class(),
        fetch=None,
        **options,
    )
    return Run(
        results=results, text=output.read_bytes().decode("utf-8"), calls=tuple(detector.calls)
    )


@pytest.fixture(scope="module")
def standard_run(
    evaluation_fixture: Any,
    make_spike_detector: Callable[[], Any],
    network_forbidden: Callable[[], Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> Run:
    """The report of the standard fixture, with the default settings."""
    output = tmp_path_factory.mktemp("srs012-standard") / "qrs-ec57-report.md"
    with network_forbidden():
        return _generate(evaluation_fixture, output, make_spike_detector)


@pytest.fixture(scope="module")
def no_episode_run(
    evaluation_fixture_without_episodes: Any,
    make_spike_detector: Callable[[], Any],
    network_forbidden: Callable[[], Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> Run:
    """The report of the fixture in which no record has an episode."""
    output = tmp_path_factory.mktemp("srs012-no-episode") / "qrs-ec57-report.md"
    with network_forbidden():
        return _generate(evaluation_fixture_without_episodes, output, make_spike_detector)


def _non_table_lines(section: Any) -> list[str]:
    return [line for line in section.lines if line.strip() and not line.lstrip().startswith("|")]


# --------------------------------------------------------------------------------------------
# The statement on what the results mean
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-012")
def test_report_states_that_it_is_a_technical_evaluation_only(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The statement on what the results do not mean (RC-005, RC-011).

    Input: the report of the standard fixture.
    Expected: the statement "Technical evaluation only. Sinus is not a medical device; these
    results are not a clinical validation." verbatim, as a paragraph of its own (an empty
    line before and after it), before the first section of results.
    """
    report = parse_report(standard_run.text)
    lines = list(report.lines)

    assert STATEMENT in lines, "the statement is missing or not verbatim"
    index = lines.index(STATEMENT)
    assert lines[index - 1] == "" and lines[index + 1] == "", "not a paragraph of its own"
    first_section = min(i for i, level, _ in report.headings if level > 1)
    assert index < first_section


# --------------------------------------------------------------------------------------------
# Database, verification, software version and settings
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-012")
def test_report_states_the_database_and_the_outcome_of_its_verification(
    standard_run: Run, evaluation_fixture: Any, parse_report: Callable[[str], Any]
) -> None:
    """The database name and version, and the outcome of its SRS-001 verification.

    Input: the report of the standard fixture, whose MIT-BIH checksum list names 45 files.
    Expected, in the section "Software, data and settings": the name "MIT-BIH Arrhythmia
    Database", the version "1.0.0", and "verified: 45 files match the published SHA-256
    checksum list (SHA256SUMS.txt, SHA-256 <digest of the fixture list>)", for the whole
    database (no list of records after it).
    """
    section = parse_report(standard_run.text).section("software, data and settings")
    verified = _verified_text(evaluation_fixture.mitdb)

    assert MITDB_TITLE in section.text
    assert "1.0.0" in section.text
    assert verified in section.text
    line = next(line for line in section.lines if verified in line)
    assert "; records" not in line


@pytest.mark.requirement("SRS-012")
def test_report_states_the_database_that_was_verified(
    tmp_path: Path,
    evaluation_fixture: Any,
    make_spike_detector: Callable[[], Any],
    parse_report: Callable[[str], Any],
) -> None:
    """The name and version stated are those of the database verified, not fixed texts.

    Input: the standard fixture, with the MIT-BIH database described as "Fixture Arrhythmia
    Database", version "2.3.4" (same files and pinned list).
    Expected: the section "Software, data and settings" states "Fixture Arrhythmia Database"
    and "2.3.4", and not "MIT-BIH Arrhythmia Database".
    """
    run = _generate(
        evaluation_fixture,
        tmp_path / "report.md",
        make_spike_detector,
        mitdb_title="Fixture Arrhythmia Database",
        mitdb_version="2.3.4",
    )
    section = parse_report(run.text).section("software, data and settings")

    assert "Fixture Arrhythmia Database" in section.text
    assert "2.3.4" in section.text
    assert MITDB_TITLE not in section.text


def _replaced(results: Any, **changes: Any) -> Any:
    return replace(results, **changes)


# --------------------------------------------------------------------------------------------
# Software version, identifier of the source code, and runtime versions
# --------------------------------------------------------------------------------------------

HEX64 = re.compile(r"^[0-9a-f]{64}$")
OTHER_SOFTWARE = SoftwareIdentity(
    version="9.8.7.dev6",
    source_sha256="0123456789abcdef" * 4,
    python="3.99",
    runtime=(("numpy", "1.2.3"), ("scipy", "4.5.6"), ("wfdb", "7.8.9")),
)


def _rows_starting_with(text: str, prefix: str) -> list[str]:
    """The lines of ``text`` that start with ``prefix``."""
    return [line for line in text.split("\n") if line.startswith(prefix)]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.requirement("SRS-012")
def test_source_identifier_of_the_test_follows_the_documented_method(
    tmp_path: Path,
    source_digest: Callable[[Path], str],
    source_manifest: Callable[[Path], bytes],
) -> None:
    """The identifier that the tests compute is the one documented in architecture 8.14.

    Checks the helper of the tests before it is used as the expected value.
    Input: a package folder `pkg` written by the test, holding `__init__.py`, `Z.py`, `b.py`
    (CR LF line endings), `sub/a.py` and `sub/é.py`, and what the method leaves out:
    `__pycache__/c.py`, `.hidden/d.py`, `.e.py`, `f.pyc`, `g.txt`, a folder `h.py` holding
    only a text file, and, where the platform allows them, a symbolic link `i.py` to `b.py`
    and a symbolic link `j` to the folder `sub`.
    Expected: the manifest is the line `<SHA-256 of the content, CR LF read as LF>  <name>`
    for `pkg/Z.py`, `pkg/__init__.py`, `pkg/b.py`, `pkg/sub/a.py` and `pkg/sub/é.py`, in this
    (code-point) order, each ended by a line feed, in UTF-8, written out literally here; the
    identifier is the SHA-256 of that manifest, 64 lowercase hexadecimal digits.
    """
    package = tmp_path / "pkg"
    contents = {
        "__init__.py": b'"""Package."""\n__version__ = "1.2.3"\n',
        "Z.py": b"z = 1\n",
        "b.py": b"b = 2\r\nc = 3\r\n",
        "sub/a.py": b"a = 1\n",
        "sub/é.py": b"e = 5\n",
        "__pycache__/c.py": b"c = 1\n",
        ".hidden/d.py": b"d = 1\n",
        ".e.py": b"e = 1\n",
        "f.pyc": b"\x00\x01",
        "g.txt": b"text\n",
        "h.py/inner.txt": b"text\n",
    }
    for name, data in contents.items():
        (package / name).parent.mkdir(parents=True, exist_ok=True)
        (package / name).write_bytes(data)
    with contextlib.suppress(OSError, NotImplementedError):
        (package / "i.py").symlink_to(package / "b.py")
    with contextlib.suppress(OSError, NotImplementedError):
        (package / "j").symlink_to(package / "sub", target_is_directory=True)
    manifest = (
        _sha256(b"z = 1\n")
        + "  pkg/Z.py\n"
        + _sha256(b'"""Package."""\n__version__ = "1.2.3"\n')
        + "  pkg/__init__.py\n"
        + _sha256(b"b = 2\nc = 3\n")
        + "  pkg/b.py\n"
        + _sha256(b"a = 1\n")
        + "  pkg/sub/a.py\n"
        + _sha256(b"e = 5\n")
        + "  pkg/sub/é.py\n"
    ).encode("utf-8")

    assert source_manifest(package) == manifest
    assert source_digest(package) == hashlib.sha256(manifest).hexdigest()
    assert HEX64.match(source_digest(package))


@pytest.mark.requirement("SRS-012")
def test_report_states_the_software_version_and_the_source_identifier(
    standard_run: Run,
    parse_report: Callable[[str], Any],
    running_software: Any,
    project_version: str,
) -> None:
    """The software version, with the identifier of the source code that produced the report.

    Input: the report of the standard fixture, written by the package under test in the test
    process; the identifier computed by the test from the source files of that package (the
    six steps of architecture section 8.14); the `__version__` literal of the package and
    the version of `dsp/pyproject.toml`.
    Expected: the table of the section "Software, data and settings" (columns Item, Value)
    has the line `| Software | sinus-dsp <version>, source SHA-256 <identifier> |` with these
    values, and the report has no other line starting with `| Software |`; the identifier
    has 64 lowercase hexadecimal digits; the version is also that of `dsp/pyproject.toml`;
    the results carry the same version and identifier.
    """
    section = parse_report(standard_run.text).section("software, data and settings")
    expected = running_software

    assert HEX64.match(expected.source_sha256)
    assert expected.version == project_version
    assert expected.software_row in section.lines
    assert _rows_starting_with(standard_run.text, "| Software |") == [expected.software_row]
    table = section.table_with_row("Software")
    assert table.header == ("Item", "Value")
    assert table.row("Software") == (
        "Software",
        f"sinus-dsp {expected.version}, source SHA-256 {expected.source_sha256}",
    )
    assert standard_run.results.software.version == expected.version
    assert standard_run.results.software.source_sha256 == expected.source_sha256


@pytest.mark.requirement("SRS-012")
def test_report_states_the_runtime_versions_of_the_environment(
    standard_run: Run,
    parse_report: Callable[[str], Any],
    running_software: Any,
    runtime_dependency_names: tuple[str, ...],
) -> None:
    """The versions of the third-party software used at run time.

    Input: the report of the standard fixture, written in the test process; the Python
    version of the test process (`sys.version_info`), the installed versions of numpy, scipy
    and wfdb (`importlib.metadata.version`) and the runtime dependencies of
    `dsp/pyproject.toml`.
    Expected: the table of the section "Software, data and settings" has the line
    `| Runtime | Python <major>.<minor>, numpy <version>, scipy <version>, wfdb <version> |`
    with these values, in this order (the documented form; Python without its patch
    number), and the report has no other line starting with `| Runtime |`; the packages
    named are exactly the runtime dependencies of `dsp/pyproject.toml`; the results carry the
    same versions.
    """
    section = parse_report(standard_run.text).section("software, data and settings")
    expected = running_software
    python = f"{sys.version_info.major}.{sys.version_info.minor}"

    assert expected.runtime_row in section.lines
    assert _rows_starting_with(standard_run.text, "| Runtime |") == [expected.runtime_row]
    value = section.table_with_row("Runtime").row("Runtime")[1]
    first, *packages = value.split(", ")
    assert first == f"Python {python}"
    assert [package.split(" ")[0] for package in packages] == ["numpy", "scipy", "wfdb"]
    assert sorted(package.split(" ")[0] for package in packages) == sorted(runtime_dependency_names)
    for package in packages:
        name, version = package.split(" ")
        assert version == importlib.metadata.version(name), name
    assert standard_run.results.software.python == python
    assert standard_run.results.software.runtime == expected.runtime


@pytest.mark.requirement("SRS-012")
def test_software_and_runtime_rows_are_those_of_the_results(
    standard_run: Run, running_software: Any
) -> None:
    """The rows state the software identity that the results carry, not fixed texts.

    Input: the results of the standard fixture with their software identity replaced by
    version "9.8.7.dev6", identifier "0123456789abcdef" four times, Python "3.99", numpy
    1.2.3, scipy 4.5.6 and wfdb 7.8.9, rendered as the full report.
    Expected: exactly one line `| Software | sinus-dsp 9.8.7.dev6, source SHA-256
    0123456789abcdef...0123456789abcdef |` and one line `| Runtime | Python 3.99, numpy
    1.2.3, scipy 4.5.6, wfdb 7.8.9 |`; neither the version, the identifier nor the runtime
    line of the package under test.
    """
    text = render_full_report(_replaced(standard_run.results, software=OTHER_SOFTWARE))

    assert _rows_starting_with(text, "| Software |") == [
        f"| Software | sinus-dsp 9.8.7.dev6, source SHA-256 {'0123456789abcdef' * 4} |"
    ]
    assert _rows_starting_with(text, "| Runtime |") == [
        "| Runtime | Python 3.99, numpy 1.2.3, scipy 4.5.6, wfdb 7.8.9 |"
    ]
    assert f"sinus-dsp {running_software.version}," not in text
    assert running_software.source_sha256 not in text
    assert running_software.runtime_row not in text


def _set_version_literal(init_file: Path, version: str) -> None:
    """Replace the string literal assigned to ``__version__`` in ``init_file``."""
    source = init_file.read_bytes()
    literals = [
        node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    assert len(literals) == 1
    literal = literals[0]
    assert literal is not None and literal.lineno == literal.end_lineno
    lines = source.split(b"\n")
    line = lines[literal.lineno - 1]
    lines[literal.lineno - 1] = (
        line[: literal.col_offset] + f'"{version}"'.encode() + line[literal.end_col_offset :]
    )
    init_file.write_bytes(b"\n".join(lines))


def _change_copy(package: Path, variant: str) -> None:
    """Change a copy of the package as the variant says."""
    if variant == "unchanged":
        return
    if variant == "comment-added":
        path = package / "evaluation" / "run.py"
        path.write_bytes(path.read_bytes() + b"\n# A comment line added by a test.\n")
    elif variant == "module-added":
        (package / "evaluation" / "added_by_a_test.py").write_bytes(b'"""Added by a test."""\n')
    elif variant == "version-changed":
        _set_version_literal(package / "__init__.py", "9.9.9.dev9")
    else:
        raise AssertionError(variant)


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    "variant", ["unchanged", "comment-added", "module-added", "version-changed"]
)
def test_report_states_the_identity_of_the_code_that_runs(
    variant: str,
    tmp_path: Path,
    evaluation_fixture_without_episodes: Any,
    copy_package: Callable[..., Path],
    expected_software: Callable[[Path], Any],
    running_software: Any,
    run_report_driver: Callable[..., Any],
) -> None:
    """The version and the identifier stated are those of the code that wrote the report.

    Input: a copy of the package under test in another folder: unchanged; with a comment
    line added at the end of `sinus_dsp/evaluation/run.py`; with a module
    `sinus_dsp/evaluation/added_by_a_test.py` added; or with its `__version__` literal set
    to "9.9.9.dev9". A separate Python process that imports the package from the copy writes
    the report of the fixture databases without episodes, with the detector double.
    Expected: the process imported the copy and wrote the report; its only `Software` row
    states the `__version__` literal of the copy and the identifier computed by the test from
    the files of the copy; that identifier equals the one of the package under test for the
    unchanged copy only (the version literal is part of the source code, so changing it
    changes the identifier too), and the version differs only for the changed version; the
    only `Runtime` row is that of the environment.
    """
    package = copy_package(tmp_path / "code copy")
    _change_copy(package, variant)
    expected = expected_software(package)
    output = tmp_path / "out" / "qrs-ec57-report.md"
    output.parent.mkdir()

    run = run_report_driver(
        evaluation_fixture_without_episodes, output, cwd=tmp_path, package_root=package.parent
    )

    assert run.completed.returncode == 0, run.completed.stderr
    assert run.package_dir is not None and run.package_dir.samefile(package)
    assert run.report is not None
    text = run.report.decode("utf-8")
    assert _rows_starting_with(text, "| Software |") == [expected.software_row]
    assert _rows_starting_with(text, "| Runtime |") == [running_software.runtime_row]
    assert (expected.source_sha256 == running_software.source_sha256) == (variant == "unchanged")
    assert (expected.version == running_software.version) == (variant != "version-changed")
    if variant == "version-changed":
        assert expected.version == "9.9.9.dev9"


@pytest.mark.requirement("SRS-012")
def test_command_report_states_the_software_and_the_runtime_versions(
    tmp_path: Path,
    ecg_evaluation_fixture: Any,
    write_command_driver: Callable[[Path], Path],
    running_software: Any,
) -> None:
    """The report written by the validation command states the same software identity.

    Input: `validate.py --offline --data-dir <fixture> --output <path>`, run in a separate
    process without network, on the fixture databases of noise-free synthetic ECGs, with the
    pinned checksum lists set to the fixture lists for that process only.
    Expected: exit status 0; the report has exactly one line starting with `| Software |`,
    equal to `| Software | sinus-dsp <version>, source SHA-256 <identifier computed by the
    test> |`, and one starting with `| Runtime |`, equal to the documented line with the
    versions of the environment that runs the test.
    """
    fixture = ecg_evaluation_fixture
    output = tmp_path / "out" / "qrs-ec57-report.md"
    output.parent.mkdir()
    driver = write_command_driver(tmp_path)
    pins = (fixture.mitdb.checksum_list_sha256, fixture.nstdb.checksum_list_sha256)

    completed = _run_command(
        driver,
        pins,
        ["--offline", "--data-dir", str(fixture.data_root), "--output", str(output)],
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    text = output.read_bytes().decode("utf-8")
    assert _rows_starting_with(text, "| Software |") == [running_software.software_row]
    assert _rows_starting_with(text, "| Runtime |") == [running_software.runtime_row]


@pytest.mark.requirement("SRS-012")
def test_report_states_the_default_settings(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The settings used: channel and mains frequency, with the default settings.

    Input: the report of the standard fixture, generated with the default settings.
    Expected: the results carry channel 0 and 60 Hz; the section "Software, data and
    settings" states channel 0 and a mains interference filter of 60 Hz, and no 50 Hz.
    """
    section = parse_report(standard_run.text).section("software, data and settings")

    assert standard_run.results.settings == EvaluationSettings(channel=0, mains_hz=60)
    assert re.search(r"\bchannel 0\b", section.text)
    assert re.search(r"(?<![\d.])60 Hz", section.text)
    assert not re.search(r"(?<![\d.])50 Hz", section.text)


@pytest.mark.requirement("SRS-012")
def test_report_states_the_settings_used_when_they_are_not_the_defaults(
    tmp_path: Path,
    evaluation_fixture: Any,
    make_spike_detector: Callable[[], Any],
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
) -> None:
    """The settings stated are those used: channel 1 and 50 Hz.

    Input: the standard fixture evaluated with channel 1 and a 50 Hz mains setting. Channel 1
    of every record is flat, so the detector double finds nothing on it.
    Expected: the section "Software, data and settings" states channel 1 and 50 Hz, and
    neither channel 0 nor 60 Hz; the detector received the 50 Hz setting at every call; every
    record has TP 0, FP 0 and all its scored reference beats as FN (the counts of channel 1,
    not of channel 0): Se 0.00 (not defined for record 105) and +P not defined.
    """
    run = _generate(
        evaluation_fixture,
        tmp_path / "report.md",
        make_spike_detector,
        settings=EvaluationSettings(channel=1, mains_hz=50),
    )
    report = parse_report(run.text)
    settings = report.section("software, data and settings").text
    table = report.section("results per record").table_with_row("100")

    assert re.search(r"\bchannel 1\b", settings)
    assert not re.search(r"\bchannel 0\b", settings)
    assert re.search(r"(?<![\d.])50 Hz", settings)
    assert not re.search(r"(?<![\d.])60 Hz", settings)
    assert run.calls and {mains for _, _, mains in run.calls} == {50}
    for name, record in evaluation_fixture.mitdb.records.items():
        scored = record.tp + record.fn
        expected = ("0", str(scored), "0", percent_text(0, scored), "not defined")
        assert table.row(name)[2:] == expected, name


# --------------------------------------------------------------------------------------------
# Per-record and aggregate statistics (SRS-011)
# --------------------------------------------------------------------------------------------


def _expected_row(record: Any, percent_text: Callable[[int, int], str]) -> tuple[str, ...]:
    return (
        record.name,
        record.signal_names[0],
        str(record.tp),
        str(record.fn),
        str(record.fp),
        percent_text(record.tp, record.tp + record.fn),
        percent_text(record.tp, record.tp + record.fp),
    )


@pytest.mark.requirement("SRS-012")
def test_report_gives_the_statistics_of_every_record(
    standard_run: Run,
    evaluation_fixture: Any,
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
) -> None:
    """The per-record statistics of SRS-011, with values matching the fixture.

    Input: the report of the standard fixture (14 records, listed in its RECORDS file in
    decreasing order of name).
    Expected, in the table of the section "Results per record": one row per record, in
    increasing order of record name, then the rows "Gross" and "Average"; each record row is
    record, signal name, TP, FN, FP, Se (%), +P (%) as designed, e.g. 101: MLII, 117, 3, 1,
    97.50, 99.15; 104: V5, 114, 6, 6, 95.00, 95.00; 105: 0, 0, 5, not defined, 0.00; 106: 0,
    120, 0, 0.00, not defined; 207: 95, 0, 0, 100.00, 100.00.
    """
    table = parse_report(standard_run.text).section("results per record").table_with_row("100")
    records = evaluation_fixture.mitdb.records

    assert table.first_cells() == [*sorted(records), "Gross", "Average"]
    for name, record in records.items():
        assert table.row(name) == _expected_row(record, percent_text), name
    assert table.row("101") == ("101", "MLII", "117", "3", "1", "97.50", "99.15")
    assert table.row("104") == ("104", "V5", "114", "6", "6", "95.00", "95.00")
    assert table.row("105") == ("105", "MLII", "0", "0", "5", "not defined", "0.00")
    assert table.row("106") == ("106", "MLII", "0", "120", "0", "0.00", "not defined")
    assert table.row("207") == ("207", "MLII", "95", "0", "0", "100.00", "100.00")


@pytest.mark.requirement("SRS-012")
def test_report_gives_the_gross_and_average_statistics(
    standard_run: Run,
    evaluation_fixture: Any,
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
    mean_percent_text: Callable[[Sequence[tuple[int, int]]], str],
) -> None:
    """The aggregate statistics of SRS-011: gross from summed counts, average of defined values.

    Input: the report of the standard fixture: summed TP 1375, FN 134, FP 21; Se is not
    defined for record 105 and +P for record 106, so each average is over 13 of 14 records.
    Expected: the row "Gross" ends with 1375, 134, 21, 91.12, 98.50; the row "Average" ends
    with 91.41 (mean of the 13 defined Se) and 91.35 (mean of the 13 defined +P); a sentence
    of the section gives the 13 records of each average out of 14.
    """
    section = parse_report(standard_run.text).section("results per record")
    table = section.table_with_row("100")
    records = list(evaluation_fixture.mitdb.records.values())
    tp, fn, fp = (sum(getattr(r, key) for r in records) for key in ("tp", "fn", "fp"))
    se_pairs = [(r.tp, r.tp + r.fn) for r in records]
    ppv_pairs = [(r.tp, r.tp + r.fp) for r in records]

    # The fixture is the one described (checked with exact arithmetic).
    assert (tp, fn, fp) == (1375, 134, 21)
    assert (percent_text(tp, tp + fn), percent_text(tp, tp + fp)) == ("91.12", "98.50")
    assert (mean_percent_text(se_pairs), mean_percent_text(ppv_pairs)) == ("91.41", "91.35")

    assert table.row("Gross")[-5:] == ("1375", "134", "21", "91.12", "98.50")
    assert table.row("Average")[-2:] == ("91.41", "91.35")
    assert any(
        re.search(r"\b13\b", line) and re.search(r"\b14\b", line)
        for line in _non_table_lines(section)
    ), "no sentence gives the number of records in each average (13 of 14)"


# --------------------------------------------------------------------------------------------
# The records with the lowest Se and +P
# --------------------------------------------------------------------------------------------


def _ranking(report: Any, keyword: str) -> list[tuple[int, str, str]]:
    """(rank, record, value) of the first table of a ranking section."""
    tables = report.section(keyword).tables()
    assert tables, f"no table in the section {keyword!r}"
    return [(int(row[0].strip("#. ")), row[1], row[2]) for row in tables[0].rows]


@pytest.mark.requirement("SRS-012")
def test_report_ranks_the_five_records_with_the_lowest_sensitivity(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The five records with the lowest Se, ties ordered by record name.

    Input: the report of the standard fixture: Se 0.00 (106), 95.00 (104), 97.50 (101 and
    103, a tie), 98.33 (118), then 100.00 for the others; not defined for 105.
    Expected, in the section "Lowest sensitivity": 1. 106 0.00, 2. 104 95.00, 3. 101 97.50,
    4. 103 97.50, 5. 118 98.33; record 105 is not ranked.
    """
    ranking = _ranking(parse_report(standard_run.text), "lowest sensitivity")

    assert ranking == [
        (1, "106", "0.00"),
        (2, "104", "95.00"),
        (3, "101", "97.50"),
        (4, "103", "97.50"),
        (5, "118", "98.33"),
    ]


@pytest.mark.requirement("SRS-012")
def test_report_ranks_the_five_records_with_the_lowest_positive_predictivity(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The five records with the lowest +P, ties ordered by record name.

    Input: the report of the standard fixture: +P 0.00 (105), 95.00 (104), 97.10 (102 and
    119, a tie; 119 comes first in the RECORDS file), 99.15 (101), then 99.16 (118, sixth);
    not defined for 106.
    Expected, in the section "Lowest positive predictivity": 1. 105 0.00, 2. 104 95.00,
    3. 102 97.10, 4. 119 97.10, 5. 101 99.15; records 118 and 106 are not listed.
    """
    ranking = _ranking(parse_report(standard_run.text), "lowest positive predictivity")

    assert ranking == [
        (1, "105", "0.00"),
        (2, "104", "95.00"),
        (3, "102", "97.10"),
        (4, "119", "97.10"),
        (5, "101", "99.15"),
    ]


# --------------------------------------------------------------------------------------------
# Results rendered from given evaluation results
# --------------------------------------------------------------------------------------------

RENDER_MITDB = Database(
    slug="mitdb", version="1.0.0", title=MITDB_TITLE, checksum_list_sha256="0" * 64
)
RENDER_NSTDB = Database(
    slug="nstdb", version="1.0.0", title=NSTDB_TITLE, checksum_list_sha256="1" * 64
)
NOISE_STRESS_NAMES = (
    "118e24",
    "118e18",
    "118e12",
    "118e06",
    "118e00",
    "118e_6",
    "119e24",
    "119e18",
    "119e12",
    "119e06",
    "119e00",
    "119e_6",
)
SNR_DB = (24, 18, 12, 6, 0, -6)


def _evaluation(
    name: str,
    tp: int,
    fn: int,
    fp: int,
    *,
    fs_hz: float = 360.0,
    figures: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
    flutter_waves: int = 0,
) -> RecordEvaluation:
    """Evaluation results of one record: counts, (episodes, episodes from 5:00, samples
    from 5:00, reference beats not scored, detections not scored) and flutter waves outside
    the episodes."""
    episodes, scored, samples, reference, detections = figures
    return RecordEvaluation(
        record=name,
        signal_name="MLII",
        fs_hz=fs_hz,
        counts=RecordCounts(record=name, tp=tp, fn=fn, fp=fp),
        vf_episodes=episodes,
        vf_episodes_scored=scored,
        vf_samples_scored=samples,
        reference_excluded=reference,
        detections_excluded=detections,
        flutter_waves_outside_vf=flutter_waves,
    )


def _noise_stress() -> NoiseStressResults:
    """Noise stress results of 12 records with 50 TP, 1 FN and 1 FP each."""
    records = tuple(_evaluation(name, 50, 1, 1) for name in NOISE_STRESS_NAMES)
    by_snr = tuple(
        SnrStatistics(
            snr_db=snr,
            statistics=aggregate_statistics([records[i].counts, records[i + 6].counts]),
        )
        for i, snr in enumerate(SNR_DB)
    )
    return NoiseStressResults(
        nstdb=VerificationResult(database=RENDER_NSTDB, records=None, files=("RECORDS",)),
        records=records,
        by_snr=by_snr,
        clean=aggregate_statistics(
            [RecordCounts(record="118", tp=50, fn=0, fp=0), RecordCounts("119", 50, 0, 0)]
        ),
    )


RENDER_SOFTWARE = SoftwareIdentity(
    version="0.0.0.dev0",
    source_sha256="e" * 64,
    python="3.11",
    runtime=(("numpy", "2.0.0"), ("scipy", "1.0.0"), ("wfdb", "4.0.0")),
)


def _results(evaluations: Sequence[RecordEvaluation]) -> ValidationResults:
    """Validation results of the given MIT-BIH record evaluations, default settings, and a
    software identity made up by the test."""
    return ValidationResults(
        software=RENDER_SOFTWARE,
        settings=EvaluationSettings(),
        mitdb=VerificationResult(database=RENDER_MITDB, records=None, files=("RECORDS",)),
        records=tuple(sorted(evaluations, key=lambda e: e.record)),
        noise_stress=_noise_stress(),
        subset=False,
    )


@pytest.mark.requirement("SRS-012")
def test_ranking_lists_only_the_records_whose_value_is_defined(
    parse_report: Callable[[str], Any],
) -> None:
    """The rankings with fewer than five defined values (a case of the SRS-012 verification).

    SRS-012 (v0.6): the lowest-value lists are among the records whose value is defined,
    fewer than five if fewer records have a defined value.
    Input: rendered results of four records: 100 (TP 0, FN 0, FP 3: Se not defined, +P
    0.00), 101 (10, 0, 0: 100.00, 100.00), 102 (9, 1, 0: 90.00, 100.00), 103 (9, 1, 1:
    90.00, 90.00).
    Expected: lowest Se: 102 90.00, 103 90.00, 101 100.00 (three records; 100 not ranked);
    lowest +P: 100 0.00, 103 90.00, 101 100.00, 102 100.00 (four records; ties by record
    name).
    """
    results = _results(
        [
            _evaluation("100", 0, 0, 3),
            _evaluation("101", 10, 0, 0),
            _evaluation("102", 9, 1, 0),
            _evaluation("103", 9, 1, 1),
        ]
    )
    report = parse_report(render_full_report(results))

    assert _ranking(report, "lowest sensitivity") == [
        (1, "102", "90.00"),
        (2, "103", "90.00"),
        (3, "101", "100.00"),
    ]
    assert _ranking(report, "lowest positive predictivity") == [
        (1, "100", "0.00"),
        (2, "103", "90.00"),
        (3, "101", "100.00"),
        (4, "102", "100.00"),
    ]


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("counts", "empty", "ranked"),
    [
        pytest.param(
            [("100", 0, 0, 3), ("101", 0, 0, 1)],
            ("lowest sensitivity", "Se"),
            ("lowest positive predictivity", [(1, "100", "0.00"), (2, "101", "0.00")]),
            id="no-defined-se",
        ),
        pytest.param(
            [("100", 0, 2, 0), ("101", 0, 1, 0)],
            ("lowest positive predictivity", "+P"),
            ("lowest sensitivity", [(1, "100", "0.00"), (2, "101", "0.00")]),
            id="no-defined-ppv",
        ),
    ],
)
def test_ranking_is_empty_when_no_record_has_a_defined_value(
    counts: list[tuple[str, int, int, int]],
    empty: tuple[str, str],
    ranked: tuple[str, list[tuple[int, str, str]]],
    parse_report: Callable[[str], Any],
) -> None:
    """The lowest-value list when none of the records has a defined value.

    The limit of the SRS-012 case "fewer than five records whose Se, or +P, is defined": none.
    Input: rendered results of two records whose Se is not defined (TP 0, FN 0, FP 3 and 1:
    +P 0.00 for both); then of two records whose +P is not defined (TP 0, FN 2 and 1, FP 0:
    Se 0.00 for both).
    Expected: the list of the measure that is never defined ranks no record: its section has
    no table, and the paragraph of the documented format "No record has a defined Se." (or
    "+P"); the list of the other measure ranks both records, 100 then 101 (a tie, by record
    name).
    """
    results = _results([_evaluation(name, tp, fn, fp) for name, tp, fn, fp in counts])
    report = parse_report(render_full_report(results))
    keyword, measure = empty
    section = report.section(keyword)

    assert section.tables() == []
    assert f"No record has a defined {measure}." in _non_table_lines(section)
    assert not any(re.search(r"\b10[01]\b", line) for line in section.lines)
    assert _ranking(report, ranked[0]) == ranked[1]


# --------------------------------------------------------------------------------------------
# Pass or fail of the SRS-007 thresholds
# --------------------------------------------------------------------------------------------

_SE = re.compile(r"\bSe\b|sensitivity", re.IGNORECASE)
_PPV = re.compile(r"\+P|positive predictiv", re.IGNORECASE)
_OUTCOME = re.compile(r"\b(pass|fail)\b", re.IGNORECASE)


def _target_line(report: Any, measure: str) -> str:
    """The only line of the section "Performance targets" that gives the outcome for Se or
    for +P."""
    lines = [line for line in report.section("performance targets").lines if _OUTCOME.search(line)]
    if measure == "Se":
        chosen = [line for line in lines if _SE.search(line) and not _PPV.search(line)]
    else:
        chosen = [line for line in lines if _PPV.search(line)]
    assert len(chosen) == 1, f"{len(chosen)} lines give the outcome for {measure}: {lines}"
    return chosen[0]


def _check_target(line: str, value: str, outcome: str) -> None:
    """The line gives the value, the target of at least 99.50 and the outcome."""
    if value == "not defined":
        assert "not defined" in line, line
    else:
        assert re.search(rf"(?<![\d.]){re.escape(value)}(?!\d)", line), (value, line)
    assert re.search(r"≥\s*99\.50", line), line
    outcomes = {match.lower() for match in _OUTCOME.findall(line)}
    assert outcomes == {outcome}, (outcome, line)


@pytest.mark.requirement("SRS-012")
def test_report_gives_fail_for_each_threshold_not_met(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The pass or fail of each SRS-007 threshold: both failed.

    Input: the report of the standard fixture: gross Se 91.12%, gross +P 98.50% (1375 of
    1396, which rounds to 98.50 but is below 99.50%).
    Expected, in the section "Performance targets": gross Se 91.12, target ≥ 99.50, fail;
    gross +P 98.50, target ≥ 99.50, fail.
    """
    report = parse_report(standard_run.text)

    _check_target(_target_line(report, "Se"), "91.12", "fail")
    _check_target(_target_line(report, "+P"), "98.50", "fail")


@pytest.mark.requirement("SRS-012")
def test_report_gives_pass_for_each_threshold_met(
    no_episode_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The pass or fail of each SRS-007 threshold: both passed.

    Input: the report of the fixture without episodes: records 100, 118 and 119 with every
    scored beat detected and one false detection: TP 374, FN 0, FP 1.
    Expected: gross Se 100.00, pass; gross +P 99.73, pass; target ≥ 99.50 for both.
    """
    report = parse_report(no_episode_run.text)

    _check_target(_target_line(report, "Se"), "100.00", "pass")
    _check_target(_target_line(report, "+P"), "99.73", "pass")


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("counts", "se", "ppv"),
    [
        pytest.param((199, 1, 1), ("99.50", "pass"), ("99.50", "pass"), id="exactly-99.50"),
        pytest.param((198, 1, 1), ("99.50", "fail"), ("99.50", "fail"), id="99.497-shown-99.50"),
        pytest.param((9949, 51, 0), ("99.49", "fail"), ("100.00", "pass"), id="99.49-and-100"),
        pytest.param((10, 0, 0), ("100.00", "pass"), ("100.00", "pass"), id="no-error"),
        pytest.param((0, 3, 0), ("0.00", "fail"), ("not defined", "fail"), id="no-detection"),
        pytest.param((0, 0, 0), ("not defined", "fail"), ("not defined", "fail"), id="nothing"),
    ],
)
def test_threshold_outcome_is_decided_on_the_exact_counts(
    counts: tuple[int, int, int],
    se: tuple[str, str],
    ppv: tuple[str, str],
    parse_report: Callable[[str], Any],
) -> None:
    """The pass or fail around the 99.50% thresholds of SRS-007 ("at least 99.5%").

    SRS-012 (v0.6): a threshold whose value is not defined (SRS-011) is reported as fail; the
    cases `no-detection` (gross +P not defined) and `nothing` (gross Se and +P not defined)
    are the verification case "a gross Se or +P that is not defined".
    Input: rendered results of one record with the given TP, FN and FP (so the gross values
    are those of the record).
    Expected: exactly 99.50% passes; 198 of 199 (99.497%, shown as 99.50) fails; 99.49%
    fails; a value that is not defined is shown as "not defined" and fails; the value shown
    with two decimals.
    """
    tp, fn, fp = counts
    report = parse_report(render_full_report(_results([_evaluation("100", tp, fn, fp)])))

    _check_target(_target_line(report, "Se"), *se)
    _check_target(_target_line(report, "+P"), *ppv)


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("tp", "other", "met"),
    [
        pytest.param(199, 1, True, id="exactly-99.50"),
        pytest.param(9950, 50, True, id="exactly-99.50-large"),
        pytest.param(198, 1, False, id="99.497"),
        pytest.param(1989, 10, False, id="99.4997"),
        pytest.param(9949, 51, False, id="99.49"),
        pytest.param(1, 0, True, id="100"),
        pytest.param(0, 1, False, id="0"),
        pytest.param(0, 0, False, id="not-defined"),
    ],
)
def test_threshold_comparison_on_integer_counts(tp: int, other: int, met: bool) -> None:
    """The comparison with the 99.50% target, on the counts (TP and FN, or TP and FP).

    Input: TP and the other count (FN for Se, FP for +P).
    Expected: met when TP / (TP + other) is at least 99.5% exactly (199 of 200, 9950 of
    10000); not met just below (198 of 199, 1989 of 1999, 9949 of 10000), and not met when
    the value is not defined (0 of 0).
    """
    assert meets_target(tp, other) is met


# --------------------------------------------------------------------------------------------
# What was not scored because of ventricular flutter and fibrillation episodes
# --------------------------------------------------------------------------------------------


def _not_scored_row(record: Any) -> tuple[str, ...]:
    """The expected row of a record in the table of what was not scored."""
    return (
        record.name,
        str(record.vf_episodes),
        str(record.vf_episodes_scored),
        f"{record.vf_samples_scored / 360:.1f}",
        str(record.reference_excluded),
        str(record.detections_excluded),
    )


def _not_scored_table(run: Run, parse_report: Callable[[str], Any]) -> Any:
    return parse_report(run.text).section("segments not scored").table_with_row("207")


@pytest.mark.requirement("SRS-012")
def test_report_states_what_was_not_scored_for_each_record_with_an_episode(
    standard_run: Run, evaluation_fixture: Any, parse_report: Callable[[str], Any]
) -> None:
    """What was not scored because of ventricular flutter episodes, per record.

    Input: the report of the standard fixture; records 207 to 211 have episodes, the others
    none.
    Expected, in the section "Segments not scored": the documented sentence that the first
    5 min are not scored and that the figures cover the part of each record from 5:00 to its
    end, except the episodes in the record, counted over the whole record (architecture
    section 8.10, SRS-012 v0.6); a table with one row per record that has an episode, in
    order of record name (207 to 211 only): record, episodes in the record, episodes from
    5:00, duration from 5:00 (s, one decimal), reference beats not scored, detections not
    scored.
    """
    section = parse_report(standard_run.text).section("segments not scored")
    table = section.table_with_row("207")

    assert NOT_SCORED_SENTENCE in " ".join(_non_table_lines(section))
    assert table.first_cells() == list(VF_RECORDS)
    for name in VF_RECORDS:
        assert table.row(name) == _not_scored_row(evaluation_fixture.mitdb.records[name]), name


@pytest.mark.requirement("SRS-012")
def test_episode_before_5_minutes_counts_only_in_the_episodes_of_the_record(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The verification fixture of SRS-012: one episode ending before 5:00, one after it.

    Input: record 207 of the standard fixture: episode 1 from 36000 to 43200 (20 reference
    beats, 21 unpaired detections inside); episode 2 from 115200 to 124350 (25 reference
    beats and 2 unpaired detections inside; a third detection inside it is paired with a
    scored beat outside it).
    Expected: 2 episodes in the record (the whole record: the episode before 5:00 counts);
    1 from 5:00; the duration of the second episode, 9151 samples = 25.4 s; 25 reference
    beats and 2 detections not scored, those of the second episode only.
    """
    row = _not_scored_table(standard_run, parse_report).row("207")

    assert row == ("207", "2", "1", "25.4", "25", "2")


@pytest.mark.requirement("SRS-012")
def test_episode_that_contains_5_minutes_counts_from_5_minutes(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """An episode that contains 5:00 (a case of the SRS-012 verification, v0.6).

    Input: record 209 of the standard fixture: one episode from 107000 to 109000, with the
    reference beats 107100, 107460 and 107820 before 5:00 and 108180, 108540 and 108900 after;
    unpaired detections inside it at 107103, 107463 and 107823 before 5:00 and at 108543 and
    108903 after (and 108020, the detection dropped by the rule at 5:00: see the next test).
    Expected: 1 episode in the record, 1 from 5:00; duration from 5:00 to its offset,
    109000 - 108000 + 1 = 1001 samples = 2.8 s; 3 reference beats and 2 detections not scored
    (those at or after 5:00 only: counting the items before 5:00 would give 6 and 5).
    """
    row = _not_scored_table(standard_run, parse_report).row("209")

    assert row == ("209", "1", "1", "2.8", "3", "2")


@pytest.mark.requirement("SRS-012")
def test_detection_dropped_by_the_rule_at_5_minutes_is_not_counted(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The detection left unscored by the rule at 5:00 inside an episode (SRS-012 v0.6 case).

    Input: record 209 of the standard fixture: inside the episode from 107000 to 109000,
    detections at 108020 (the first after 5:00, within 150 ms of it, and the next detection
    is closer to the first scored beat 109260: dropped by the rule at 5:00 of SRS-008),
    108543 and 108903 (not paired).
    Expected: 2 detections not scored, in the report and in the results; the dropped one is
    not included (3 if it were).
    """
    row = _not_scored_table(standard_run, parse_report).row("209")
    evaluation = next(r for r in standard_run.results.records if r.record == "209")

    assert row[5] == "2"
    assert evaluation.detections_excluded == 2


@pytest.mark.requirement("SRS-012")
def test_duration_includes_the_onset_and_offset_samples(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The duration counts the samples of the onset and offset annotations.

    Input: record 208 of the standard fixture: 20 episodes after 5:00, each from an onset to
    an offset 360 samples later, one beat and one detection inside each.
    Expected: 20 episodes, 20 from 5:00, 20 x 361 = 7220 samples = 20.1 s (without the onset
    or the offset sample it would be 7200 samples, 20.0 s); 20 beats and 20 detections not
    scored.
    """
    row = _not_scored_table(standard_run, parse_report).row("208")

    assert row == ("208", "20", "20", "20.1", "20", "20")


@pytest.mark.requirement("SRS-012")
def test_episode_without_offset_lasts_until_the_end_of_the_record(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """An episode without an offset annotation lasts until the end of the record (SRS-008).

    Input: record 211 of the standard fixture (151200 samples): an onset at 140000 and no
    offset; 31 beats and 31 unpaired detections after it.
    Expected: 1 episode, 1 from 5:00, 151199 - 140000 + 1 = 11200 samples = 31.1 s; 31
    reference beats and 31 detections not scored.
    """
    row = _not_scored_table(standard_run, parse_report).row("211")

    assert row == ("211", "1", "1", "31.1", "31", "31")


@pytest.mark.requirement("SRS-012")
def test_record_whose_episodes_all_end_before_5_minutes_is_listed_with_zeros(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """A record with at least one episode, none of which reaches 5:00.

    Input: record 210 of the standard fixture: one episode from 36000 to 43200, with beats
    and detections inside.
    Expected: its row: 1 episode in the record, 0 from 5:00, duration 0.0 s, 0 reference
    beats and 0 detections not scored.
    """
    row = _not_scored_table(standard_run, parse_report).row("210")

    assert row == ("210", "1", "0", "0.0", "0", "0")


@pytest.mark.requirement("SRS-012")
def test_report_says_so_when_no_record_has_an_episode(
    no_episode_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The statement given instead of the figures when no record has an episode.

    Input: the report of the fixture without episodes (records 100, 118, 119).
    Expected, in the section "Segments not scored": "No ventricular flutter or fibrillation
    episode is annotated in these records." and no table.
    """
    section = parse_report(no_episode_run.text).section("segments not scored")

    assert NO_EPISODE_SENTENCE in " ".join(_non_table_lines(section))
    assert section.tables() == []


@pytest.mark.requirement("SRS-012")
def test_flutter_waves_outside_episodes_are_counted(
    standard_run: Run, no_episode_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The count of flutter-wave annotations outside the episodes (architecture 8.8, 8.10).

    A design figure of the section on what is not scored: the `!` annotations from 5:00 to
    the end of each record that lie outside every episode, summed over the records.
    Input: the standard fixture (a flutter wave `!` inside an episode of record 207, after
    5:00; in record 210, one at 60090, before 5:00, and one at 120240, after 5:00, both
    outside any episode) and the fixture without episodes (none).
    Expected: "Flutter-wave annotations outside ventricular flutter and fibrillation
    episodes, in all records: 1." (only the one at 120240 in record 210) and, for the fixture
    without episodes, ": 0.".
    """
    standard = parse_report(standard_run.text).section("segments not scored")
    no_episode = parse_report(no_episode_run.text).section("segments not scored")

    assert FLUTTER_SENTENCE.format(n=1) in " ".join(_non_table_lines(standard))
    assert FLUTTER_SENTENCE.format(n=0) in " ".join(_non_table_lines(no_episode))


@pytest.mark.requirement("SRS-012")
def test_duration_is_given_at_the_sampling_frequency_of_each_record(
    parse_report: Callable[[str], Any],
) -> None:
    """The duration from 5:00 is the number of samples over the sampling frequency.

    Input: rendered results of three records with episodes: 100 at 250 Hz with 13 samples
    from 5:00 (0.052 s), 101 at 250 Hz with 12 samples (0.048 s), 102 at 360 Hz with 9151
    samples (25.42 s).
    Expected: durations 0.1, 0.0 and 25.4 s.
    """
    results = _results(
        [
            _evaluation("100", 10, 0, 0, fs_hz=250.0, figures=(1, 1, 13, 0, 0)),
            _evaluation("101", 10, 0, 0, fs_hz=250.0, figures=(1, 1, 12, 0, 0)),
            _evaluation("102", 10, 0, 0, figures=(2, 1, 9151, 25, 2)),
        ]
    )
    table = parse_report(render_full_report(results)).section("segments not scored")

    rows = table.table_with_row("100")
    assert rows.row("100")[3] == "0.1"
    assert rows.row("101")[3] == "0.0"
    assert rows.row("102") == ("102", "2", "1", "25.4", "25", "2")


@pytest.mark.requirement("SRS-012")
def test_evaluation_results_carry_the_figures_of_every_record(
    standard_run: Run, evaluation_fixture: Any
) -> None:
    """The evaluation results that the report is rendered from, per record.

    Input: the evaluation results of the standard fixture.
    Expected: one result per record, in order of record name, each with the signal name, the
    sampling frequency (360 Hz), TP, FN, FP, the episodes in the record, the episodes from
    5:00, the samples from 5:00 inside an episode, the reference beats and the detections not
    scored, and the flutter waves outside the episodes, as designed; the whole database
    verified (every listed file, no record selection).
    """
    results = standard_run.results
    records = evaluation_fixture.mitdb.records

    assert [r.record for r in results.records] == sorted(records)
    for evaluation in results.records:
        record = records[evaluation.record]
        assert evaluation.signal_name == record.signal_names[0]
        assert evaluation.fs_hz == 360.0
        assert (evaluation.counts.tp, evaluation.counts.fn, evaluation.counts.fp) == (
            record.tp,
            record.fn,
            record.fp,
        ), record.name
        assert (
            evaluation.vf_episodes,
            evaluation.vf_episodes_scored,
            evaluation.vf_samples_scored,
            evaluation.reference_excluded,
            evaluation.detections_excluded,
            evaluation.flutter_waves_outside_vf,
        ) == (
            record.vf_episodes,
            record.vf_episodes_scored,
            record.vf_samples_scored,
            record.reference_excluded,
            record.detections_excluded,
            record.flutter_waves_outside_vf,
        ), record.name
    assert results.mitdb.records is None
    assert len(results.mitdb.files) == evaluation_fixture.mitdb.n_listed_files
    assert results.subset is False


def _record(
    *,
    beats: Sequence[int],
    detections: Sequence[int],
    others: Sequence[tuple[int, str]],
    n_samples: int = 151200,
    fs_hz: float = 360.0,
) -> Record:
    """A record (360 Hz by default) whose channel has a 1 mV spike at each detection sample."""
    signal = np.zeros(n_samples, dtype=np.float64)
    signal[list(detections)] = 1.0
    return Record(
        name="900",
        channel=0,
        signal_name="MLII",
        fs_hz=fs_hz,
        signal_mv=signal,
        beat_samples=np.asarray(beats, dtype=np.int64),
        beat_symbols=tuple("N" for _ in beats),
        other_annotations=tuple(
            Annotation(sample=sample, symbol=symbol, subtype=0, aux_note="")
            for sample, symbol in others
        ),
    )


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("others", "beats", "detections", "n_samples", "expected"),
    [
        pytest.param(
            [(100000, "["), (107999, "]")],
            [100180, 107900, 110000],
            [100183, 107903, 110003],
            151200,
            (1, 0, 0, 1, 0, 0, 0, 0),
            id="ends-one-sample-before-5min",
        ),
        pytest.param(
            [(100000, "["), (108000, "]")],
            [108000, 110000],
            [110003],
            151200,
            (1, 0, 0, 1, 1, 1, 1, 0),
            id="ends-at-5min",
        ),
        pytest.param(
            [(108000, "["), (108359, "]")],
            [108180, 108540],
            [108183, 108543],
            151200,
            (1, 0, 0, 1, 1, 360, 1, 1),
            id="starts-at-5min",
        ),
        pytest.param(
            [(140000, "[")],
            [120000, 140180],
            [120003, 140183],
            151200,
            (1, 0, 0, 1, 1, 11200, 1, 1),
            id="no-offset",
        ),
        pytest.param(
            [(150000, "["), (151300, "]")],
            [120000],
            [120003],
            151200,
            (1, 0, 0, 1, 1, 1200, 0, 0),
            id="offset-after-the-end-of-the-record",
        ),
        pytest.param(
            [(115000, "["), (120000, "]"), (120000, "["), (121000, "]")],
            [110000, 120000],
            [110003],
            151200,
            (1, 0, 0, 2, 2, 6001, 1, 0),
            id="two-episodes-sharing-a-sample",
        ),
        pytest.param(
            [(50000, "["), (60000, "]"), (120000, "["), (123000, "]")],
            [52000, 55000, 110000, 120500, 121500, 140000],
            [57000, 110003, 122000, 140003],
            151200,
            (2, 0, 0, 2, 1, 3001, 2, 1),
            id="one-before-and-one-after-5min",
        ),
        pytest.param(
            [(100000, "[")],
            [100180],
            [100183],
            108000,
            (0, 0, 0, 1, 0, 0, 0, 0),
            id="record-of-exactly-5min",
        ),
        pytest.param([], [110000], [110003], 151200, (1, 0, 0, 0, 0, 0, 0, 0), id="no-episode"),
        pytest.param(
            [(107000, "["), (109000, "]")],
            [107100, 107460, 108180, 108540, 110000],
            [107103, 107463, 108183, 108543, 110003],
            151200,
            (1, 0, 0, 1, 1, 1001, 2, 2),
            id="contains-5min",
        ),
        pytest.param(
            [(107000, "["), (109000, "]")],
            [110000],
            [108020, 110000],
            151200,
            (1, 0, 0, 1, 1, 1001, 0, 0),
            id="dropped-at-5min-inside-an-episode",
        ),
        pytest.param(
            [(107000, "[")],
            [108180],
            [108020, 108183],
            151200,
            (0, 0, 0, 1, 1, 43200, 1, 1),
            id="dropped-at-5min-no-scored-beat",
        ),
        pytest.param(
            [(0, "["), (1000, "]"), (50000, "["), (60000, "]"), (120000, "["), (121000, "]")],
            [500, 55000, 110000, 120500],
            [503, 55003, 110003, 120503],
            151200,
            (1, 0, 0, 3, 1, 1001, 1, 1),
            id="episodes-over-the-whole-record",
        ),
    ],
)
def test_figures_of_what_was_not_scored_are_counted_from_5_minutes(
    others: list[tuple[int, str]],
    beats: list[int],
    detections: list[int],
    n_samples: int,
    expected: tuple[int, ...],
    make_spike_detector: Callable[[], Any],
) -> None:
    """The figures of one record around 5:00 and around the limits of its episodes.

    Input: a record at 360 Hz (5:00 = sample 108000) with the given episodes (onset `[`,
    offset `]`), reference beats and detections (spikes found by the detector double),
    evaluated with the default settings:
    - an episode ending one sample before 5:00: in the episodes of the record only;
    - an episode ending at 5:00, with a beat on that sample: 1 from 5:00, 1 sample, 1 beat;
    - an episode starting at 5:00, 360 samples long, with a beat and a detection inside;
    - an episode without an offset from 140000: to the end of the record, 11200 samples;
    - an offset beyond the end of the record: counted to the last sample, 1200 samples;
    - two episodes sharing the sample 120000 (offset of the first, onset of the second): the
      shared sample counted once, 5001 + 1001 - 1 = 6001 samples, the beat on it once;
    - one episode ending before 5:00 and one after it (the verification configuration);
    - a record of exactly 5 min with an episode: no scored part, nothing from 5:00;
    - no episode;
    - an episode from 107000 to 109000, which contains 5:00, with the beats 107100 and 107460
      and unpaired detections 3 samples after them before 5:00, and the beats 108180 and
      108540 and unpaired detections 3 samples after them from 5:00; a scored beat at 110000
      and its detection: only the 2 beats and 2 detections from 5:00 counted (SRS-012 v0.6);
    - the same episode, a first scored beat at 110000 and detections at 108020 and 110000:
      108020 is dropped by the rule at 5:00 of SRS-008 (the next detection is closer to the
      first scored beat) and is not counted although it lies inside the episode;
    - an episode from 107000 without an offset, the beat 108180 inside it (so no reference
      beat is scored) and detections at 108020 and 108183: 108020 is dropped by the rule at
      5:00 (no reference beat is scored) and not counted, 108183 is counted; the episode lasts
      from 5:00 to the last sample, 151199 - 108000 + 1 = 43200 samples;
    - three episodes, from sample 0 (the first sample of the record) to 1000, from 50000 to
      60000 and from 120000 to 121000, each with a beat and a detection inside: all three are
      episodes in the record (the whole record, SRS-012 v0.6); only the last one is from 5:00,
      with its beat and its detection.
    Expected: (TP, FN, FP, episodes in the record, episodes from 5:00, samples from 5:00
    inside an episode, reference beats not scored, detections not scored) as given.
    """
    record = _record(beats=beats, detections=detections, others=others, n_samples=n_samples)

    result = evaluate_record(record, EvaluationSettings(), detector=make_spike_detector())

    assert result.record == "900"
    assert (
        result.counts.tp,
        result.counts.fn,
        result.counts.fp,
        result.vf_episodes,
        result.vf_episodes_scored,
        result.vf_samples_scored,
        result.reference_excluded,
        result.detections_excluded,
    ) == expected


@pytest.mark.requirement("SRS-012")
def test_sample_shared_by_two_episodes_is_counted_once(
    make_spike_detector: Callable[[], Any], parse_report: Callable[[str], Any]
) -> None:
    """Two episodes that share a sample (a case of the SRS-012 verification, v0.6).

    At 250 Hz one sample changes the duration shown with one decimal here, which it cannot
    do at 360 Hz (every rounding limit of 0.1 s falls on a whole sample there).
    Input: a record of 7 min at 250 Hz (105000 samples; 5:00 = sample 75000, match window
    37 samples) with an episode from 80000 to 81500 and one from 81500 to 82511 (the offset
    of the first and the onset of the second on the same sample); reference beats at 78000,
    81500 (the shared sample) and 90000; detections (spikes) at 78002, 81500 and 90002. The
    record is evaluated with the default settings and its results rendered as the report.
    Expected: TP 2, FN 0, FP 0; 2 episodes in the record and 2 from 5:00; 82511 - 80000 + 1 =
    2512 samples inside an episode, the shared sample counted once, shown as 10.0 s (2512 /
    250 = 10.048; counted twice, 2513 samples would show 10.1 s); the beat and the detection
    on the shared sample counted once each: 1 reference beat and 1 detection not scored.
    """
    record = _record(
        beats=[78000, 81500, 90000],
        detections=[78002, 81500, 90002],
        others=[(80000, "["), (81500, "]"), (81500, "["), (82511, "]")],
        n_samples=105000,
        fs_hz=250.0,
    )

    evaluation = evaluate_record(record, EvaluationSettings(), detector=make_spike_detector())
    report = parse_report(render_full_report(_results([evaluation])))
    row = report.section("segments not scored").table_with_row("900").row("900")

    assert (evaluation.counts.tp, evaluation.counts.fn, evaluation.counts.fp) == (2, 0, 0)
    assert (evaluation.vf_episodes, evaluation.vf_episodes_scored) == (2, 2)
    assert evaluation.vf_samples_scored == 2512
    assert (evaluation.reference_excluded, evaluation.detections_excluded) == (1, 1)
    assert row == ("900", "2", "2", "10.0", "1", "1")


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("others", "counted"),
    [
        pytest.param([(60090, "!")], 0, id="before-5min"),
        pytest.param([(107999, "!")], 0, id="one-sample-before-5min"),
        pytest.param([(108000, "!")], 1, id="at-5min"),
        pytest.param([(120240, "!")], 1, id="after-5min"),
        pytest.param([(151199, "!")], 1, id="on-the-last-sample"),
        pytest.param([(151200, "!")], 0, id="after-the-last-sample"),
        pytest.param([(119999, "!"), (120000, "["), (121000, "]")], 1, id="before-an-onset"),
        pytest.param([(120000, "["), (120000, "!"), (121000, "]")], 0, id="on-the-onset"),
        pytest.param([(120000, "["), (120500, "!"), (121000, "]")], 0, id="inside-an-episode"),
        pytest.param([(120000, "["), (121000, "!"), (121000, "]")], 0, id="on-the-offset"),
        pytest.param([(120000, "["), (121000, "]"), (121001, "!")], 1, id="after-an-offset"),
        pytest.param(
            [(107000, "["), (108500, "!"), (109000, "]")], 0, id="inside-an-episode-over-5min"
        ),
        pytest.param([(140000, "["), (151199, "!")], 0, id="inside-an-episode-without-offset"),
        pytest.param(
            [(50000, "["), (55000, "!"), (60000, "]")], 0, id="inside-an-episode-before-5min"
        ),
        pytest.param(
            [
                (60090, "!"),
                (107999, "!"),
                (108000, "!"),
                (120000, "["),
                (120500, "!"),
                (121000, "]"),
                (130000, "!"),
                (151199, "!"),
            ],
            3,
            id="several",
        ),
    ],
)
def test_flutter_waves_are_counted_from_5_minutes_outside_every_episode(
    others: list[tuple[int, str]], counted: int, make_spike_detector: Callable[[], Any]
) -> None:
    """The limits of the count of flutter waves outside the episodes (a design figure).

    Architecture sections 8.8 and 8.10: the report counts the `!` annotations from 5:00 to
    the last sample of the record (the scored part, the only part where a `!` could change a
    count) that lie outside every episode; a `!` on the onset or the offset sample of an
    episode is inside it. A `!` is not a reference beat.
    Input: a record of 7 min at 360 Hz (151200 samples, 5:00 = sample 108000) with a beat at
    110000 and its detection at 110003, and the given `!` and episode annotations: a `!`
    before 5:00, one sample before it, at 5:00, after it, on the last sample (151199), one
    sample after it (an annotation beyond the end of the signal is kept by the loader); one
    sample before the onset of an episode from 120000 to 121000, on its onset, inside it, on
    its offset, one sample after it; inside an episode that contains 5:00, inside an episode
    without an offset, inside an episode before 5:00; eight annotations together.
    Expected: TP 1, FN 0, FP 0 in every case; flutter waves outside the episodes: 1 for a
    `!` outside every episode from 108000 to 151199, 0 otherwise; 3 for the eight together
    (108000, 130000 and 151199).
    """
    record = _record(beats=[110000], detections=[110003], others=others)

    result = evaluate_record(record, EvaluationSettings(), detector=make_spike_detector())

    assert (result.counts.tp, result.counts.fn, result.counts.fp) == (1, 0, 0)
    assert result.flutter_waves_outside_vf == counted


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("evaluations", "total", "with_episodes"),
    [
        pytest.param(
            [
                _evaluation("100", 10, 0, 0, flutter_waves=2),
                _evaluation("101", 10, 0, 0),
                _evaluation("102", 10, 0, 0, figures=(1, 1, 360, 1, 1), flutter_waves=3),
            ],
            5,
            True,
            id="with-episodes",
        ),
        pytest.param(
            [_evaluation("100", 10, 0, 0, flutter_waves=1), _evaluation("101", 10, 0, 0)],
            1,
            False,
            id="without-episodes",
        ),
    ],
)
def test_report_gives_the_flutter_waves_of_all_records(
    evaluations: list[RecordEvaluation],
    total: int,
    with_episodes: bool,
    parse_report: Callable[[str], Any],
) -> None:
    """The flutter-wave sentence gives the sum over the records (a design figure, 8.10).

    Input: rendered results of three records with 2, 0 and 3 flutter waves outside the
    episodes, one of which has an episode; then of two records with 1 and 0 flutter waves and
    no episode.
    Expected: "Flutter-wave annotations outside ventricular flutter and fibrillation
    episodes, in all records: 5." after the table, and ": 1." after the sentence that no
    record has an episode; the introduction sentence of the section in both reports.
    """
    section = parse_report(render_full_report(_results(evaluations))).section("segments not scored")
    text = " ".join(_non_table_lines(section))

    assert NOT_SCORED_SENTENCE in text
    assert FLUTTER_SENTENCE.format(n=total) in text
    assert (NO_EPISODE_SENTENCE in text) is not with_episodes
    assert bool(section.tables()) is with_episodes


# --------------------------------------------------------------------------------------------
# No report when the verification of the database fails
# --------------------------------------------------------------------------------------------


def _flip_one_bit(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))


def _damage(folder: Path, kind: str, altered: str, missing: str) -> None:
    """Alter a fixture database folder."""
    checksum_list = folder / "SHA256SUMS.txt"
    if kind == "file-altered-and-file-missing":
        _flip_one_bit(folder / altered)
        (folder / missing).unlink()
    elif kind == "checksum-list-missing":
        checksum_list.unlink()
    elif kind == "checksum-list-altered":
        checksum_list.write_bytes(checksum_list.read_bytes() + b"0" * 64 + b" extra.dat\n")
    else:
        raise AssertionError(kind)


DAMAGES = [
    pytest.param("file-altered-and-file-missing", id="one-file-altered-one-missing"),
    pytest.param("checksum-list-missing", id="checksum-list-missing"),
    pytest.param("checksum-list-altered", id="checksum-list-altered"),
]


def _expected_names(kind: str, altered: str, missing: str) -> tuple[tuple[str, ...], ...]:
    """(missing, mismatched) named by the error for a damage."""
    return {
        "file-altered-and-file-missing": ((missing,), (altered,)),
        "checksum-list-missing": (("SHA256SUMS.txt",), ()),
        "checksum-list-altered": ((), ("SHA256SUMS.txt",)),
    }[kind]


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize("kind", DAMAGES)
def test_no_report_is_written_when_the_reference_database_is_not_verified(
    kind: str,
    tmp_path: Path,
    evaluation_fixture: Any,
    copy_evaluation_fixture: Callable[[Any, Path], Any],
    make_spike_detector: Callable[[], Any],
) -> None:
    """A fixture MIT-BIH database that fails its SRS-001 verification.

    Input: a copy of the standard fixture with, in the MIT-BIH database, record file 118.dat
    altered by one bit and 100.atr deleted; or its checksum list deleted; or its checksum
    list altered. The report is requested at a path that holds a previous report, and at a
    path where no file exists.
    Expected: each request raises `DataVerificationError` for "mitdb 1.0.0", naming the
    missing and the altered files; the previous report is unchanged, no report is written at
    the other path, and nothing else is written in the output folder; the detector is never
    called (the database is verified before any evaluation).
    """
    fixture = copy_evaluation_fixture(evaluation_fixture, tmp_path / "data")
    _damage(fixture.mitdb.folder.folder, kind, altered="118.dat", missing="100.atr")
    mitdb, nstdb = _databases(fixture)
    output = tmp_path / "out"
    output.mkdir()
    (output / "previous.md").write_bytes(b"previous report\n")
    detector = make_spike_detector()

    for name in ("previous.md", "new.md"):
        with pytest.raises(DataVerificationError) as excinfo:
            write_validation_report(
                output / name,
                fixture.data_root,
                mitdb=mitdb,
                nstdb=nstdb,
                detector=detector,
                fetch=None,
            )
        assert excinfo.value.database == "mitdb 1.0.0"
        assert (excinfo.value.missing, excinfo.value.mismatched) == _expected_names(
            kind, "118.dat", "100.atr"
        )

    assert sorted(p.name for p in output.iterdir()) == ["previous.md"]
    assert (output / "previous.md").read_bytes() == b"previous report\n"
    assert detector.calls == []


@pytest.mark.requirement("SRS-012")
def test_no_report_is_written_when_the_download_leaves_the_database_not_verified(
    tmp_path: Path,
    evaluation_fixture: Any,
    copy_evaluation_fixture: Callable[[Any, Path], Any],
    make_spike_detector: Callable[[], Any],
    make_fake_fetch: Callable[[dict[str, bytes]], Any],
) -> None:
    """The report requested with download, when a missing file cannot be obtained.

    Input: a copy of the standard fixture without the MIT-BIH file 101.dat; a fetch function
    that serves nothing (every request fails).
    Expected: the software asks for https://physionet.org/files/mitdb/1.0.0/101.dat, then
    raises `DataVerificationError` naming 101.dat as missing; no report is written; the
    detector is never called.
    """
    fixture = copy_evaluation_fixture(evaluation_fixture, tmp_path / "data")
    (fixture.mitdb.folder.folder / "101.dat").unlink()
    mitdb, nstdb = _databases(fixture)
    fetch = make_fake_fetch({})
    detector = make_spike_detector()
    output = tmp_path / "out" / "report.md"
    output.parent.mkdir()

    with pytest.raises(DataVerificationError) as excinfo:
        write_validation_report(
            output, fixture.data_root, mitdb=mitdb, nstdb=nstdb, detector=detector, fetch=fetch
        )

    assert "https://physionet.org/files/mitdb/1.0.0/101.dat" in fetch.calls
    assert excinfo.value.missing == ("101.dat",)
    assert list(output.parent.iterdir()) == []
    assert detector.calls == []


def _run_command(
    driver: Path, pins: tuple[str, str], arguments: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(driver), *pins, str(VALIDATE_SCRIPT), *arguments],
        cwd=cwd,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize("data", ["empty-data-folder", "fixture-data"])
def test_command_writes_no_report_when_the_database_is_not_verified(
    data: str,
    tmp_path: Path,
    evaluation_fixture: Any,
    write_command_driver: Callable[[Path], Path],
) -> None:
    """The validation command, when the reference database is not verified.

    Input: `validate.py --offline --data-dir <folder> --output <path>`, run in a separate
    process without network, with the real pinned checksum lists, on an empty data folder,
    or on the standard fixture (whose checksum list is not the published one); the output
    path holds a previous report.
    Expected: exit status 1; on standard error, a message that the database is not verified,
    naming SHA256SUMS.txt, and no traceback; the previous report is unchanged and nothing
    else is written in its folder.
    """
    if data == "empty-data-folder":
        data_root = tmp_path / "data"
        data_root.mkdir()
    else:
        data_root = evaluation_fixture.data_root
    output = tmp_path / "out" / "qrs-ec57-report.md"
    output.parent.mkdir()
    output.write_bytes(b"previous report\n")
    driver = write_command_driver(tmp_path)

    completed = _run_command(
        driver,
        ("-", "-"),
        ["--offline", "--data-dir", str(data_root), "--output", str(output)],
        cwd=tmp_path,
    )

    assert completed.returncode == 1, completed.stderr
    assert "not verified" in completed.stderr
    assert "SHA256SUMS.txt" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert output.read_bytes() == b"previous report\n"
    assert [p.name for p in output.parent.iterdir()] == [output.name]


# --------------------------------------------------------------------------------------------
# Layout of the report
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-012")
def test_report_sections_follow_the_documented_order(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The report layout of architecture section 8.10.

    Input: the report of the standard fixture.
    Expected: the first line is the title "# QRS detection: EC57 beat-by-beat evaluation";
    the sections "Software, data and settings", "Performance targets", "Results per
    record", "Lowest sensitivity", "Lowest positive predictivity", "Segments not scored" and
    "Noise stress test" come in this order.
    """
    report = parse_report(standard_run.text)
    order = [
        "software, data and settings",
        "performance targets",
        "results per record",
        "lowest sensitivity",
        "lowest positive predictivity",
        "segments not scored",
        "noise stress test",
    ]
    positions = []
    for keyword in order:
        matches = [i for i, _, title in report.headings if keyword in title.casefold()]
        assert matches, f"no section {keyword!r}; headings: {report.titles()}"
        positions.append(matches[0])

    assert report.lines[0] == "# QRS detection: EC57 beat-by-beat evaluation"
    assert positions == sorted(positions)
