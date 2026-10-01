"""EC57 beat-by-beat matching of detections to reference beats (SRS-008, architecture §8.8).

The scoring of ANSI/AAMI EC57 is defined in practice by ``bxb``, the beat-by-beat comparator of
the WFDB software package. This module reproduces the part of ``bxb`` that determines the QRS
counts: a match window of 150 ms, inclusive; a learning period of 5 minutes that is not
scored; a sequential, closest-first pairing with a one-step look-ahead (it is not a maximum
matching); and ventricular flutter and fibrillation episodes that are not scored.

All the arithmetic is on Python integers, so the rules hold exactly.
"""

from __future__ import annotations

import bisect
import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

from sinus_dsp._units import floor_samples_ms
from sinus_dsp.data.records import Annotation
from sinus_dsp.errors import InvalidInputError

MATCH_WINDOW_MS: Final = 150
LEARNING_PERIOD_S: Final = 300

_VF_ONSET: Final = "["
_VF_OFFSET: Final = "]"

# Sentinel that ends the reference and the detection lists.
_HUGE: Final = 2**62
# Samples, the window and the start are below this bound, so that the sentinel is never
# within the window of a sample.
_MAX_VALUE: Final = 2**61


@dataclass(frozen=True)
class Episode:
    """A ventricular flutter or fibrillation episode, which is not scored (SRS-008).

    Attributes:
        start_sample: Sample of the ``[`` annotation.
        end_sample: Sample of the matching ``]`` annotation, inclusive.
    """

    start_sample: int
    end_sample: int


@dataclass(frozen=True)
class MatchResult:
    """Outcome of the matching of one record (SRS-008).

    Attributes:
        tp: Number of pairs.
        fn: Number of scored reference beats without a match.
        fp: Number of scored detections without a match.
        matched: The pairs ``(reference sample, detection sample)``, in time order.
        false_negatives: Reference samples without a match.
        false_positives: Detection samples without a match.
        reference_excluded: Reference beats inside ventricular flutter or fibrillation
            episodes, never scored.
        detections_excluded: Unpaired detections inside such episodes, not counted.
    """

    tp: int
    fn: int
    fp: int
    matched: tuple[tuple[int, int], ...]
    false_negatives: tuple[int, ...]
    false_positives: tuple[int, ...]
    reference_excluded: int
    detections_excluded: int


def match_window_samples(fs_hz: float) -> int:
    """Return the match window in samples: ``floor(150 * fs_hz / 1000)``.

    SRS-008: a detection and a reference beat can match if they are at most 150 ms apart.
    The conversion rounds down, so the bound is never exceeded: 54 samples at 360 Hz.

    Raises:
        InvalidInputError: If ``fs_hz`` is not a positive finite number.
    """
    _check_fs(fs_hz)
    return floor_samples_ms(MATCH_WINDOW_MS, fs_hz)


def learning_period_samples(fs_hz: float) -> int:
    """Return the first scored sample, 5:00 into the record: ``ceil(300 * fs_hz)``.

    SRS-008: reference beats before 5:00 are not scored. A reference beat at the returned
    sample is scored; one at the sample before is not. 108000 samples at 360 Hz.

    Raises:
        InvalidInputError: If ``fs_hz`` is not a positive finite number.
    """
    _check_fs(fs_hz)
    return math.ceil(LEARNING_PERIOD_S * fs_hz)


