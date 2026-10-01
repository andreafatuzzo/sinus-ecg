"""Requirement tests of SRS-006: QRS detection (risk control RC-001).

The inputs are synthetic ECGs whose QRS positions are known by construction (generator in
`conftest.py`, independent of the software under test). The pass criteria are applied in
samples, keeping the bounds of the requirement exact:

- "within 150 ms": |index - QRS| <= floor(0.150 * fs) samples (54 at 360 Hz, 37 at 250 Hz);
- "no closer than 200 ms": spacing >= ceil(0.200 * fs) samples (72 at 360 Hz, 50 at 250 Hz).

The statement has two parts, and the tests follow them:

- for every input accepted by SRS-003, the indices are strictly increasing, no two are closer
  than 200 ms, and each lies within 150 ms of the QRS complex it represents;
- for a noise-free input with a heart rate between 30 and 200 bpm (bounds included), there is
  exactly one index for each QRS complex and no other index.

No test requires exactly one index per QRS complex outside 30-200 bpm. The detection is
exercised through each of its public entry points.
"""

from __future__ import annotations

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


def _detect_qrs_directly(signal: Any, fs_hz: float, mains_hz: int) -> Any:
    return detect_qrs(signal, fs_hz)


DETECTORS = [
    pytest.param(_detect_beats, id="detect_beats"),
    pytest.param(_run_pipeline_beats, id="run_pipeline"),
    pytest.param(_detect_qrs_after_filters, id="filters+detect_qrs"),
]
FLAT_DETECTORS = [*DETECTORS, pytest.param(_detect_qrs_directly, id="detect_qrs")]

SAMPLING_FREQUENCIES_HZ = [360, 250]
# The heart rates of the verification of SRS-006: both limits of 30-200 bpm and three inside.
HEART_RATES_BPM = [30, 40, 75, 180, 200]
MAINS_SETTINGS_HZ = [50, 60]

# Beats of a 30 s synthetic ECG: every k >= 0 with 0.5 + k * 60 / heart rate <= 29.5 s.
EXPECTED_BEATS = {30: 15, 40: 20, 75: 37, 180: 88, 200: 97}

# Heart rates outside 30-200 bpm, just outside each limit and further: one index per QRS
# complex is not required there, but the criteria of every accepted input still apply.
OUTSIDE_RANGE_BPM = [20, 29, 201, 240, 300]


def _assert_index_array(beats: Any, n_samples: int) -> None:
    """The output is a one-dimensional int64 array of indices of input samples."""
    assert isinstance(beats, np.ndarray)
    assert beats.dtype == np.int64
    assert beats.ndim == 1
    assert np.all((beats >= 0) & (beats < n_samples))


