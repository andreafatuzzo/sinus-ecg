"""Requirement tests of SRS-010: QRS detection with baseline wander and mains interference.

Risk control RC-002: detection meets all the criteria of SRS-006, including exactly one index
for each QRS complex and no other index, on an ECG with a regular rhythm between 30 and
200 bpm (bounds included) and 1 mV QRS amplitude, to which a 0.3 Hz sinusoid of 1 mV and a
sinusoid of 0.2 mV at the mains frequency are added (SRS v0.6). The inputs are the synthetic
ECGs of the SRS-006 tests (a regular rhythm, known QRS positions) at 30, 40, 75, 180 and
200 bpm; the mains setting matches the interference. The pass criteria are those of SRS-006,
applied in samples with exact bounds (see the SRS-006 tests): with exactly one index for each
QRS complex and no other index, every index is the index of a detected QRS complex and must
lie within 150 ms of it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.filters import remove_baseline_wander, remove_mains_interference
from sinus_dsp.pipeline import detect_beats, run_pipeline
from sinus_dsp.qrs import detect_qrs

Detector = Callable[[Any, float, int], Any]


def _detect_beats(signal: Any, fs_hz: float, mains_hz: int) -> Any:
    return detect_beats(signal, fs_hz, mains_hz)


def _run_pipeline_beats(signal: Any, fs_hz: float, mains_hz: int) -> Any:
    return run_pipeline(signal, fs_hz, mains_hz).beats


def _detect_qrs_after_filters(signal: Any, fs_hz: float, mains_hz: int) -> Any:
    baseline = remove_baseline_wander(signal, fs_hz)
    conditioned = remove_mains_interference(baseline, fs_hz, mains_hz)
    return detect_qrs(conditioned, fs_hz)


DETECTORS = [
    pytest.param(_detect_beats, id="detect_beats"),
    pytest.param(_run_pipeline_beats, id="run_pipeline"),
    pytest.param(_detect_qrs_after_filters, id="filters+detect_qrs"),
]

SAMPLING_FREQUENCIES_HZ = [360, 250]
# The heart rates of SRS-006: both limits of 30-200 bpm and three inside.
HEART_RATES_BPM = [30, 40, 75, 180, 200]
MAINS_FREQUENCIES_HZ = [50, 60]

# Beats of a 30 s synthetic ECG: every k >= 0 with 0.5 + k * 60 / heart rate <= 29.5 s.
EXPECTED_BEATS = {30: 15, 40: 20, 75: 37, 180: 88, 200: 97}
# Beats of a 10 s synthetic ECG: every k >= 0 with 0.5 + k * 60 / heart rate <= 9.5 s.
EXPECTED_BEATS_10_S = {30: 5, 40: 7, 75: 12, 180: 28, 200: 31}


def _amplitude_at(signal_mv: Any, frequency_hz: float, fs_hz: float) -> float:
    """Amplitude of the component at one frequency, by projection on a sine and a cosine.

    Exact for a signal that contains a whole number of periods of that frequency.
    """
    t_s = np.arange(signal_mv.size, dtype=np.float64) / fs_hz
    in_phase = 2.0 * float(np.mean(signal_mv * np.sin(2.0 * np.pi * frequency_hz * t_s)))
    quadrature = 2.0 * float(np.mean(signal_mv * np.cos(2.0 * np.pi * frequency_hz * t_s)))
    return math.hypot(in_phase, quadrature)


@pytest.mark.requirement("SRS-010")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", MAINS_FREQUENCIES_HZ)
def test_input_carries_the_stated_interference(
    fs_hz: int, heart_rate_bpm: int, mains_hz: int, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """The test input is the ECG of SRS-006 plus the interference stated by the requirement.

    Input: the synthetic ECG of 30 s at 360 Hz and at 250 Hz, at 30, 40, 75, 180 and 200 bpm,
    without and with interference at 50 Hz and at 60 Hz.
    Expected: the same known QRS positions and a QRS amplitude of 1 mV; the difference
    between the two signals has an amplitude of 1 mV at 0.3 Hz and of 0.2 mV at the mains
    frequency (30 s hold a whole number of periods of both), and nothing else.
    """
    clean = make_synthetic_ecg(fs_hz, heart_rate_bpm)
    noisy = make_synthetic_ecg(fs_hz, heart_rate_bpm, mains_hz=mains_hz)

    assert np.array_equal(noisy.qrs_samples, clean.qrs_samples)
    assert np.all(np.abs(clean.signal_mv[clean.qrs_samples] - 1.0) <= 0.05)
    added = noisy.signal_mv - clean.signal_mv
    assert _amplitude_at(added, 0.3, fs_hz) == pytest.approx(1.0, abs=1e-9)
    assert _amplitude_at(added, float(mains_hz), fs_hz) == pytest.approx(0.2, abs=1e-9)
    assert float(np.max(np.abs(added))) <= 1.2 + 1e-9
    assert float(np.sqrt(np.mean(added**2))) == pytest.approx(
        math.sqrt((1.0**2 + 0.2**2) / 2.0), abs=1e-9
    )


@pytest.mark.requirement("SRS-010")
@pytest.mark.parametrize("detector", DETECTORS)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", MAINS_FREQUENCIES_HZ)
def test_each_qrs_has_exactly_one_detection_within_150_ms_and_no_other(
    detector: Detector,
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    make_synthetic_ecg: Callable[..., Any],
    detection_errors: Callable[..., list[str]],
) -> None:
    """With interference, the output still has exactly one index per QRS and no other index.

    Input: the synthetic ECG of 30 s (1 mV QRS) at 360 Hz and at 250 Hz, at 30, 40, 75, 180
    and 200 bpm (15, 20, 37, 88 and 97 known QRS; 30 and 200 bpm are the limits of the range,
    both included), plus 1 mV at 0.3 Hz and 0.2 mV at the mains frequency; one case with
    interference and setting at 50 Hz, one at 60 Hz.
    Expected: a one-dimensional int64 array of indices of input samples; every known QRS has
    exactly one index within 150 ms (54 samples at 360 Hz, 37 at 250 Hz), and no index lies
    further than that from every known QRS.
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm, mains_hz=mains_hz)

    beats = detector(ecg.signal_mv, ecg.fs_hz, mains_hz)

    assert isinstance(beats, np.ndarray)
    assert beats.dtype == np.int64
    assert beats.ndim == 1
    assert np.all((beats >= 0) & (beats < ecg.signal_mv.size))
    assert detection_errors(beats, ecg.qrs_samples, ecg.fs_hz) == []
    assert beats.size == EXPECTED_BEATS[heart_rate_bpm]


