"""Requirement tests of SRS-008: EC57 beat-by-beat matching (risk control RC-004).

Every case is built at 360 Hz from the rules of the SRS-008 statement: a match window of
150 ms (54 samples, inclusive), sequential pairing in time order with its look-ahead, the
5:00 boundary (sample 108000), and ventricular flutter or fibrillation episodes. The expected
pairs, false negatives, false positives and items not scored are worked out by hand from the
statement; the docstring of each test gives the reasoning.

An item "not scored" appears in no pair, in no false negative and in no false positive. For
the items inside a ventricular flutter episode after 5:00, the result also gives their
numbers. How the items not scored are counted when an episode reaches back before 5:00, or
holds the detection left unscored by the rule at 5:00, is stated by SRS-012 and verified in
`test_srs_012_not_scored_counts.py`; the cases of this file that involve both only check the
pairs, the false negatives and the false positives.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pytest

from sinus_dsp.data.records import Annotation
from sinus_dsp.evaluation.matching import (
    Episode,
    MatchResult,
    learning_period_samples,
    match_beats,
    match_window_samples,
    vf_episodes,
)

FS_HZ = 360.0
WINDOW = 54  # 150 ms at 360 Hz
START = 108000  # 5:00 at 360 Hz

# Position of the cases that do not involve the 5:00 boundary, far after it.
X = 200000

# Matched beats placed around a case, at least 240 samples away from it, so that the case is
# also exercised in the middle of a sequence. Each has a detection 3 samples after the beat.
CONTEXT_BEFORE = (X - 900, X - 600)
CONTEXT_AFTER = (X + 600, X + 900)

Pairs = Sequence[tuple[int, int]]


def _match(
    reference: Sequence[int], detections: Sequence[int], vf: Sequence[Episode] = ()
) -> MatchResult:
    """Match two lists at 360 Hz, passed as int64 arrays."""
    return match_beats(
        np.asarray(reference, dtype=np.int64),
        np.asarray(detections, dtype=np.int64),
        window_samples=WINDOW,
        start_sample=START,
        vf=vf,
    )


def _check(
    result: MatchResult,
    *,
    pairs: Pairs,
    false_negatives: Sequence[int],
    false_positives: Sequence[int],
    reference_excluded: int = 0,
    detections_excluded: int = 0,
) -> None:
    """Compare a result with the expected pairs, errors and numbers of items not scored."""
    assert [(int(r), int(d)) for r, d in result.matched] == list(pairs)
    assert [int(s) for s in result.false_negatives] == list(false_negatives)
    assert [int(s) for s in result.false_positives] == list(false_positives)
    assert result.tp == len(pairs)
    assert result.fn == len(false_negatives)
    assert result.fp == len(false_positives)
    assert result.reference_excluded == reference_excluded
    assert result.detections_excluded == detections_excluded


@pytest.fixture(params=[False, True], ids=["isolated", "between-matched-beats"])
def context(request: pytest.FixtureRequest) -> bool:
    """Whether the case stands alone or between matched beats."""
    return bool(request.param)


def _in_context(
    reference: Sequence[int], detections: Sequence[int], pairs: Pairs, context: bool
) -> tuple[list[int], list[int], list[tuple[int, int]]]:
    """Add the context beats, their detections and their pairs around a case."""
    if not context:
        return list(reference), list(detections), list(pairs)
    before = [(r, r + 3) for r in CONTEXT_BEFORE]
    after = [(r, r + 3) for r in CONTEXT_AFTER]
    return (
        [*CONTEXT_BEFORE, *reference, *CONTEXT_AFTER],
        [d for _, d in before] + list(detections) + [d for _, d in after],
        before + list(pairs) + after,
    )


# --------------------------------------------------------------------------------------------
# Parameters at 360 Hz and at other sampling frequencies
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
def test_window_and_start_at_360_hz() -> None:
    """The match window and the 5:00 boundary at 360 Hz.

    Input: a sampling frequency of 360 Hz.
    Expected: "at most 150 ms" is 54 samples and 5:00 is sample 108000, the values used by
    every other case of this file.
    """
    assert match_window_samples(FS_HZ) == WINDOW
    assert learning_period_samples(FS_HZ) == START


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("fs_hz", "expected"),
    [
        pytest.param(360.0, 54, id="360Hz"),
        pytest.param(250.0, 37, id="250Hz-37.5-samples"),
        pytest.param(125.0, 18, id="125Hz-18.75-samples"),
        pytest.param(128.0, 19, id="128Hz-19.2-samples"),
        pytest.param(500.0, 75, id="500Hz"),
        pytest.param(1000.0, 150, id="1000Hz"),
    ],
)
def test_match_window_never_exceeds_150_ms(fs_hz: float, expected: int) -> None:
    """ "At most 150 ms" in samples, at several sampling frequencies.

    Input: a sampling frequency; at 250 Hz and 125 Hz, 150 ms is not a whole number of
    samples (37.5 and 18.75).
    Expected: the largest whole number of samples that lasts at most 150 ms. At 250 Hz it
    is 37, not the 38 samples (152 ms) that rounding to the nearest would give: SRS-008
    keeps its own bound where `bxb` rounds above 150 ms.
    """
    window = match_window_samples(fs_hz)

    assert window == expected
    assert window * 1000 <= 150 * fs_hz < (window + 1) * 1000


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("fs_hz", "expected"),
    [
        pytest.param(360.0, 108000, id="360Hz"),
        pytest.param(250.0, 75000, id="250Hz"),
        pytest.param(125.0, 37500, id="125Hz"),
        pytest.param(128.0, 38400, id="128Hz"),
        pytest.param(1000.0, 300000, id="1000Hz"),
    ],
)
def test_learning_period_is_5_minutes(fs_hz: float, expected: int) -> None:
    """The 5:00 boundary in samples.

    Input: a sampling frequency.
    Expected: the index of the first sample at or after 5:00, 300 s times the sampling
    frequency.
    """
    assert learning_period_samples(fs_hz) == expected


# --------------------------------------------------------------------------------------------
# Match window: at most 150 ms
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize("offset", [-54, -53, -1, 0, 1, 53, 54])
def test_detection_within_150_ms_is_paired(offset: int, context: bool) -> None:
    """A detection at most 150 ms from a reference beat is paired with it.

    Input: one reference beat at sample 200000 and one detection ``offset`` samples from it,
    up to exactly 150 ms (54 samples) before or after, including the same sample; alone, and
    between matched beats.
    Expected: one pair (beat, detection), no false negative, no false positive.
    """
    reference, detections, pairs = _in_context([X], [X + offset], [(X, X + offset)], context)

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[], false_positives=[])


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize("offset", [-200, -108, -56, -55, 55, 56, 108, 200])
def test_detection_beyond_150_ms_is_not_paired(offset: int, context: bool) -> None:
    """A detection more than 150 ms from a reference beat is not paired with it.

    Input: one reference beat at sample 200000 and one detection ``offset`` samples from it,
    from 150 ms plus one sample (55 samples) before or after; alone, and between matched
    beats.
    Expected: no pair for them; the beat is a false negative and the detection a false
    positive.
    """
    reference, detections, pairs = _in_context([X], [X + offset], [], context)

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[X], false_positives=[X + offset])


# --------------------------------------------------------------------------------------------
# Two detections near one reference beat
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("offsets", "paired"),
    [
        pytest.param((-40, 10), 10, id="before-and-after-later-closer"),
        pytest.param((-10, 40), -10, id="before-and-after-earlier-closer"),
        pytest.param((-40, -10), -10, id="both-before"),
        pytest.param((10, 40), 10, id="both-after"),
        pytest.param((-54, 53), 53, id="150ms-before-and-one-sample-less-after"),
        pytest.param((-53, 54), -53, id="one-sample-less-before-and-150ms-after"),
        pytest.param((-60, 20), 20, id="one-beyond-150ms-before"),
        pytest.param((20, 70), 20, id="one-beyond-150ms-after"),
    ],
)
def test_closer_of_two_detections_is_paired(
    offsets: tuple[int, int], paired: int, context: bool
) -> None:
    """Two detections near one reference beat: the closer one is paired.

    Input: one reference beat at sample 200000 and two detections at the given offsets from
    it, at different distances; alone, and between matched beats.
    Expected: the beat is paired with the closer detection; the other detection is a false
    positive; no false negative.
    """
    other = offsets[0] if paired == offsets[1] else offsets[1]
    reference, detections, pairs = _in_context(
        [X], [X + offsets[0], X + offsets[1]], [(X, X + paired)], context
    )

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[], false_positives=[X + other])


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize("distance", [1, 20, 53, 54])
def test_later_of_two_equidistant_detections_is_paired(distance: int, context: bool) -> None:
    """Two detections equidistant from one reference beat: the later one is paired.

    Input: one reference beat at sample 200000, one detection ``distance`` samples before it
    and one ``distance`` samples after it, up to exactly 150 ms; alone, and between matched
    beats.
    Expected: the beat is paired with the later detection; the earlier detection is a false
    positive; no false negative.
    """
    reference, detections, pairs = _in_context(
        [X], [X - distance, X + distance], [(X, X + distance)], context
    )

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[], false_positives=[X - distance])


# --------------------------------------------------------------------------------------------
# One detection between two reference beats
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("gap", "offset", "paired_beat"),
    [
        pytest.param(80, 30, 0, id="30-and-50-samples"),
        pytest.param(80, 50, 1, id="50-and-30-samples"),
        pytest.param(100, 46, 0, id="46-and-54-samples"),
        pytest.param(100, 54, 1, id="54-and-46-samples"),
        pytest.param(90, 44, 0, id="44-and-46-samples"),
        pytest.param(90, 46, 1, id="46-and-44-samples"),
    ],
)
def test_detection_between_two_beats_is_paired_with_the_closer_one(
    gap: int, offset: int, paired_beat: int, context: bool
) -> None:
    """One detection between two reference beats within 150 ms: paired with the closer one.

    Input: two reference beats, at sample 200000 and ``gap`` samples later, and one detection
    ``offset`` samples after the first beat, at most 54 samples from each and at different
    distances; alone, and between matched beats.
    Expected: the detection is paired with the closer beat; the other beat is a false
    negative; no false positive.
    """
    beats = (X, X + gap)
    detection = X + offset
    reference, detections, pairs = _in_context(
        beats, [detection], [(beats[paired_beat], detection)], context
    )

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[beats[1 - paired_beat]], false_positives=[])


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize("distance", [1, 25, 40, 54])
def test_detection_equidistant_from_two_beats_is_paired_with_the_later_one(
    distance: int, context: bool
) -> None:
    """One detection equidistant from two reference beats: paired with the later one.

    Input: two reference beats ``2 * distance`` samples apart and one detection halfway, up
    to exactly 150 ms from each; alone, and between matched beats.
    Expected: the detection is paired with the later beat; the earlier beat is a false
    negative; no false positive.
    """
    beats = (X, X + 2 * distance)
    detection = X + distance
    reference, detections, pairs = _in_context(beats, [detection], [(beats[1], detection)], context)

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[beats[0]], false_positives=[])


# --------------------------------------------------------------------------------------------
# Sequential pairing: the look-ahead, and not a maximum matching
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
def test_earlier_detection_is_paired_when_the_next_one_belongs_to_the_next_beat(
    context: bool,
) -> None:
    """The look-ahead of the pairing rule, with the detection first.

    Input: a detection at 199970, a beat at 200000, a detection at 200025 and a beat at
    200040. The second detection is closer to the first beat (25 samples) than the first
    detection is (30), but it is closer still to the second beat (15).
    Expected: the first detection is paired with the first beat (the exception of the rule
    does not apply, because the next detection is closer to the next beat), and the second
    detection with the second beat: two pairs, no false negative, no false positive.
    """
    reference, detections, pairs = _in_context(
        [X, X + 40], [X - 30, X + 25], [(X, X - 30), (X + 40, X + 25)], context
    )

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[], false_positives=[])


@pytest.mark.requirement("SRS-008")
def test_earlier_beat_is_paired_when_the_next_one_has_its_own_detection(context: bool) -> None:
    """The look-ahead of the pairing rule, with the reference beat first.

    Input: a beat at 200000, a detection at 200030, a beat at 200055 and a detection at
    200070. The second beat is closer to the first detection (25 samples) than the first
    beat is (30), but it is closer still to the second detection (15).
    Expected: the first beat is paired with the first detection and the second beat with the
    second detection: two pairs, no false negative, no false positive.
    """
    reference, detections, pairs = _in_context(
        [X, X + 55], [X + 30, X + 70], [(X, X + 30), (X + 55, X + 70)], context
    )

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[], false_positives=[])


@pytest.mark.requirement("SRS-008")
def test_pairing_is_sequential_and_not_a_maximum_matching(context: bool) -> None:
    """A case where the sequential rule pairs fewer beats than the largest possible number.

    Input: a detection at 199950, a beat at 200000, a detection at 200040 and a beat at
    200094. A maximum matching would give two pairs (50 and 54 samples apart).
    Expected, from the rule of SRS-008: the first detection is not paired with the first
    beat, because the next detection is closer to that beat (40 against 50) and no closer to
    the next beat (54); it is a false positive. The first beat is paired with the second
    detection, and the second beat is a false negative.
    """
    reference, detections, pairs = _in_context(
        [X, X + 94], [X - 50, X + 40], [(X, X + 40)], context
    )

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[X + 94], false_positives=[X - 50])


@pytest.mark.requirement("SRS-008")
def test_sequence_with_missed_and_extra_detections() -> None:
    """A long sequence: counts, and at most one match per item.

    Input: 150 reference beats every 280 samples from 108200. Every beat has a detection 3
    samples later, except every tenth beat, which has none; after every seventh beat there
    is an extra detection 140 samples later (more than 150 ms from both neighbours).
    Expected: 135 pairs (beat, beat + 3), the 15 beats without a detection as false
    negatives, the 21 extra detections as false positives; no beat and no detection appears
    in two pairs.
    """
    beats = [108200 + 280 * k for k in range(150)]
    missed = [b for k, b in enumerate(beats) if k % 10 == 0]
    extra = [b + 140 for k, b in enumerate(beats) if k % 7 == 3]
    detections = sorted([b + 3 for b in beats if b not in missed] + extra)
    pairs = [(b, b + 3) for b in beats if b not in missed]

    result = _match(beats, detections)

    assert (len(pairs), len(missed), len(extra)) == (135, 15, 21)
    _check(result, pairs=pairs, false_negatives=missed, false_positives=extra)
    assert len({r for r, _ in result.matched}) == result.tp
    assert len({d for _, d in result.matched}) == result.tp


@pytest.mark.requirement("SRS-008")
def test_plain_sequences_are_accepted() -> None:
    """The lists may be given as plain Python lists.

    Input: reference beats and detections as lists of integers instead of arrays.
    Expected: the same result as with arrays: a pair, a false negative and a false positive.
    """
    result = match_beats(
        [X, X + 300, X + 600],
        [X + 5, X + 450],
        window_samples=WINDOW,
        start_sample=START,
    )

    _check(
        result, pairs=[(X, X + 5)], false_negatives=[X + 300, X + 600], false_positives=[X + 450]
    )


# --------------------------------------------------------------------------------------------
# The 5:00 boundary: reference beats
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("beat", "scored"),
    [
        pytest.param(0, False, id="first-sample"),
        pytest.param(54000, False, id="2min30"),
        pytest.param(107946, False, id="150ms-before-5min"),
        pytest.param(107999, False, id="one-sample-before-5min"),
        pytest.param(108000, True, id="at-5min"),
        pytest.param(108001, True, id="one-sample-after-5min"),
        pytest.param(108054, True, id="150ms-after-5min"),
    ],
)
def test_reference_beat_is_scored_from_5_minutes(beat: int, scored: bool) -> None:
    """Reference beats before 5:00 are not scored; from 5:00 they are.

    Input: one reference beat at the given sample and no detection.
    Expected: a beat before sample 108000 is not scored (no false negative); a beat at
    108000 or later is a false negative.
    """
    result = _match([beat], [])

    _check(result, pairs=[], false_negatives=[beat] if scored else [], false_positives=[])


@pytest.mark.requirement("SRS-008")
def test_beats_just_before_and_at_5_minutes_with_their_detections() -> None:
    """Reference beats just before and at 5:00, each with a detection on it.

    Input: reference beats at 107700, 107999, 108000 and 108300, and a detection at each of
    these samples.
    Expected: the beats at 107700 and 107999 and their detections are not scored (the
    detection at 107999 is no closer to the beat at 108000 than the detection at 108000
    is); the beats at 108000 and 108300 are paired with the detections at the same samples.
    No false negative, no false positive.
    """
    samples = [107700, 107999, 108000, 108300]

    result = _match(samples, samples)

    _check(
        result,
        pairs=[(108000, 108000), (108300, 108300)],
        false_negatives=[],
        false_positives=[],
    )


@pytest.mark.requirement("SRS-008")
def test_nothing_is_scored_before_5_minutes() -> None:
    """Beats and detections of the first 5 minutes, matched or not, are not scored.

    Input: reference beats at 1000, 50000 and 107000 with detections 3 samples later, a
    reference beat at 20000 without detection, detections at 30000 and 107500 without a
    beat, and one beat at 108500 with its detection at 108503.
    Expected: the only pair is (108500, 108503); no false negative and no false positive.
    """
    result = _match(
        [1000, 20000, 50000, 107000, 108500], [1003, 30000, 50003, 107003, 107500, 108503]
    )

    _check(result, pairs=[(108500, 108503)], false_negatives=[], false_positives=[])


# --------------------------------------------------------------------------------------------
# The 5:00 boundary: the last detection before it
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("reference", "detections", "pairs"),
    [
        pytest.param([108020], [107990], [(108020, 107990)], id="no-next-detection"),
        pytest.param(
            [108020, 108320],
            [107990, 108323],
            [(108020, 107990), (108320, 108323)],
            id="next-detection-far",
        ),
        pytest.param(
            [108020], [107990, 108055], [(108020, 107990)], id="next-detection-less-close"
        ),
        pytest.param([108053], [107999], [(108053, 107999)], id="exactly-150ms"),
        pytest.param([108000], [107946], [(108000, 107946)], id="beat-at-5min-exactly-150ms"),
        pytest.param([108010], [107960, 107999], [(108010, 107999)], id="only-the-last-one"),
        pytest.param(
            [108020], [107700, 107850, 107990], [(108020, 107990)], id="earlier-ones-not-scored"
        ),
    ],
)
def test_last_detection_before_5_minutes_is_paired_with_the_first_scored_beat(
    reference: list[int], detections: list[int], pairs: list[tuple[int, int]]
) -> None:
    """The last detection before 5:00 is paired when it is the closer one.

    Input: a first scored reference beat shortly after 5:00, and a last detection before
    5:00 within 150 ms of it and closer to it than the next detection (if any).
    Expected: that detection is paired with the first scored beat. A detection that follows
    and has no beat is a false positive; the detections before the last one of the first 5
    minutes are not scored. No false negative.
    """
    unpaired = [d for d in detections if d >= START and d not in {p[1] for p in pairs}]

    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[], false_positives=unpaired)


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("reference", "detections", "pairs", "false_negatives"),
    [
        pytest.param(
            [108020], [107990, 108040], [(108020, 108040)], [], id="next-detection-closer"
        ),
        pytest.param(
            [108020], [107990, 108050], [(108020, 108050)], [], id="next-detection-as-close"
        ),
        pytest.param([108054], [107999], [], [108054], id="150ms-plus-one-sample"),
        pytest.param([108020], [107960], [], [108020], id="beyond-150ms"),
        pytest.param([], [107990], [], [], id="no-scored-beat"),
    ],
)
def test_last_detection_before_5_minutes_is_otherwise_not_scored(
    reference: list[int],
    detections: list[int],
    pairs: list[tuple[int, int]],
    false_negatives: list[int],
) -> None:
    """The last detection before 5:00 is not scored when it is not the closer one.

    Input: a last detection before 5:00 that is more than 150 ms from the first scored
    reference beat, or no closer to it than the next detection, or that has no scored beat.
    Expected: that detection is not scored: it is in no pair and is not a false positive.
    The first scored beat is paired with the next detection when that one is within 150 ms,
    and is a false negative otherwise.
    """
    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=false_negatives, false_positives=[])


@pytest.mark.requirement("SRS-008")
def test_last_detection_before_5_minutes_is_not_paired_by_the_look_ahead() -> None:
    """At 5:00 the closer detection decides, without the look-ahead of the general rule.

    Input: reference beats at 108020 and 108045, a last detection before 5:00 at 107990 (30
    samples from the first scored beat) and a next detection at 108040 (20 samples from it).
    Expected: the detection at 107990 is not scored, because the next detection is closer to
    the first scored beat. From there the general rule applies: the beat at 108020 is not
    paired with the detection at 108040, because the next beat (108045) is closer to that
    detection and has no closer detection of its own; it is a false negative, and the pair
    is (108045, 108040). No false positive.
    """
    result = _match([108020, 108045], [107990, 108040, 108400])

    _check(
        result,
        pairs=[(108045, 108040)],
        false_negatives=[108020],
        false_positives=[108400],
    )


# --------------------------------------------------------------------------------------------
# The 5:00 boundary: the first detection at or after it
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("reference", "detections", "pairs", "false_positives"),
    [
        pytest.param([108100], [108030, 108095], [(108100, 108095)], [], id="30-samples-after"),
        pytest.param([108060], [108000, 108058], [(108060, 108058)], [], id="at-5min"),
        pytest.param([108124], [108054, 108120], [(108124, 108120)], [], id="exactly-150ms-after"),
        pytest.param(
            [107999, 108300],
            [108002, 108303],
            [(108300, 108303)],
            [],
            id="detection-of-a-beat-just-before-5min",
        ),
        pytest.param(
            [108100],
            [107990, 108030, 108095],
            [(108100, 108095)],
            [],
            id="after-an-unscored-detection-before-5min",
        ),
        pytest.param(
            [108200],
            [108010, 108040, 108203],
            [(108200, 108203)],
            [108040],
            id="only-the-first-one",
        ),
    ],
)
def test_first_detection_after_5_minutes_is_not_scored_when_the_next_is_closer(
    reference: list[int],
    detections: list[int],
    pairs: list[tuple[int, int]],
    false_positives: list[int],
) -> None:
    """The first detection within 150 ms after 5:00, with a closer next detection.

    Input: a first detection at or after 5:00 that lies at most 150 ms (54 samples) after
    5:00, and a next detection that is closer to the first scored reference beat.
    Expected: the first detection is not scored: it is in no pair and is not a false
    positive. The following detections are scored normally (paired with their beat, or false
    positives). No false negative.
    """
    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=[], false_positives=false_positives)


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("reference", "detections", "pairs", "false_negatives", "false_positives"),
    [
        pytest.param(
            [108125],
            [108055, 108121],
            [(108125, 108121)],
            [],
            [108055],
            id="150ms-plus-one-sample-after-5min",
        ),
        pytest.param(
            [108100, 108400],
            [108030, 108403],
            [(108400, 108403)],
            [108100],
            [108030],
            id="next-detection-farther",
        ),
        pytest.param(
            [108050],
            [108020, 108080],
            [(108050, 108080)],
            [],
            [108020],
            id="next-detection-as-close",
        ),
        pytest.param(
            [108030],
            [108033, 108400],
            [(108030, 108033)],
            [],
            [108400],
            id="first-detection-is-the-closer-one",
        ),
    ],
)
def test_first_detection_after_5_minutes_is_otherwise_scored(
    reference: list[int],
    detections: list[int],
    pairs: list[tuple[int, int]],
    false_negatives: list[int],
    false_positives: list[int],
) -> None:
    """The first detection at or after 5:00 is scored when the exception does not apply.

    Input: a first detection at or after 5:00 that lies more than 150 ms after 5:00, or
    whose next detection is not closer to the first scored reference beat.
    Expected: the first detection is scored by the general rule: paired with the beat if it
    is within 150 ms and the closer one, a false positive otherwise.
    """
    result = _match(reference, detections)

    _check(result, pairs=pairs, false_negatives=false_negatives, false_positives=false_positives)


# --------------------------------------------------------------------------------------------
# Empty lists
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
def test_empty_detection_list_gives_every_scored_beat_as_false_negative() -> None:
    """An empty detection list.

    Input: reference beats at 100, 107999, 108000, 108300 and 200000, and no detection.
    Expected: no pair; the three beats at or after 5:00 are false negatives; the two beats
    before 5:00 are not scored; no false positive.
    """
    result = _match([100, 107999, 108000, 108300, 200000], [])

    _check(result, pairs=[], false_negatives=[108000, 108300, 200000], false_positives=[])


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("detections", "false_positives"),
    [
        pytest.param(
            [500, 107999, 108030, 108400, 200000], [108400, 200000], id="first-30-samples-after"
        ),
        pytest.param([108000, 108400], [108400], id="first-at-5min"),
        pytest.param([108054, 108400], [108400], id="first-exactly-150ms-after"),
        pytest.param([108055, 108400], [108055, 108400], id="first-150ms-plus-one-sample-after"),
        pytest.param([108010, 108040], [108040], id="two-within-150ms-after"),
        pytest.param([108010], [], id="single-within-150ms-after"),
        pytest.param([108055], [108055], id="single-150ms-plus-one-sample-after"),
        pytest.param([100, 50000, 107999], [], id="all-before-5min"),
    ],
)
def test_empty_reference_list_gives_detections_after_5_minutes_as_false_positives(
    detections: list[int], false_positives: list[int]
) -> None:
    """An empty reference list.

    Input: no reference beat, and detections before and after 5:00.
    Expected: no pair and no false negative; every detection at or after 5:00 is a false
    positive, except the first one when it is at most 150 ms (54 samples) after 5:00;
    detections before 5:00 are not scored.
    """
    result = _match([], detections)

    _check(result, pairs=[], false_negatives=[], false_positives=false_positives)


@pytest.mark.requirement("SRS-008")
def test_no_scored_reference_beat_is_treated_as_an_empty_reference_list() -> None:
    """Reference beats only before 5:00: no reference beat is scored.

    Input: reference beats at 1000 and 107000, detections at 1003, 107003, 108010 and
    108400.
    Expected: no pair and no false negative; the first detection after 5:00 (108010, within
    150 ms of 5:00) is not scored; the detection at 108400 is a false positive.
    """
    result = _match([1000, 107000], [1003, 107003, 108010, 108400])

    _check(result, pairs=[], false_negatives=[], false_positives=[108400])


@pytest.mark.requirement("SRS-008")
def test_both_lists_empty() -> None:
    """No reference beat and no detection.

    Input: two empty lists, as arrays and as plain lists.
    Expected: no pair, no false negative, no false positive, nothing excluded.
    """
    _check(_match([], []), pairs=[], false_negatives=[], false_positives=[])
    _check(
        match_beats([], [], window_samples=WINDOW, start_sample=START),
        pairs=[],
        false_negatives=[],
        false_positives=[],
    )


# --------------------------------------------------------------------------------------------
# Ventricular flutter and fibrillation episodes
# --------------------------------------------------------------------------------------------

VF_START = 200000
VF_END = 203000


def _annotation(sample: int, symbol: str, subtype: int = 0, aux_note: str = "") -> Annotation:
    return Annotation(sample=sample, symbol=symbol, subtype=subtype, aux_note=aux_note)


def _spans(episodes: Sequence[Episode]) -> list[tuple[int, int]]:
    return [(int(e.start_sample), int(e.end_sample)) for e in episodes]


@pytest.mark.requirement("SRS-008")
def test_episode_runs_from_onset_to_offset_annotation() -> None:
    """An episode from `[` to the next `]`, both included.

    Input: the non-beat annotations of a record of 650000 samples: a rhythm change, `[` at
    200000, two flutter waves, `]` at 203000, and a signal-quality mark.
    Expected: one episode, from sample 200000 to sample 203000.
    """
    annotations = [
        _annotation(150, "+", aux_note="(N"),
        _annotation(VF_START, "["),
        _annotation(200400, "!"),
        _annotation(200800, "!"),
        _annotation(VF_END, "]"),
        _annotation(300000, "~", subtype=1),
    ]

    assert _spans(vf_episodes(annotations, 650000)) == [(VF_START, VF_END)]


@pytest.mark.requirement("SRS-008")
def test_episode_without_offset_lasts_until_the_end_of_the_record() -> None:
    """An episode whose `[` has no `]`.

    Input: annotations with a closed episode (`[` at 200000, `]` at 203000) and a later `[`
    at 400000 without `]`, in a record of 650000 samples.
    Expected: two episodes; the second lasts from 400000 to the last sample, 649999.
    """
    annotations = [
        _annotation(VF_START, "["),
        _annotation(VF_END, "]"),
        _annotation(400000, "["),
        _annotation(400500, "!"),
    ]

    assert _spans(vf_episodes(annotations, 650000)) == [(VF_START, VF_END), (400000, 649999)]


@pytest.mark.requirement("SRS-008")
def test_record_without_onset_annotation_has_no_episode() -> None:
    """No `[` annotation: no episode.

    Input: no annotation at all; then rhythm changes, signal-quality marks and flutter waves
    without `[`; then a `]` alone.
    Expected: no episode in the three cases.
    """
    others = [
        _annotation(150, "+", aux_note="(VFL"),
        _annotation(9000, "~", subtype=2),
        _annotation(9500, "!"),
    ]

    assert _spans(vf_episodes([], 650000)) == []
    assert _spans(vf_episodes(others, 650000)) == []
    assert _spans(vf_episodes([_annotation(5000, "]")], 650000)) == []


@pytest.mark.requirement("SRS-008")
def test_each_onset_is_closed_by_the_next_offset() -> None:
    """Several `[` and `]` annotations: each episode ends at the next `]`.

    Input: `]` at 1000 (no open episode), `[` at 200000, `[` at 201000 (episode already
    open), `]` at 203000, `]` at 204000 (no open episode), `[` at 300000 and `]` at 300900.
    Expected: two episodes, 200000 to 203000 and 300000 to 300900.
    """
    annotations = [
        _annotation(1000, "]"),
        _annotation(VF_START, "["),
        _annotation(201000, "["),
        _annotation(VF_END, "]"),
        _annotation(204000, "]"),
        _annotation(300000, "["),
        _annotation(300900, "]"),
    ]

    assert _spans(vf_episodes(annotations, 650000)) == [(VF_START, VF_END), (300000, 300900)]


@pytest.mark.requirement("SRS-008")
def test_beats_and_unpaired_detection_inside_an_episode_are_not_scored() -> None:
    """Reference beats and an unpaired detection inside a ventricular flutter episode.

    Input: an episode from 200000 to 203000. Reference beats at 199700 and 203300 (outside)
    and at 200000, 200500, 201000 and 203000 (inside, two of them on the `[` and `]`
    samples). Detections at 199703 and 203303, and one at 201200, inside the episode and
    more than 150 ms from every scored beat.
    Expected: the two beats outside are paired with their detections; the four beats inside
    are not scored (no false negative) and the detection inside is not scored (no false
    positive); the result counts 4 reference beats and 1 detection excluded.
    """
    episode = Episode(start_sample=VF_START, end_sample=VF_END)

    result = _match(
        [199700, 200000, 200500, 201000, 203000, 203300], [199703, 201200, 203303], vf=[episode]
    )

    _check(
        result,
        pairs=[(199700, 199703), (203300, 203303)],
        false_negatives=[],
        false_positives=[],
        reference_excluded=4,
        detections_excluded=1,
    )


@pytest.mark.requirement("SRS-008")
def test_same_lists_without_episode_are_scored() -> None:
    """Control of the previous case: without the episode, the same items are errors.

    Input: the reference beats and detections of the previous case, and no episode.
    Expected: the four beats between 200000 and 203000 are false negatives and the detection
    at 201200 is a false positive; nothing is excluded.
    """
    result = _match([199700, 200000, 200500, 201000, 203000, 203300], [199703, 201200, 203303])

    _check(
        result,
        pairs=[(199700, 199703), (203300, 203303)],
        false_negatives=[200000, 200500, 201000, 203000],
        false_positives=[201200],
    )


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("beat", "inside"),
    [
        pytest.param(VF_START - 1, False, id="one-sample-before-onset"),
        pytest.param(VF_START, True, id="at-onset"),
        pytest.param(VF_START + 1, True, id="one-sample-after-onset"),
        pytest.param(VF_END - 1, True, id="one-sample-before-offset"),
        pytest.param(VF_END, True, id="at-offset"),
        pytest.param(VF_END + 1, False, id="one-sample-after-offset"),
    ],
)
def test_episode_includes_its_onset_and_offset_samples_for_reference_beats(
    beat: int, inside: bool
) -> None:
    """Limits of an episode for a reference beat: onset and offset are both included.

    Input: an episode from 200000 to 203000, one reference beat at the given sample and no
    detection.
    Expected: a beat from the onset sample to the offset sample is not scored and is counted
    as excluded; a beat one sample before the onset or one sample after the offset is a
    false negative.
    """
    result = _match([beat], [], vf=[Episode(start_sample=VF_START, end_sample=VF_END)])

    _check(
        result,
        pairs=[],
        false_negatives=[] if inside else [beat],
        false_positives=[],
        reference_excluded=1 if inside else 0,
    )


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("detection", "inside"),
    [
        pytest.param(VF_START - 1, False, id="one-sample-before-onset"),
        pytest.param(VF_START, True, id="at-onset"),
        pytest.param(VF_START + 1500, True, id="in-the-middle"),
        pytest.param(VF_END, True, id="at-offset"),
        pytest.param(VF_END + 1, False, id="one-sample-after-offset"),
    ],
)
def test_unpaired_detection_is_excluded_only_inside_the_episode(
    detection: int, inside: bool
) -> None:
    """Limits of an episode for an unpaired detection.

    Input: an episode from 200000 to 203000, a matched beat at 150000 (detection at 150003)
    and one detection at the given sample, far from every reference beat.
    Expected: a detection from the onset sample to the offset sample is not scored and is
    counted as excluded; one sample outside the episode it is a false positive.
    """
    result = _match(
        [150000], [150003, detection], vf=[Episode(start_sample=VF_START, end_sample=VF_END)]
    )

    _check(
        result,
        pairs=[(150000, 150003)],
        false_negatives=[],
        false_positives=[] if inside else [detection],
        detections_excluded=1 if inside else 0,
    )


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("reference", "detection", "pair", "reference_excluded"),
    [
        pytest.param([203030], 202990, (203030, 202990), 0, id="beat-after-the-episode"),
        pytest.param([199980], 200010, (199980, 200010), 0, id="beat-before-the-episode"),
        pytest.param([203054], 203000, (203054, 203000), 0, id="exactly-150ms"),
        pytest.param(
            [202975, 203030],
            202990,
            (203030, 202990),
            1,
            id="closer-to-an-unscored-beat-of-the-episode",
        ),
    ],
)
def test_detection_inside_an_episode_is_paired_with_a_scored_beat_outside(
    reference: list[int], detection: int, pair: tuple[int, int], reference_excluded: int
) -> None:
    """A detection inside an episode, within 150 ms of a scored reference beat outside it.

    Input: an episode from 200000 to 203000, a scored reference beat outside it and a
    detection inside it at most 150 ms (54 samples) from that beat. In one case an unscored
    beat of the episode is closer to the detection.
    Expected: the detection is paired with the scored beat outside the episode: one pair, no
    false negative, no false positive, no detection excluded.
    """
    result = _match(reference, [detection], vf=[Episode(start_sample=VF_START, end_sample=VF_END)])

    _check(
        result,
        pairs=[pair],
        false_negatives=[],
        false_positives=[],
        reference_excluded=reference_excluded,
    )


@pytest.mark.requirement("SRS-008")
def test_detection_inside_an_episode_beyond_150_ms_of_the_beat_outside_is_not_scored() -> None:
    """A detection inside an episode, 150 ms plus one sample from the scored beat outside.

    Input: an episode from 200000 to 203000, a scored reference beat at 203055 and a
    detection at 203000, 55 samples from it.
    Expected: no pair; the beat is a false negative; the detection is inside the episode and
    unpaired, so it is not scored (no false positive) and is counted as excluded.
    """
    result = _match([203055], [203000], vf=[Episode(start_sample=VF_START, end_sample=VF_END)])

    _check(
        result,
        pairs=[],
        false_negatives=[203055],
        false_positives=[],
        detections_excluded=1,
    )


@pytest.mark.requirement("SRS-008")
def test_two_episodes_are_both_excluded() -> None:
    """Two episodes in one record.

    Input: episodes from 200000 to 201000 and from 210000 to 211000. Reference beats at
    199700, 205000 and 212000 (outside, each with a detection 3 samples later), and at
    200500 and 210500 (inside). Unpaired detections at 200700 and 210700 (inside) and at
    207000 (between the episodes).
    Expected: three pairs; the detection at 207000 is a false positive; the two beats and
    the two detections inside the episodes are not scored and are counted as excluded.
    """
    episodes = [
        Episode(start_sample=200000, end_sample=201000),
        Episode(start_sample=210000, end_sample=211000),
    ]

    result = _match(
        [199700, 200500, 205000, 210500, 212000],
        [199703, 200700, 205003, 207000, 210700, 212003],
        vf=episodes,
    )

    _check(
        result,
        pairs=[(199700, 199703), (205000, 205003), (212000, 212003)],
        false_negatives=[],
        false_positives=[207000],
        reference_excluded=2,
        detections_excluded=2,
    )


@pytest.mark.requirement("SRS-008")
def test_annotations_of_a_record_exclude_its_episodes_from_scoring() -> None:
    """From the non-beat annotations of a record to the scoring, with an unclosed episode.

    Input: a record of 650000 samples at 360 Hz whose non-beat annotations hold a rhythm
    change, a closed episode (`[` at 200000, `]` at 203000) and a `[` at 400000 without `]`.
    Reference beats at 199700, 201000, 300000, 400300, 500000 and 649999; detections at
    199703, 201500, 300003, 450000 and 649999. The window and the 5:00 boundary are obtained
    for 360 Hz.
    Expected: the pairs are (199700, 199703) and (300000, 300003). The beat at 201000 and
    the detection at 201500 are inside the first episode; the beats at 400300, 500000 and
    649999 and the detections at 450000 and 649999 are inside the second one, which lasts
    until the end of the record. None of them is scored: no false negative, no false
    positive, 4 reference beats and 3 detections excluded.
    """
    annotations = [
        _annotation(100, "+", aux_note="(N"),
        _annotation(VF_START, "["),
        _annotation(VF_END, "]"),
        _annotation(400000, "["),
    ]
    episodes = vf_episodes(annotations, 650000)

    result = match_beats(
        np.asarray([199700, 201000, 300000, 400300, 500000, 649999], dtype=np.int64),
        np.asarray([199703, 201500, 300003, 450000, 649999], dtype=np.int64),
        window_samples=match_window_samples(FS_HZ),
        start_sample=learning_period_samples(FS_HZ),
        vf=episodes,
    )

    _check(
        result,
        pairs=[(199700, 199703), (300000, 300003)],
        false_negatives=[],
        false_positives=[],
        reference_excluded=4,
        detections_excluded=3,
    )


# --------------------------------------------------------------------------------------------
# An episode without an offset annotation
# --------------------------------------------------------------------------------------------

N_SAMPLES = 650000  # record length of these cases (30 min 5.6 s at 360 Hz)
OPEN_ONSET = 400000


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("annotations", "expected"),
    [
        pytest.param(
            [(150, "+"), (OPEN_ONSET, "["), (400500, "!"), (500000, "~")],
            [(OPEN_ONSET, N_SAMPLES - 1)],
            id="only-episode-of-the-record",
        ),
        pytest.param(
            [(OPEN_ONSET, "["), (500000, "[")],
            [(OPEN_ONSET, N_SAMPLES - 1)],
            id="second-onset-while-open",
        ),
        pytest.param(
            [(N_SAMPLES - 1, "[")],
            [(N_SAMPLES - 1, N_SAMPLES - 1)],
            id="onset-on-the-last-sample",
        ),
    ],
)
def test_lone_episode_without_offset_lasts_until_the_end_of_the_record(
    annotations: list[tuple[int, str]], expected: list[tuple[int, int]]
) -> None:
    """An episode without offset annotation, with no episode before it in the record.

    Input: the non-beat annotations of a record of 650000 samples, holding a `[` without
    any `]`: at sample 400000, among other annotations; at 400000 followed by a second `[`
    at 500000; on the last sample, 649999.
    Expected: a single episode, from the onset to the last sample of the record, 649999.
    """
    episodes = vf_episodes([_annotation(s, symbol) for s, symbol in annotations], N_SAMPLES)

    assert _spans(episodes) == expected


def _open_episode_annotations(earlier_closed: bool) -> list[Annotation]:
    """Non-beat annotations with a `[` at 400000 and no `]` after it.

    With ``earlier_closed``, a closed episode (`[` at 200000, `]` at 203000) comes first.
    """
    annotations = [_annotation(100, "+", aux_note="(N")]
    if earlier_closed:
        annotations += [_annotation(VF_START, "["), _annotation(VF_END, "]")]
    return [*annotations, _annotation(OPEN_ONSET, "["), _annotation(OPEN_ONSET + 10, "!")]


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize("earlier_closed", [False, True], ids=["alone", "after-a-closed-episode"])
def test_items_from_an_unclosed_onset_to_the_end_of_the_record_are_not_scored(
    earlier_closed: bool,
) -> None:
    """Reference beats and unpaired detections from an unclosed onset to the end of the record.

    Input: a record of 650000 samples at 360 Hz with a `[` at 400000 and no `]` after it,
    alone or after a closed episode from 200000 to 203000 (which holds a reference beat at
    201000 and a detection at 201500). Reference beats at 300000 (detection at 300003),
    399800 (no detection; before the onset), 400000 (on the onset), 520000 and 649999 (the
    last sample). Detections also at 399999 (one sample before the onset, 199 samples from
    the beat at 399800), 400000 (on the onset), 450000 and 649999 (the last sample), none
    within 150 ms of a scored beat. The episodes are obtained from the annotations.
    Expected: the pair (300000, 300003); the beat at 399800 is a false negative and the
    detection at 399999 a false positive; the beats at 400000, 520000 and 649999 and the
    detections at 400000, 450000 and 649999 are not scored (3 reference beats and 3
    detections excluded, plus the beat and the detection of the closed episode when it is
    there). The earlier closed episode does not change how the open one is treated.
    """
    episodes = vf_episodes(_open_episode_annotations(earlier_closed), N_SAMPLES)
    reference = [300000, 399800, 400000, 520000, 649999]
    detections = [300003, 399999, 400000, 450000, 649999]
    if earlier_closed:
        reference = [201000, *reference]
        detections = [201500, *detections]

    result = match_beats(
        np.asarray(reference, dtype=np.int64),
        np.asarray(detections, dtype=np.int64),
        window_samples=match_window_samples(FS_HZ),
        start_sample=learning_period_samples(FS_HZ),
        vf=episodes,
    )

    _check(
        result,
        pairs=[(300000, 300003)],
        false_negatives=[399800],
        false_positives=[399999],
        reference_excluded=4 if earlier_closed else 3,
        detections_excluded=4 if earlier_closed else 3,
    )


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("detection", "pairs", "false_negatives", "detections_excluded"),
    [
        pytest.param(400034, [(399980, 400034)], [], 0, id="150ms-after-the-beat"),
        pytest.param(400035, [], [399980], 1, id="150ms-plus-one-sample"),
    ],
)
def test_detection_after_an_unclosed_onset_is_paired_with_a_scored_beat_before_it(
    detection: int,
    pairs: list[tuple[int, int]],
    false_negatives: list[int],
    detections_excluded: int,
) -> None:
    """A detection inside an episode without offset, near a scored beat before its onset.

    Input: a record of 650000 samples with a `[` at 400000 and no `]`; a scored reference
    beat at 399980, 20 samples before the onset; one detection inside the episode, 54
    samples (150 ms) or 55 samples after the beat.
    Expected: at 54 samples the detection is paired with the beat (a match, not excluded);
    at 55 samples the beat is a false negative and the detection is not scored (excluded,
    not a false positive).
    """
    episodes = vf_episodes(_open_episode_annotations(False), N_SAMPLES)

    result = _match([399980], [detection], vf=episodes)

    _check(
        result,
        pairs=pairs,
        false_negatives=false_negatives,
        false_positives=[],
        detections_excluded=detections_excluded,
    )


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("onset", "false_negatives", "reference_excluded"),
    [
        pytest.param(N_SAMPLES - 1, [N_SAMPLES - 2], 1, id="onset-on-the-last-sample"),
        pytest.param(N_SAMPLES, [N_SAMPLES - 2, N_SAMPLES - 1], 0, id="onset-after-the-end"),
        pytest.param(N_SAMPLES + 500, [N_SAMPLES - 2, N_SAMPLES - 1], 0, id="onset-far-after"),
    ],
)
def test_unclosed_onset_at_the_end_of_the_record(
    onset: int, false_negatives: list[int], reference_excluded: int
) -> None:
    """An unclosed onset on the last sample of the record, or after its end.

    Input: a record of 650000 samples whose only `[` (without `]`) is on the last sample
    (649999), on the first sample after the end (650000) or 500 samples after the end;
    reference beats at 649998 and 649999; no detection.
    Expected: with the onset on the last sample, the beat on that sample is not scored and
    the beat before it is a false negative. With the onset after the end, the episode holds
    no sample of the record: both beats are false negatives and nothing is excluded.
    """
    episodes = vf_episodes([_annotation(onset, "[")], N_SAMPLES)

    result = _match([N_SAMPLES - 2, N_SAMPLES - 1], [], vf=episodes)

    _check(
        result,
        pairs=[],
        false_negatives=false_negatives,
        false_positives=[],
        reference_excluded=reference_excluded,
    )


# --------------------------------------------------------------------------------------------
# Episodes and the rules at 5:00 (pairs, false negatives and false positives)
# --------------------------------------------------------------------------------------------


def _check_lists(
    result: MatchResult,
    *,
    pairs: Pairs,
    false_negatives: Sequence[int],
    false_positives: Sequence[int],
) -> None:
    """Compare the pairs, false negatives and false positives only (not the counts)."""
    assert [(int(r), int(d)) for r, d in result.matched] == list(pairs)
    assert [int(s) for s in result.false_negatives] == list(false_negatives)
    assert [int(s) for s in result.false_positives] == list(false_positives)
    assert (result.tp, result.fn, result.fp) == (
        len(pairs),
        len(false_negatives),
        len(false_positives),
    )


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("vf", "pairs", "false_negatives"),
    [
        pytest.param(
            [Episode(start_sample=107000, end_sample=108015)],
            [(108040, 107995)],
            [],
            id="beat-at-108010-inside-an-episode",
        ),
        pytest.param([], [(108010, 107995)], [108040], id="control-without-episode"),
    ],
)
def test_first_scored_beat_is_the_first_one_outside_every_episode(
    vf: list[Episode], pairs: list[tuple[int, int]], false_negatives: list[int]
) -> None:
    """The first scored reference beat of the rule at 5:00, when an episode spans 5:00.

    Input: an episode from 107000 to 108015; reference beats at 107990 (inside, before
    5:00), 108010 (inside, after 5:00) and 108040 (outside); one detection at 107995, the
    last before 5:00, 15 samples from 108010 and 45 from 108040. Control: the same lists
    without the episode.
    Expected: with the episode, the first scored reference beat is 108040, and the detection
    is paired with it; the beats inside are not scored. Without the episode, the detection
    is paired with 108010 and the beat at 108040 is a false negative. No false positive.
    """
    result = _match([107990, 108010, 108040], [107995], vf=vf)

    _check_lists(result, pairs=pairs, false_negatives=false_negatives, false_positives=[])


@pytest.mark.requirement("SRS-008")
def test_detection_before_5_minutes_inside_an_episode_can_be_paired() -> None:
    """The last detection before 5:00 lies inside an episode that ends before 5:00.

    Input: an episode from 107900 to 107995; the last detection before 5:00 at 107990,
    inside it; the first scored reference beat at 108020, 30 samples from it; no other item.
    Expected: the detection is paired with the beat (a match, as for any detection inside an
    episode that is paired with a scored beat outside it). No false negative or positive.
    """
    result = _match([108020], [107990], vf=[Episode(start_sample=107900, end_sample=107995)])

    _check_lists(result, pairs=[(108020, 107990)], false_negatives=[], false_positives=[])


EPISODE_OVER_5_MIN = Episode(start_sample=107000, end_sample=109000)


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize(
    ("reference", "detections", "pairs", "false_negatives", "false_positives"),
    [
        pytest.param(
            [107500, 108500], [107500, 108500], [], [], [], id="items-inside-before-and-after"
        ),
        pytest.param(
            [110000], [108020, 110000], [(110000, 110000)], [], [], id="first-detection-dropped"
        ),
        pytest.param(
            [110000],
            [108020, 113000],
            [],
            [110000],
            [113000],
            id="first-detection-inside-not-dropped",
        ),
        pytest.param(
            [107500, 108500],
            [108010, 108600, 109500],
            [],
            [],
            [109500],
            id="no-scored-beat",
        ),
    ],
)
def test_episode_that_spans_5_minutes(
    reference: list[int],
    detections: list[int],
    pairs: list[tuple[int, int]],
    false_negatives: list[int],
    false_positives: list[int],
) -> None:
    """An episode from 107000 to 109000, which contains 5:00 (sample 108000).

    Input and expected result, from the rules of SRS-008:
    - beats and detections at 107500 and 108500: the items before 5:00 are not scored, and
      those after it lie inside the episode (the detection is unpaired): nothing is scored;
    - a first scored beat at 110000 and detections at 108020 and 110000: the detection at
      108020 is the first one after 5:00, within 150 ms of it, and the next detection is
      closer to the first scored beat: it is not scored; the pair is (110000, 110000);
    - a first scored beat at 110000 and detections at 108020 and 113000: the next detection
      is farther from the beat, so the rule at 5:00 does not apply; the detection at 108020
      is unpaired inside the episode and not scored; the beat is a false negative and the
      detection at 113000 a false positive;
    - beats at 107500 and 108500 (none scored) and detections at 108010, 108600 and 109500:
      the detection at 108010 is not scored (no reference beat is scored), the one at 108600
      is unpaired inside the episode, the one at 109500 is a false positive.
    """
    result = _match(reference, detections, vf=[EPISODE_OVER_5_MIN])

    _check_lists(
        result, pairs=pairs, false_negatives=false_negatives, false_positives=false_positives
    )


# --------------------------------------------------------------------------------------------
# The statement on random configurations around 5:00 and around episodes
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-008")
def test_rule_at_5_minutes_of_the_test_helper(
    five_minute_rule: Callable[..., tuple[int | None, int | None]],
) -> None:
    """The helper that applies the two exceptions at 5:00 agrees with the verification cases.

    Input: the configurations of the verification of SRS-008 at 5:00, given to the helper
    of `conftest.py` that the property test below uses.
    Expected: the last detection before 5:00 is returned as paired when it is within 150 ms
    of the first scored beat and closer than the next detection; the first detection after
    5:00 is returned as not scored when it is within 150 ms of 5:00 and the next detection is
    closer to the first scored beat, or no beat is scored; otherwise neither.
    """
    rule = five_minute_rule
    assert rule([108020], [107990], START, WINDOW) == (107990, None)
    assert rule([108053], [107999], START, WINDOW) == (107999, None)
    assert rule([108054], [107999], START, WINDOW) == (None, None)
    assert rule([108020], [107990, 108050], START, WINDOW) == (None, None)
    assert rule([108100], [108030, 108095], START, WINDOW) == (None, 108030)
    assert rule([108124], [108054, 108120], START, WINDOW) == (None, 108054)
    assert rule([108125], [108055, 108121], START, WINDOW) == (None, None)
    assert rule([108050], [108020, 108080], START, WINDOW) == (None, None)
    assert rule([], [108010], START, WINDOW) == (None, 108010)
    assert rule([], [108055], START, WINDOW) == (None, None)
    assert rule([108100], [], START, WINDOW) == (None, None)


def _inside(sample: int, episodes: Sequence[tuple[int, int]]) -> bool:
    """Whether a sample lies inside an episode, onset and offset included."""
    return any(onset <= sample <= offset for onset, offset in episodes)


@pytest.mark.requirement("SRS-008")
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_statement_holds_on_random_configurations_around_5_minutes(
    seed: int,
    make_matching_cases: Callable[..., list[Any]],
    five_minute_rule: Callable[..., tuple[int | None, int | None]],
) -> None:
    """What the statement fixes about every result, on 500 random configurations per seed.

    Input: reference beats and detections from about 4 s before 5:00 to 8 s after it, 40 to
    400 samples apart, with 0 to 2 ventricular flutter episodes that may span 5:00 and whose
    limits often fall on a beat or a detection (generator of `conftest.py`, fixed seeds 1 to
    4). Expected, for every configuration, from the statement:
    - each pair is at most 150 ms (54 samples) long, and no beat or detection is in two
      pairs;
    - the scored reference beats (at or after 5:00 and outside every episode) are exactly
      the paired beats and the false negatives; no other beat is in either;
    - a detection before 5:00 is paired only if it is the last one before 5:00 and the rule
      at 5:00 pairs it with the first scored beat;
    - the false positives are exactly the detections at or after 5:00 that are not paired,
      lie outside every episode and are not the first detection left unscored by the rule
      at 5:00; that detection is never paired.
    The random configurations must include each situation of interest (checked at the end).
    """
    coverage: Counter[str] = Counter()
    for index, case in enumerate(make_matching_cases(seed, 500)):
        episodes = [Episode(start_sample=a, end_sample=b) for a, b in case.episodes]
        result = _match(case.reference, case.detections, vf=episodes)
        scored = [r for r in case.reference if r >= START and not _inside(r, case.episodes)]
        paired_before, dropped = five_minute_rule(scored, case.detections, START, WINDOW)
        pairs = [(int(r), int(d)) for r, d in result.matched]
        paired_beats = [r for r, _ in pairs]
        paired_detections = [d for _, d in pairs]
        false_negatives = [int(s) for s in result.false_negatives]
        false_positives = [int(s) for s in result.false_positives]
        where = f"seed {seed}, case {index}: {case}"

        assert len(set(paired_beats)) == len(pairs), where
        assert len(set(paired_detections)) == len(pairs), where
        assert all(abs(r - d) <= WINDOW for r, d in pairs), where
        assert sorted(paired_beats + false_negatives) == scored, where
        expected_before = [] if paired_before is None else [(scored[0], paired_before)]
        assert [p for p in pairs if p[1] < START] == expected_before, where
        assert dropped is None or dropped not in paired_detections, where
        expected_false_positives = [
            d
            for d in case.detections
            if d >= START
            and d not in paired_detections
            and d != dropped
            and not _inside(d, case.episodes)
        ]
        assert false_positives == expected_false_positives, where
        assert (result.tp, result.fn, result.fp) == (
            len(pairs),
            len(false_negatives),
            len(false_positives),
        ), where

        coverage["paired before 5:00"] += paired_before is not None
        coverage["dropped at 5:00"] += dropped is not None
        coverage["dropped inside an episode"] += dropped is not None and _inside(
            dropped, case.episodes
        )
        coverage["episode spanning 5:00"] += any(a < START <= b for a, b in case.episodes)
        coverage["detection on an episode limit"] += any(
            d in e for d in case.detections for e in case.episodes
        )
        coverage["unpaired detection inside, after 5:00"] += any(
            d >= START and d not in paired_detections and _inside(d, case.episodes)
            for d in case.detections
        )
        coverage["detection inside, paired"] += any(
            _inside(d, case.episodes) for d in paired_detections
        )

    assert min(coverage.values()) >= 5 and len(coverage) == 7, coverage
