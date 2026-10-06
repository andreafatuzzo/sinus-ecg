"""Unit tests of the QRS detector internals and of its behaviour on synthetic signals."""

import math
from typing import Any

import numpy as np
import pytest

from sinus_dsp import filters, qrs
from sinus_dsp.errors import InvalidInputError

FS_360 = 360.0


def _conditioned(raw_mv: Any, fs_hz: float, mains_hz: int = 50) -> Any:
    """The conditioning chain: baseline wander removal, then mains interference removal."""
    baseline = filters.apply_sos(filters.baseline_sos(fs_hz), np.asarray(raw_mv, dtype=np.float64))
    return filters.apply_sos(filters.mains_sos(fs_hz, mains_hz), baseline)


# --- parameters and linear stages -------------------------------------------------------------


def test_constants() -> None:
    assert (qrs.BAND_LOW_HZ, qrs.BAND_HIGH_HZ) == (5.0, 15.0)
    assert qrs.BAND_DELAY_MS == 36
    assert qrs.INTEGRATION_WINDOW_MS == 150
    assert qrs.PEAK_TIMEOUT_MS == 95
    assert qrs.REFRACTORY_MS == 200
    assert qrs.T_WAVE_WINDOW_MS == 360
    assert qrs.LEARNING_S == 2
    assert qrs.RELEARN_AFTER_S == 8
    assert qrs.SEARCH_BACK_FACTOR == 1.66
    assert qrs.RR_AVERAGE_COUNT == 8
    assert qrs.MIN_INTEGRATED == 1e-4


@pytest.mark.parametrize(
    ("fs_hz", "expected"),
    [
        (360.0, qrs.DetectorSamples(13, 54, 34, 72, 130, 720, 2880)),
        (250.0, qrs.DetectorSamples(9, 38, 24, 50, 90, 500, 2000)),
        (125.0, qrs.DetectorSamples(5, 19, 12, 25, 45, 250, 1000)),
        (1000.0, qrs.DetectorSamples(36, 150, 95, 200, 360, 2000, 8000)),
    ],
)
def test_detector_samples(fs_hz: float, expected: qrs.DetectorSamples) -> None:
    assert qrs.detector_samples(fs_hz) == expected


@pytest.mark.parametrize("fs_hz", [0.0, -360.0, float("nan"), float("inf")])
def test_detector_samples_rejects_a_bad_sampling_frequency(fs_hz: float) -> None:
    with pytest.raises(InvalidInputError, match="sampling frequency"):
        qrs.detector_samples(fs_hz)


@pytest.mark.parametrize("fs_hz", [125.0, 250.0, 360.0, 1000.0])
def test_detection_band_sos(fs_hz: float) -> None:
    sos = qrs.detection_band_sos(fs_hz)
    assert sos.shape == (2, 6)
    assert np.array_equal(sos[0:1], filters.butterworth2_highpass_sos(5.0, fs_hz))
    assert np.array_equal(sos[1:2], filters.butterworth2_lowpass_sos(15.0, fs_hz))


