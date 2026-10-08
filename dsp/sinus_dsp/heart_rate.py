"""Heart rate from the detections (architecture §13.5).

SRS-024: the heart rate is reported at each detection marked reliable and at each change of
its validity or of the reason for which it is withheld, computed only from intervals between
consecutive reliable detections of the stream. SRS-025: one missed or one added detection
moves the reported rate by no more than 5 bpm. SRS-026: the rate is withheld as "not enough
beats", "no recent beat" or "out of range".

The estimator and every decision use integers only (the real-time library makes the same
decisions); only the rate itself is a floating-point value.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

import numpy as np
import numpy.typing as npt

from sinus_dsp.errors import InvalidInputError
from sinus_dsp.input_checks import validate_fs

STATUS_VALID: Final = "valid"
STATUS_NOT_ENOUGH_BEATS: Final = "not_enough_beats"
STATUS_NO_RECENT_BEAT: Final = "no_recent_beat"
STATUS_OUT_OF_RANGE: Final = "out_of_range"
HEART_RATE_STATUSES: Final = (
    STATUS_VALID,
    STATUS_NOT_ENOUGH_BEATS,
    STATUS_NO_RECENT_BEAT,
    STATUS_OUT_OF_RANGE,
)
#: SRS-026: intervals needed for the first heart rate.
MIN_INTERVALS: Final = 4
#: Intervals of the window of the robust estimate.
ROBUST_WINDOW: Final = 5
#: Intervals of the mean estimate.
MEAN_WINDOW: Final = 6
#: Limits of an inlier around the middle interval, in percent (RR AVERAGE2 of Pan and Tompkins).
INLIER_LOW_PERCENT: Final = 92
INLIER_HIGH_PERCENT: Final = 116
#: SRS-026: the range of the rate, as the mean interval (200 bpm and 30 bpm).
MIN_INTERVAL_MS: Final = 300
MAX_INTERVAL_MS: Final = 2000
#: SRS-026: the time without a reliable detection after which the rate is withheld.
NO_RECENT_BEAT_MS: Final = 3000
METHOD_ROBUST: Final = "robust"
METHOD_MEAN: Final = "mean"


@dataclass(frozen=True)
class IntervalEstimate:
    """``n_intervals`` (k) intervals that sum to ``span_samples`` (S), by ``method``."""

    n_intervals: int
    span_samples: int
    method: str


@dataclass(frozen=True)
class HeartRateEvent:
    """One report of the heart rate (SRS-024).

    ``beat_index`` is the index of the reliable detection it is reported at, ``None`` for a
    change of status at no detection. ``bpm`` is given for ``valid`` and ``out_of_range``.
    """

    sample: int
    beat_index: int | None
    status: str
    bpm: float | None


def _ms_samples(milliseconds: int, fs_hz: float) -> Fraction:
    """``milliseconds * fs_hz / 1000`` samples, exactly."""
    return Fraction(milliseconds) * Fraction(fs_hz) / 1000


def no_recent_beat_samples(fs_hz: float) -> int:
    """SRS-026: ``ceil(3000 * fs_hz / 1000)`` samples (1080 at 360 Hz).

    Raises:
        InvalidInputError: If ``fs_hz`` is rejected by ``validate_fs``.
    """
    fs = validate_fs(fs_hz)
    return math.ceil(_ms_samples(NO_RECENT_BEAT_MS, fs))


def estimate_intervals(intervals: Sequence[int]) -> IntervalEstimate:
    """Choose the intervals of the heart rate estimate (architecture §13.5, steps 1 to 4).

    SRS-024, SRS-025: the window is the last five intervals; the middle one fixes the limits of
    the inliers. With no outlier, one, or two adjacent ones (a missed or an added detection, an
    isolated premature beat), the estimate is that of the inliers (``robust``); otherwise it is
    the mean of all the intervals given (``mean``).

    Args:
        intervals: Four to six positive integers (samples), oldest first.

    Raises:
        InvalidInputError: If ``intervals`` does not hold four to six positive integers.
    """
    values = _checked_intervals(intervals)
    window = values[-ROBUST_WINDOW:]
    middle = sorted(window)[2]
    outlier = [
        100 * v < INLIER_LOW_PERCENT * middle or 100 * v > INLIER_HIGH_PERCENT * middle
        for v in window
    ]
    where = [i for i, is_outlier in enumerate(outlier) if is_outlier]
    if len(where) <= 1 or (len(where) == 2 and where[1] == where[0] + 1):
        inliers = [v for v, is_outlier in zip(window, outlier, strict=True) if not is_outlier]
        return IntervalEstimate(len(inliers), sum(inliers), METHOD_ROBUST)
    return IntervalEstimate(len(values), sum(values), METHOD_MEAN)


def _checked_intervals(intervals: Sequence[int]) -> list[int]:
    try:
        count = len(intervals)
    except TypeError:
        raise InvalidInputError("intervals is not a sequence") from None
    if not MIN_INTERVALS <= count <= MEAN_WINDOW:
        raise InvalidInputError(
            f"intervals holds {MIN_INTERVALS} to {MEAN_WINDOW} values, not {count}"
        )
    values: list[int] = []
    for v in intervals:
        if isinstance(v, bool) or not isinstance(v, numbers.Integral) or v <= 0:
            raise InvalidInputError(f"interval is not a positive integer: {v!r}")
        values.append(int(v))
    return values


def interval_rate_bpm(estimate: IntervalEstimate, fs_hz: float) -> float:
    """The rate of an estimate, ``60.0 * fs_hz * k / S`` bpm in float64, in this order."""
    fs = validate_fs(fs_hz)
    return 60.0 * fs * estimate.n_intervals / estimate.span_samples


def interval_in_range(estimate: IntervalEstimate, fs_hz: float) -> bool:
    """SRS-026: whether the mean interval lies from 300 ms to 2000 ms (200 to 30 bpm), bounds in.

    Exact, on integers: ``ceil(300 k fs / 1000) <= S <= floor(2000 k fs / 1000)``.
    """
    fs = validate_fs(fs_hz)
    k = estimate.n_intervals
    low = math.ceil(_ms_samples(MIN_INTERVAL_MS, fs) * k)
    high = math.floor(_ms_samples(MAX_INTERVAL_MS, fs) * k)
    return low <= estimate.span_samples <= high


def _integer_array(values: npt.ArrayLike, name: str, *, kind: str) -> list[int] | list[bool]:
    array = np.asarray(values)
    if array.ndim != 1:
        raise InvalidInputError(f"{name} is not one-dimensional")
    if array.size and array.dtype.kind not in kind:
        raise InvalidInputError(f"{name} has the wrong type: {array.dtype}")
    result: list[int] | list[bool] = array.tolist()
    return result


def _checked_n_samples(n_samples: int) -> int:
    if isinstance(n_samples, bool) or not isinstance(n_samples, numbers.Integral) or n_samples < 1:
        raise InvalidInputError(f"n_samples is not an integer of at least 1: {n_samples!r}")
    return int(n_samples)


def track_heart_rate(
    indices: npt.ArrayLike,
    startup: npt.ArrayLike,
    fs_hz: float,
    n_samples: int,
    *,
    reported_at: npt.ArrayLike | None = None,
) -> tuple[HeartRateEvent, ...]:
    """The heart rate events of a stream, sample by sample (SRS-024, SRS-025, SRS-026).

    The stream starts with the status ``not_enough_beats`` (no event at sample 0). A start-up
    detection produces no event and no interval. A reliable detection adds the interval from
    the previous detection, when that is reliable and later than the last "no recent beat",
    and reports an event: withheld (``not_enough_beats``, or ``no_recent_beat`` after one has
    started) with fewer than four intervals, otherwise ``valid`` or ``out_of_range`` with the
    rate of :func:`estimate_intervals`. When a sample lies at least
    :func:`no_recent_beat_samples` after the last reliable detection reported, the status
    becomes ``no_recent_beat`` (an event at no detection), the intervals are cleared, and
    four new ones are needed.

    Args:
        indices: Detection indices, strictly increasing, within ``[0, n_samples)``.
        startup: One boolean per detection, true for a start-up detection.
        fs_hz: The sampling frequency, in Hz.
        n_samples: The length of the stream, in samples.
        reported_at: The sample at which each detection is reported, non-decreasing, with
            ``indices[i] <= reported_at[i] < n_samples``; by default each detection is
            reported at its own index.

    Returns:
        The events in order of sample.

    Raises:
        InvalidInputError: If an argument is rejected by the checks of architecture §13.5.
    """
    fs = validate_fs(fs_hz)
    length = _checked_n_samples(n_samples)
    idx = _integer_array(indices, "indices", kind="iu")
    marks = _integer_array(startup, "startup", kind="b")
    if len(marks) != len(idx):
        raise InvalidInputError(f"startup holds {len(marks)} values for {len(idx)} indices")
    if any(b <= a for a, b in zip(idx, idx[1:], strict=False)):
        raise InvalidInputError("indices is not strictly increasing")
    if idx and (idx[0] < 0 or idx[-1] >= length):
        raise InvalidInputError(f"indices lies outside [0, {length})")
    if reported_at is None:
        reports = list(idx)
    else:
        reports = [int(r) for r in _integer_array(reported_at, "reported_at", kind="iu")]
        if len(reports) != len(idx):
            raise InvalidInputError(
                f"reported_at holds {len(reports)} values for {len(idx)} indices"
            )
        if any(b < a for a, b in zip(reports, reports[1:], strict=False)):
            raise InvalidInputError("reported_at is decreasing")
        if any(not i <= r < length for i, r in zip(idx, reports, strict=True)):
            raise InvalidInputError("reported_at is not within [index, n_samples) for a detection")

    wait = no_recent_beat_samples(fs)
    events: list[HeartRateEvent] = []
    window: list[int] = []
    count = 0
    reset_at = -1
    previous: tuple[int, bool] | None = None  # index, start-up mark
    last: int | None = None  # index of the last reliable detection reported
    fired_for: int | None = None
    status = STATUS_NOT_ENOUGH_BEATS

    def fire(sample: int) -> None:
        nonlocal reset_at, count, status, fired_for
        fired_for = last
        reset_at = sample
        window.clear()
        count = 0
        if status != STATUS_NO_RECENT_BEAT:
            status = STATUS_NO_RECENT_BEAT
            events.append(HeartRateEvent(sample, None, status, None))

    def pending(before: int) -> bool:
        return last is not None and fired_for != last and last + wait < before

    position = 0
    while position < len(idx):
        n = reports[position]
        if pending(n):
            assert last is not None
            fire(last + wait)
        while position < len(idx) and reports[position] == n:
            index = idx[position]
            if marks[position]:
                previous = (index, True)
            else:
                if previous is not None and not previous[1] and previous[0] > reset_at:
                    window.append(index - previous[0])
                    del window[:-MEAN_WINDOW]
                    count += 1
                previous = (index, False)
                last = index
                if count < MIN_INTERVALS:
                    status = STATUS_NO_RECENT_BEAT if reset_at >= 0 else STATUS_NOT_ENOUGH_BEATS
                    events.append(HeartRateEvent(n, index, status, None))
                else:
                    estimate = estimate_intervals(window)
                    status = (
                        STATUS_VALID if interval_in_range(estimate, fs) else STATUS_OUT_OF_RANGE
                    )
                    events.append(HeartRateEvent(n, index, status, interval_rate_bpm(estimate, fs)))
            position += 1
        if last is not None and fired_for != last and n - last >= wait:
            fire(n)
    if pending(length):
        assert last is not None
        fire(last + wait)
    return tuple(events)
