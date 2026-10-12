"""Unit tests of the display low-pass (architecture §16.2, §16.3) and its place in the pipeline."""

import math
from typing import Any

import numpy as np
import pytest
from scipy import signal

from sinus_dsp.display import (
    DISPLAY_CUTOFF_HZ,
    DISPLAY_HALF_LENGTH_MS,
    DISPLAY_MAX_DELAY_SAMPLES,
    apply_display_lowpass,
    display_delay_samples,
    display_lowpass,
    display_lowpass_taps,
)
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.pipeline import detect_beats, run_pipeline
from sinus_dsp.synthetic import synthetic_ecg

RATES = [125.0, 250.0, 360.0, 500.0, 1000.0, 147.5, 333.3]


def test_constants() -> None:
    assert DISPLAY_CUTOFF_HZ == 50.0
    assert DISPLAY_HALF_LENGTH_MS == 30
    assert DISPLAY_MAX_DELAY_SAMPLES == 30


@pytest.mark.parametrize(
    ("fs", "delay"),
    [(125.0, 4), (250.0, 8), (360.0, 11), (500.0, 15), (1000.0, 30), (125.0, 4)],
)
def test_delay(fs: float, delay: int) -> None:
    assert display_delay_samples(fs) == delay
    assert display_lowpass_taps(fs).size == 2 * delay + 1


def test_the_delay_never_exceeds_the_maximum() -> None:
    for fs in np.arange(125.0, 1000.5, 0.5):
        assert 1 <= display_delay_samples(float(fs)) <= DISPLAY_MAX_DELAY_SAMPLES


@pytest.mark.parametrize("fs", RATES)
def test_taps_are_symmetric_normalised_and_match_firwin(fs: float) -> None:
    taps = display_lowpass_taps(fs)
    assert taps.dtype == np.float64
    assert np.allclose(taps, taps[::-1], rtol=0.0, atol=1e-15)
    assert abs(float(np.sum(taps)) - 1.0) < 1e-14
    reference = signal.firwin(taps.size, DISPLAY_CUTOFF_HZ, window="hamming", fs=fs)
    assert np.allclose(taps, reference, rtol=0.0, atol=1e-12)


def test_taps_follow_the_written_formula_at_360_hz() -> None:
    fs, half = 360.0, 11
    n = 2 * half + 1
    raw = []
    for k in range(n):
        j = k - half
        ideal = (
            2.0 * 50.0 / fs if j == 0 else math.sin(2.0 * math.pi * 50.0 * j / fs) / (math.pi * j)
        )
        raw.append((0.54 - 0.46 * math.cos(2.0 * math.pi * k / (n - 1))) * ideal)
    total = 0.0
    for value in raw:
        total += value
    assert display_lowpass_taps(fs).tolist() == [value / total for value in raw]


def test_taps_are_a_new_array() -> None:
    first = display_lowpass_taps(360.0)
    first[0] = 99.0
    assert display_lowpass_taps(360.0)[0] != 99.0


@pytest.mark.parametrize("fs", [124.9, 1000.1, float("nan"), float("inf"), "360", True, None])
def test_bad_sampling_frequencies_are_rejected(fs: Any) -> None:
    for function in (display_delay_samples, display_lowpass_taps):
        with pytest.raises(InvalidInputError):
            function(fs)
    with pytest.raises(InvalidInputError):
        display_lowpass(np.zeros(100), fs)


def _loop_filter(taps: list[float], x: list[float]) -> list[float]:
    out = []
    for n in range(len(x)):
        total = taps[0] * x[n]
        for k in range(1, len(taps)):
            total = total + taps[k] * x[max(n - k, 0)]
        out.append(total)
    return out


def test_filtering_equals_the_written_loop_bit_for_bit() -> None:
    rng = np.random.default_rng(7)
    x = rng.standard_normal(200) * 3.0 + 1.5
    taps = display_lowpass_taps(250.0)
    got = apply_display_lowpass(taps, x)
    assert got.tolist() == _loop_filter(taps.tolist(), x.tolist())


