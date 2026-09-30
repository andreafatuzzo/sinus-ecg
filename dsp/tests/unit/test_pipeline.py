"""Unit tests of the processing chain: stage order, single validation and the result."""

import dataclasses
from typing import Any

import numpy as np
import pytest

from sinus_dsp import filters, pipeline, qrs
from sinus_dsp.errors import InvalidInputError


def test_stages() -> None:
    assert pipeline.STAGES == ("baseline", "mains")


@pytest.mark.parametrize(("fs_hz", "mains_hz"), [(360.0, 60), (250.0, 50)])
def test_result_holds_each_stage_in_order(fs_hz: float, mains_hz: int, synthetic_ecg: Any) -> None:
    variant = "bw-mains60" if mains_hz == 60 else "bw-mains50"
    x, _ = synthetic_ecg(fs_hz, 75, variant)
    result = pipeline.run_pipeline(x, fs_hz, mains_hz)

    baseline_sos = filters.baseline_sos(fs_hz)
    mains_sos = filters.mains_sos(fs_hz, mains_hz)
    baseline = filters.apply_sos(baseline_sos, x)
    mains = filters.apply_sos(mains_sos, baseline)

    assert result.fs_hz == fs_hz
    assert result.mains_hz == mains_hz
    assert len(result.coefficients) == 2
    assert np.array_equal(result.coefficients[0], baseline_sos)
    assert np.array_equal(result.coefficients[1], mains_sos)
    assert np.array_equal(result.input_mv, x)
    assert np.array_equal(result.baseline_mv, baseline)
    assert np.array_equal(result.mains_mv, mains)
    assert np.array_equal(result.beats, qrs.detect_qrs(mains, fs_hz))
    assert result.beats.dtype == np.int64


def test_stage_outputs_equal_the_public_filters(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75, "bw-mains50")
    result = pipeline.run_pipeline(x, 360.0, 50)
    baseline = filters.remove_baseline_wander(x, 360.0)
    assert np.array_equal(result.baseline_mv, baseline)
    assert np.array_equal(result.mains_mv, filters.remove_mains_interference(baseline, 360.0, 50))


