"""Causal Pan-Tompkins QRS detection with delay compensation (SRS-006, architecture §8.7).

Reference algorithm: J. Pan and W. J. Tompkins, "A real-time QRS detection algorithm", IEEE
Trans. Biomed. Eng. 32(3):230-236, 1985. The peak rule follows P. S. Hamilton and W. J.
Tompkins, "Quantitative investigation of QRS detection rules using the MIT/BIH arrhythmia
database", IEEE Trans. Biomed. Eng. 33(12):1157-1165, 1986.

The detector uses only the current and past samples, with a bounded look-back, and takes its
decisions on candidate peaks in time order, so that a streaming implementation evaluates the
same procedure sample by sample. It reports the positions of the QRS complexes in the time
base of its input.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy import signal as _signal

from sinus_dsp._types import FloatArray, IndexArray
from sinus_dsp._units import ceil_samples_ms, round_samples, round_samples_ms
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.filters import apply_sos, butterworth2_highpass_sos, butterworth2_lowpass_sos
from sinus_dsp.input_checks import validate_input

BAND_LOW_HZ: Final = 5.0
BAND_HIGH_HZ: Final = 15.0
BAND_DELAY_MS: Final = 36
INTEGRATION_WINDOW_MS: Final = 150
PEAK_TIMEOUT_MS: Final = 95
REFRACTORY_MS: Final = 200
T_WAVE_WINDOW_MS: Final = 360
LEARNING_S: Final = 2
RELEARN_AFTER_S: Final = 8
SEARCH_BACK_FACTOR: Final = 1.66
RR_AVERAGE_COUNT: Final = 8
MIN_INTEGRATED: Final = 1e-4  # (mV/s)^2


@dataclass(frozen=True)
class DetectorSamples:
    """The detector parameters in samples, at one sampling frequency."""

    band_delay: int
    window: int
    peak_timeout: int
    refractory: int
    t_wave_window: int
    learning: int
    relearn_after: int


@dataclass(frozen=True)
class QrsSignals:
    """The intermediate signals of the detector, for unit tests and diagnostics."""

    bandpassed_mv: FloatArray
    derivative_mv_per_s: FloatArray
    integrated: FloatArray  # (mV/s)^2


def detector_samples(fs_hz: float) -> DetectorSamples:
    """Convert the detector parameters to samples at ``fs_hz``.

    SRS-006: times are rounded half up, except the refractory period, which is rounded up so
    that the spacing between reported indices is at least 200 ms.

    Raises:
        InvalidInputError: If ``fs_hz`` is not a positive finite number.
    """
    if not (math.isfinite(fs_hz) and fs_hz > 0.0):
        raise InvalidInputError(f"sampling frequency is not a positive finite number: {fs_hz!r}")
    return DetectorSamples(
        band_delay=round_samples_ms(BAND_DELAY_MS, fs_hz),
        window=round_samples_ms(INTEGRATION_WINDOW_MS, fs_hz),
        peak_timeout=round_samples_ms(PEAK_TIMEOUT_MS, fs_hz),
        refractory=ceil_samples_ms(REFRACTORY_MS, fs_hz),
        t_wave_window=round_samples_ms(T_WAVE_WINDOW_MS, fs_hz),
        learning=round_samples(LEARNING_S, fs_hz),
        relearn_after=round_samples(RELEARN_AFTER_S, fs_hz),
    )


def detection_band_sos(fs_hz: float) -> FloatArray:
    """Sections of the detection band-pass, shape ``(2, 6)``.

    SRS-006: the band-pass of the detection. A second-order Butterworth high-pass at 5 Hz
    followed by a second-order Butterworth low-pass at 15 Hz: the pass band of Pan and
    Tompkins.

    Raises:
        InvalidInputError: If 15 Hz is not below half the sampling frequency.
    """
    return np.vstack(
        [
            butterworth2_highpass_sos(BAND_LOW_HZ, fs_hz),
            butterworth2_lowpass_sos(BAND_HIGH_HZ, fs_hz),
        ]
    )


def _signals(x: FloatArray, fs_hz: float, window: int) -> QrsSignals:
    """The linear stages and the squaring, on an input that has already been checked."""
    # 1. Band-pass (mV). The high-pass section has zero gain at 0 Hz, so b[0] is exactly 0.
    bandpassed = apply_sos(detection_band_sos(fs_hz), x)
    # 2. Five-point derivative of Pan and Tompkins, made causal (mV/s); 2 samples of delay.
    derivative_taps = (fs_hz / 8.0) * np.array([1.0, 2.0, 0.0, -2.0, -1.0])
    derivative = np.asarray(_signal.lfilter(derivative_taps, [1.0], bandpassed), dtype=np.float64)
    # 3. Squaring ((mV/s)^2).
    squared = derivative * derivative
    # 4. Moving-window integration over N samples ((mV/s)^2).
    integration_taps = np.full(window, 1.0 / window)
    integrated = np.asarray(_signal.lfilter(integration_taps, [1.0], squared), dtype=np.float64)
    return QrsSignals(
        bandpassed_mv=bandpassed, derivative_mv_per_s=derivative, integrated=integrated
    )


def qrs_signals(conditioned_mv: npt.ArrayLike, fs_hz: float) -> QrsSignals:
    """Compute the intermediate signals of the detector from a conditioned ECG.

    SRS-006: the linear stages of the detection, all causal: band-pass 5 Hz to 15 Hz,
    five-point derivative, squaring, and moving-window integration over 150 ms.

    Args:
        conditioned_mv: The ECG after signal conditioning, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.

    Raises:
        InvalidInputError: If the input is rejected by the input checks.
    """
    x = validate_input(conditioned_mv, fs_hz)
    fs = float(fs_hz)
    return _signals(x, fs, detector_samples(fs).window)


@dataclass(frozen=True)
class _Peak:
    """A confirmed peak of the integrated signal and its features."""

    m: int  # index of the maximum of the integrated signal
    peak_i: float  # integrated signal at m, (mV/s)^2
    peak_f: float  # largest |band-passed signal| in the window of the peak, mV
    f: int  # fiducial point: index of the QRS in the input time base
    slope: float  # largest |derivative| in the window of the peak, mV/s


class _PeakTracker:
    """One maximum of the integrated signal per rise, found causally."""

    def __init__(self, peak_timeout: int) -> None:
        self._peak_timeout = peak_timeout
        self._value = 0.0
        self._index: int | None = None

    def step(self, n: int, y_n: float, y_previous: float) -> int | None:
        """Process sample ``n`` (``n >= 1``); return the index of a peak confirmed at ``n``."""
        if y_n > y_previous and y_n > self._value and y_n >= MIN_INTEGRATED:
            self._value = y_n
            self._index = n
            return None
        index = self._index
        if index is not None and (y_n < self._value / 2.0 or n - index > self._peak_timeout):
            self._value = 0.0
            self._index = None
            return index
        return None


def _peak_features(m: int, signals: QrsSignals, samples: DetectorSamples) -> _Peak:
    """Features of the peak at ``m``, from a bounded look-back on the intermediate signals."""
    # The band-pass samples whose derivative enters the window of y[m].
    low = max(0, m - samples.window - 1)
    high = max(0, m - 2)
    magnitudes = np.abs(signals.bandpassed_mv[low : high + 1])
    k_star = low + int(np.argmax(magnitudes))
    slope_low = max(0, m - samples.window + 1)
    return _Peak(
        m=m,
        peak_i=float(signals.integrated[m]),
        peak_f=float(magnitudes[k_star - low]),
        # Delay compensation: the band-pass delays the QRS by D samples.
        f=max(0, k_star - samples.band_delay),
        slope=float(np.max(np.abs(signals.derivative_mv_per_s[slope_low : m + 1]))),
    )


class _Decisions:
    """The adaptive thresholds and the decisions on the confirmed peaks."""

    def __init__(self, samples: DetectorSamples, signals: QrsSignals) -> None:
        self._samples = samples
        self._integrated = signals.integrated
        self._abs_bandpassed = np.abs(signals.bandpassed_mv)
        self.spki = 0.0
        self.npki = 0.0
        self.spkf = 0.0
        self.npkf = 0.0
        self.last: _Peak | None = None
        self.rr_intervals: deque[int] = deque(maxlen=RR_AVERAGE_COUNT)
        self.rr_flag = False
        self.candidate: _Peak | None = None
        self.init_n: int | None = None
        self.peaks: deque[_Peak] = deque()
        self.output: list[int] = []

    @property
    def initialised(self) -> bool:
        return self.init_n is not None

    @property
    def threshold_i1(self) -> float:
        return self.npki + 0.25 * (self.spki - self.npki)

    @property
    def threshold_f1(self) -> float:
        return self.npkf + 0.25 * (self.spkf - self.npkf)

    def store(self, peak: _Peak) -> None:
        """Keep the record of a confirmed peak while its ``m`` can enter a learning window."""
        self.peaks.append(peak)
        oldest = peak.m - self._samples.learning + 1
        while self.peaks[0].m < oldest:
            self.peaks.popleft()

    def _accept(self, peak: _Peak, weight: float) -> None:
        """Make ``peak`` a QRS, with a signal-level update of the given weight."""
        self.spki = weight * peak.peak_i + (1.0 - weight) * self.spki
        self.spkf = weight * peak.peak_f + (1.0 - weight) * self.spkf
        if self.last is not None and self.rr_flag:
            self.rr_intervals.append(peak.m - self.last.m)
        self.last = peak
        self.rr_flag = True
        self.candidate = None
        self.output.append(peak.f)

    def _noise(self, peak: _Peak) -> None:
        self.npki = 0.125 * peak.peak_i + 0.875 * self.npki
        self.npkf = 0.125 * peak.peak_f + 0.875 * self.npkf

    def classify(self, peak: _Peak) -> None:
        """Classify a confirmed peak: ignored, QRS, T wave or noise."""
        last = self.last
        refractory = self._samples.refractory
        # 1. Refractory period, on the peak position and on the reported index.
        if last is not None and (peak.m - last.m < refractory or peak.f - last.f < refractory):
            return
        # 2. Above the first thresholds of both signals.
        if peak.peak_i > self.threshold_i1 and peak.peak_f > self.threshold_f1:
            if (
                last is not None
                and peak.m - last.m < self._samples.t_wave_window
                and peak.slope < 0.5 * last.slope
            ):
                self._noise(peak)  # T wave
                return
            self._accept(peak, 0.125)
            return
        # 3. Noise peak; the largest one since the last QRS is the search-back candidate.
        self._noise(peak)
        if self.candidate is None or peak.peak_i > self.candidate.peak_i:
            self.candidate = peak

    def search_back(self, n: int) -> None:
        """Accept the candidate with the second thresholds if a QRS is overdue at ``n``."""
        last = self.last
        candidate = self.candidate
        if last is None or candidate is None or not self.rr_intervals:
            return
        mean_rr = math.fsum(self.rr_intervals) / len(self.rr_intervals)
        limit = math.floor(SEARCH_BACK_FACTOR * mean_rr + 0.5)
        if (
            n - last.m >= limit
            and candidate.peak_i > 0.5 * self.threshold_i1
            and candidate.peak_f > 0.5 * self.threshold_f1
        ):
            self._accept(candidate, 0.25)

    def relearn_due(self, n: int) -> bool:
        """Whether no QRS was found for the re-learning time before ``n``."""
        assert self.init_n is not None
        reference = self.init_n if self.last is None else max(self.last.m, self.init_n)
        return n - reference >= self._samples.relearn_after

    def initialise(self, n: int) -> None:
        """Learn the levels from the last ``learning`` samples, then classify their peaks."""
        low = max(0, n - self._samples.learning + 1)
        integrated = self._integrated[low : n + 1]
        abs_bandpassed = self._abs_bandpassed[low : n + 1]
        count = n + 1 - low
        self.spki = float(np.max(integrated)) / 3.0
        self.npki = math.fsum(integrated.tolist()) / count / 2.0
        self.spkf = float(np.max(abs_bandpassed)) / 3.0
        self.npkf = math.fsum(abs_bandpassed.tolist()) / count / 2.0
        self.rr_intervals.clear()
        self.candidate = None
        self.rr_flag = False
        self.init_n = n
        # The last QRS is kept, for the refractory period and the output spacing.
        for peak in [p for p in self.peaks if low <= p.m <= n]:
            self.classify(peak)


def _detect(x: FloatArray, fs_hz: float) -> IndexArray:
    """Detect the QRS complexes of a conditioned signal that has already been checked."""
    samples = detector_samples(fs_hz)
    signals = _signals(x, fs_hz, samples.window)
    integrated = signals.integrated.tolist()
    tracker = _PeakTracker(samples.peak_timeout)
    decisions = _Decisions(samples, signals)
    learning = samples.learning

    previous = 0.0
    for n, y_n in enumerate(integrated):
        # 1. A peak confirmed at n is stored, and classified once the detector is initialised.
        if n >= 1:
            m = tracker.step(n, y_n, previous)
            if m is not None:
                peak = _peak_features(m, signals, samples)
                decisions.store(peak)
                if decisions.initialised:
                    decisions.classify(peak)
        previous = y_n
        # 2. First initialisation, at the end of the learning period.
        if n == learning - 1:
            decisions.initialise(n)
            continue
        # 3. Search-back, then re-learning.
        if n >= learning:
            decisions.search_back(n)
            if decisions.relearn_due(n):
                decisions.initialise(n)

    return np.array(decisions.output, dtype=np.int64)


def detect_qrs(conditioned_mv: npt.ArrayLike, fs_hz: float) -> IndexArray:
    """Detect the QRS complexes of a conditioned ECG.

    SRS-006: returns the sample indices of the detected QRS complexes in the time base of
    the input (index 0 is the first input sample), strictly increasing and at least 200 ms
    apart. A flat input gives an empty array and no error.

    The input is expected to be conditioned (baseline wander and mains interference removed);
    ``sinus_dsp.pipeline.detect_beats`` conditions a raw ECG first.

    Args:
        conditioned_mv: The ECG after signal conditioning, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.

    Returns:
        A new int64 array of sample indices, possibly empty.

    Raises:
        InvalidInputError: If the input is rejected by the input checks.
    """
    x = validate_input(conditioned_mv, fs_hz)
    return _detect(x, float(fs_hz))
