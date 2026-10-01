"""Requirement tests of SRS-004: baseline wander removal (risk control RC-002).

Each gain is measured as SRS-004 states: the input lasts at least ten periods of its
frequency (60 s for the constant offset), and the amplitude is the RMS of the second half of
the signal. Every input also lasts at least 10 s, the shortest input that the filter accepts
(SRS-003).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.filters import remove_baseline_wander

SAMPLING_FREQUENCIES_HZ = [360.0, 250.0]
STOP_FREQUENCIES_HZ = [0.05, 0.1]
PASS_FREQUENCIES_HZ = [1.0, 5.0, 10.0, 20.0, 40.0]
PHASES = [pytest.param(0.0, id="sine"), pytest.param(math.pi / 2.0, id="cosine")]

AMPLITUDE_MV = 1.0
MIN_ATTENUATION_DB = 20.0
MAX_GAIN_CHANGE_DB = 0.5
OFFSET_DURATION_S = 60.0
MIN_PERIODS = 10
MIN_INPUT_S = 10.0


def _duration_s(frequency_hz: float) -> float:
    """At least ten periods of the frequency, and at least the 10 s that SRS-003 requires."""
    return max(MIN_PERIODS / frequency_hz, MIN_INPUT_S)


def _filtered(signal_mv: Any, fs_hz: float) -> Any:
    """The filter output, checked to have one finite sample per input sample."""
    output = remove_baseline_wander(signal_mv, fs_hz)
    assert isinstance(output, np.ndarray)
    assert output.shape == signal_mv.shape
    assert np.all(np.isfinite(output))
    return output


@pytest.mark.requirement("SRS-004")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_constant_offset_is_attenuated_by_at_least_20_db(
    fs_hz: float, second_half_rms: Callable[..., float]
) -> None:
    """A constant offset is attenuated by at least 20 dB.

    Input: a constant of 1 mV lasting 60 s, at 360 Hz and at 250 Hz.
    Expected: the RMS of the second half of the output is at most 1 mV * 10^(-20/20) = 0.1 mV.
    The output may be exactly zero, so the RMS is compared with the limit instead of taking
    the logarithm of a ratio.
    """
    offset = np.full(round(OFFSET_DURATION_S * fs_hz), AMPLITUDE_MV, dtype=np.float64)

    output = _filtered(offset, fs_hz)

    limit_mv = second_half_rms(offset) * 10.0 ** (-MIN_ATTENUATION_DB / 20.0)
    assert second_half_rms(output) <= limit_mv


@pytest.mark.requirement("SRS-004")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("frequency_hz", STOP_FREQUENCIES_HZ)
@pytest.mark.parametrize("phase_rad", PHASES)
def test_sinusoid_at_or_below_0_1_hz_is_attenuated_by_at_least_20_db(
    fs_hz: float,
    frequency_hz: float,
    phase_rad: float,
    make_sinusoid: Callable[..., Any],
    second_half_rms: Callable[..., float],
) -> None:
    """Sinusoidal components at 0.1 Hz and below are attenuated by at least 20 dB.

    Input: a sinusoid of 1 mV at 0.05 Hz (200 s) and at 0.1 Hz (100 s), ten periods each,
    starting at phase 0 and at phase 90 degrees, at 360 Hz and at 250 Hz.
    Expected: the RMS of the second half of the output is at most 10^(-20/20) times the RMS
    of the second half of the input.
    """
    duration_s = _duration_s(frequency_hz)
    assert duration_s * frequency_hz >= MIN_PERIODS
    sinusoid = make_sinusoid(frequency_hz, fs_hz, duration_s, phase_rad=phase_rad)

    output = _filtered(sinusoid, fs_hz)

    limit_mv = second_half_rms(sinusoid) * 10.0 ** (-MIN_ATTENUATION_DB / 20.0)
    assert second_half_rms(output) <= limit_mv


@pytest.mark.requirement("SRS-004")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("frequency_hz", PASS_FREQUENCIES_HZ)
@pytest.mark.parametrize("phase_rad", PHASES)
def test_components_from_1_to_40_hz_keep_their_amplitude_within_half_a_db(
    fs_hz: float,
    frequency_hz: float,
    phase_rad: float,
    make_sinusoid: Callable[..., Any],
    second_half_rms: Callable[..., float],
) -> None:
    """Components between 1 Hz and 40 Hz change in amplitude by no more than 0.5 dB.

    Input: a sinusoid of 1 mV at 1, 5, 10, 20 and 40 Hz lasting 10 s (ten periods at 1 Hz,
    more above), starting at phase 0 and at phase 90 degrees, at 360 Hz and at 250 Hz.
    Expected: the gain, 20 * log10 of the RMS of the second half of the output over the RMS
    of the second half of the input, lies within -0.5 dB and +0.5 dB.
    """
    duration_s = _duration_s(frequency_hz)
    assert duration_s * frequency_hz >= MIN_PERIODS
    sinusoid = make_sinusoid(frequency_hz, fs_hz, duration_s, phase_rad=phase_rad)

    output = _filtered(sinusoid, fs_hz)

    ratio = second_half_rms(output) / second_half_rms(sinusoid)
    assert ratio > 0.0
    gain_db = 20.0 * math.log10(ratio)
    assert -MAX_GAIN_CHANGE_DB <= gain_db <= MAX_GAIN_CHANGE_DB