def vf_episodes(annotations: Sequence[Annotation], n_samples: int) -> tuple[Episode, ...]:
    """Return the ventricular flutter and fibrillation episodes of a record.

    SRS-008: an episode runs from an onset annotation (``[``) to the next offset annotation
    (``]``), both included; an episode without an offset lasts until the end of the record.

    The annotations are scanned in the order given. A ``[`` opens an episode and the next
    ``]`` closes it. A ``[`` while an episode is open and a ``]`` while none is open are
    ignored. An episode still open at the end ends at ``n_samples - 1``.

    Args:
        annotations: The non-beat annotations of the record, in file order.
        n_samples: Number of samples of the record.

    Returns:
        The episodes, in the order of their onsets.
    """
    episodes: list[Episode] = []
    open_start: int | None = None
    for annotation in annotations:
        if annotation.symbol == _VF_ONSET:
            if open_start is None:
                open_start = annotation.sample
        elif annotation.symbol == _VF_OFFSET and open_start is not None:
            episodes.append(Episode(start_sample=open_start, end_sample=annotation.sample))
            open_start = None
    if open_start is not None:
        episodes.append(Episode(start_sample=open_start, end_sample=n_samples - 1))
    return tuple(episodes)


def match_beats(
    reference_samples: npt.ArrayLike,
    detection_samples: npt.ArrayLike,
    *,
    window_samples: int,
    start_sample: int,
    vf: Sequence[Episode] = (),
) -> MatchResult:
    """Match detections to reference beats, beat by beat, with the pairing rules of ``bxb``.

    SRS-008. The procedure is the one of architecture §8.8.2:

    1. The reference beats inside an episode of ``vf`` (bounds included) are removed and
       counted in ``reference_excluded``. A sentinel ends both lists.
    2. ``T`` and ``T2`` are the current and the next reference beat; ``t`` and ``t2`` the
       current and the next detection.
    3. Start. ``T`` is the first reference beat at or after ``start_sample``; ``t2`` is the
       first detection at or after it and ``t`` the detection before it, if any. If ``t``
       exists, ``T - t <= window_samples`` and ``T - t < |T - t2|``, the pair ``(T, t)`` is
       made and both lists advance. Otherwise the detections advance (the detection before
       the start is dropped, not scored); then, if ``t - start_sample <= window_samples`` and
       ``|T - t2| < |T - t|``, they advance once more (the first detection after the start
       is dropped, not scored).
    4. Loop, until both lists are at their sentinel. If ``t < T``: the pair ``(T, t)`` is
       made if ``T - t <= window_samples`` and (``T - t < |T - t2|`` or
       ``|T2 - t2| < |T - t2|``); otherwise ``t`` is not counted if it lies inside an episode
       of ``vf``, and is a false positive if it does not, and the detections advance. If
       ``T <= t``: the pair is made if ``t - T <= window_samples`` and (``t - T < |t - T2|``
       or ``|t2 - T2| < |t - T2|``); otherwise ``T`` is a false negative and the reference
       advances. After a pair both lists advance.

    Args:
        reference_samples: Samples of the reference beats, integers, non-decreasing.
        detection_samples: Samples of the detections, integers, strictly increasing.
        window_samples: Match window, in samples (:func:`match_window_samples`).
        start_sample: First scored sample (:func:`learning_period_samples`).
        vf: Episodes that are not scored (:func:`vf_episodes`).

    Returns:
        The pairs, the false negatives, the false positives and the numbers not scored.

    Raises:
        InvalidInputError: If a list is not a one-dimensional sequence of integers, if the
            reference samples decrease, if the detection samples do not strictly increase,
            if ``window_samples`` or ``start_sample`` is negative or not an integer, or if a
            value is not below 2**61.
    """
    window = _check_parameter(window_samples, "window_samples")
    start = _check_parameter(start_sample, "start_sample")
    all_reference = _sample_list(reference_samples, "reference samples", strictly=False)
    all_detections = _sample_list(detection_samples, "detection samples", strictly=True)
    episodes = tuple(vf)

    # 1. Scored reference sequence. Two sentinels: the element after the current one is read
    # even when the current one is the sentinel.
    reference = [sample for sample in all_reference if not _inside(sample, episodes)]
    reference_excluded = len(all_reference) - len(reference)
    reference += [_HUGE, _HUGE]
    detections = [*all_detections, _HUGE, _HUGE]

    matched: list[tuple[int, int]] = []
    false_negatives: list[int] = []
    false_positives: list[int] = []
    detections_excluded = 0

    # 3. Start. i is the index of T in the reference, j the index of t in the detections.
    i = bisect.bisect_left(reference, start)
    first_scored = bisect.bisect_left(detections, start)
    big_t = reference[i]
    paired_at_start = False
    if first_scored > 0:
        t = detections[first_scored - 1]
        t2 = detections[first_scored]
        if big_t - t <= window and big_t - t < abs(big_t - t2):
            matched.append((big_t, t))
            i += 1
            paired_at_start = True
    j = first_scored
    if not paired_at_start:
        t = detections[j]
        t2 = detections[j + 1]
        if t - start <= window and abs(big_t - t2) < abs(big_t - t):
            j += 1

    # 4. Loop. The current element of a list advances only while it is not the sentinel.
    while reference[i] != _HUGE or detections[j] != _HUGE:
        big_t, big_t2 = reference[i], reference[i + 1]
        t, t2 = detections[j], detections[j + 1]
        if t < big_t:
            if big_t - t <= window and (
                big_t - t < abs(big_t - t2) or abs(big_t2 - t2) < abs(big_t - t2)
            ):
                matched.append((big_t, t))
                i += 1
                j += 1
            else:
                if _inside(t, episodes):
                    detections_excluded += 1
                else:
                    false_positives.append(t)
                j += 1
        elif t - big_t <= window and (
            t - big_t < abs(t - big_t2) or abs(t2 - big_t2) < abs(t - big_t2)
        ):
            matched.append((big_t, t))
            i += 1
            j += 1
        else:
            false_negatives.append(big_t)
            i += 1

    # 5. Counts.
    return MatchResult(
        tp=len(matched),
        fn=len(false_negatives),
        fp=len(false_positives),
        matched=tuple(matched),
        false_negatives=tuple(false_negatives),
        false_positives=tuple(false_positives),
        reference_excluded=reference_excluded,
        detections_excluded=detections_excluded,
    )


