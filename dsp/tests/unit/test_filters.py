"""Unit tests of the filter design, the closed-form initial state and the filtering."""

import math
from typing import Any

import numpy as np
import pytest
from scipy import signal

from sinus_dsp import filters
from sinus_dsp._types import FloatArray
from sinus_dsp.errors import InvalidInputError

FS_VALUES = (125.0, 250.0, 360.0, 1000.0)


def _steady_gain(sos: FloatArray, freq_hz: float, fs_hz: float) -> float:
    """Magnitude of the frequency response of the sections at ``freq_hz``."""
    _, h = signal.sosfreqz(sos, worN=[freq_hz], fs=fs_hz)
    return float(np.abs(h[0]))


def _db(gain: float) -> float:
    return 20.0 * math.log10(gain)


# --- design -----------------------------------------------------------------------------------


def test_constants() -> None:
    assert filters.BASELINE_CUTOFF_HZ == 0.5
    assert filters.NOTCH_Q == 30.0


@pytest.mark.parametrize("fs_hz", FS_VALUES)
@pytest.mark.parametrize("cutoff_hz", [0.5, 5.0, 15.0])
def test_highpass_matches_scipy_butter(fs_hz: float, cutoff_hz: float) -> None:
    sos = filters.butterworth2_highpass_sos(cutoff_hz, fs_hz)
    reference = signal.butter(2, cutoff_hz, "highpass", fs=fs_hz, output="sos")
    assert sos.shape == (1, 6)
    assert sos.dtype == np.float64
    assert np.max(np.abs(sos - reference)) <= 1e-12


@pytest.mark.parametrize("fs_hz", FS_VALUES)
@pytest.mark.parametrize("cutoff_hz", [0.5, 5.0, 15.0])
def test_lowpass_matches_scipy_butter(fs_hz: float, cutoff_hz: float) -> None:
    sos = filters.butterworth2_lowpass_sos(cutoff_hz, fs_hz)
    reference = signal.butter(2, cutoff_hz, "lowpass", fs=fs_hz, output="sos")
    assert sos.shape == (1, 6)
    assert np.max(np.abs(sos - reference)) <= 1e-12


@pytest.mark.parametrize("fs_hz", FS_VALUES)
@pytest.mark.parametrize("mains_hz", [50, 60])
def test_notch_equals_scipy_iirnotch_bit_for_bit(fs_hz: float, mains_hz: int) -> None:
    sos = filters.notch_sos(float(mains_hz), 30.0, fs_hz)
    b, a = signal.iirnotch(mains_hz, 30.0, fs=fs_hz)
    assert sos.shape == (1, 6)
    assert sos[0].tolist() == [*b.tolist(), *a.tolist()]


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_sections_are_normalised(fs_hz: float) -> None:
    for sos in (
        filters.butterworth2_highpass_sos(5.0, fs_hz),
        filters.butterworth2_lowpass_sos(15.0, fs_hz),
        filters.notch_sos(50.0, 30.0, fs_hz),
    ):
        assert sos[0, 3] == 1.0


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_highpass_has_exactly_zero_gain_at_dc(fs_hz: float) -> None:
    b0, b1, b2 = filters.butterworth2_highpass_sos(0.5, fs_hz)[0, :3].tolist()
    assert b0 + b1 + b2 == 0.0


def test_named_designs() -> None:
    assert np.array_equal(
        filters.baseline_sos(360.0), filters.butterworth2_highpass_sos(0.5, 360.0)
    )
    assert np.array_equal(filters.mains_sos(360.0, 50), filters.notch_sos(50.0, 30.0, 360.0))
    assert np.array_equal(filters.mains_sos(250.0, 60), filters.notch_sos(60.0, 30.0, 250.0))
    assert np.array_equal(filters.mains_sos(250.0, 60.0), filters.mains_sos(250.0, 60))  # type: ignore[arg-type]


@pytest.mark.parametrize("cutoff_hz", [0.0, -1.0, 180.0, 200.0, float("nan"), float("inf")])
def test_butterworth_rejects_a_cutoff_out_of_range(cutoff_hz: float) -> None:
    with pytest.raises(InvalidInputError, match="cut-off frequency"):
        filters.butterworth2_highpass_sos(cutoff_hz, 360.0)
    with pytest.raises(InvalidInputError, match="cut-off frequency"):
        filters.butterworth2_lowpass_sos(cutoff_hz, 360.0)


@pytest.mark.parametrize("fs_hz", [0.0, -360.0, float("nan"), float("inf")])
def test_design_rejects_a_bad_sampling_frequency(fs_hz: float) -> None:
    with pytest.raises(InvalidInputError):
        filters.butterworth2_highpass_sos(0.5, fs_hz)
    with pytest.raises(InvalidInputError):
        filters.notch_sos(50.0, 30.0, fs_hz)