def test_bandpass_starts_at_exactly_zero_whatever_the_offset(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(FS_360, 75)
    for offset in (0.0, 5.0, -123.456):
        signals = qrs.qrs_signals(x + offset, FS_360)
        assert signals.bandpassed_mv[0] == 0.0
        assert signals.derivative_mv_per_s[0] == 0.0
        assert signals.integrated[0] == 0.0


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
def test_linear_stages_follow_their_difference_equations(fs_hz: float, synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(fs_hz, 75, "bw-mains50")
    signals = qrs.qrs_signals(x, fs_hz)
    n = x.shape[0]
    window = qrs.detector_samples(fs_hz).window

    b = signals.bandpassed_mv
    assert np.array_equal(b, filters.apply_sos(qrs.detection_band_sos(fs_hz), x))

    padded = np.concatenate([np.zeros(4), b])
    derivative = (fs_hz / 8.0) * (
        padded[4:] + 2.0 * padded[3:-1] - 2.0 * padded[1:-3] - padded[:-4]
    )
    scale = float(np.max(np.abs(derivative)))
    assert np.allclose(signals.derivative_mv_per_s, derivative, rtol=0.0, atol=1e-12 * scale)

    squared = signals.derivative_mv_per_s**2
    padded_squares = np.concatenate([np.zeros(window - 1), squared])
    integrated = np.array(
        [math.fsum(padded_squares[i : i + window].tolist()) / window for i in range(n)]
    )
    scale = float(np.max(integrated))
    assert np.allclose(signals.integrated, integrated, rtol=0.0, atol=1e-12 * scale)
    assert signals.integrated.shape == signals.derivative_mv_per_s.shape == b.shape == (n,)


def test_qrs_signals_validates_its_input() -> None:
    with pytest.raises(InvalidInputError, match="shorter than"):
        qrs.qrs_signals(np.zeros(100), FS_360)
    with pytest.raises(InvalidInputError, match="sampling frequency is outside"):
        qrs.qrs_signals(np.zeros(3600), 2000.0)


def test_qrs_level_on_a_synthetic_ecg(synthetic_ecg: Any) -> None:
    # The integrated level of a 1 mV QRS is orders of magnitude above MIN_INTEGRATED.
    x, _ = synthetic_ecg(FS_360, 75)
    peak = float(np.max(qrs.qrs_signals(x, FS_360).integrated))
    assert 10.0 < peak < 1e4


# --- peak tracker -----------------------------------------------------------------------------


def _confirmed(y: list[float], peak_timeout: int) -> list[tuple[int, int]]:
    """``(m, confirmation sample)`` of every peak of ``y``."""
    tracker = qrs._PeakTracker(peak_timeout)
    out = []
    for n in range(1, len(y)):
        m = tracker.step(n, y[n], y[n - 1])
        if m is not None:
            out.append((m, n))
    return out


def test_tracker_one_peak_per_rise_despite_ripples() -> None:
    #    n: 0    1    2    3    4    5    6    7    8
    y = [0.0, 1.0, 2.0, 3.0, 2.5, 2.8, 3.5, 3.0, 1.7]
    # The ripple at n = 5 does not exceed the tracked maximum; n = 6 raises it; 1.7 < 3.5 / 2.
    assert _confirmed(y, peak_timeout=34) == [(6, 8)]


def test_tracker_confirms_when_the_signal_falls_below_half() -> None:
    assert _confirmed([0.0, 4.0, 2.0, 2.0], peak_timeout=34) == []  # 2.0 is not below 4.0 / 2
    assert _confirmed([0.0, 4.0, 2.0, 1.99], peak_timeout=34) == [(1, 3)]


def test_tracker_confirms_after_the_timeout() -> None:
    peak_timeout = 5
    y = [0.0, 1.0, 4.0] + [3.0] * 10
    # m = 2; n - m > P first holds at n = 8.
    assert _confirmed(y, peak_timeout) == [(2, 8)]


def test_tracker_resets_after_a_confirmation() -> None:
    y = [0.0, 4.0, 1.0, 0.5, 0.6, 0.7, 0.2]
    # The second rise starts from a reset tracker, so 0.7 is a peak although it is below 4.0.
    assert _confirmed(y, peak_timeout=34) == [(1, 2), (5, 6)]


def test_tracker_needs_a_strict_rise_above_the_tracked_maximum() -> None:
    assert _confirmed([0.0, 3.0, 3.0, 3.0, 1.0], peak_timeout=34) == [(1, 4)]
    # A later sample equal to the maximum does not move the peak.
    assert _confirmed([0.0, 3.0, 2.0, 3.0, 1.0], peak_timeout=34) == [(1, 4)]


def test_tracker_ignores_levels_below_the_minimum() -> None:
    tiny = qrs.MIN_INTEGRATED / 2.0
    assert _confirmed([0.0, tiny / 2.0, tiny, 0.0, 0.0], peak_timeout=2) == []
    assert _confirmed([0.0] * 50, peak_timeout=2) == []
    at_minimum = qrs.MIN_INTEGRATED
    assert _confirmed([0.0, at_minimum, 0.0], peak_timeout=2) == [(1, 2)]


def test_tracker_prefers_a_new_maximum_over_a_confirmation() -> None:
    # At n = 8 the timeout has passed, but the sample is a new maximum: it moves the peak.
    peak_timeout = 5
    y = [0.0, 1.0, 4.0, 3.0, 3.0, 3.0, 3.0, 3.0, 5.0, 1.0]
    assert _confirmed(y, peak_timeout) == [(8, 9)]


# --- peak features ----------------------------------------------------------------------------


def _signals(n: int = 2000) -> qrs.QrsSignals:
    return qrs.QrsSignals(
        bandpassed_mv=np.zeros(n), derivative_mv_per_s=np.zeros(n), integrated=np.zeros(n)
    )


def test_features_use_the_window_of_the_peak() -> None:
    samples = qrs.detector_samples(FS_360)  # N = 54, D = 13
    signals = _signals()
    m = 200
    signals.integrated[m] = 7.0
    # Band-pass window: [m - N - 1, m - 2] = [145, 198].
    signals.bandpassed_mv[144] = 5.0  # outside
    signals.bandpassed_mv[199] = -5.0  # outside
    signals.bandpassed_mv[145] = 0.3
    signals.bandpassed_mv[160] = -0.9
    signals.bandpassed_mv[198] = 0.8
    # Slope window: [m - N + 1, m] = [147, 200].
    signals.derivative_mv_per_s[146] = 99.0  # outside
    signals.derivative_mv_per_s[201] = 99.0  # outside
    signals.derivative_mv_per_s[147] = -40.0
    signals.derivative_mv_per_s[200] = 30.0

    peak = qrs._peak_features(m, signals, samples)
    assert peak.m == m
    assert peak.peak_i == 7.0
    assert peak.peak_f == 0.9
    assert peak.f == 160 - 13
    assert peak.slope == 40.0


def test_features_window_bounds_are_inclusive() -> None:
    samples = qrs.detector_samples(FS_360)
    m = 200
    for k in (145, 198):
        signals = _signals()
        signals.bandpassed_mv[k] = 1.0
        assert qrs._peak_features(m, signals, samples).f == k - 13
    for k in (147, 200):
        signals = _signals()
        signals.derivative_mv_per_s[k] = -2.0
        assert qrs._peak_features(m, signals, samples).slope == 2.0


def test_features_tie_takes_the_first_maximum() -> None:
    samples = qrs.detector_samples(FS_360)
    signals = _signals()
    signals.bandpassed_mv[150] = -0.5
    signals.bandpassed_mv[170] = 0.5
    assert qrs._peak_features(200, signals, samples).f == 150 - 13


def test_features_near_the_start_are_clipped_and_the_fiducial_is_never_negative() -> None:
    samples = qrs.detector_samples(FS_360)
    signals = _signals()
    signals.bandpassed_mv[5] = 1.0
    signals.bandpassed_mv[9] = 3.0  # outside [0, 8] for m = 10
    signals.derivative_mv_per_s[0] = 6.0
    peak = qrs._peak_features(10, signals, samples)
    assert peak.peak_f == 1.0
    assert peak.f == 0
    assert peak.slope == 6.0
    first = qrs._peak_features(1, signals, samples)  # band-pass window [0, 0]
    assert (first.peak_f, first.f) == (0.0, 0)


# --- decisions --------------------------------------------------------------------------------


def _decisions(fs_hz: float = FS_360, n: int = 20000) -> Any:
    """Decisions with TH_I1 = 2.0 and TH_F1 = 0.2, as after an initialisation."""
    decisions = qrs._Decisions(qrs.detector_samples(fs_hz), _signals(n))
    decisions.spki, decisions.npki = 8.0, 0.0
    decisions.spkf, decisions.npkf = 0.8, 0.0
    decisions.init_n = qrs.detector_samples(fs_hz).learning - 1
    return decisions


def _peak(
    m: int, peak_i: float = 4.0, peak_f: float = 0.4, f: int | None = None, slope: float = 50.0
) -> Any:
    return qrs._Peak(m=m, peak_i=peak_i, peak_f=peak_f, f=m - 40 if f is None else f, slope=slope)


def _levels(decisions: Any) -> tuple[float, float, float, float]:
    return (decisions.spki, decisions.npki, decisions.spkf, decisions.npkf)


def test_thresholds() -> None:
    decisions = _decisions()
    decisions.spki, decisions.npki = 10.0, 2.0
    decisions.spkf, decisions.npkf = 1.0, 0.2
    assert decisions.threshold_i1 == 2.0 + 0.25 * 8.0
    assert decisions.threshold_f1 == 0.2 + 0.25 * 0.8


def test_first_qrs_updates_the_signal_levels_and_adds_no_interval() -> None:
    decisions = _decisions()
    peak = _peak(1000)
    decisions.classify(peak)
    assert decisions.output == [960]
    assert decisions.spki == 0.125 * 4.0 + 0.875 * 8.0
    assert decisions.spkf == 0.125 * 0.4 + 0.875 * 0.8
    assert (decisions.npki, decisions.npkf) == (0.0, 0.0)
    assert decisions.last is peak
    assert decisions.rr_flag is True
    assert list(decisions.rr_intervals) == []


def test_consecutive_qrs_add_intervals_between_their_peak_positions() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000, f=955))
    decisions.classify(_peak(1300, f=1262))
    decisions.classify(_peak(1580, f=1540))
    assert decisions.output == [955, 1262, 1540]
    assert list(decisions.rr_intervals) == [300, 280]