def test_result_fields_and_types(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(250.0, 75)
    result = pipeline.run_pipeline(x.tolist(), 250, 50.0)  # type: ignore[arg-type]
    assert [f.name for f in dataclasses.fields(result)] == [
        "fs_hz",
        "mains_hz",
        "coefficients",
        "input_mv",
        "baseline_mv",
        "mains_mv",
        "beats",
    ]
    assert type(result.fs_hz) is float
    assert type(result.mains_hz) is int
    assert result.input_mv.dtype == np.float64
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.mains_hz = 60  # type: ignore[misc]


def test_input_is_not_modified_and_the_result_holds_a_copy(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75)
    before = x.copy()
    result = pipeline.run_pipeline(x, 360.0, 50)
    assert np.array_equal(x, before)
    assert not np.shares_memory(result.input_mv, x)
    assert not np.shares_memory(result.baseline_mv, result.input_mv)
    assert not np.shares_memory(result.mains_mv, result.baseline_mv)


def test_detect_beats_is_the_beats_of_the_pipeline(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75, "bw-mains60")
    beats = pipeline.detect_beats(x, 360.0, 60)
    assert beats.dtype == np.int64
    assert np.array_equal(beats, pipeline.run_pipeline(x, 360.0, 60).beats)


def test_signal_is_checked_before_the_mains_setting() -> None:
    with pytest.raises(InvalidInputError, match="shorter than"):
        pipeline.run_pipeline(np.zeros(100), 360.0, 55)
    with pytest.raises(InvalidInputError, match="mains frequency"):
        pipeline.run_pipeline(np.zeros(3600), 360.0, 55)
    with pytest.raises(InvalidInputError, match="mains frequency"):
        pipeline.detect_beats(np.zeros(3600), 360.0, 0)


@pytest.mark.parametrize(
    ("signal", "fs_hz", "message"),
    [
        ([], 360.0, "signal is empty"),
        (np.full(3600, np.inf), 360.0, "non-finite"),
        (np.zeros(3599), 360.0, "shorter than"),
        (np.zeros(3600), 124.9, "sampling frequency is outside"),
        (np.zeros(20000), 1000.1, "sampling frequency is outside"),
        (np.zeros(3600), float("nan"), "sampling frequency is not finite"),
    ],
)
def test_rejected_input_raises_before_any_processing(
    signal: Any, fs_hz: float, message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a stage ran on a rejected input")

    monkeypatch.setattr(pipeline, "apply_sos", fail)
    monkeypatch.setattr(pipeline, "_detect", fail)
    with pytest.raises(InvalidInputError, match=message):
        pipeline.run_pipeline(signal, fs_hz, 50)
    with pytest.raises(InvalidInputError, match=message):
        pipeline.detect_beats(signal, fs_hz, 50)


def test_input_is_validated_once(monkeypatch: pytest.MonkeyPatch, synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75)
    calls = []
    original = pipeline.validate_input

    def counting(signal_mv: Any, fs_hz: float) -> Any:
        calls.append(fs_hz)
        return original(signal_mv, fs_hz)

    monkeypatch.setattr(pipeline, "validate_input", counting)
    monkeypatch.setattr(qrs, "validate_input", counting)
    monkeypatch.setattr(filters, "validate_input", counting)
    pipeline.run_pipeline(x, 360.0, 50)
    assert calls == [360.0]


@pytest.mark.parametrize("fs_hz", [125.0, 250.0, 360.0, 1000.0])
@pytest.mark.parametrize("level", [0.0, 1.0, -0.35])
def test_flat_input_gives_no_beats_and_zero_conditioned_output(fs_hz: float, level: float) -> None:
    result = pipeline.run_pipeline(np.full(int(10 * fs_hz), level), fs_hz, 50)
    assert result.beats.shape == (0,)
    assert result.beats.dtype == np.int64
    assert np.all(result.baseline_mv == 0.0)
    assert np.all(result.mains_mv == 0.0)


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
@pytest.mark.parametrize("heart_rate_bpm", [40, 75, 180])
@pytest.mark.parametrize("variant", ["clean", "bw-mains50", "bw-mains60"])
def test_synthetic_ecg_one_detection_per_beat_8_ms_after_the_r_centre(
    fs_hz: float, heart_rate_bpm: int, variant: str, synthetic_ecg: Any
) -> None:
    x, r_peaks = synthetic_ecg(fs_hz, heart_rate_bpm, variant)
    mains_hz = 60 if variant == "bw-mains60" else 50
    beats = pipeline.detect_beats(x, fs_hz, mains_hz)
    offset = {360.0: 3, 250.0: 2}[fs_hz]
    assert beats.tolist() == (r_peaks + offset).tolist()


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
def test_clean_ecg_gives_the_same_beats_with_either_mains_setting(
    fs_hz: float, synthetic_ecg: Any
) -> None:
    x, _ = synthetic_ecg(fs_hz, 75)
    assert np.array_equal(pipeline.detect_beats(x, fs_hz, 50), pipeline.detect_beats(x, fs_hz, 60))


@pytest.mark.parametrize("fs_hz", [125.0, 1000.0])
def test_limits_of_the_sampling_frequency_range(fs_hz: float, synthetic_ecg: Any) -> None:
    x, r_peaks = synthetic_ecg(fs_hz, 75, "bw-mains50")
    beats = pipeline.detect_beats(x, fs_hz, 50)
    assert beats.shape == r_peaks.shape
    assert int(np.max(np.abs(beats - r_peaks))) <= 0.150 * fs_hz
    assert int(np.min(np.diff(beats))) >= qrs.detector_samples(fs_hz).refractory