def _check_fs(fs_hz: float) -> None:
    if not (math.isfinite(fs_hz) and fs_hz > 0.0):
        raise InvalidInputError(f"sampling frequency is not a positive finite number: {fs_hz!r}")


def _check_parameter(value: int, name: str) -> int:
    """Check a number of samples given as a parameter and return it as an ``int``."""
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise InvalidInputError(f"{name} is not an integer: {value!r}")
    number = int(value)
    if number < 0:
        raise InvalidInputError(f"{name} is negative: {number}")
    if number >= _MAX_VALUE:
        raise InvalidInputError(f"{name} is not below 2**61: {number}")
    return number


def _sample_list(samples: npt.ArrayLike, name: str, *, strictly: bool) -> list[int]:
    """Check a list of samples and return it as Python integers."""
    try:
        array = np.asarray(samples)
    except (TypeError, ValueError) as error:
        raise InvalidInputError(f"{name} do not convert to an array: {error}") from error
    if array.ndim != 1:
        raise InvalidInputError(
            f"{name} are not one-dimensional: {array.ndim} dimensions, shape {array.shape}"
        )
    if array.size == 0:
        return []
    if array.dtype.kind not in "iu":
        raise InvalidInputError(f"{name} are not integers: dtype {array.dtype}")
    values = [int(value) for value in array.tolist()]
    for index in range(1, len(values)):
        previous, current = values[index - 1], values[index]
        if current < previous or (strictly and current == previous):
            order = "strictly increasing" if strictly else "non-decreasing"
            raise InvalidInputError(
                f"{name} are not {order}: {current} at index {index} follows {previous}"
            )
    if values[-1] >= _MAX_VALUE:
        raise InvalidInputError(f"{name} are not below 2**61: {values[-1]}")
    return values


def _inside(sample: int, episodes: Sequence[Episode]) -> bool:
    """Whether a sample lies inside any episode, bounds included."""
    return any(episode.start_sample <= sample <= episode.end_sample for episode in episodes)