def test_only_the_eight_most_recent_intervals_are_kept() -> None:
    decisions = _decisions()
    m = 1000
    decisions.classify(_peak(m))
    for step in range(300, 311):  # 11 intervals: 300 .. 310
        m += step
        decisions.classify(_peak(m))
    assert list(decisions.rr_intervals) == list(range(303, 311))
    assert len(decisions.output) == 12


def test_refractory_on_the_peak_position() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000, f=960))
    levels = _levels(decisions)
    decisions.classify(_peak(1000 + 71, f=960 + 100))  # m closer than R = 72
    assert decisions.output == [960]
    assert _levels(decisions) == levels  # ignored: no level changes
    assert decisions.candidate is None  # and not a candidate
    decisions.classify(_peak(1000 + 72, f=960 + 100))
    assert decisions.output == [960, 1060]


def test_refractory_on_the_fiducial() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000, f=960))
    levels = _levels(decisions)
    decisions.classify(_peak(1000 + 100, f=960 + 71))  # m far enough, f closer than R
    assert decisions.output == [960]
    assert _levels(decisions) == levels
    assert decisions.candidate is None
    decisions.classify(_peak(1000 + 100, f=960 + 72))
    assert decisions.output == [960, 1032]


def test_refractory_ignores_even_a_weak_peak() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000))
    levels = _levels(decisions)
    decisions.classify(_peak(1050, peak_i=0.5, peak_f=0.05))
    assert _levels(decisions) == levels
    assert decisions.candidate is None


