"""Requirement tests of SRS-005: mains interference removal (risk control RC-002).

Each gain is measured as SRS-005 states: the input lasts at least ten periods of its
frequency and at least 2 s, and the amplitude is the RMS of the second half of the signal.
Every input lasts 10 s, the shortest input that the filter accepts (SRS-003), which satisfies
both conditions at every frequency tested.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.filters import remove_mains_interference

SAMPLING_FREQUENCIES_HZ = [360.0, 250.0]
MAINS_SETTINGS_HZ = [50, 60]
PASS_FREQUENCIES_HZ = [1.0, 5.0, 10.0, 20.0, 40.0]
PHASES = [pytest.param(0.0, id="sine"), pytest.param(math.pi / 2.0, id="cosine")]

MIN_ATTENUATION_DB = 30.0
MAX_GAIN_CHANGE_DB = 0.5
DURATION_S = 10.0
MIN_PERIODS = 10
MIN_DURATION_S = 2.0


def _filtered(signal_mv: Any, fs_hz: float, mains_hz: int) -> Any:
    """The filter output, checked to have one finite sample per input sample."""
    output = remove_mains_interference(signal_mv, fs_hz, mains_hz)
    assert isinstance(output, np.ndarray)
    assert output.shape == signal_mv.shape
    assert np.all(np.isfinite(output))
    return output


@pytest.mark.requirement("SRS-005")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("mains_hz", MAINS_SETTINGS_HZ)
@pytest.mark.parametrize("phase_rad", PHASES)
def test_sinusoid_at_the_configured_frequency_is_attenuated_by_at_least_30_db(
    fs_hz: float,
    mains_hz: int,
    phase_rad: float,
    make_sinusoid: Callable[..., Any],
    second_half_rms: Callable[..., float],
) -> None:
    """A sinusoid at the configured mains frequency is attenuated by at least 30 dB.

    Input: a sinusoid of 1 mV at the configured frequency, for the settings 50 Hz and 60 Hz,
    lasting 10 s (500 or 600 periods), starting at phase 0 and at phase 90 degrees, at 360 Hz
    and at 250 Hz.
    Expected: the RMS of the second half of the output is at most 10^(-30/20) times the RMS
    of the second half of the input. The limit is compared on the RMS values, because the
    output may be zero.
    """
    assert DURATION_S >= MIN_DURATION_S
    assert DURATION_S * mains_hz >= MIN_PERIODS
    sinusoid = make_sinusoid(float(mains_hz), fs_hz, DURATION_S, phase_rad=phase_rad)

    output = _filtered(sinusoid, fs_hz, mains_hz)

    limit_mv = second_half_rms(sinusoid) * 10.0 ** (-MIN_ATTENUATION_DB / 20.0)
    assert second_half_rms(output) <= limit_mv


@pytest.mark.requirement("SRS-005")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("mains_hz", MAINS_SETTINGS_HZ)
@pytest.mark.parametrize("frequency_hz", PASS_FREQUENCIES_HZ)
@pytest.mark.parametrize("phase_rad", PHASES)
def test_components_from_1_to_40_hz_keep_their_amplitude_within_half_a_db(
    fs_hz: float,
    mains_hz: int,
    frequency_hz: float,
    phase_rad: float,
    make_sinusoid: Callable[..., Any],
    second_half_rms: Callable[..., float],
) -> None:
    """Components between 1 Hz and 40 Hz change in amplitude by no more than 0.5 dB.

    Input: a sinusoid of 1 mV at 1, 5, 10, 20 and 40 Hz lasting 10 s (ten periods at 1 Hz,
    more above), starting at phase 0 and at phase 90 degrees, for the settings 50 Hz and
    60 Hz, at 360 Hz and at 250 Hz.
    Expected: the gain, 20 * log10 of the RMS of the second half of the output over the RMS
    of the second half of the input, lies within -0.5 dB and +0.5 dB.
    """
    assert DURATION_S >= MIN_DURATION_S
    assert DURATION_S * frequency_hz >= MIN_PERIODS
    sinusoid = make_sinusoid(frequency_hz, fs_hz, DURATION_S, phase_rad=phase_rad)

    output = _filtered(sinusoid, fs_hz, mains_hz)

    ratio = second_half_rms(output) / second_half_rms(sinusoid)
    assert ratio > 0.0
    gain_db = 20.0 * math.log10(ratio)
    assert -MAX_GAIN_CHANGE_DB <= gain_db <= MAX_GAIN_CHANGE_DB
