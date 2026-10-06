"""Requirement tests of SRS-015: the golden-vector files of the export (RC-012).

SRS-015 (v0.7.2): one golden-vector file for each synthetic input (2 sampling frequencies x
3 heart rates x 3 variants) and for the first 60 s of each record of the subset of SRS-016
(first stored signal), "if the files of all these records are available and verified against
the checksum list of SRS-001; otherwise, none of these record segments". Each file contains
an identifier of the input, its sampling frequency in Hz, the settings used (mains
frequency), the software version with an identifier of the source code, the input samples in
mV, the output of each conditioning stage of SRS-004 and SRS-005 in the order applied, and
the detected QRS sample indices of SRS-006, in the format documented in `architecture.md`.
Numbers read back give exactly the values computed. Two runs on the same computer and
inputs, with the same software and third-party versions, give byte-identical files.

The cases of the verification of SRS-015 and their tests (the command itself is run in
`test_srs_015_export_command.py`):
- two runs on the synthetic set and on fixture records give byte-identical outputs:
  `test_two_runs_give_byte_identical_files`,
  `test_same_inputs_in_another_data_folder_give_identical_files`;
- every file contains each listed item: `test_file_contains_each_listed_item`, with the format
  of architecture section 7.3 read by the test's own reader
  (`test_file_follows_the_documented_format`);
- the software version and the source identifier are those of the software under test,
  checked as for SRS-012: `test_file_states_the_software_under_test` (identifier computed by
  the test with the method of architecture section 8.14);
- the set of files matches the list: `test_export_writes_one_file_per_listed_input` (18
  synthetic files and 6 record segments), "also when a file of one of the records fails
  verification": `test_record_segments_are_skipped_when_the_records_are_not_verified` (one
  file of one record altered or missing, or one record without any file, while the files of
  the five others are verified: 18 files only, none of the six segments, as the clause "all
  or none" of v0.7.2 requires), and
  `test_record_segments_need_only_the_files_of_the_six_records`;
- the values read back equal the outputs of the conditioning and detection functions called
  directly on the same input: `test_values_read_back_equal_the_functions_called_directly`,
  `test_input_is_that_of_the_generator_or_of_the_record`, and the reader of the software in
  `test_reader_of_the_software_reads_back_the_same_values`.

Inputs: `export_golden_vectors(output_dir, data_root=..., database=<fixture Database>)` with
the default record selection (the subset of SRS-016), on fixture databases written by the
test (`conftest.py`): six records named as the subset, at least 60 s long, with a checksum
list pinned in the fixture `Database`; `subset_ecg_fixture` (6-min synthetic ECGs at 360 Hz,
channel 1 flat) and, for the limits of the segment, a database written in this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sinus_dsp.data.physionet import Database, DatabaseLicence
from sinus_dsp.data.records import load_record
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.filters import (
    baseline_sos,
    mains_sos,
    remove_baseline_wander,
    remove_mains_interference,
)
from sinus_dsp.golden import GOLDEN_FILE_SUFFIX, export_golden_vectors, read_golden_vector
from sinus_dsp.pipeline import detect_beats, run_pipeline
from sinus_dsp.qrs import detect_qrs
from sinus_dsp.synthetic import synthetic_ecg

pytestmark = pytest.mark.usefixtures("forbid_network")

SUBSET = ("100", "105", "108", "119", "203", "207")
SYNTHETIC = tuple(
    (fs, hr, variant)
    for fs in (250, 360)
    for hr in (40, 75, 180)
    for variant in ("clean", "bw-mains50", "bw-mains60")
)
SYNTHETIC_IDS = tuple(f"syn-fs{fs}-hr{hr:03d}-{variant}" for fs, hr, variant in SYNTHETIC)
SEGMENT_IDS = tuple(f"mitdb-{name}-first60s" for name in SUBSET)
ALL_IDS = SYNTHETIC_IDS + SEGMENT_IDS
SUFFIX = ".golden.txt"
QUANTIZATION_MV = 1 / 200  # one step of the fixture records (gain 200 per mV)
WAVEFORM_TOLERANCE_MV = 1e-9


# A licence of the fixture database: the `Database` has no default for it (architecture,
# section 8.3). A golden-vector file does not state it (section 7.3).
FIXTURE_LICENCE = DatabaseLicence(
    name="Fixture Data Licence 1.0", url="https://licences.example.org/fixture/1-0/"
)


def _database(pin: str) -> Database:
    """MIT-BIH Arrhythmia Database 1.0.0 pinned to a fixture checksum list."""
    return Database(
        slug="mitdb",
        version="1.0.0",
        title="MIT-BIH Arrhythmia Database",
        checksum_list_sha256=pin,
        licence=FIXTURE_LICENCE,
    )


def _segment_parameters(name: str) -> str:
    return (
        f"database=mitdb;database_version=1.0.0;record={name};signal=0;start_sample=0;duration_s=60"
    )


def _synthetic_of(input_id: str) -> tuple[int, int, str]:
    return SYNTHETIC[SYNTHETIC_IDS.index(input_id)]


def _files(folder: Path) -> dict[str, bytes]:
    """Every entry of ``folder`` (name -> bytes); a folder among them fails the test."""
    entries = sorted(folder.iterdir())
    assert all(entry.is_file() for entry in entries), entries
    return {entry.name: entry.read_bytes() for entry in entries}


def _same_float64(a: Any, b: Any) -> bool:
    """Bitwise equality of two float64 arrays (so -0.0 differs from 0.0)."""
    x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return x.shape == y.shape and x.tobytes() == y.tobytes()


class Export:
    """One run of the export: its summary and the files of its output folder."""

    def __init__(self, folder: Path, summary: Any) -> None:
        self.folder = folder
        self.summary = summary
        self.files = _files(folder)


@pytest.fixture(scope="module")
def two_exports(
    subset_ecg_fixture: Any,
    network_forbidden: Callable[[], Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Export, Export]:
    """Two runs of the export on the synthetic ECG subset fixture, into two new folders."""
    database = _database(subset_ecg_fixture.checksum_list_sha256)
    runs = []
    with network_forbidden():
        for name in ("srs015-export-a", "srs015-export-b"):
            folder = tmp_path_factory.mktemp(name) / "golden"
            summary = export_golden_vectors(
                folder, data_root=subset_ecg_fixture.data_root, database=database
            )
            runs.append(Export(folder, summary))
    return runs[0], runs[1]


@pytest.fixture(scope="module")
def parsed(
    two_exports: tuple[Export, Export], read_golden_file: Callable[[bytes], Any]
) -> dict[str, Any]:
    """The files of the first run read by the test (input id -> file)."""
    return {
        name.removesuffix(SUFFIX): read_golden_file(data)
        for name, data in two_exports[0].files.items()
        if name.endswith(SUFFIX)
    }


# --------------------------------------------------------------------------------------------
# The set of files and byte identity
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-015")
def test_export_writes_one_file_per_listed_input(two_exports: tuple[Export, Export]) -> None:
    """The export writes one file for each input of the list, and nothing else.

    Input: the export on the synthetic ECG subset fixture (the six records named as the
    subset of SRS-016, their files verified against the fixture checksum list), into a new
    folder.
    Expected: the folder holds exactly 24 files, `<input id>.golden.txt` for the 18 synthetic
    identifiers `syn-fs<fs>-hr<hr>-<variant>` and the 6 identifiers `mitdb-<record>-first60s`
    of records 100, 105, 108, 119, 203 and 207 (no temporary file, no subfolder);
    `GOLDEN_FILE_SUFFIX` is `.golden.txt`; the summary lists the 24 names in the order
    written (synthetic inputs in the order of the set, then the records in code-point order)
    and nothing skipped (`skipped` empty, `skip_reason` None).
    """
    run = two_exports[0]
    expected = [input_id + SUFFIX for input_id in ALL_IDS]

    assert GOLDEN_FILE_SUFFIX == SUFFIX
    assert sorted(run.files) == sorted(expected)
    assert list(run.summary.written) == expected
    assert run.summary.skipped == ()
    assert run.summary.skip_reason is None


@pytest.mark.requirement("SRS-015")
def test_two_runs_give_byte_identical_files(two_exports: tuple[Export, Export]) -> None:
    """Two runs on the same computer and the same inputs give byte-identical files.

    Input: two runs of the export, with the same software and third-party versions, on the
    synthetic set and the six fixture records, into two different folders.
    Expected: the same 24 file names, each with the same bytes in both runs, and the same
    summaries.
    """
    first, second = two_exports

    assert sorted(first.files) == sorted(second.files)
    differing = [name for name in first.files if first.files[name] != second.files[name]]
    assert differing == []
    assert first.summary == second.summary


@pytest.mark.requirement("SRS-015")
def test_same_inputs_in_another_data_folder_give_identical_files(
    tmp_path: Path,
    subset_ecg_fixture: Any,
    copy_subset_fixture: Callable[..., Any],
    two_exports: tuple[Export, Export],
) -> None:
    """The files depend on the inputs, not on where they are read from or written to.

    Input: a copy of the synthetic ECG subset fixture in a data folder whose path holds a
    space and non-ASCII letters, exported into an output folder in another place, also with
    a space in its path.
    Expected: the same 24 file names with the same bytes as the reference run (the files hold
    no path).
    """
    copy = copy_subset_fixture(subset_ecg_fixture, tmp_path / "other data è" / "data")
    output = tmp_path / "another output" / "golden vectors"

    summary = export_golden_vectors(
        output, data_root=copy.data_root, database=_database(copy.checksum_list_sha256)
    )

    assert summary == two_exports[0].summary
    assert _files(output) == two_exports[0].files


@pytest.mark.requirement("SRS-015")
def test_existing_files_in_the_output_folder(
    tmp_path: Path, subset_ecg_fixture: Any, two_exports: tuple[Export, Export]
) -> None:
    """A run into a folder that already holds files writes the same golden-vector files.

    Input: an output folder that holds a stale file under the name of one synthetic file, a
    stale file under the name of one record segment, and an unrelated file `notes.txt`.
    Expected: every golden-vector file has the bytes of the reference run (the stale ones
    are replaced); `notes.txt` is left as it was; no other file is added.
    """
    output = tmp_path / "golden"
    output.mkdir()
    (output / f"{SYNTHETIC_IDS[0]}{SUFFIX}").write_bytes(b"stale\n")
    (output / f"{SEGMENT_IDS[2]}{SUFFIX}").write_bytes(b"")
    (output / "notes.txt").write_bytes(b"kept\n")

    export_golden_vectors(
        output,
        data_root=subset_ecg_fixture.data_root,
        database=_database(subset_ecg_fixture.checksum_list_sha256),
    )

    assert _files(output) == {**two_exports[0].files, "notes.txt": b"kept\n"}


# --------------------------------------------------------------------------------------------
# The content of each file
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("input_id", ALL_IDS)
def test_file_follows_the_documented_format(
    input_id: str,
    two_exports: tuple[Export, Export],
    read_golden_file: Callable[[bytes], Any],
) -> None:
    """Each file follows the documented format, version 1 (architecture, section 7.3).

    Input: the file of the input, as written by the export.
    Expected: the test's own reader of section 7.3 accepts it (UTF-8, line feeds, no space,
    tab, carriage return or empty line, the 13 header keys in order with valid values, the
    sections `[coefficients]`, `[signals]`, `[beats]`, `[reference_beats]`, `[end]` in order
    with their column lines, row counts as in the header, the documented number syntax,
    finite floats, beats in range and in order, one line feed after `[end]` and nothing
    after it); no byte-order mark; every float is written as Python's `repr()` of its value
    (the shortest form that reads back exactly).
    """
    data = two_exports[0].files[input_id + SUFFIX]
    golden = read_golden_file(data)

    assert not data.startswith(b"\xef\xbb\xbf")
    assert data.endswith(b"\n[end]\n")
    assert golden.not_shortest == ()


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("input_id", ALL_IDS)
def test_file_contains_each_listed_item(input_id: str, parsed: dict[str, Any]) -> None:
    """Each file contains every item that SRS-015 lists, with the documented values.

    Input: the file of the input, read by the test.
    Expected:
    - format `sinus-golden-vector`, version 1;
    - identifier of the input: `input_id` is the identifier of the file; `input_source` is
      `synthetic` or `mitdb`; `input_parameters` gives the generator parameters
      (`duration_s=30;heart_rate_bpm=...;...`) or
      `database=mitdb;database_version=1.0.0;record=<r>;signal=0;start_sample=0;duration_s=60`;
    - sampling frequency in Hz: 250.0 or 360.0 (the fixture records are at 360 Hz);
    - settings: mains 50 Hz for `clean` and `bw-mains50`, 60 Hz for `bw-mains60` and for
      the records (the settings of SRS-007);
    - the software version and the source identifier (keys present; their values are
      checked in `test_file_states_the_software_under_test`);
    - the stages `baseline,mains` (SRS-004, then SRS-005, the order applied) with one
      coefficient row each and the columns `input_mv,baseline_mv,mains_mv`;
    - the input samples: 30 s (7500 or 10800 rows) or 60 s (21600 rows);
    - the detected QRS indices (`[beats]`, at least one beat) and the reference beats.
    """
    golden = parsed[input_id]
    header = golden.header

    assert header["format"] == "sinus-golden-vector"
    assert header["format_version"] == "1"
    assert header["input_id"] == input_id
    if input_id in SYNTHETIC_IDS:
        fs, hr, variant = _synthetic_of(input_id)
        mains = 60 if variant == "bw-mains60" else 50
        wander, amplitude = ("0.0", "0.0") if variant == "clean" else ("1.0", "0.2")
        assert header["input_source"] == "synthetic"
        assert header["input_parameters"] == (
            f"duration_s=30;heart_rate_bpm={hr};baseline_wander_hz=0.3;"
            f"baseline_wander_mv={wander};mains_hz={mains};mains_mv={amplitude}"
        )
        n_samples = 30 * fs
    else:
        fs, mains, n_samples = 360, 60, 21600
        assert header["input_source"] == "mitdb"
        assert header["input_parameters"] == _segment_parameters(input_id.split("-")[1])
    assert header["sampling_frequency_hz"] == f"{fs}.0"
    assert header["mains_frequency_hz"] == str(mains)
    assert header["software_version"] and header["source_sha256"]
    assert header["stages"] == "baseline,mains"
    assert golden.stages == ("baseline", "mains")
    assert [rows.shape for rows in golden.coefficients.values()] == [(1, 5), (1, 5)]
    assert golden.signals.shape == (n_samples, 3)
    assert header["n_samples"] == str(n_samples)
    assert golden.beats.size > 0
    assert header["n_beats"] == str(golden.beats.size)
    assert header["n_reference_beats"] == str(golden.reference_beats.size)


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("input_id", ALL_IDS)
def test_file_states_the_software_under_test(
    input_id: str, parsed: dict[str, Any], running_software: Any, project_version: str
) -> None:
    """Each file states the version and the source identifier of the software under test.

    Input: the file of the input; the identity of the package under test worked out by the
    test, as for SRS-012: the `__version__` literal of `sinus_dsp/__init__.py`, and the
    SHA-256 source identifier computed by the test's own implementation of the six steps of
    architecture section 8.14 on the package that the tests import.
    Expected: `software_version` equals that version, which is also the version of
    `dsp/pyproject.toml`; `source_sha256` equals the identifier computed by the test (64
    lowercase hexadecimal digits).
    """
    header = parsed[input_id].header

    assert header["software_version"] == running_software.version == project_version
    assert header["source_sha256"] == running_software.source_sha256


def _check_read_back(golden: Any) -> list[str]:
    """Compare the values of a file with the public functions called directly on its input.

    Returns the problems found: the coefficients against `baseline_sos` and `mains_sos`; the
    stage outputs against `remove_baseline_wander` (on the input) and
    `remove_mains_interference` (on the baseline output); the beats against `detect_qrs` (on
    the mains output); and all of them against `run_pipeline` and `detect_beats` on the input.
    Every comparison is exact (bitwise for floats).
    """
    fs = float(golden.header["sampling_frequency_hz"])
    mains = int(golden.header["mains_frequency_hz"])
    signal = golden.input_mv.copy()
    baseline = remove_baseline_wander(signal, fs)
    conditioned = remove_mains_interference(baseline, fs, mains)
    beats = detect_qrs(conditioned, fs)
    pipeline = run_pipeline(signal, fs, mains)
    problems = []
    for stage, sos in (("baseline", baseline_sos(fs)), ("mains", mains_sos(fs, mains))):
        if not np.all(sos[:, 3] == 1.0):
            problems.append(f"{stage}: designed a0 is not 1")
        if not _same_float64(golden.coefficients[stage], sos[:, [0, 1, 2, 4, 5]]):
            problems.append(f"{stage}: coefficients differ from the design function")
    checks = {
        "baseline_mv = remove_baseline_wander(input)": (golden.stage_mv("baseline"), baseline),
        "mains_mv = remove_mains_interference(baseline_mv)": (
            golden.stage_mv("mains"),
            conditioned,
        ),
        "baseline_mv = run_pipeline(input).baseline_mv": (
            golden.stage_mv("baseline"),
            pipeline.baseline_mv,
        ),
        "mains_mv = run_pipeline(input).mains_mv": (golden.stage_mv("mains"), pipeline.mains_mv),
        "input_mv = run_pipeline(input).input_mv": (golden.input_mv, pipeline.input_mv),
    }
    problems += [
        name for name, (read, computed) in checks.items() if not _same_float64(read, computed)
    ]
    for name, computed in (
        ("detect_qrs(mains_mv)", beats),
        ("run_pipeline(input).beats", pipeline.beats),
        ("detect_beats(input)", detect_beats(signal, fs, mains)),
    ):
        if golden.beats.tolist() != np.asarray(computed).tolist():
            problems.append(f"beats differ from {name}")
    return problems


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("input_id", ALL_IDS)
def test_values_read_back_equal_the_functions_called_directly(
    input_id: str, parsed: dict[str, Any]
) -> None:
    """The values read back from each file equal the outputs of the conditioning and
    detection functions called directly on the same input.

    Input: the file of the input, read by the test (floats converted with `float()`); the
    public functions of SRS-004, SRS-005 and SRS-006 called on the input read back, at the
    sampling frequency and mains setting of the file.
    Expected, exactly (bitwise for floats, so a -0.0 written as 0.0 fails):
    `baseline_mv` = `remove_baseline_wander(input_mv)`; `mains_mv` =
    `remove_mains_interference(baseline_mv)`; `[beats]` = `detect_qrs(mains_mv)`; the same
    values from `run_pipeline(input_mv)` and `detect_beats(input_mv)`; the `[coefficients]`
    rows equal `baseline_sos(fs)` and `mains_sos(fs, mains)` without a0, whose a0 is 1.
    """
    assert _check_read_back(parsed[input_id]) == []


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("input_id", ALL_IDS)
def test_input_is_that_of_the_generator_or_of_the_record(
    input_id: str,
    parsed: dict[str, Any],
    subset_ecg_fixture: Any,
    make_synthetic_ecg: Callable[..., Any],
    golden_r_peaks: Callable[[int, int], list[int]],
) -> None:
    """The input samples of each file are the input that SRS-015 lists.

    Input: the file of the input, read by the test.
    Expected, synthetic inputs: `input_mv` equals `synthetic_ecg(fs, hr, variant).signal_mv`
    bitwise, and lies within 1e-9 mV of the test's own synthetic ECG of architecture section
    7.2; `[reference_beats]` are the r_k of the integer rule. Record segments: `input_mv`
    equals the first 21600 samples (60 s at 360 Hz) of channel 0 of the fixture record as
    `load_record` (SRS-002) reads it, bitwise, and lies within one quantization step (1/200
    mV) of the ECG written on channel 0 (channel 1 is flat, so the first stored signal is the
    one used); `[reference_beats]` are the beat annotations of the record below sample 21600.
    """
    golden = parsed[input_id]
    if input_id in SYNTHETIC_IDS:
        fs, hr, variant = _synthetic_of(input_id)
        mains = None if variant == "clean" else (60 if variant == "bw-mains60" else 50)
        generated = synthetic_ecg(fs, hr, variant).signal_mv
        expected = make_synthetic_ecg(fs, hr, mains_hz=mains).signal_mv
        assert _same_float64(golden.input_mv, generated)
        assert float(np.max(np.abs(golden.input_mv - expected))) <= WAVEFORM_TOLERANCE_MV
        assert golden.reference_beats.tolist() == golden_r_peaks(fs, hr)
    else:
        name = input_id.split("-")[1]
        record = subset_ecg_fixture.records[name]
        loaded = load_record(subset_ecg_fixture.folder / name, 0).signal_mv[:21600]
        assert _same_float64(golden.input_mv, loaded)
        assert float(np.max(np.abs(golden.input_mv - record.ecg_mv[:21600]))) <= QUANTIZATION_MV
        assert golden.reference_beats.tolist() == [b for b in record.beats if b < 21600]


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("input_id", ALL_IDS)
def test_reader_of_the_software_reads_back_the_same_values(
    input_id: str, two_exports: tuple[Export, Export], parsed: dict[str, Any]
) -> None:
    """The reader of the software gives back exactly the values written in each file.

    Input: `read_golden_vector(<path of the file>)`.
    Expected: every field equals what the test's own reader reads from the same file: the
    header values, `fs_hz` as a float, `mains_hz`, `stages`, the coefficient matrices with
    a0 = 1, the input, the two stage outputs (bitwise), the beats and the reference beats.
    """
    golden = parsed[input_id]
    vector = read_golden_vector(two_exports[0].folder / (input_id + SUFFIX))
    header = golden.header

    assert (vector.input_id, vector.input_source, vector.input_parameters) == (
        header["input_id"],
        header["input_source"],
        header["input_parameters"],
    )
    assert type(vector.fs_hz) is float
    assert vector.fs_hz == float(header["sampling_frequency_hz"])
    assert vector.mains_hz == int(header["mains_frequency_hz"])
    assert (vector.software_version, vector.source_sha256) == (
        header["software_version"],
        header["source_sha256"],
    )
    assert vector.stages == golden.stages
    for stage, matrix in zip(golden.stages, vector.coefficients, strict=True):
        assert _same_float64(np.asarray(matrix)[:, [0, 1, 2, 4, 5]], golden.coefficients[stage])
        assert np.all(np.asarray(matrix)[:, 3] == 1.0)
    assert _same_float64(vector.input_mv, golden.input_mv)
    for stage, output in zip(golden.stages, vector.stage_outputs_mv, strict=True):
        assert _same_float64(output, golden.stage_mv(stage))
    assert np.asarray(vector.beats).tolist() == golden.beats.tolist()
    assert np.asarray(vector.reference_beats).tolist() == golden.reference_beats.tolist()


# --------------------------------------------------------------------------------------------
# Record segments only where the files of the six records are available and verified
# --------------------------------------------------------------------------------------------


def _flip_one_bit(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))


SKIP_CASES = {
    "no-database": "SHA256SUMS.txt",
    "checksum-list-missing": "SHA256SUMS.txt",
    "checksum-list-altered": "SHA256SUMS.txt",
    "signal-file-altered": "105.dat",
    "annotation-file-missing": "203.atr",
    "calibration-file-missing": "207.xws",
    "further-annotation-file-altered": "108.at_",
    "header-file-missing": "100.hea",
    "record-absent": "119.dat",
}


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("case", list(SKIP_CASES))
def test_record_segments_are_skipped_when_the_records_are_not_verified(
    case: str,
    tmp_path: Path,
    subset_ecg_fixture: Any,
    copy_subset_fixture: Callable[..., Any],
    two_exports: tuple[Export, Export],
) -> None:
    """Without the verified files of all six records, none of the record segments is
    written (SRS-015 v0.7.2: all six or none), only the synthetic files.

    Input: the export with the fixture `Database` on a data folder without the database; or
    on a copy of the synthetic ECG subset fixture whose checksum list is missing or altered
    (one bit), or with one file of one record altered (105.dat, 108.at_) or missing (203.atr,
    207.xws, 100.hea), or with every file of record 119 missing; in each case but the first
    two, the files of the other records are intact and verify.
    Expected: the export completes; the folder holds exactly the 18 synthetic files, with the
    bytes of the reference run, and no file of any record segment; `written` lists them in
    order; `skipped` lists the six record-segment identifiers in code-point order of the
    record names; `skip_reason` says that the database is not verified and names the file
    concerned.
    """
    data_root = tmp_path / "data"
    if case == "no-database":
        data_root.mkdir()
    else:
        copy = copy_subset_fixture(subset_ecg_fixture, data_root)
        target = copy.folder / SKIP_CASES[case]
        if case.endswith("altered"):
            _flip_one_bit(target)
        elif case == "record-absent":
            for path in copy.folder.glob("119.*"):
                path.unlink()
            assert not list(copy.folder.glob("119.*"))
        else:
            target.unlink()
    output = tmp_path / "golden"

    summary = export_golden_vectors(
        output,
        data_root=data_root,
        database=_database(subset_ecg_fixture.checksum_list_sha256),
    )

    synthetic_names = [input_id + SUFFIX for input_id in SYNTHETIC_IDS]
    assert list(summary.written) == synthetic_names
    assert summary.skipped == SEGMENT_IDS
    assert summary.skip_reason is not None
    assert "not verified" in summary.skip_reason
    assert SKIP_CASES[case] in summary.skip_reason
    assert _files(output) == {name: two_exports[0].files[name] for name in synthetic_names}


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("case", ["only-the-six-records", "files-of-other-records-altered"])
def test_record_segments_need_only_the_files_of_the_six_records(
    case: str,
    tmp_path: Path,
    subset_ecg_fixture: Any,
    copy_subset_fixture: Callable[..., Any],
    two_exports: tuple[Export, Export],
) -> None:
    """The record segments need the verified files of the six records, not the whole database.

    Input: a copy of the synthetic ECG subset fixture holding only the checksum list and the
    28 files of the six records (as the cache of the build); or a full copy in which files
    that belong to no record of the subset are altered (`RECORDS`, `x_mitdb/x_108.hea`).
    Expected: the 24 files are written, with the bytes of the reference run; nothing skipped.
    """
    copy = copy_subset_fixture(
        subset_ecg_fixture, tmp_path / "data", only_subset=case == "only-the-six-records"
    )
    if case == "files-of-other-records-altered":
        _flip_one_bit(copy.folder / "RECORDS")
        _flip_one_bit(copy.folder / "x_mitdb" / "x_108.hea")
    output = tmp_path / "golden"

    summary = export_golden_vectors(
        output, data_root=copy.data_root, database=_database(copy.checksum_list_sha256)
    )

    assert summary.skipped == ()
    assert _files(output) == two_exports[0].files


# --------------------------------------------------------------------------------------------
# The first 60 s of a record: limits
# --------------------------------------------------------------------------------------------

# Records of the limits fixture: sampling frequency (Hz), number of samples, heart rate of
# the synthetic ECG on channel 0 (bpm). The segment is the first round(60 fs) samples.
LIMIT_RECORDS: dict[str, tuple[int, int, int]] = {
    "100": (360, 21600, 75),  # exactly 60 s
    "105": (360, 21601, 60),  # one sample more than 60 s
    "108": (250, 17500, 75),  # 70 s at 250 Hz: 15000 samples
    "119": (360, 25200, 90),  # 70 s; beat codes and non-beat annotations of every kind
    "203": (360, 25200, 75),  # two beat annotations on one sample
    "207": (128, 7808, 60),  # 61 s at 128 Hz, the lowest accepted rate is 125 Hz: 7680 samples
}
# Beat codes used on record 119 besides N, and non-beat annotations with their subtype and
# auxiliary note (`!` is a ventricular flutter wave, not a beat).
OTHER_BEAT_CODES = ("V", "A", "L", "R", "/", "f", "Q", "?", "j", "E")
NON_BEATS = (
    ("+", 0, "(AFIB"),
    ("~", 3, ""),
    ("!", 0, ""),
    ("[", 0, ""),
    ("]", 0, ""),
    ("|", 0, ""),
)


def _limit_annotations(
    name: str, fs: int, n_samples: int, qrs: list[int]
) -> list[tuple[int, str, int, str]]:
    """Annotations of a record of the limits fixture, in sample order.

    A rhythm annotation `+ (N` at sample 10, a beat `N` at each QRS, and beats at the last
    sample of the segment and, if the record is longer, at its first sample after the segment.
    Record 119: the beats take the codes of ``OTHER_BEAT_CODES`` in turn, and the non-beat
    annotations of ``NON_BEATS`` lie between beats, one also at the last sample of the segment.
    Record 203: a second beat `V` on the sample of its third QRS.
    """
    segment = round(60 * fs)
    annotations = [(10, "+", 0, "(N")]
    beats = sorted({*qrs, segment - 1, *([segment] if n_samples > segment else [])})
    for i, sample in enumerate(beats):
        symbol = OTHER_BEAT_CODES[i % len(OTHER_BEAT_CODES)] if name == "119" else "N"
        annotations.append((sample, symbol, 0, ""))
    if name == "119":
        for i, (symbol, subtype, note) in enumerate(NON_BEATS):
            annotations.append((qrs[2 * i + 1] + fs // 4, symbol, subtype, note))
        annotations.append((segment - 1, "~", 1, ""))
    if name == "203":
        annotations.append((qrs[2], "V", 0, ""))
    return sorted(annotations, key=lambda a: a[0])


class LimitsFixture:
    """The limits fixture: data folder, pinned digest, and per record its channel 0 and its
    expected reference beats in the segment."""

    def __init__(
        self, data_root: Path, pin: str, ecg: Mapping[str, Any], beats: Mapping[str, list[int]]
    ) -> None:
        self.data_root = data_root
        self.pin = pin
        self.ecg = dict(ecg)
        self.beats = dict(beats)


def _write_limits_fixture(
    data_root: Path,
    records: Mapping[str, tuple[int, int, int]],
    write_wfdb_record: Callable[..., Path],
    write_database_folder: Callable[..., Any],
    make_synthetic_ecg: Callable[..., Any],
) -> LimitsFixture:
    """Write the records as a fixture MIT-BIH Arrhythmia database with its checksum list.

    Channel 0 is a noise-free synthetic ECG, channel 1 is 0.3 mV minus half of it. Besides
    the WFDB files, the folder holds `<record>.xws`, `108.at_`, `119.at_`, `203.at-`,
    `203.at_` and a `RECORDS` file, all listed.
    """
    folder = data_root / "mitdb"
    folder.mkdir(parents=True)
    ecg, beats = {}, {}
    for name, (fs, n_samples, rate) in records.items():
        synthetic = make_synthetic_ecg(fs, rate, n_samples=n_samples)
        annotations = _limit_annotations(name, fs, n_samples, synthetic.qrs_samples.tolist())
        signals = np.column_stack([synthetic.signal_mv, 0.3 - 0.5 * synthetic.signal_mv])
        write_wfdb_record(
            folder,
            name,
            fs_hz=fs,
            signals_mv=signals,
            signal_names=("MLII", "V1"),
            annotations=annotations,
        )
        ecg[name] = synthetic.signal_mv
        segment = round(60 * fs)
        beat_codes = {"N", *OTHER_BEAT_CODES}
        beats[name] = [a[0] for a in annotations if a[1] in beat_codes and a[0] < segment]
    files = {path.name: path.read_bytes() for path in sorted(folder.iterdir())}
    files.update({f"{name}.xws": f"xws {name}\n".encode("ascii") for name in records})
    files.update({name: b"annotations\n" for name in ("108.at_", "119.at_", "203.at-", "203.at_")})
    files["RECORDS"] = "".join(f"{name}\n" for name in records).encode("ascii")
    database = write_database_folder(data_root, "mitdb", files)
    return LimitsFixture(data_root, database.checksum_list_sha256, ecg, beats)


@pytest.fixture(scope="module")
def limits_export(
    tmp_path_factory: pytest.TempPathFactory,
    write_wfdb_record: Callable[..., Path],
    write_database_folder: Callable[..., Any],
    make_synthetic_ecg: Callable[..., Any],
    network_forbidden: Callable[[], Any],
    read_golden_file: Callable[[bytes], Any],
) -> tuple[LimitsFixture, Any, dict[str, Any]]:
    """The limits fixture, the summary of its export and its record-segment files, read."""
    root = tmp_path_factory.mktemp("srs015-limits")
    fixture = _write_limits_fixture(
        root / "data", LIMIT_RECORDS, write_wfdb_record, write_database_folder, make_synthetic_ecg
    )
    with network_forbidden():
        summary = export_golden_vectors(
            root / "golden", data_root=fixture.data_root, database=_database(fixture.pin)
        )
    files = {
        name: read_golden_file((root / "golden" / f"mitdb-{name}-first60s{SUFFIX}").read_bytes())
        for name in LIMIT_RECORDS
    }
    return fixture, summary, files


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("name", list(LIMIT_RECORDS))
def test_record_segment_is_the_first_60_s_of_the_first_stored_signal(
    name: str, limits_export: tuple[LimitsFixture, Any, dict[str, Any]]
) -> None:
    """Each record segment holds exactly the first 60 s of channel 0, at the record's rate.

    Input: the export on the limits fixture: records of exactly 60 s and of 60 s plus one
    sample at 360 Hz, of 70 s at 360 Hz and at 250 Hz, of 61 s at 128 Hz; channel 1 differs
    from channel 0; beat annotations on the last sample of the segment and on the first sample
    after it; on record 119 ten other beat codes and non-beat annotations (`+`, `~`, `!`, `[`,
    `]`, `|`), one on the last sample of the segment; on record 203 two beats on one sample.
    Expected: the file of each record has `round(60 fs)` samples (21600 at 360 Hz, 15000 at
    250 Hz, 7680 at 128 Hz), `sampling_frequency_hz` equal to the rate as a float (`360.0`,
    `250.0`, `128.0`), `input_parameters` naming the record and `duration_s=60`; `input_mv`
    equals channel 0 as `load_record` reads it, cut at the segment, bitwise, and lies within
    one quantization step of the ECG written on channel 0; `[reference_beats]` are exactly the
    beat annotations below the end of the segment (the one on its last sample included, the
    one after it excluded, the two on one sample both kept, no non-beat annotation); the
    values read back equal the functions called directly on the input.
    """
    fixture, summary, files = limits_export
    golden = files[name]
    fs, _, _ = LIMIT_RECORDS[name]
    segment = round(60 * fs)
    loaded = load_record(fixture.data_root / "mitdb" / name, 0).signal_mv[:segment]

    assert summary.skipped == ()
    assert golden.header["n_samples"] == str(segment)
    assert golden.header["sampling_frequency_hz"] == f"{fs}.0"
    assert golden.header["mains_frequency_hz"] == "60"
    assert golden.header["input_parameters"] == _segment_parameters(name)
    assert _same_float64(golden.input_mv, loaded)
    assert float(np.max(np.abs(golden.input_mv - fixture.ecg[name][:segment]))) <= QUANTIZATION_MV
    assert golden.reference_beats.tolist() == fixture.beats[name]
    assert segment - 1 in fixture.beats[name]
    assert _check_read_back(golden) == []


@pytest.mark.requirement("SRS-015")
def test_record_shorter_than_60_s_gives_no_segment(
    tmp_path: Path,
    write_wfdb_record: Callable[..., Path],
    write_database_folder: Callable[..., Any],
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """A record that does not have 60 s gives no segment file: the export fails instead.

    Input: a fixture database of the six records, verified, in which record 119 has 21599
    samples at 360 Hz (one sample less than 60 s) and the others 70 s.
    Expected: `InvalidInputError` naming record 119; no file `mitdb-119-first60s.golden.txt`
    and no temporary file in the output folder; every file present is complete (the test's
    reader accepts it).
    """
    records = {name: (360, 25200, 75) for name in SUBSET}
    records["119"] = (360, 21599, 75)
    fixture = _write_limits_fixture(
        tmp_path / "data", records, write_wfdb_record, write_database_folder, make_synthetic_ecg
    )
    output = tmp_path / "golden"

    with pytest.raises(InvalidInputError) as excinfo:
        export_golden_vectors(output, data_root=fixture.data_root, database=_database(fixture.pin))

    assert "119" in str(excinfo.value)
    names = sorted(path.name for path in output.iterdir())
    assert f"mitdb-119-first60s{SUFFIX}" not in names
    assert all(name.endswith(SUFFIX) for name in names), names


@pytest.mark.requirement("SRS-015")
def test_record_segment_files_are_complete_after_a_failed_export(
    tmp_path: Path,
    write_wfdb_record: Callable[..., Path],
    write_database_folder: Callable[..., Any],
    make_synthetic_ecg: Callable[..., Any],
    read_golden_file: Callable[[bytes], Any],
) -> None:
    """The files left by an export that stops on an error are complete files.

    Input: as in `test_record_shorter_than_60_s_gives_no_segment`, with record 203 short
    instead (it comes after 100, 105, 108 and 119 in code-point order).
    Expected: `InvalidInputError` naming record 203; every file in the output folder is a
    golden-vector file that the test's reader accepts; no file for record 203 or 207.
    """
    records = {name: (360, 25200, 75) for name in SUBSET}
    records["203"] = (360, 21599, 75)
    fixture = _write_limits_fixture(
        tmp_path / "data", records, write_wfdb_record, write_database_folder, make_synthetic_ecg
    )
    output = tmp_path / "golden"

    with pytest.raises(InvalidInputError) as excinfo:
        export_golden_vectors(output, data_root=fixture.data_root, database=_database(fixture.pin))

    assert "203" in str(excinfo.value)
    names = sorted(path.name for path in output.iterdir())
    assert all(name.endswith(SUFFIX) for name in names), names
    assert not {f"mitdb-203-first60s{SUFFIX}", f"mitdb-207-first60s{SUFFIX}"} & set(names)
    for name in names:
        read_golden_file((output / name).read_bytes())