def test_a_constant_input_gives_the_constant_from_the_first_sample() -> None:
    for value in (0.0, 1.25, -7.5):
        out = display_lowpass(np.full(50, value), 360.0)
        assert np.allclose(out, value, rtol=0.0, atol=1e-14)
    assert display_lowpass(np.zeros(50), 360.0).tolist() == [0.0] * 50


def test_the_impulse_response_is_delayed_by_m_samples() -> None:
    x = np.zeros(80)
    x[20] = 1.0
    out = display_lowpass(x, 360.0)
    assert int(np.argmax(out)) == 20 + 11
    assert out[20 + 11] > 0.2


def test_single_sample_and_inputs_are_not_modified() -> None:
    assert display_lowpass(np.array([2.0]), 360.0).tolist() == pytest.approx([2.0])
    x = np.arange(30.0)
    taps = display_lowpass_taps(360.0)
    copy_x, copy_taps = x.copy(), taps.copy()
    out = apply_display_lowpass(taps, x)
    assert out is not x and out.shape == x.shape and out.dtype == np.float64
    assert x.tobytes() == copy_x.tobytes() and taps.tobytes() == copy_taps.tobytes()


def test_display_lowpass_converts_lists() -> None:
    assert display_lowpass([1, 2, 3], 360.0).dtype == np.float64


@pytest.mark.parametrize(
    "x",
    [np.zeros(0), np.zeros((2, 2)), np.array([1.0, float("nan")]), np.array([float("inf")])],
)
def test_bad_signals_are_rejected(x: Any) -> None:
    with pytest.raises(InvalidInputError):
        display_lowpass(x, 360.0)
    with pytest.raises(InvalidInputError):
        apply_display_lowpass(display_lowpass_taps(360.0), x)


def test_non_numeric_signal_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        display_lowpass(["a", "b"], 360.0)


@pytest.mark.parametrize(
    "taps",
    [np.zeros(0), np.ones(4), np.ones((3, 3)), np.array([0.25, float("nan"), 0.25])],
)
def test_bad_taps_are_rejected(taps: Any) -> None:
    with pytest.raises(InvalidInputError):
        apply_display_lowpass(taps, np.zeros(10))


# --- pipeline ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ecg() -> Any:
    return synthetic_ecg(360.0, 75, "bw-mains60")


def test_pipeline_filters_the_binary64_mains_output(ecg: Any) -> None:
    result = run_pipeline(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz)
    assert result.display_delay_samples == 11
    assert result.display_taps.tolist() == display_lowpass_taps(360.0).tolist()
    assert result.display_mv is not None
    assert result.display_mv.shape == result.mains_mv.shape
    assert result.display_mv.tolist() == display_lowpass(result.mains_mv, 360.0).tolist()
    assert result.display_mv[0] == 0.0


def test_pipeline_without_display(ecg: Any) -> None:
    on = run_pipeline(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz)
    off = run_pipeline(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz, display=False)
    assert off.display_mv is None
    assert off.display_delay_samples == 11
    assert off.display_taps.tolist() == on.display_taps.tolist()
    assert (
        off.beats.tolist() == on.beats.tolist() == detect_beats(ecg.signal_mv, 360.0, 60).tolist()
    )
    assert off.mains_mv.tobytes() == on.mains_mv.tobytes()
    assert off.heart_rate == on.heart_rate


@pytest.mark.parametrize("display", [1, 0, None, "yes", np.bool_(True)])
def test_pipeline_display_must_be_a_bool(ecg: Any, display: Any) -> None:
    with pytest.raises(InvalidInputError, match="display"):
        run_pipeline(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz, display=display)


def test_pipeline_display_is_checked_before_the_input() -> None:
    with pytest.raises(InvalidInputError, match="display is not a bool"):
        run_pipeline(np.zeros(3), 360.0, 60, display=1)  # type: ignore[arg-type]


def test_r_peak_of_the_display_trace_is_not_shifted(ecg: Any) -> None:
    result = run_pipeline(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz)
    assert result.display_mv is not None
    m = result.display_delay_samples
    for beat in result.beats[2:-2].tolist():
        lo = beat - 15
        peak = int(np.argmax(result.mains_mv[lo : beat + 16]))
        shown = int(np.argmax(result.display_mv[lo + m : beat + 16 + m]))
        assert abs(shown - peak) <= 1
