"""Requirement tests of SRS-012: the counts of what was not scored (risk control RC-004).

SRS-012 states which figures the validation report gives on what SRS-008 leaves unscored
because of ventricular flutter or fibrillation episodes. They cover the part of each record
from 5:00 to its end:

- the number of reference beats at or after 5:00 that lie inside an episode;
- the number of detections at or after 5:00 that lie inside an episode and are not paired,
  without the detection left unscored by the rule at 5:00 of SRS-008.

These two counts are produced by the beat-by-beat matching, for each record, in the fields
`reference_excluded` and `detections_excluded` of its result (architecture, section 8.8.3),
and the report takes them from there. The tests of this file check the two counts, on lists
at 360 Hz (match window 54 samples, 5:00 = sample 108000) whose correct counts are worked out
from the statement. The pairs, false negatives and false positives of the same kind of cases
are checked under SRS-008; the other figures and the report itself are checked with the
report.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pytest

from sinus_dsp.evaluation.matching import Episode, MatchResult, match_beats

WINDOW = 54  # 150 ms at 360 Hz
START = 108000  # 5:00 at 360 Hz


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


def _counts(result: MatchResult) -> tuple[int, int]:
    """(reference beats not scored, detections not scored), as the result gives them."""
    return result.reference_excluded, result.detections_excluded


EARLY = Episode(start_sample=50000, end_sample=60000)  # ends before 5:00
LATE = Episode(start_sample=200000, end_sample=203000)  # after 5:00
OVER_5_MIN = Episode(start_sample=107000, end_sample=109000)  # contains 5:00


# --------------------------------------------------------------------------------------------
# Episodes before and after 5:00
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("vf", "expected"),
    [
        pytest.param([EARLY, LATE], (2, 1), id="one-before-and-one-after-5min"),
        pytest.param([EARLY], (0, 0), id="only-the-one-before-5min"),
        pytest.param([LATE], (2, 1), id="only-the-one-after-5min"),
        pytest.param([], (0, 0), id="no-episode"),
    ],
)
def test_only_the_episode_after_5_minutes_is_counted(
    vf: list[Episode], expected: tuple[int, int]
) -> None:
    """Two episodes, one that ends before 5:00 and one after 5:00.

    The configuration of the verification of SRS-012, for the two counts.
    Input: an episode from 50000 to 60000 (ends before 5:00) with reference beats at 52000
    and 55000 and an unpaired detection at 57000 inside it; an episode from 200000 to 203000
    with reference beats at 200500 and 201500 and an unpaired detection at 202000 inside it;
    reference beats outside both at 40000, 150000 and 250000, each with a detection 3 samples
    later. Matched with both episodes, with each alone, and without episode.
    Expected: 2 reference beats and 1 detection not scored when the episode after 5:00 is
    given (the items of the episode before 5:00 are in neither count); 0 and 0 otherwise.
    """
    reference = [40000, 52000, 55000, 150000, 200500, 201500, 250000]
    detections = [40003, 57000, 150003, 202000, 250003]

    result = _match(reference, detections, vf=vf)

    assert _counts(result) == expected


@pytest.mark.requirement("SRS-012")
def test_episode_that_contains_5_minutes_counts_only_the_items_after_it() -> None:
    """An episode from 107000 to 109000, which contains 5:00.

    Input: reference beats at 107500 and 108500 and detections at 107500 and 108500, all
    inside the episode; nothing else.
    Expected: 1 reference beat and 1 detection not scored: those at 108500. The beat and
    the detection at 107500 lie before 5:00 and are in neither count.
    """
    result = _match([107500, 108500], [107500, 108500], vf=[OVER_5_MIN])

    assert _counts(result) == (1, 1)


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("beat", "counted"),
    [
        pytest.param(107000, 0, id="on-the-onset-before-5min"),
        pytest.param(107999, 0, id="one-sample-before-5min"),
        pytest.param(108000, 1, id="at-5min"),
        pytest.param(108001, 1, id="one-sample-after-5min"),
        pytest.param(109000, 1, id="on-the-offset"),
        pytest.param(109001, 0, id="one-sample-after-the-offset"),
    ],
)
def test_reference_beat_inside_an_episode_is_counted_from_5_minutes(
    beat: int, counted: int
) -> None:
    """The 5:00 limit, and the offset, for a reference beat inside an episode.

    Input: the episode from 107000 to 109000, one reference beat at the given sample and no
    detection.
    Expected: the beat is counted as not scored when it lies inside the episode at or after
    5:00 (108000 to 109000); not before 5:00 (107000, 107999), where the first 5 minutes
    already leave it out, and not after the offset (109001), where it is scored.
    """
    result = _match([beat], [], vf=[OVER_5_MIN])

    assert _counts(result) == (counted, 0)


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("detection", "counted"),
    [
        pytest.param(107000, 0, id="on-the-onset-before-5min"),
        pytest.param(107999, 0, id="one-sample-before-5min"),
        pytest.param(108000, 1, id="at-5min"),
        pytest.param(108054, 1, id="150ms-after-5min"),
        pytest.param(108055, 1, id="150ms-plus-one-sample-after-5min"),
        pytest.param(109000, 1, id="on-the-offset"),
    ],
)
def test_unpaired_detection_inside_an_episode_is_counted_from_5_minutes(
    detection: int, counted: int
) -> None:
    """The 5:00 limit for an unpaired detection inside an episode.

    Input: the episode from 107000 to 109000; a first scored reference beat at 110000; a
    detection at the given sample, more than 150 ms from the beat, and a detection at 113000
    (farther from the beat than the first one, so that the rule at 5:00 does not leave the
    first detection after 5:00 unscored).
    Expected: the detection is counted as not scored when it lies inside the episode at or
    after 5:00, on the offset included; not when it lies before 5:00. No reference beat is
    counted.
    """
    result = _match([110000], [detection, 113000], vf=[OVER_5_MIN])

    assert _counts(result) == (0, counted)


# --------------------------------------------------------------------------------------------
# The detection left unscored by the rule at 5:00
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("reference", "detections", "expected"),
    [
        pytest.param([110000], [108020, 110000], (0, 0), id="next-detection-closer-to-the-beat"),
        pytest.param([107500, 108500], [108010, 108600], (1, 1), id="no-scored-beat"),
        pytest.param([107500, 108500], [108000, 108600], (1, 1), id="dropped-at-5min"),
        pytest.param([107500, 108500], [108054, 108600], (1, 1), id="dropped-150ms-after"),
        pytest.param([107500, 108500], [108055, 108600], (1, 2), id="not-dropped-150ms-plus-1"),
        pytest.param([110000], [108020, 113000], (0, 1), id="next-detection-farther"),
    ],
)
def test_detection_left_unscored_by_the_rule_at_5_minutes_is_not_counted(
    reference: list[int], detections: list[int], expected: tuple[int, int]
) -> None:
    """The first detection after 5:00, inside an episode that contains 5:00.

    Input: the episode from 107000 to 109000, and:
    - a first scored beat at 110000 and detections at 108020 and 110000: the detection at
      108020 is left unscored by the rule at 5:00 (the next detection is closer to the first
      scored beat); it is not counted (the beat is paired with the detection at 110000);
    - beats at 107500 and 108500 (no scored beat) and a first detection at 108010, 108000 or
      108054, then one at 108600: the first detection is left unscored by the rule at 5:00
      (no reference beat is scored) and is not counted; the detection at 108600 is counted,
      and so is the beat at 108500;
    - the same with a first detection at 108055, 150 ms plus one sample after 5:00: the rule
      does not apply, and both detections are counted;
    - a first scored beat at 110000 and detections at 108020 and 113000: the rule does not
      apply (the next detection is farther), and the detection at 108020 is counted.
    Expected: (reference beats, detections) not scored as given in each case.
    """
    result = _match(reference, detections, vf=[OVER_5_MIN])

    assert _counts(result) == expected


# --------------------------------------------------------------------------------------------
# Detections inside an episode that are paired
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize(
    ("vf", "reference", "detections", "expected"),
    [
        pytest.param([LATE], [203030], [202990], (0, 0), id="after-5min"),
        pytest.param([LATE], [202975, 203030], [202990], (1, 0), id="beat-of-the-episode-closer"),
        pytest.param(
            [Episode(start_sample=107900, end_sample=107995)],
            [108020],
            [107990],
            (0, 0),
            id="last-detection-before-5min",
        ),
    ],
)
def test_detection_inside_an_episode_that_is_paired_is_not_counted(
    vf: list[Episode], reference: list[int], detections: list[int], expected: tuple[int, int]
) -> None:
    """A detection inside an episode, paired with a scored reference beat outside it.

    Input:
    - the episode from 200000 to 203000, a scored beat at 203030 and a detection at 202990
      inside the episode, 40 samples from it;
    - the same, with a beat of the episode at 202975, closer to the detection (not scored);
    - an episode from 107900 to 107995, the last detection before 5:00 at 107990 inside it,
      and the first scored beat at 108020, which the rule at 5:00 pairs with it.
    Expected: the detection is a match and is not counted as not scored; only the beat
    inside the episode after 5:00 (202975) is counted.
    """
    result = _match(reference, detections, vf=vf)

    assert _counts(result) == expected


# --------------------------------------------------------------------------------------------
# The definitions on random configurations around 5:00 and around episodes
# --------------------------------------------------------------------------------------------


def _inside(sample: int, episodes: Sequence[tuple[int, int]]) -> bool:
    """Whether a sample lies inside an episode, onset and offset included."""
    return any(onset <= sample <= offset for onset, offset in episodes)


@pytest.mark.requirement("SRS-012")
@pytest.mark.parametrize("seed", [11, 12, 13, 14])
def test_counts_follow_their_definition_on_random_configurations(
    seed: int,
    make_matching_cases: Callable[..., list[Any]],
    five_minute_rule: Callable[..., tuple[int | None, int | None]],
) -> None:
    """The two counts on 500 random configurations per seed.

    Input: reference beats and detections from about 4 s before 5:00 to 8 s after it, with
    0 to 2 episodes that may contain 5:00 and whose limits often fall on a beat or a
    detection (generator of `conftest.py`, fixed seeds 11 to 14).
    Expected, for every configuration:
    - reference beats not scored = the reference beats at or after 5:00 inside an episode;
    - detections not scored = the detections at or after 5:00 inside an episode that are in
      no pair, minus the first detection after 5:00 if the rule at 5:00 of SRS-008 leaves it
      unscored;
    - with them, every reference beat and every detection is in exactly one class: before
      5:00 (unscored), not scored in an episode, paired, false negative or false positive.
    The random configurations must include each situation of interest (checked at the end).
    """
    coverage: Counter[str] = Counter()
    for index, case in enumerate(make_matching_cases(seed, 500)):
        episodes = [Episode(start_sample=a, end_sample=b) for a, b in case.episodes]
        result = _match(case.reference, case.detections, vf=episodes)
        scored = [r for r in case.reference if r >= START and not _inside(r, case.episodes)]
        paired_before, dropped = five_minute_rule(scored, case.detections, START, WINDOW)
        paired_detections = {int(d) for _, d in result.matched}
        where = f"seed {seed}, case {index}: {case}"

        beats_inside = [r for r in case.reference if r >= START and _inside(r, case.episodes)]
        detections_inside = [
            d
            for d in case.detections
            if d >= START
            and _inside(d, case.episodes)
            and d not in paired_detections
            and d != dropped
        ]
        assert _counts(result) == (len(beats_inside), len(detections_inside)), where

        beats_before = sum(1 for r in case.reference if r < START)
        assert beats_before + result.reference_excluded + result.tp + result.fn == len(
            case.reference
        ), where
        detections_before = sum(1 for d in case.detections if d < START)
        left_out_at_5_min = detections_before - (paired_before is not None) + (dropped is not None)
        assert left_out_at_5_min + result.detections_excluded + result.tp + result.fp == len(
            case.detections
        ), where

        coverage["beat before 5:00 inside"] += any(
            r < START and _inside(r, case.episodes) for r in case.reference
        )
        coverage["detection before 5:00 inside"] += any(
            d < START and _inside(d, case.episodes) for d in case.detections
        )
        coverage["beat counted"] += bool(beats_inside)
        coverage["detection counted"] += bool(detections_inside)
        coverage["dropped inside, not counted"] += dropped is not None and _inside(
            dropped, case.episodes
        )
        coverage["episode containing 5:00"] += any(a < START <= b for a, b in case.episodes)
        coverage["detection inside, paired"] += any(
            _inside(d, case.episodes) for d in paired_detections
        )

    assert min(coverage.values()) >= 5 and len(coverage) == 7, coverage
