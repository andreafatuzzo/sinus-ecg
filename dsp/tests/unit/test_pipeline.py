"""Unit tests of the processing chain: stage order, single validation and the result."""

import dataclasses
from typing import Any

import numpy as np
import pytest

from sinus_dsp import filters, input_checks, pipeline, qrs
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
        "detections",
        "heart_rate",
        "quality",
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
        (np.full(3600, 1000.0000000000001), 360.0, "magnitude exceeds 1000.0 mV"),
        (np.full(3600, -1e308), 360.0, "magnitude exceeds 1000.0 mV"),
    ],
)
def test_rejected_input_raises_before_any_processing(
    signal: Any, fs_hz: float, message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a stage ran on a rejected input")

    monkeypatch.setattr(pipeline, "apply_sos", fail)
    monkeypatch.setattr(pipeline, "_trace", fail)
    with pytest.raises(InvalidInputError, match=message):
        pipeline.run_pipeline(signal, fs_hz, 50)
    with pytest.raises(InvalidInputError, match=message):
        pipeline.detect_beats(signal, fs_hz, 50)
    with pytest.raises(InvalidInputError, match=message):
        pipeline.detect_marked(signal, fs_hz, 50)


@pytest.mark.parametrize("level", [1000.0, -1000.0])
def test_input_at_the_amplitude_bound_is_processed(level: float) -> None:
    signal = np.full(3600, level)
    signal[::7] = -level
    result = pipeline.run_pipeline(signal, 360.0, 50)
    assert bool(np.isfinite(result.mains_mv).all())
    assert np.array_equal(pipeline.detect_beats(signal, 360.0, 50), result.beats)


def test_input_is_validated_once(monkeypatch: pytest.MonkeyPatch, synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75)
    calls = []
    original = input_checks.validate_input

    def counting(signal_mv: Any, fs_hz: float) -> Any:
        calls.append(fs_hz)
        return original(signal_mv, fs_hz)

    monkeypatch.setattr(pipeline, "validate_input", counting)
    monkeypatch.setattr(qrs, "validate_input", counting)
    monkeypatch.setattr(filters, "validate_input", counting)
    pipeline.run_pipeline(x, 360.0, 50)
    assert calls == [360.0]
    pipeline.detect_marked(x, 360.0, 50)
    assert calls == [360.0, 360.0]
    pipeline.detect_beats(x, 360.0, 50)
    assert calls == [360.0, 360.0, 360.0]


def test_mains_setting_is_checked_by_detect_marked() -> None:
    with pytest.raises(InvalidInputError, match="shorter than"):
        pipeline.detect_marked(np.zeros(100), 360.0, 55)
    with pytest.raises(InvalidInputError, match="mains frequency"):
        pipeline.detect_marked(np.zeros(3600), 360.0, 55)


@pytest.mark.parametrize("mains_hz", [50.5, "50", True, 59.9])
@pytest.mark.parametrize("function", ["run_pipeline", "detect_marked", "detect_beats"])
def test_mains_setting_is_never_rounded(mains_hz: Any, function: str) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        getattr(pipeline, function)(np.zeros(3600), 360.0, mains_hz)
    assert str(excinfo.value) == f"mains frequency is not one of (50, 60) Hz: {mains_hz!r}"


# --- detections with their trace (architecture §13.3) -----------------------------------------


def _assert_same_detections(actual: qrs.Detections, expected: qrs.Detections) -> None:
    for field in dataclasses.fields(qrs.Detections):
        got, want = getattr(actual, field.name), getattr(expected, field.name)
        if isinstance(want, tuple):
            assert got == want, field.name
        else:
            assert got.dtype == want.dtype, field.name
            assert np.array_equal(got, want), field.name


@pytest.mark.parametrize(("fs_hz", "mains_hz"), [(360.0, 60), (250.0, 50)])
def test_detections_are_the_trace_of_the_mains_output(
    fs_hz: float, mains_hz: int, synthetic_ecg: Any
) -> None:
    variant = "bw-mains60" if mains_hz == 60 else "bw-mains50"
    x, _ = synthetic_ecg(fs_hz, 75, variant)
    result = pipeline.run_pipeline(x, fs_hz, mains_hz)
    _assert_same_detections(result.detections, qrs.trace_qrs(result.mains_mv, fs_hz).detections)
    assert result.beats is result.detections.indices
    _assert_same_detections(pipeline.detect_marked(x, fs_hz, mains_hz), result.detections)
    assert np.array_equal(pipeline.detect_beats(x, fs_hz, mains_hz), result.beats)


def test_detect_marked_types_and_new_arrays(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(250.0, 75)
    before = x.copy()
    first = pipeline.detect_marked(x.tolist(), 250, 50.0)  # type: ignore[arg-type]
    second = pipeline.detect_marked(x, 250.0, 50)
    assert np.array_equal(x, before)
    _assert_same_detections(first, second)
    assert first.indices is not second.indices
    assert first.indices.dtype == np.int64
    assert first.startup.dtype == np.bool_
    assert first.reported_at.dtype == first.peaks.dtype == np.int64
    assert first.initialisations.dtype == np.int64
    assert type(first.paths) is tuple
    assert set(first.paths) <= set(qrs.DETECTION_PATHS)


def test_detect_beats_goes_through_detect_marked_only(
    monkeypatch: pytest.MonkeyPatch, synthetic_ecg: Any
) -> None:
    # Architecture §13.3: the evaluation does not compute what it does not use.
    x, _ = synthetic_ecg(360.0, 75)
    expected = pipeline.run_pipeline(x, 360.0, 50).beats

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("detect_beats ran the whole pipeline")

    monkeypatch.setattr(pipeline, "run_pipeline", fail)
    assert np.array_equal(pipeline.detect_beats(x, 360.0, 50), expected)
    calls: list[Any] = []
    original = pipeline.detect_marked

    def recording(*args: Any) -> qrs.Detections:
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(pipeline, "detect_marked", recording)
    pipeline.detect_beats(x, 360.0, 50)
    assert len(calls) == 1


@pytest.mark.parametrize("fs_hz", [125.0, 360.0, 1000.0])
def test_flat_input_has_no_detection_and_relearns_every_eight_seconds(fs_hz: float) -> None:
    # Architecture §13.3, edge cases: the initialisation at L - 1, then one every G samples.
    samples = qrs.detector_samples(fs_hz)
    n = int(30 * fs_hz)
    detections = pipeline.detect_marked(np.full(n, 0.4), fs_hz, 50)
    for array in (detections.indices, detections.reported_at, detections.peaks):
        assert array.shape == (0,)
        assert array.dtype == np.int64
    assert detections.startup.shape == (0,)
    assert detections.startup.dtype == np.bool_
    assert detections.paths == ()
    expected = list(range(samples.learning - 1, n, samples.relearn_after))
    assert detections.initialisations.tolist() == expected
    assert len(expected) == 4


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
