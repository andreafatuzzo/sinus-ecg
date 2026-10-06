"""Unit tests of the noise stress test: record names, SNR and aggregation per SNR.

The 12 records are small WFDB records written in a temporary folder at 20 Hz, evaluated
with a fake detector. No test uses the network or the real databases.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp.data.physionet import Database, DatabaseLicence, VerificationResult
from sinus_dsp.data.records import Record, load_record
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.metrics import RecordCounts, aggregate_statistics
from sinus_dsp.evaluation.noise_stress import (
    CLEAN_RECORDS,
    NOISE_STRESS_RECORDS,
    NoiseStressResults,
    SnrStatistics,
    evaluate_noise_stress,
    snr_db,
)
from sinus_dsp.evaluation.run import EvaluationSettings, RecordEvaluation

SNRS = (24, 18, 12, 6, 0, -6)
VERIFICATION = VerificationResult(
    database=Database(
        "nstdb",
        "1.0.0",
        "Fixture Noise Database",
        "0" * 64,
        DatabaseLicence("Fixture Licence 1.0", "https://licences.example/nstdb/"),
    ),
    records=None,
    files=("118e24.dat",),
)


def test_record_constants() -> None:
    assert NOISE_STRESS_RECORDS == (
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
    assert CLEAN_RECORDS == ("118", "119")
    assert [snr_db(name) for name in NOISE_STRESS_RECORDS] == [*SNRS, *SNRS]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("118e24", 24),
        ("119e_6", -6),
        ("118e00", 0),
        ("118e06", 6),
        ("1e5", 5),
        ("100e_12", -12),
        ("118e_0", 0),
    ],
)
def test_snr_from_the_name(name: str, expected: int) -> None:
    assert snr_db(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "118",
        "118e",
        "118e_",
        "e24",
        "118e24x",
        "118E24",
        "118e-6",
        "118em",
        "bw",
        "em",
        "",
        "a18e24",
        "118e 6",
        " 118e24",
        "118e24\n",
        "118e__6",
        118,
    ],
)
def test_other_names_are_rejected(name: Any) -> None:
    with pytest.raises(InvalidInputError, match="not a noise stress record name"):
        snr_db(name)


def record_evaluation(name: str, tp: int, fn: int, fp: int) -> RecordEvaluation:
    return RecordEvaluation(
        record=name,
        signal_name="MLII",
        fs_hz=360.0,
        counts=RecordCounts(name, tp, fn, fp),
        vf_episodes=0,
        vf_episodes_scored=0,
        vf_samples_scored=0,
        reference_excluded=0,
        detections_excluded=0,
        flutter_waves_outside_vf=0,
    )


MITDB_RECORDS = (
    record_evaluation("100", 50, 0, 0),
    record_evaluation("118", 100, 3, 2),
    record_evaluation("119", 90, 1, 7),
)


def expected_counts(name: str) -> RecordCounts:
    """At SNR index j: 118 has tp j + 1, fn 1, fp 0; 119 has tp j + 1, fn 0, fp j."""
    j = SNRS.index(snr_db(name))
    if name.startswith("118"):
        return RecordCounts(name, j + 1, 1, 0)
    return RecordCounts(name, j + 1, 0, j)


@pytest.fixture
def nstdb_dir(tmp_path: Path, write_fixture_record: Callable[..., None]) -> Path:
    for name in NOISE_STRESS_RECORDS:
        j = SNRS.index(snr_db(name))
        if name.startswith("118"):
            beats = [6100 + 100 * m for m in range(j + 2)]
            detections = beats[:-1]
        else:
            beats = [6100 + 100 * m for m in range(j + 1)]
            detections = sorted([*beats, *(6150 + 100 * m for m in range(j))])
        write_fixture_record(tmp_path, name, n_samples=7000, beats=beats, detections=detections)
    return tmp_path


class RecordingLoader:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, int]] = []

    def __call__(self, path: Path, channel: int) -> Record:
        self.calls.append((path, channel))
        return load_record(path, channel)


def test_evaluation_of_the_noise_stress_records(
    nstdb_dir: Path, fake_detector: Callable[..., npt.NDArray[np.int64]]
) -> None:
    loader = RecordingLoader()
    results = evaluate_noise_stress(
        nstdb_dir,
        MITDB_RECORDS,
        EvaluationSettings(),
        nstdb=VERIFICATION,
        detector=fake_detector,
        loader=loader,
    )
    assert isinstance(results, NoiseStressResults)
    assert results.nstdb is VERIFICATION
    assert loader.calls == [(nstdb_dir / name, 0) for name in NOISE_STRESS_RECORDS]
    assert [evaluation.record for evaluation in results.records] == list(NOISE_STRESS_RECORDS)
    assert [evaluation.counts for evaluation in results.records] == [
        expected_counts(name) for name in NOISE_STRESS_RECORDS
    ]
    assert [entry.snr_db for entry in results.by_snr] == list(SNRS)
    for entry in results.by_snr:
        j = SNRS.index(entry.snr_db)
        names = [name for name in NOISE_STRESS_RECORDS if snr_db(name) == entry.snr_db]
        assert entry.statistics == aggregate_statistics([expected_counts(name) for name in names])
        assert (entry.statistics.tp, entry.statistics.fn, entry.statistics.fp) == (2 * j + 2, 1, j)
        assert entry.statistics.n_records == 2
    assert results.clean == aggregate_statistics(
        [RecordCounts("118", 100, 3, 2), RecordCounts("119", 90, 1, 7)]
    )
    assert (results.clean.tp, results.clean.fn, results.clean.fp) == (190, 4, 9)


def test_snr_statistics_values(
    nstdb_dir: Path, fake_detector: Callable[..., npt.NDArray[np.int64]]
) -> None:
    results = evaluate_noise_stress(
        nstdb_dir,
        MITDB_RECORDS,
        EvaluationSettings(),
        nstdb=VERIFICATION,
        detector=fake_detector,
        loader=load_record,
    )
    first = results.by_snr[0]
    assert first == SnrStatistics(snr_db=24, statistics=first.statistics)
    assert first.statistics.gross_se_percent == 200 / 3
    assert first.statistics.gross_ppv_percent == 100.0
    last = results.by_snr[-1]
    assert last.snr_db == -6
    assert last.statistics.gross_se_percent == 1200 / 13
    assert last.statistics.gross_ppv_percent == 1200 / 17


def test_settings_reach_the_loader_and_the_detector(
    nstdb_dir: Path, fake_detector: Callable[..., npt.NDArray[np.int64]]
) -> None:
    loader = RecordingLoader()
    mains: list[int] = []

    def detector(signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int) -> Any:
        mains.append(mains_hz)
        return fake_detector(signal_mv, fs_hz, mains_hz)

    evaluate_noise_stress(
        nstdb_dir,
        MITDB_RECORDS,
        EvaluationSettings(channel=1, mains_hz=50),
        nstdb=VERIFICATION,
        detector=detector,
        loader=loader,
    )
    assert {channel for _, channel in loader.calls} == {1}
    assert mains == [50] * 12


@pytest.mark.parametrize(
    ("mitdb_records", "message"),
    [
        (MITDB_RECORDS[:2], "needs record 119 .* there 0 times"),
        ((MITDB_RECORDS[0], MITDB_RECORDS[2]), "needs record 118 .* there 0 times"),
        ((), "needs record 118 .* there 0 times"),
        ((*MITDB_RECORDS, record_evaluation("119", 1, 0, 0)), "needs record 119 .* there 2 times"),
    ],
)
def test_clean_records_are_required_before_anything_is_loaded(
    nstdb_dir: Path,
    fake_detector: Callable[..., npt.NDArray[np.int64]],
    mitdb_records: tuple[RecordEvaluation, ...],
    message: str,
) -> None:
    loader = RecordingLoader()
    with pytest.raises(InvalidInputError, match=message):
        evaluate_noise_stress(
            nstdb_dir,
            mitdb_records,
            EvaluationSettings(),
            nstdb=VERIFICATION,
            detector=fake_detector,
            loader=loader,
        )
    assert loader.calls == []


def test_absent_noise_stress_record_propagates_the_error_of_wfdb(
    tmp_path: Path, fake_detector: Callable[..., npt.NDArray[np.int64]]
) -> None:
    with pytest.raises(FileNotFoundError):
        evaluate_noise_stress(
            tmp_path,
            MITDB_RECORDS,
            EvaluationSettings(),
            nstdb=VERIFICATION,
            detector=fake_detector,
            loader=load_record,
        )