def test_t_wave_is_a_noise_peak_and_not_a_candidate() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000, slope=50.0))
    spki, spkf = decisions.spki, decisions.spkf
    decisions.classify(_peak(1100, slope=24.9))  # within TW = 130, slope below half
    assert decisions.output == [960]
    assert decisions.npki == 0.125 * 4.0
    assert decisions.npkf == 0.125 * 0.4
    assert (decisions.spki, decisions.spkf) == (spki, spkf)
    assert decisions.candidate is None
    assert decisions.last.m == 1000


def test_t_wave_rule_needs_a_slope_strictly_below_half() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000, slope=50.0))
    decisions.classify(_peak(1100, slope=25.0))
    assert decisions.output == [960, 1060]


def test_t_wave_rule_applies_only_inside_the_window() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000, slope=50.0))
    decisions.classify(_peak(1000 + 130, slope=1.0))  # exactly TW after the last QRS
    assert decisions.output == [960, 1090]
    inside = _decisions()
    inside.classify(_peak(1000, slope=50.0))
    inside.classify(_peak(1000 + 129, slope=1.0))
    assert inside.output == [960]


def test_t_wave_rule_compares_with_the_last_qrs_slope() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000, slope=10.0))
    decisions.classify(_peak(1100, slope=6.0))  # above half of 10
    assert decisions.output == [960, 1060]