@pytest.mark.parametrize("notch_hz", [0.0, -50.0, 180.0, 500.0, float("nan")])
def test_notch_rejects_a_frequency_out_of_range(notch_hz: float) -> None:
    with pytest.raises(InvalidInputError, match="notch frequency"):
        filters.notch_sos(notch_hz, 30.0, 360.0)


@pytest.mark.parametrize("q", [0.0, -1.0, float("nan"), float("inf")])
def test_notch_rejects_a_bad_quality_factor(q: float) -> None:
    with pytest.raises(InvalidInputError, match="quality factor"):
        filters.notch_sos(50.0, q, 360.0)


@pytest.mark.parametrize("mains_hz", [0, 55, 100, 50.5])
def test_mains_sos_rejects_other_frequencies(mains_hz: Any) -> None:
    with pytest.raises(InvalidInputError, match="mains frequency"):
        filters.mains_sos(360.0, mains_hz)


# --- steady-state gains of the designs (the computed table of the design) ----------------------


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
def test_baseline_design_gains(fs_hz: float) -> None:
    sos = filters.baseline_sos(fs_hz)
    assert _db(_steady_gain(sos, 0.05, fs_hz)) == pytest.approx(-40.00, abs=0.01)
    assert _db(_steady_gain(sos, 0.1, fs_hz)) == pytest.approx(-27.97, abs=0.01)
    assert _db(_steady_gain(sos, 1.0, fs_hz)) == pytest.approx(-0.263, abs=0.001)
    for freq_hz in (5.0, 10.0, 20.0, 40.0):
        assert abs(_db(_steady_gain(sos, freq_hz, fs_hz))) < 0.001


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
@pytest.mark.parametrize("mains_hz", [50, 60])
def test_notch_design_gains(fs_hz: float, mains_hz: int) -> None:
    sos = filters.mains_sos(fs_hz, mains_hz)
    assert _steady_gain(sos, float(mains_hz), fs_hz) < 10.0 ** (-200.0 / 20.0)
    for freq_hz in (1.0, 5.0, 10.0, 20.0, 40.0):
        assert abs(_db(_steady_gain(sos, freq_hz, fs_hz))) < 0.03
    assert _steady_gain(sos, 0.0, fs_hz) == pytest.approx(1.0, abs=1e-12)


# --- initial state ----------------------------------------------------------------------------


@pytest.mark.parametrize("fs_hz", FS_VALUES)
@pytest.mark.parametrize("level", [1.0, -3.7, 1234.5678, 1e-3, 0.0])
def test_highpass_output_is_exactly_zero_on_a_constant(fs_hz: float, level: float) -> None:
    x = np.full(int(20 * fs_hz), level)
    y = filters.apply_sos(filters.baseline_sos(fs_hz), x)
    assert y.shape == x.shape
    assert np.all(y == 0.0)


def test_initial_state_closed_form_of_the_highpass() -> None:
    sos = filters.baseline_sos(360.0)
    b0, b1, b2, _, _a1, _a2 = sos[0].tolist()
    state = filters.initial_state(sos, 2.5)
    assert state.shape == (1, 2)
    assert state[0, 0] == (b1 + b2) * 2.5
    assert state[0, 1] == b2 * 2.5


def test_initial_state_closed_form_of_two_sections() -> None:
    fs_hz = 360.0
    sos = np.vstack(
        [filters.notch_sos(50.0, 30.0, fs_hz), filters.butterworth2_lowpass_sos(15.0, fs_hz)]
    )
    level = 0.75
    state = filters.initial_state(sos, level)
    assert state.shape == (2, 2)
    for i in range(2):
        b0, b1, b2, _, a1, a2 = sos[i].tolist()
        gain = (b0 + b1 + b2) / (1.0 + a1 + a2)
        assert state[i, 0] == (b1 + b2 - (a1 + a2) * gain) * level
        assert state[i, 1] == (b2 - a2 * gain) * level
        level = gain * level


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_initial_state_is_close_to_sosfilt_zi(fs_hz: float) -> None:
    sos = np.vstack(
        [
            filters.notch_sos(50.0, 30.0, fs_hz),
            filters.butterworth2_lowpass_sos(15.0, fs_hz),
            filters.butterworth2_highpass_sos(5.0, fs_hz),
        ]
    )
    expected = signal.sosfilt_zi(sos) * 1.7
    assert np.allclose(filters.initial_state(sos, 1.7), expected, rtol=0.0, atol=1e-9)


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
def test_notch_and_lowpass_keep_a_constant(fs_hz: float) -> None:
    x = np.full(int(10 * fs_hz), 0.8)
    for sos in (filters.mains_sos(fs_hz, 50), filters.butterworth2_lowpass_sos(15.0, fs_hz)):
        y = filters.apply_sos(sos, x)
        assert np.max(np.abs(y - 0.8)) < 1e-12


def test_initial_state_of_a_highpass_feeds_zero_to_the_next_section() -> None:
    sos = np.vstack(
        [
            filters.butterworth2_highpass_sos(5.0, 360.0),
            filters.butterworth2_lowpass_sos(15.0, 360.0),
        ]
    )
    state = filters.initial_state(sos, 3.0)
    assert np.all(state[1] == 0.0)