@pytest.mark.requirement("SRS-010")
@pytest.mark.parametrize("detector", DETECTORS)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", MAINS_FREQUENCIES_HZ)
def test_indices_are_strictly_increasing_and_at_least_200_ms_apart(
    detector: Detector,
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    make_synthetic_ecg: Callable[..., Any],
    ordering_errors: Callable[..., list[str]],
) -> None:
    """With interference, the indices stay strictly increasing and at least 200 ms apart.

    Input: the synthetic ECG of 30 s (1 mV QRS) at 360 Hz and at 250 Hz, at 30, 40, 75, 180
    and 200 bpm, plus 1 mV at 0.3 Hz and 0.2 mV at the mains frequency; one case with
    interference and setting at 50 Hz, one at 60 Hz.
    Expected: a non-empty output in which every index is larger than the previous one by at
    least 200 ms (72 samples at 360 Hz, 50 at 250 Hz).
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm, mains_hz=mains_hz)

    beats = detector(ecg.signal_mv, ecg.fs_hz, mains_hz)

    assert beats.size > 0
    assert ordering_errors(beats, ecg.fs_hz) == []


# --- Beyond the verification cases: the shortest accepted input, other phases ---------------


@pytest.mark.requirement("SRS-010")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", MAINS_FREQUENCIES_HZ)
def test_criteria_hold_on_the_shortest_accepted_input_with_interference(
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    make_synthetic_ecg: Callable[..., Any],
    detection_errors: Callable[..., list[str]],
    ordering_errors: Callable[..., list[str]],
) -> None:
    """The criteria of SRS-006 hold with interference on an input of the minimum duration.

    The statement does not restrict the duration of the ECG beyond SRS-003; this case goes
    beyond the 30 s inputs of the verification.
    Input: the synthetic ECG of exactly 10 s (1 mV QRS) at 360 Hz and at 250 Hz, at 30, 40,
    75, 180 and 200 bpm (5, 7, 12, 28 and 31 known QRS), plus 1 mV at 0.3 Hz and 0.2 mV at
    the mains frequency, with the matching setting (50 Hz and 60 Hz).
    Expected: exactly one index within 150 ms of every known QRS and no other index; indices
    strictly increasing and at least 200 ms apart.
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm, n_samples=10 * fs_hz, mains_hz=mains_hz)
    assert ecg.qrs_samples.size == EXPECTED_BEATS_10_S[heart_rate_bpm]

    beats = detect_beats(ecg.signal_mv, ecg.fs_hz, mains_hz)

    assert beats.dtype == np.int64
    assert detection_errors(beats, ecg.qrs_samples, ecg.fs_hz) == []
    assert ordering_errors(beats, ecg.fs_hz) == []


@pytest.mark.requirement("SRS-010")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", MAINS_FREQUENCIES_HZ)
@pytest.mark.parametrize("phase_deg", [pytest.param(p, id=f"{p}deg") for p in (90, 180, 270)])
def test_criteria_hold_whatever_the_phase_of_the_interference(
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    phase_deg: int,
    make_synthetic_ecg: Callable[..., Any],
    detection_errors: Callable[..., list[str]],
    ordering_errors: Callable[..., list[str]],
) -> None:
    """The criteria of SRS-006 hold with the interference starting at another phase.

    The statement gives the frequency and the amplitude of the two sinusoids, not their
    phase; the verification inputs start both at phase 0. At 90 degrees the input starts
    1.2 mV above the ECG, at the peak of both sinusoids.
    Input: the noise-free synthetic ECG of 30 s (1 mV QRS) at 360 Hz and at 250 Hz, at 30, 40,
    75, 180 and 200 bpm, plus 1 mV * sin(2 pi 0.3 t + phase) and 0.2 mV * sin(2 pi f t +
    phase) at the mains frequency f (50 Hz and 60 Hz, with the matching setting), for a phase
    of 90, 180 and 270 degrees.
    Expected: exactly one index within 150 ms of every known QRS and no other index; indices
    strictly increasing and at least 200 ms apart.
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm)
    t_s = np.arange(ecg.signal_mv.size, dtype=np.float64) / fs_hz
    phase_rad = math.radians(phase_deg)
    signal = (
        ecg.signal_mv
        + 1.0 * np.sin(2.0 * np.pi * 0.3 * t_s + phase_rad)
        + 0.2 * np.sin(2.0 * np.pi * mains_hz * t_s + phase_rad)
    )

    beats = detect_beats(signal, ecg.fs_hz, mains_hz)

    assert beats.dtype == np.int64
    assert detection_errors(beats, ecg.qrs_samples, ecg.fs_hz) == []
    assert beats.size == EXPECTED_BEATS[heart_rate_bpm]
    assert ordering_errors(beats, ecg.fs_hz) == []
