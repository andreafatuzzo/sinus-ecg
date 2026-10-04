"""System verification of SRS-007: QRS detection performance on the MIT-BIH Arrhythmia Database.

The evaluation is run once for the whole module, as the validation report is produced
(architecture §8.10): ``run_validation`` verifies both local databases without the network,
then runs QRS detection and the evaluation of SRS-008 and SRS-011 on every record. The
detector and the record loader given to the run delegate to the defaults of
``run_validation`` (``detect_beats`` and ``load_record``) and only record their calls, so the
results are those of the default run, and the settings actually used can be checked.

The expected values come from SRS-007 and from the database itself, not from the
implementation: the 48 record names of the database, the first stored signal of each record
as its header names it, the number of scored reference beats counted here from the annotation
files with the rules of SRS-002 and SRS-008, and the 99.5 % targets compared exactly on the
summed counts.

These tests need the verified local copies of the MIT-BIH Arrhythmia Database (``data/mitdb``)
and of the MIT-BIH Noise Stress Test Database (``data/nstdb``), which the validation run also
verifies; ``scripts/download_data.py`` obtains both. Every test uses that run, so every test
is marked ``needs_data`` and ``needs_nstdb`` and is skipped unless both databases are
complete, as in CI, which keeps only the subset records. Their result is recorded in the
milestone's validation report.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
import wfdb

from sinus_dsp.data.physionet import MITDB
from sinus_dsp.data.records import Record, load_record
from sinus_dsp.evaluation.report import render_full_report
from sinus_dsp.evaluation.run import (
    EvaluationSettings,
    RecordEvaluation,
    ValidationResults,
    meets_target,
    run_validation,
)
from sinus_dsp.pipeline import detect_beats

DATA_ROOT = Path(__file__).resolve().parents[3] / "data"
MITDB_DIR = DATA_ROOT / MITDB.slug

#: The 48 records of the MIT-BIH Arrhythmia Database, version 1.0.0, as the database
#: documentation lists them (not read from its ``RECORDS`` file).
MITDB_RECORDS = (
    "100", "101", "102", "103", "104", "105", "106", "107", "108", "109",
    "111", "112", "113", "114", "115", "116", "117", "118", "119",
    "121", "122", "123", "124",
    "200", "201", "202", "203", "205", "207", "208", "209", "210",
    "212", "213", "214", "215", "217", "219",
    "220", "221", "222", "223", "228", "230", "231", "232", "233", "234",
)  # fmt: skip

#: SRS-007: the first stored signal of each record, and the mains filter set to 60 Hz.
SRS_007_CHANNEL = 0
SRS_007_MAINS_HZ = 60

#: SRS-007: gross Se and gross +P of at least 99.5 %, as an exact fraction.
TARGET = Fraction(995, 1000)

#: SRS-002: the reference beat annotation codes.
BEAT_CODES = frozenset("N L R B A a J S V r F e j n E / f Q ?".split())

#: SRS-008: reference beats before 5:00 are not scored.
LEARNING_PERIOD_S = 300


@dataclass(frozen=True)
class LoaderCall:
    """One call of the record loader during the run."""

    folder: str
    record: str
    channel: int
    n_samples: int
    signal_name: str


@dataclass(frozen=True)
class DetectorCall:
    """One call of the detector during the run, with the record loaded just before it."""

    loaded: LoaderCall | None
    n_samples: int
    fs_hz: float
    mains_hz: int


@dataclass(frozen=True)
class Run:
    """The results of the validation run and the calls it made."""

    results: ValidationResults
    loader_calls: tuple[LoaderCall, ...]
    detector_calls: tuple[DetectorCall, ...]

    def mitdb_records(self) -> dict[str, RecordEvaluation]:
        return {evaluation.record: evaluation for evaluation in self.results.records}


@pytest.fixture(scope="module")
def run() -> Iterator[Run]:
    """Run the validation once on the full local databases, without the network."""
    loader_calls: list[LoaderCall] = []
    detector_calls: list[DetectorCall] = []

    def loader(record_path: Path, channel: int) -> Record:
        record = load_record(record_path, channel)
        loader_calls.append(
            LoaderCall(
                folder=Path(record_path).parent.name,
                record=Path(record_path).name,
                channel=channel,
                n_samples=record.n_samples,
                signal_name=record.signal_name,
            )
        )
        return record

    def detector(
        signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int
    ) -> npt.NDArray[np.int64]:
        detector_calls.append(
            DetectorCall(
                loaded=loader_calls[-1] if loader_calls else None,
                n_samples=len(signal_mv),
                fs_hz=fs_hz,
                mains_hz=mains_hz,
            )
        )
        return detect_beats(signal_mv, fs_hz, mains_hz)

    results = run_validation(DATA_ROOT, detector=detector, loader=loader, fetch=None)
    yield Run(
        results=results,
        loader_calls=tuple(loader_calls),
        detector_calls=tuple(detector_calls),
    )


def _header(record: str) -> wfdb.Record:
    return wfdb.rdheader(str(MITDB_DIR / record))


def _scored_reference_beats(record: str) -> int:
    """Count the scored reference beats of a record from its annotation file.

    SRS-002: beats are the annotations with the codes of ``BEAT_CODES``. SRS-008: reference
    beats before 5:00 are not scored, nor those from a ``[`` to the next ``]``, both
    included; an episode without ``]`` lasts until the end of the record.
    """
    header = _header(record)
    annotations = wfdb.rdann(str(MITDB_DIR / record), "atr")
    samples = [int(sample) for sample in annotations.sample]
    symbols = [str(symbol) for symbol in annotations.symbol]
    episodes: list[tuple[int, int]] = []
    onset: int | None = None
    for sample, symbol in zip(samples, symbols, strict=True):
        if symbol == "[" and onset is None:
            onset = sample
        elif symbol == "]" and onset is not None:
            episodes.append((onset, sample))
            onset = None
    if onset is not None:
        episodes.append((onset, int(header.sig_len) - 1))
    first_scored = LEARNING_PERIOD_S * float(header.fs)
    return sum(
        1
        for sample, symbol in zip(samples, symbols, strict=True)
        if symbol in BEAT_CODES
        and sample >= first_scored
        and not any(start <= sample <= end for start, end in episodes)
    )


def _percent(tp: int, other: int) -> str:
    return "not defined" if tp + other == 0 else f"{100 * tp / (tp + other):.2f}"


def _records_below_target(evaluations: Sequence[RecordEvaluation]) -> str:
    """Per-record figures of the records whose Se or +P is below the target, for messages."""
    lines = [
        f"{e.record} ({e.signal_name}): TP {e.counts.tp}, FN {e.counts.fn}, FP {e.counts.fp}, "
        f"Se {_percent(e.counts.tp, e.counts.fn)} %, +P {_percent(e.counts.tp, e.counts.fp)} %"
        for e in evaluations
        if e.counts.tp + e.counts.fn == 0
        or e.counts.tp + e.counts.fp == 0
        or Fraction(e.counts.tp, e.counts.tp + e.counts.fn) < TARGET
        or Fraction(e.counts.tp, e.counts.tp + e.counts.fp) < TARGET
    ]
    return "records below 99.50 %:\n  " + "\n  ".join(lines) if lines else "no record below 99.50 %"


def _gross(evaluations: Sequence[RecordEvaluation]) -> tuple[int, int, int]:
    tp = sum(e.counts.tp for e in evaluations)
    fn = sum(e.counts.fn for e in evaluations)
    fp = sum(e.counts.fp for e in evaluations)
    return tp, fn, fp


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.requirement("SRS-007")
def test_run_uses_the_settings_of_srs_007(run: Run) -> None:
    """The evaluation uses the first stored signal and the mains filter set to 60 Hz.

    Case: the default validation run, as ``scripts/validate.py`` performs it.
    Inputs: the full local databases; the defaults of ``run_validation``.
    Expected: the run is the default one (detector ``detect_beats``, loader ``load_record``,
    settings channel 0 and 60 Hz); the results state channel 0 and 60 Hz; and every record
    was actually loaded with channel 0 and every detection was run with the mains setting
    60 Hz, as the recorded calls show.
    """
    defaults = inspect.signature(run_validation).parameters
    assert defaults["detector"].default is detect_beats
    assert defaults["loader"].default is load_record
    assert defaults["settings"].default == EvaluationSettings(
        channel=SRS_007_CHANNEL, mains_hz=SRS_007_MAINS_HZ
    )

    assert run.results.settings == EvaluationSettings(
        channel=SRS_007_CHANNEL, mains_hz=SRS_007_MAINS_HZ
    )
    assert run.loader_calls, "no record was loaded"
    assert {call.channel for call in run.loader_calls} == {SRS_007_CHANNEL}
    assert run.detector_calls, "the detector was not called"
    assert {call.mains_hz for call in run.detector_calls} == {SRS_007_MAINS_HZ}


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.requirement("SRS-007")
def test_all_48_records_are_evaluated_in_full(run: Run) -> None:
    """Every one of the 48 records is evaluated once, on its whole signal.

    Case: the default validation run.
    Inputs: the full local MIT-BIH Arrhythmia Database, version 1.0.0.
    Expected: the whole database was verified (every listed file, not a subset of records);
    the results hold the 48 records of the database, each once, in record-name order; each was
    loaded once from the database folder, and the detector received its whole signal (as many
    samples as its header states) at its sampling frequency of 360 Hz.
    """
    verification = run.results.mitdb
    assert verification.database == MITDB
    assert verification.database.version == "1.0.0"
    assert verification.records is None, "only a subset of the records was verified"
    assert not run.results.subset

    assert tuple(e.record for e in run.results.records) == MITDB_RECORDS

    mitdb_loads = [call for call in run.loader_calls if call.folder == MITDB.slug]
    assert sorted(call.record for call in mitdb_loads) == list(MITDB_RECORDS)

    mitdb_detections = [
        call
        for call in run.detector_calls
        if call.loaded is not None and call.loaded.folder == MITDB.slug
    ]
    detected = {call.loaded.record: call for call in mitdb_detections if call.loaded is not None}
    assert len(mitdb_detections) == len(MITDB_RECORDS)
    assert sorted(detected) == list(MITDB_RECORDS)
    evaluations = run.mitdb_records()
    for record in MITDB_RECORDS:
        header = _header(record)
        call = detected[record]
        assert call.n_samples == int(header.sig_len), record
        assert call.fs_hz == float(header.fs) == 360.0, record
        assert evaluations[record].fs_hz == 360.0, record


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.requirement("SRS-007")
def test_first_stored_signal_of_each_record_is_evaluated(run: Run) -> None:
    """The signal evaluated is the first one stored in each record.

    Case: the default validation run.
    Inputs: the full local MIT-BIH Arrhythmia Database; the header of each record, read here
    with wfdb.
    Expected: for each of the 48 records, the signal named in the results is the first signal
    of the header, and its units are mV.
    """
    evaluations = run.mitdb_records()
    assert sorted(evaluations) == list(MITDB_RECORDS)
    for record in MITDB_RECORDS:
        header = _header(record)
        assert evaluations[record].signal_name == str(header.sig_name[0]), record
        assert str(header.units[0]) == "mV", record


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.requirement("SRS-007")
def test_every_scored_reference_beat_is_counted(run: Run) -> None:
    """TP + FN of each record equals its number of scored reference beats.

    Case: the default validation run; the scored reference beats are counted independently.
    Inputs: the full local MIT-BIH Arrhythmia Database; the ``atr`` annotation file of each
    record, read here with wfdb.
    Expected: for each of the 48 records, TP + FN equals the number of beat annotations
    (SRS-002 codes) at or after 5:00 and outside every ventricular flutter or fibrillation
    episode (SRS-008), so that every scored reference beat of the whole record is either
    detected or missed.
    """
    evaluations = run.mitdb_records()
    assert sorted(evaluations) == list(MITDB_RECORDS)
    mismatches: dict[str, tuple[int, int]] = {}
    for record in MITDB_RECORDS:
        counts = evaluations[record].counts
        expected = _scored_reference_beats(record)
        if counts.tp + counts.fn != expected:
            mismatches[record] = (counts.tp + counts.fn, expected)
    assert not mismatches, f"record: (TP + FN, scored reference beats): {mismatches}"


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.requirement("SRS-007")
def test_gross_sensitivity_is_at_least_99_5_percent(run: Run) -> None:
    """Gross Se over the 48 records is at least 99.5 %.

    Case: the default validation run.
    Inputs: the full local MIT-BIH Arrhythmia Database, first stored signal, 60 Hz.
    Expected: with TP and FN summed over the 48 records, TP / (TP + FN) >= 99.5 %, compared
    exactly.
    """
    tp, fn, _ = _gross(run.results.records)
    assert tp + fn > 0
    assert Fraction(tp, tp + fn) >= TARGET, (
        f"gross Se {_percent(tp, fn)} % (TP {tp}, FN {fn}) is below 99.50 %; "
        + _records_below_target(run.results.records)
    )


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.requirement("SRS-007")
def test_gross_positive_predictivity_is_at_least_99_5_percent(run: Run) -> None:
    """Gross +P over the 48 records is at least 99.5 %.

    Case: the default validation run.
    Inputs: the full local MIT-BIH Arrhythmia Database, first stored signal, 60 Hz.
    Expected: with TP and FP summed over the 48 records, TP / (TP + FP) >= 99.5 %, compared
    exactly.
    """
    tp, _, fp = _gross(run.results.records)
    assert tp + fp > 0
    assert Fraction(tp, tp + fp) >= TARGET, (
        f"gross +P {_percent(tp, fp)} % (TP {tp}, FP {fp}) is below 99.50 %; "
        + _records_below_target(run.results.records)
    )


@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.requirement("SRS-007")
def test_report_states_the_gross_values_and_verdicts(run: Run) -> None:
    """The validation report states the gross values and the verdicts that the counts give.

    SRS-007 is verified by analysis of the validation report, so the report must agree with
    the counts on the real data.

    Case: the full report rendered from the default validation run.
    Inputs: the results of the run.
    Expected: ``meets_target`` agrees with the exact comparison for Se and for +P; the report
    states the gross Se and +P with two decimals, the target 99.50 and ``pass`` or ``fail``
    as the exact comparison gives.
    """
    tp, fn, fp = _gross(run.results.records)
    se_met = Fraction(tp, tp + fn) >= TARGET
    ppv_met = Fraction(tp, tp + fp) >= TARGET
    assert meets_target(tp, fn) is se_met
    assert meets_target(tp, fp) is ppv_met

    report = render_full_report(run.results)
    rows = {
        cells[0]: cells[1:]
        for line in report.splitlines()
        if line.startswith("| Gross ")
        and len(cells := [cell.strip() for cell in line.strip("|").split("|")]) == 4
    }
    assert rows["Gross Se"][0] == _percent(tp, fn)
    assert "99.50" in rows["Gross Se"][1]
    assert rows["Gross Se"][2] == ("pass" if se_met else "fail")
    assert rows["Gross +P"][0] == _percent(tp, fp)
    assert "99.50" in rows["Gross +P"][1]
    assert rows["Gross +P"][2] == ("pass" if ppv_met else "fail")
