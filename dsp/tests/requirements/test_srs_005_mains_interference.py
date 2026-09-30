"""Requirement tests of SRS-005: mains interference removal (risk control RC-002).

Each gain is measured as SRS-005 states: the input lasts at least ten periods of its
frequency and at least 2 s, and the amplitude is the RMS of the second half of the signal.
Every input lasts 10 s, the shortest input that the filter accepts (SRS-003), which satisfies
both conditions at every frequency tested.

A setting other than 50 Hz or 60 Hz must be rejected with an explicit error and no filtered
signal. It is checked on the mains filter and on the two public functions that configure it
from a mains setting (the processing pipeline and the beat detection built on it), with an
otherwise valid input, so that the setting is the only reason to reject it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError, SinusError
from sinus_dsp.filters import remove_mains_interference
from sinus_dsp.pipeline import detect_beats, run_pipeline

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


# --- Settings other than 50 Hz or 60 Hz -------------------------------------------------------

Configured = Callable[[Any, float, Any], Any]


def _mains_filter(signal: Any, fs_hz: float, mains_hz: Any) -> Any:
    return remove_mains_interference(signal, fs_hz, mains_hz)


def _pipeline(signal: Any, fs_hz: float, mains_hz: Any) -> Any:
    return run_pipeline(signal, fs_hz, mains_hz)


def _beats(signal: Any, fs_hz: float, mains_hz: Any) -> Any:
    return detect_beats(signal, fs_hz, mains_hz)


CONFIGURED = [
    pytest.param(_mains_filter, id="remove_mains_interference"),
    pytest.param(_pipeline, id="run_pipeline"),
    pytest.param(_beats, id="detect_beats"),
]

# The settings named by the verification of SRS-005.
INVALID_SETTINGS = [
    pytest.param(49, id="49Hz"),
    pytest.param(51, id="51Hz"),
    pytest.param(59, id="59Hz"),
    pytest.param(61, id="61Hz"),
    pytest.param(100, id="100Hz"),
    pytest.param(math.nan, id="NaN"),
    pytest.param(math.inf, id="+inf"),
    pytest.param(-math.inf, id="-inf"),
]

# Further settings other than 50 Hz or 60 Hz: 0.1 Hz on each side of both settings (a
# setting rounded or truncated to the nearest whole number would be accepted), zero,
# negative values and the first harmonics.
OTHER_INVALID_SETTINGS = [
    pytest.param(49.9, id="49.9Hz"),
    pytest.param(50.1, id="50.1Hz"),
    pytest.param(59.9, id="59.9Hz"),
    pytest.param(60.1, id="60.1Hz"),
    pytest.param(0, id="0Hz"),
    pytest.param(-50, id="-50Hz"),
    pytest.param(-60, id="-60Hz"),
    pytest.param(120, id="120Hz"),
]


def _assert_setting_rejected(operation: Configured, fs_hz: float, mains_hz: Any) -> None:
    """The call raises the explicit error of SRS-005, so it returns no filtered signal."""
    signal = np.sin(2.0 * np.pi * 10.0 * np.arange(round(DURATION_S * fs_hz)) / fs_hz)
    with pytest.raises(InvalidInputError) as excinfo:
        operation(signal, fs_hz, mains_hz)
    assert isinstance(excinfo.value, SinusError)
    assert str(excinfo.value).strip(), "the error carries no message"


@pytest.mark.requirement("SRS-005")
@pytest.mark.parametrize("operation", CONFIGURED)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("mains_hz", INVALID_SETTINGS)
def test_setting_other_than_50_or_60_hz_is_rejected(
    operation: Configured, fs_hz: float, mains_hz: Any
) -> None:
    """A mains setting of 49, 51, 59, 61 or 100 Hz, or a non-finite setting, is rejected.

    Input: a valid input of 10 s (a 10 Hz sinusoid of 1 mV) at 360 Hz and at 250 Hz, with
    the mains setting 49, 51, 59, 61 or 100 Hz, NaN, +infinity or -infinity; given to the
    mains filter, to the processing pipeline and to the beat detection.
    Expected: `InvalidInputError` with a message; no filtered signal (and no detections) is
    returned.
    """
    _assert_setting_rejected(operation, fs_hz, mains_hz)


@pytest.mark.requirement("SRS-005")
@pytest.mark.parametrize("operation", CONFIGURED)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("mains_hz", OTHER_INVALID_SETTINGS)
def test_setting_close_to_50_or_60_hz_or_not_a_mains_frequency_is_rejected(
    operation: Configured, fs_hz: float, mains_hz: Any
) -> None:
    """Settings just beside 50 Hz and 60 Hz, and settings that are no mains frequency.

    Beyond the settings named for the verification: the statement rejects every setting
    other than 50 Hz or 60 Hz.
    Input: a valid input of 10 s at 360 Hz and at 250 Hz, with the mains setting 49.9, 50.1,
    59.9, 60.1, 0, -50, -60 or 120 Hz; given to the mains filter, the processing pipeline
    and the beat detection.
    Expected: `InvalidInputError` with a message; no filtered signal is returned.
    """
    _assert_setting_rejected(operation, fs_hz, mains_hz)


@pytest.mark.requirement("SRS-005")
@pytest.mark.parametrize("operation", CONFIGURED)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("mains_hz", MAINS_SETTINGS_HZ)
def test_settings_of_50_and_60_hz_are_accepted(
    operation: Configured, fs_hz: float, mains_hz: int
) -> None:
    """Control of the rejections: the two valid settings, on the same inputs.

    Input: the valid input of 10 s used by the rejection cases, at 360 Hz and at 250 Hz,
    with the mains setting 50 Hz and 60 Hz; given to the mains filter, the processing
    pipeline and the beat detection.
    Expected: no error; each function returns its result (a filtered signal with one sample
    per input sample, a pipeline result, an array of indices).
    """
    signal = np.sin(2.0 * np.pi * 10.0 * np.arange(round(DURATION_S * fs_hz)) / fs_hz)

    result = operation(signal, fs_hz, mains_hz)

    assert result is not None
    if operation is _mains_filter:
        assert result.shape == signal.shape