@pytest.mark.parametrize(
    ("peak_i", "peak_f"),
    [(1.5, 0.4), (4.0, 0.15), (1.5, 0.15), (2.0, 0.4), (4.0, 0.2)],  # the last two: equality
)
def test_peak_not_above_both_thresholds_is_noise_and_a_candidate(
    peak_i: float, peak_f: float
) -> None:
    decisions = _decisions()
    peak = _peak(1000, peak_i=peak_i, peak_f=peak_f)
    decisions.classify(peak)
    assert decisions.output == []
    assert decisions.npki == 0.125 * peak_i
    assert decisions.npkf == 0.125 * peak_f
    assert (decisions.spki, decisions.spkf) == (8.0, 0.8)
    assert decisions.candidate is peak
    assert decisions.last is None


def test_candidate_is_the_largest_noise_peak() -> None:
    decisions = _decisions()
    first = _peak(1000, peak_i=1.0, peak_f=0.1)
    larger = _peak(1200, peak_i=1.5, peak_f=0.1)
    smaller = _peak(1400, peak_i=1.2, peak_f=0.1)
    equal = _peak(1600, peak_i=1.5, peak_f=0.1)
    decisions.classify(first)
    assert decisions.candidate is first
    decisions.classify(larger)
    assert decisions.candidate is larger
    decisions.classify(smaller)
    assert decisions.candidate is larger
    decisions.classify(equal)
    assert decisions.candidate is larger


def test_a_qrs_clears_the_candidate() -> None:
    decisions = _decisions()
    decisions.classify(_peak(1000, peak_i=1.0, peak_f=0.1))
    assert decisions.candidate is not None
    decisions.classify(_peak(1300))
    assert decisions.candidate is None
    assert decisions.output == [1260]


# --- search-back ------------------------------------------------------------------------------


def _ready_for_search_back() -> tuple[Any, Any]:
    decisions = _decisions()
    decisions.last = _peak(1000)
    decisions.output.append(960)
    decisions.rr_flag = True
    decisions.rr_intervals.append(300)
    candidate = _peak(1250, peak_i=1.5, peak_f=0.15)  # between the second and first thresholds
    decisions.candidate = candidate
    return decisions, candidate


def test_search_back_waits_for_166_percent_of_the_mean_interval() -> None:
    decisions, candidate = _ready_for_search_back()
    limit = math.floor(1.66 * 300.0 + 0.5)  # 498
    decisions.search_back(1000 + limit - 1)
    assert decisions.output == [960]
    assert decisions.candidate is candidate
    decisions.search_back(1000 + limit)
    assert decisions.output == [960, 1210]


def test_search_back_update() -> None:
    decisions, candidate = _ready_for_search_back()
    decisions.search_back(1600)
    assert decisions.output == [960, 1210]
    assert decisions.spki == 0.25 * 1.5 + 0.75 * 8.0
    assert decisions.spkf == 0.25 * 0.15 + 0.75 * 0.8
    assert (decisions.npki, decisions.npkf) == (0.0, 0.0)
    assert decisions.last is candidate
    assert decisions.candidate is None
    assert decisions.rr_flag is True
    assert list(decisions.rr_intervals) == [300, 250]