# --- filtering --------------------------------------------------------------------------------


def test_apply_sos_equals_sosfilt_with_the_closed_form_state() -> None:
    rng = np.random.default_rng(1)
    x = rng.standard_normal(2000)
    sos = filters.mains_sos(360.0, 60)
    expected, _ = signal.sosfilt(sos, x, zi=filters.initial_state(sos, float(x[0])))
    y = filters.apply_sos(sos, x)
    assert np.array_equal(y, expected)


def test_apply_sos_does_not_modify_its_input_and_returns_a_new_array() -> None:
    rng = np.random.default_rng(2)
    x = rng.standard_normal(1000)
    before = x.copy()
    y = filters.apply_sos(filters.baseline_sos(360.0), x)
    assert np.array_equal(x, before)
    assert not np.shares_memory(x, y)
    assert y.dtype == np.float64


def test_apply_sos_does_not_depend_on_earlier_calls() -> None:
    rng = np.random.default_rng(3)
    x = rng.standard_normal(1000)
    sos = filters.baseline_sos(250.0)
    first = filters.apply_sos(sos, x)
    filters.apply_sos(sos, rng.standard_normal(500) * 100.0)
    assert np.array_equal(filters.apply_sos(sos, x), first)


def test_apply_sos_is_causal() -> None:
    rng = np.random.default_rng(4)
    x = rng.standard_normal(1000)
    changed = x.copy()
    changed[600:] += 5.0
    sos = filters.mains_sos(360.0, 50)
    assert np.array_equal(filters.apply_sos(sos, x)[:600], filters.apply_sos(sos, changed)[:600])


def test_apply_sos_rejects_bad_shapes() -> None:
    sos = filters.baseline_sos(360.0)
    with pytest.raises(InvalidInputError, match="non-empty 1-D"):
        filters.apply_sos(sos, np.zeros(0))
    with pytest.raises(InvalidInputError, match="non-empty 1-D"):
        filters.apply_sos(sos, np.zeros((2, 10)))
    with pytest.raises(InvalidInputError, match="n_sections, 6"):
        filters.apply_sos(np.zeros(6), np.zeros(10))


# --- public filters ---------------------------------------------------------------------------


def test_remove_baseline_wander_is_the_baseline_stage() -> None:
    rng = np.random.default_rng(5)
    x = rng.standard_normal(3600)
    expected = filters.apply_sos(filters.baseline_sos(360.0), x)
    assert np.array_equal(filters.remove_baseline_wander(x, 360.0), expected)
    assert np.array_equal(filters.remove_baseline_wander(x.tolist(), 360), expected)


def test_remove_mains_interference_is_the_mains_stage() -> None:
    rng = np.random.default_rng(6)
    x = rng.standard_normal(2500)
    for mains_hz in (50, 60):
        expected = filters.apply_sos(filters.mains_sos(250.0, mains_hz), x)
        assert np.array_equal(filters.remove_mains_interference(x, 250.0, mains_hz), expected)


def test_public_filters_do_not_modify_their_input() -> None:
    rng = np.random.default_rng(7)
    x = rng.standard_normal(3600)
    before = x.copy()
    filters.remove_baseline_wander(x, 360.0)
    filters.remove_mains_interference(x, 360.0, 50)
    assert np.array_equal(x, before)


def test_public_filters_validate_before_filtering() -> None:
    short = np.zeros(100)
    with pytest.raises(InvalidInputError, match="shorter than"):
        filters.remove_baseline_wander(short, 360.0)
    with pytest.raises(InvalidInputError, match="shorter than"):
        filters.remove_mains_interference(short, 360.0, 50)
    with pytest.raises(InvalidInputError, match="sampling frequency is outside"):
        filters.remove_baseline_wander(np.zeros(3600), 100.0)


def test_remove_mains_interference_checks_the_signal_before_the_mains_setting() -> None:
    with pytest.raises(InvalidInputError, match="shorter than"):
        filters.remove_mains_interference(np.zeros(100), 360.0, 55)
    with pytest.raises(InvalidInputError, match="mains frequency"):
        filters.remove_mains_interference(np.zeros(3600), 360.0, 55)


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
@pytest.mark.parametrize("mains_hz", [50, 60])
def test_mains_sinusoid_is_attenuated_after_settling(fs_hz: float, mains_hz: int) -> None:
    n = int(4 * fs_hz) + int(10 * fs_hz)
    t = np.arange(n) / fs_hz
    x = np.sin(2.0 * np.pi * mains_hz * t)
    y = filters.remove_mains_interference(x, fs_hz, mains_hz)
    half = n // 2
    rms_in = math.sqrt(math.fsum((x[half:] ** 2).tolist()) / (n - half))
    rms_out = math.sqrt(math.fsum((y[half:] ** 2).tolist()) / (n - half))
    assert _db(rms_out / rms_in) < -60.0