# --- The test inputs and the pass criteria themselves ---------------------------------------


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
def test_synthetic_ecg_has_qrs_complexes_at_the_known_positions(
    fs_hz: int, heart_rate_bpm: int, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """The test input is an ECG whose QRS positions are known.

    Input: the synthetic ECG of 30 s at 360 Hz and at 250 Hz, at 30, 40, 75, 180 and 200 bpm.
    Expected: 15, 20, 37, 88 and 97 known positions, spaced by 60 / heart rate (within one
    sample), the first at 0.5 s; at each of them the signal has its R wave: a local maximum
    of about 1 mV, which is also the largest sample within 150 ms.
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm)
    signal, qrs = ecg.signal_mv, ecg.qrs_samples

    assert signal.size == 30 * fs_hz
    assert qrs.size == EXPECTED_BEATS[heart_rate_bpm]
    assert qrs[0] == fs_hz // 2
    rr_samples = 60.0 * fs_hz / heart_rate_bpm
    assert np.all(np.abs(np.diff(qrs) - rr_samples) <= 1.0)
    window = (150 * fs_hz) // 1000
    for r in qrs.tolist():
        assert 0.95 <= signal[r] <= 1.05
        assert signal[r] == np.max(signal[r - window : r + window + 1])


@pytest.mark.requirement("SRS-006")
def test_criteria_are_applied_with_exact_bounds_in_samples(
    match_window_samples: Callable[[float], int], min_spacing_samples: Callable[[float], int]
) -> None:
    """The 150 ms and 200 ms bounds of the requirement are converted without loosening them.

    Input: the sampling frequencies 360, 250, 125 and 1000 Hz.
    Expected: "within 150 ms" is 54, 37, 18 and 150 samples (rounded down: 37.5 -> 37);
    "at least 200 ms apart" is 72, 50, 25 and 200 samples (rounded up).
    """
    assert [match_window_samples(fs) for fs in (360.0, 250.0, 125.0, 1000.0)] == [54, 37, 18, 150]
    assert [min_spacing_samples(fs) for fs in (360.0, 250.0, 125.0, 1000.0)] == [72, 50, 25, 200]


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize(("fs_hz", "window"), [(360.0, 54), (250.0, 37)])
def test_criteria_accept_a_detection_at_150_ms_and_reject_one_sample_beyond(
    fs_hz: float, window: int, detection_errors: Callable[..., list[str]]
) -> None:
    """The check of "exactly one detection within 150 ms, no other" holds at its boundary.

    Input: known QRS at samples 1000 and 2000; detection lists built by hand.
    Expected: detections exactly 150 ms before or after each QRS are accepted; a detection one
    sample further is reported twice (the QRS has no detection, the detection has no QRS);
    a missed QRS, two detections on one QRS and a detection far from every QRS are reported.
    """
    qrs = [1000, 2000]

    assert detection_errors([1000, 2000], qrs, fs_hz) == []
    assert detection_errors([1000 - window, 2000 + window], qrs, fs_hz) == []
    assert len(detection_errors([1000, 2000 + window + 1], qrs, fs_hz)) == 2
    assert len(detection_errors([1000 - window - 1, 2000], qrs, fs_hz)) == 2
    assert len(detection_errors([1000], qrs, fs_hz)) == 1
    assert len(detection_errors([], qrs, fs_hz)) == 2
    assert len(detection_errors([1000 - window, 1000 + window, 2000], qrs, fs_hz)) == 1
    assert len(detection_errors([1000, 1500, 2000], qrs, fs_hz)) == 1
    assert len(detection_errors([500], [], fs_hz)) == 1
    assert detection_errors([], [], fs_hz) == []


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize(("fs_hz", "spacing"), [(360.0, 72), (250.0, 50)])
def test_criteria_accept_a_spacing_of_200_ms_and_reject_one_sample_less(
    fs_hz: float, spacing: int, ordering_errors: Callable[..., list[str]]
) -> None:
    """The check of "strictly increasing, at least 200 ms apart" holds at its boundary.

    Input: index lists built by hand.
    Expected: indices exactly 200 ms apart are accepted; indices one sample closer, equal
    indices and decreasing indices are reported; an empty list and a single index are accepted.
    """
    assert ordering_errors([100, 100 + spacing, 100 + 2 * spacing], fs_hz) == []
    assert len(ordering_errors([100, 100 + spacing - 1], fs_hz)) == 1
    assert len(ordering_errors([100, 100], fs_hz)) == 1
    assert len(ordering_errors([100 + spacing, 100], fs_hz)) == 1
    assert len(ordering_errors([100, 101, 102], fs_hz)) == 2
    assert ordering_errors([], fs_hz) == []
    assert ordering_errors([100], fs_hz) == []


# --- The requirement ------------------------------------------------------------------------


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize("detector", DETECTORS)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", MAINS_SETTINGS_HZ)
def test_each_qrs_has_exactly_one_detection_within_150_ms_and_no_other(
    detector: Detector,
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    make_synthetic_ecg: Callable[..., Any],
    detection_errors: Callable[..., list[str]],
) -> None:
    """On a noise-free ECG, the output has exactly one index per QRS and no other index.

    Input: the noise-free synthetic ECG of 30 s at 360 Hz and at 250 Hz, at 30, 40, 75, 180
    and 200 bpm (15, 20, 37, 88 and 97 known QRS; 30 and 200 bpm are the limits of the range
    of the statement, both included), with the mains setting 50 Hz and 60 Hz.
    Expected: a one-dimensional int64 array of indices of input samples (index 0 = first input
    sample); every known QRS has exactly one index within 150 ms (54 samples at 360 Hz, 37 at
    250 Hz), and no index lies further than that from every known QRS.
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm)

    beats = detector(ecg.signal_mv, ecg.fs_hz, mains_hz)

    _assert_index_array(beats, ecg.signal_mv.size)
    assert detection_errors(beats, ecg.qrs_samples, ecg.fs_hz) == []
    assert beats.size == EXPECTED_BEATS[heart_rate_bpm]


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize("detector", DETECTORS)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", MAINS_SETTINGS_HZ)
def test_indices_are_strictly_increasing_and_at_least_200_ms_apart(
    detector: Detector,
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    make_synthetic_ecg: Callable[..., Any],
    ordering_errors: Callable[..., list[str]],
) -> None:
    """The output indices are strictly increasing and no two are closer than 200 ms.

    Input: the noise-free synthetic ECG of 30 s at 360 Hz and at 250 Hz, at 30, 40, 75, 180
    and 200 bpm, with the mains setting 50 Hz and 60 Hz.
    Expected: a non-empty output in which every index is larger than the previous one by at
    least 200 ms (72 samples at 360 Hz, 50 at 250 Hz).
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm)

    beats = detector(ecg.signal_mv, ecg.fs_hz, mains_hz)

    assert beats.size > 0
    assert ordering_errors(beats, ecg.fs_hz) == []


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize("detector", FLAT_DETECTORS)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("level_mv", [0.0, 1.0, -0.5])
@pytest.mark.parametrize("mains_hz", MAINS_SETTINGS_HZ)
def test_flat_input_of_10_s_gives_no_detection_and_no_error(
    detector: Detector, fs_hz: int, level_mv: float, mains_hz: int
) -> None:
    """A flat input of 10 s produces no detections and no error.

    A case named by the verification of SRS-006. A flat input has no QRS complex, so no
    index can lie within 150 ms of a QRS complex that it represents (a criterion of every
    accepted input); the output must be empty.
    Input: a constant signal of exactly 10 s (3600 samples at 360 Hz, 2500 at 250 Hz), at
    0 mV, 1 mV and -0.5 mV, with the mains setting 50 Hz and 60 Hz.
    Expected: no error, and an empty int64 array of indices.
    """
    flat = np.full(10 * fs_hz, level_mv, dtype=np.float64)

    beats = detector(flat, float(fs_hz), mains_hz)

    _assert_index_array(beats, flat.size)
    assert beats.size == 0


# --- The limits of an accepted input (SRS-003), beyond the cases listed for verification ----


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize("fs_hz", [125, 1000])
@pytest.mark.parametrize("heart_rate_bpm", [30, 75, 200])
@pytest.mark.parametrize("mains_hz", MAINS_SETTINGS_HZ)
def test_criteria_hold_at_the_limits_of_the_sampling_frequency(
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    make_synthetic_ecg: Callable[..., Any],
    detection_errors: Callable[..., list[str]],
    ordering_errors: Callable[..., list[str]],
) -> None:
    """The criteria hold for an accepted input at the lowest and highest sampling frequency.

    The requirement applies to every input accepted by SRS-003; this case goes beyond the
    sampling frequencies listed for its verification.
    Input: the noise-free synthetic ECG of 30 s at 30, 75 and 200 bpm (15, 37 and 97 known
    QRS), sampled at 125 Hz and at 1000 Hz, with the mains setting 50 Hz and 60 Hz.
    Expected: exactly one index within 150 ms of every known QRS (18 samples at 125 Hz, 150
    at 1000 Hz) and no other; indices strictly increasing and at least 200 ms apart (25 and
    200 samples).
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm)
    assert ecg.qrs_samples.size == EXPECTED_BEATS[heart_rate_bpm]

    beats = detect_beats(ecg.signal_mv, ecg.fs_hz, mains_hz)

    _assert_index_array(beats, ecg.signal_mv.size)
    assert detection_errors(beats, ecg.qrs_samples, ecg.fs_hz) == []
    assert ordering_errors(beats, ecg.fs_hz) == []


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize(
    ("heart_rate_bpm", "n_beats"), [(30, 5), (40, 7), (75, 12), (180, 28), (200, 31)]
)
def test_criteria_hold_on_the_shortest_accepted_input(
    fs_hz: int,
    heart_rate_bpm: int,
    n_beats: int,
    make_synthetic_ecg: Callable[..., Any],
    detection_errors: Callable[..., list[str]],
    ordering_errors: Callable[..., list[str]],
) -> None:
    """The criteria hold for an accepted input of the minimum duration, 10 s.

    The requirement applies to every input accepted by SRS-003; this case goes beyond the
    durations needed by the cases listed for its verification.
    Input: the noise-free synthetic ECG of exactly 10 s at 360 Hz and at 250 Hz, at 30, 40,
    75, 180 and 200 bpm (5, 7, 12, 28 and 31 known QRS, the last one 0.5 s or more before the
    end), with the mains setting 50 Hz.
    Expected: exactly one index within 150 ms of every known QRS and no other; indices
    strictly increasing and at least 200 ms apart.
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm, n_samples=10 * fs_hz)
    assert ecg.qrs_samples.size == n_beats

    beats = detect_beats(ecg.signal_mv, ecg.fs_hz, 50)

    _assert_index_array(beats, ecg.signal_mv.size)
    assert detection_errors(beats, ecg.qrs_samples, ecg.fs_hz) == []
    assert ordering_errors(beats, ecg.fs_hz) == []


# --- Criteria of every accepted input, outside the heart-rate range and on noise ------------


def _indices_far_from_every_qrs(beats: Any, qrs_samples: Any, window: int) -> list[int]:
    """The indices that lie more than ``window`` samples from every known QRS."""
    qrs = np.asarray(qrs_samples, dtype=np.int64)
    return [d for d in np.asarray(beats).tolist() if not np.any(np.abs(qrs - d) <= window)]


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize("detector", DETECTORS)
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", OUTSIDE_RANGE_BPM)
def test_outside_30_to_200_bpm_the_criteria_of_every_accepted_input_hold(
    detector: Detector,
    fs_hz: int,
    heart_rate_bpm: int,
    make_synthetic_ecg: Callable[..., Any],
    match_window_samples: Callable[[float], int],
    ordering_errors: Callable[..., list[str]],
) -> None:
    """Outside 30-200 bpm, only the criteria of every accepted input are required.

    One index per QRS complex is required only from 30 to 200 bpm; the order, the spacing
    and the 150 ms criterion apply to every input accepted by SRS-003.
    Input: the noise-free synthetic ECG of 30 s at 360 Hz and at 250 Hz, at 20 and 29 bpm
    (below the range) and at 201, 240 and 300 bpm (above it; at 300 bpm the QRS complexes are
    exactly 200 ms apart), with the mains setting 50 Hz.
    Expected: a non-empty int64 array of indices of input samples, strictly increasing and at
    least 200 ms apart; every index within 150 ms of a known QRS. The number of indices per
    QRS complex is not checked.
    """
    ecg = make_synthetic_ecg(fs_hz, heart_rate_bpm)

    beats = detector(ecg.signal_mv, ecg.fs_hz, 50)

    _assert_index_array(beats, ecg.signal_mv.size)
    assert beats.size > 0
    assert ordering_errors(beats, ecg.fs_hz) == []
    window = match_window_samples(ecg.fs_hz)
    assert _indices_far_from_every_qrs(beats, ecg.qrs_samples, window) == []


NOISE_KINDS = ["white", "spikes", "ecg+noise", "steps"]


def _noise_input(kind: str, fs_hz: int, make_synthetic_ecg: Callable[..., Any]) -> Any:
    """A 30 s input that is not a noise-free ECG, generated with a fixed seed per case.

    - ``white``: Gaussian white noise of 1 mV standard deviation;
    - ``spikes``: zero, with 200 spikes of random amplitude (standard deviation 3 mV) at
      random samples;
    - ``ecg+noise``: the synthetic ECG at 75 bpm plus Gaussian white noise of 0.3 mV;
    - ``steps``: a random staircase (a new level of standard deviation 2 mV every 0.7 s)
      plus the synthetic ECG at 180 bpm.
    """
    n = 30 * fs_hz
    rng = np.random.default_rng([20260930, fs_hz, NOISE_KINDS.index(kind)])
    if kind == "white":
        return rng.normal(0.0, 1.0, n)
    if kind == "spikes":
        signal = np.zeros(n, dtype=np.float64)
        where = rng.choice(n, size=200, replace=False)
        signal[where] = rng.normal(0.0, 3.0, where.size)
        return signal
    if kind == "ecg+noise":
        return make_synthetic_ecg(fs_hz, 75).signal_mv + rng.normal(0.0, 0.3, n)
    step = round(0.7 * fs_hz)
    levels = np.repeat(rng.normal(0.0, 2.0, n // step + 1), step)[:n]
    return make_synthetic_ecg(fs_hz, 180).signal_mv + levels


@pytest.mark.requirement("SRS-006")
@pytest.mark.parametrize("detector", FLAT_DETECTORS)
@pytest.mark.parametrize("fs_hz", [125, 250, 360, 1000])
@pytest.mark.parametrize("kind", NOISE_KINDS)
def test_indices_are_increasing_and_200_ms_apart_for_any_accepted_input(
    detector: Detector,
    fs_hz: int,
    kind: str,
    make_synthetic_ecg: Callable[..., Any],
    ordering_errors: Callable[..., list[str]],
) -> None:
    """Order and spacing hold for every accepted input, not only for a noise-free ECG.

    Input: 30 s inputs that are not noise-free ECGs (white noise, isolated spikes, an ECG
    with white noise, an ECG on a random staircase; fixed seeds), at 125, 250, 360 and
    1000 Hz, with the mains setting 50 Hz where the entry point takes one.
    Expected: no error; an int64 array of indices of input samples, strictly increasing,
    with no two indices closer than 200 ms (25, 50, 72 and 200 samples). What the indices
    detect is not checked: on such inputs detection performance is the subject of SRS-007.
    """
    signal = _noise_input(kind, fs_hz, make_synthetic_ecg)

    beats = detector(signal, float(fs_hz), 50)

    _assert_index_array(beats, signal.size)
    assert ordering_errors(beats, float(fs_hz)) == []