def test_search_back_uses_the_mean_of_the_intervals() -> None:
    decisions, _ = _ready_for_search_back()
    decisions.rr_intervals.clear()
    decisions.rr_intervals.extend([300, 300, 303])  # mean 301: limit floor(499.66 + 0.5) = 500
    decisions.search_back(1499)
    assert decisions.output == [960]
    decisions.search_back(1500)
    assert decisions.output == [960, 1210]


@pytest.mark.parametrize(("peak_i", "peak_f"), [(1.0, 0.15), (1.5, 0.1), (0.9, 0.05)])
def test_search_back_needs_the_candidate_above_both_second_thresholds(
    peak_i: float, peak_f: float
) -> None:
    decisions, _ = _ready_for_search_back()
    decisions.candidate = _peak(1250, peak_i=peak_i, peak_f=peak_f)  # TH_I2 = 1.0, TH_F2 = 0.1
    decisions.search_back(5000)
    assert decisions.output == [960]
    assert decisions.candidate is not None


def test_search_back_needs_a_last_qrs_an_interval_and_a_candidate() -> None:
    decisions, _ = _ready_for_search_back()
    decisions.rr_intervals.clear()
    decisions.search_back(5000)
    assert decisions.output == [960]

    decisions, _ = _ready_for_search_back()
    decisions.candidate = None
    decisions.search_back(5000)
    assert decisions.output == [960]

    decisions, _ = _ready_for_search_back()
    decisions.last = None
    decisions.search_back(5000)
    assert decisions.output == [960]


def test_search_back_finds_a_weak_beat(monkeypatch: pytest.MonkeyPatch, synthetic_ecg: Any) -> None:
    weak = 12
    raw, r_peaks = synthetic_ecg(FS_360, 75, beat_gains={weak: 0.4})
    x = _conditioned(raw, FS_360)
    found = qrs.detect_qrs(x, FS_360)
    assert found.tolist() == (r_peaks + 3).tolist()

    monkeypatch.setattr(qrs._Decisions, "search_back", lambda self, n: None)
    without = qrs.detect_qrs(x, FS_360)
    assert without.tolist() == (np.delete(r_peaks, weak) + 3).tolist()


# --- initialisation and re-learning -----------------------------------------------------------


def test_initialise_learns_the_levels_from_the_window() -> None:
    samples = qrs.detector_samples(FS_360)  # L = 720
    n = 2000
    rng = np.random.default_rng(11)
    signals = qrs.QrsSignals(
        bandpassed_mv=rng.standard_normal(n),
        derivative_mv_per_s=np.zeros(n),
        integrated=rng.random(n),
    )
    # Values just outside the window must not count.
    signals.integrated[1500 - 720] = 50.0
    signals.bandpassed_mv[1501] = -50.0
    decisions = qrs._Decisions(samples, signals)
    decisions.initialise(1500)

    window_y = signals.integrated[781:1501]
    window_b = np.abs(signals.bandpassed_mv[781:1501])
    assert decisions.spki == float(np.max(window_y)) / 3.0
    assert decisions.npki == math.fsum(window_y.tolist()) / 720 / 2.0
    assert decisions.spkf == float(np.max(window_b)) / 3.0
    assert decisions.npkf == math.fsum(window_b.tolist()) / 720 / 2.0
    assert decisions.init_n == 1500
    assert decisions.initialised


def test_first_initialisation_uses_the_samples_from_zero() -> None:
    samples = qrs.detector_samples(FS_360)
    signals = _signals()
    signals.integrated[0] = 9.0
    signals.integrated[719] = 3.0
    signals.integrated[720] = 100.0
    decisions = qrs._Decisions(samples, signals)
    assert not decisions.initialised
    decisions.initialise(samples.learning - 1)
    assert decisions.spki == 3.0
    assert decisions.npki == 12.0 / 720 / 2.0


def test_initialise_clears_the_rhythm_state_and_keeps_the_last_qrs() -> None:
    decisions = _decisions()
    last = _peak(1000)
    decisions.last = last
    decisions.rr_flag = True
    decisions.rr_intervals.extend([300, 310])
    decisions.candidate = _peak(1250, peak_i=1.0, peak_f=0.1)
    decisions.initialise(9000)
    assert list(decisions.rr_intervals) == []
    assert decisions.candidate is None
    assert decisions.rr_flag is False
    assert decisions.last is last
    assert decisions.init_n == 9000


def test_initialise_classifies_the_stored_peaks_of_the_window_in_order() -> None:
    samples = qrs.detector_samples(FS_360)
    signals = _signals(8000)
    signals.integrated[5000:5720] = 1.0  # SPKI = 1/3, NPKI = 0.5: TH_I1 = 0.5 + 0.25 * (-1/6)
    signals.bandpassed_mv[5000:5720] = 0.1
    decisions = qrs._Decisions(samples, signals)
    outside = _peak(4990)
    first = _peak(5100)
    second = _peak(5500)
    for peak in (outside, first, second):
        decisions.store(peak)
    decisions.initialise(5719)  # window [5000, 5719]
    assert decisions.output == [first.f, second.f]
    assert list(decisions.rr_intervals) == [400]  # the first QRS after an initialisation adds none


def test_stored_peaks_older_than_the_learning_window_are_dropped() -> None:
    decisions = _decisions()
    for m in (1000, 1500, 1719, 1720, 2000):
        decisions.store(_peak(m))
    decisions.store(_peak(2439))  # window of a later initialisation starts at 1720 or later
    assert [p.m for p in decisions.peaks] == [1720, 2000, 2439]


def test_relearn_is_due_eight_seconds_after_the_initialisation_without_a_qrs() -> None:
    decisions = _decisions()  # init_n = 719, no last QRS, G = 2880
    assert not decisions.relearn_due(719 + 2879)
    assert decisions.relearn_due(719 + 2880)


def test_relearn_is_due_eight_seconds_after_the_last_qrs() -> None:
    decisions = _decisions()
    decisions.last = _peak(5000)
    assert not decisions.relearn_due(5000 + 2879)
    assert decisions.relearn_due(5000 + 2880)


def test_relearn_counts_from_the_initialisation_when_it_is_later_than_the_last_qrs() -> None:
    decisions = _decisions()
    decisions.last = _peak(5000)
    decisions.init_n = 9000
    assert not decisions.relearn_due(9000 + 2879)
    assert decisions.relearn_due(9000 + 2880)


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
def test_detection_recovers_by_relearning_after_a_large_artefact(
    fs_hz: float, synthetic_ecg: Any
) -> None:
    samples = qrs.detector_samples(fs_hz)
    artefact = 12
    raw, r_peaks = synthetic_ecg(fs_hz, 75, duration_s=40.0, beat_gains={artefact: 10.0})
    found = qrs.detect_qrs(_conditioned(raw, fs_hz), fs_hz)
    offset = int(found[0] - r_peaks[0])
    r_artefact = int(r_peaks[artefact])

    # Every beat up to the artefact is found.
    n_before = artefact + 1
    assert found[:n_before].tolist() == (r_peaks[:n_before] + offset).tolist()
    # The artefact raises the signal levels: nothing is found until the detector learns again,
    # 8 s after it, from its last 2 s.
    gap_end = r_artefact + samples.relearn_after - samples.learning
    after = found[n_before:]
    assert after.size > 0
    assert int(after[0]) > gap_end
    assert int(after[0]) <= r_artefact + samples.relearn_after + samples.window
    # From there on, every beat is found again.
    resumed = r_peaks[r_peaks >= int(after[0]) - offset]
    assert after.tolist() == (resumed + offset).tolist()
    assert resumed.size >= 20


# --- the detector on whole signals ------------------------------------------------------------


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
@pytest.mark.parametrize("heart_rate_bpm", [40, 75, 180])
@pytest.mark.parametrize("variant", ["clean", "bw-mains50", "bw-mains60"])
def test_conditioned_synthetic_ecg_one_detection_per_beat(
    fs_hz: float, heart_rate_bpm: int, variant: str, synthetic_ecg: Any
) -> None:
    raw, r_peaks = synthetic_ecg(fs_hz, heart_rate_bpm, variant)
    mains_hz = 60 if variant == "bw-mains60" else 50
    found = qrs.detect_qrs(_conditioned(raw, fs_hz, mains_hz), fs_hz)
    # The reported index lies 8 ms after the R-wave centre: 3 samples at 360 Hz, 2 at 250 Hz.
    offset = {360.0: 3, 250.0: 2}[fs_hz]
    assert found.dtype == np.int64
    assert found.tolist() == (r_peaks + offset).tolist()


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
def test_unconditioned_fast_rhythm_still_gives_one_detection_per_beat(
    fs_hz: float, synthetic_ecg: Any
) -> None:
    # Without conditioning, the two largest lobes of the band-passed QRS swap at 180 bpm and the
    # fiducial moves by the distance between them. Each beat keeps exactly one detection.
    raw, r_peaks = synthetic_ecg(fs_hz, 180)
    found = qrs.detect_qrs(raw, fs_hz)
    assert found.shape == r_peaks.shape
    assert int(np.max(np.abs(found - r_peaks))) <= qrs.detector_samples(fs_hz).band_delay


@pytest.mark.parametrize("level", [0.0, 0.7, -2.5, 1e6])
@pytest.mark.parametrize("fs_hz", [125.0, 360.0, 1000.0])
def test_flat_input_gives_an_empty_array(level: float, fs_hz: float) -> None:
    found = qrs.detect_qrs(np.full(int(10 * fs_hz), level), fs_hz)
    assert found.dtype == np.int64
    assert found.shape == (0,)


def test_detect_qrs_validates_its_input() -> None:
    with pytest.raises(InvalidInputError, match="shorter than"):
        qrs.detect_qrs(np.zeros(3599), FS_360)
    with pytest.raises(InvalidInputError, match="non-finite"):
        qrs.detect_qrs(np.full(3600, np.nan), FS_360)
    with pytest.raises(InvalidInputError, match="sampling frequency"):
        qrs.detect_qrs(np.zeros(3600), float("nan"))


def test_detect_qrs_does_not_modify_its_input_and_is_repeatable(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(FS_360, 75)
    before = x.copy()
    first = qrs.detect_qrs(x, FS_360)
    second = qrs.detect_qrs(x, FS_360)
    assert np.array_equal(x, before)
    assert np.array_equal(first, second)
    assert first is not second


@pytest.mark.parametrize("fs_hz", [125.0, 250.0, 360.0, 1000.0])
def test_output_order_and_spacing_hold_on_noise(fs_hz: float) -> None:
    rng = np.random.default_rng(2024)
    refractory = qrs.detector_samples(fs_hz).refractory
    for _ in range(3):
        x = rng.standard_normal(int(30 * fs_hz))
        found = qrs.detect_qrs(x, fs_hz)
        assert found.size > 0
        assert int(found[0]) >= 0
        assert int(found[-1]) < x.shape[0]
        assert int(np.min(np.diff(found))) >= refractory


@pytest.mark.parametrize("fs_hz", [250.0, 360.0])
def test_detector_is_causal(fs_hz: float, synthetic_ecg: Any) -> None:
    # The detections of a truncated signal are the first detections of the whole signal.
    x, _ = synthetic_ecg(fs_hz, 75, "bw-mains50")
    rng = np.random.default_rng(5)
    noisy = x + 0.3 * rng.standard_normal(x.shape[0])
    for signal_mv in (x, noisy):
        whole = qrs.detect_qrs(signal_mv, fs_hz).tolist()
        for seconds in (10.0, 17.3, 25.0):
            part = qrs.detect_qrs(signal_mv[: int(seconds * fs_hz)], fs_hz).tolist()
            assert part == whole[: len(part)]
