"""Unit tests of the beat-by-beat matching: parameters, episodes and every pairing rule.

The cases are at 360 Hz: a window of 54 samples and a start at sample 108000.
"""

import dataclasses
import random
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp.data.records import Annotation
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.matching import (
    LEARNING_PERIOD_S,
    MATCH_WINDOW_MS,
    Episode,
    MatchResult,
    learning_period_samples,
    match_beats,
    match_window_samples,
    vf_episodes,
)

W = 54
START = 108000
HUGE = 2**62


def match(
    reference: npt.ArrayLike,
    detections: npt.ArrayLike,
    vf: Sequence[Episode] = (),
    *,
    window: int = W,
    start: int = START,
) -> MatchResult:
    return match_beats(reference, detections, window_samples=window, start_sample=start, vf=vf)


Outcome = tuple[tuple[tuple[int, int], ...], tuple[int, ...], tuple[int, ...]]


def outcome(result: MatchResult) -> Outcome:
    """The pairs, the false negatives and the false positives."""
    return result.matched, result.false_negatives, result.false_positives


def annotation(sample: int, symbol: str) -> Annotation:
    return Annotation(sample=sample, symbol=symbol, subtype=0, aux_note="")


# Parameters


def test_constants() -> None:
    assert MATCH_WINDOW_MS == 150
    assert LEARNING_PERIOD_S == 300


@pytest.mark.parametrize(
    ("fs_hz", "expected"),
    [(360.0, 54), (250.0, 37), (125.0, 18), (1000.0, 150), (128.0, 19), (500, 75), (257.0, 38)],
)
def test_match_window_is_rounded_down(fs_hz: float, expected: int) -> None:
    window = match_window_samples(fs_hz)
    assert window == expected
    assert type(window) is int
    # At most 150 ms, and one more sample would exceed it.
    assert window * 1000 <= 150 * fs_hz < (window + 1) * 1000


@pytest.mark.parametrize(
    ("fs_hz", "expected"),
    [(360.0, 108000), (250.0, 75000), (125, 37500), (1000.0, 300000), (128.5, 38550)],
)
def test_learning_period(fs_hz: float, expected: int) -> None:
    start = learning_period_samples(fs_hz)
    assert start == expected
    assert type(start) is int


def test_learning_period_is_rounded_up() -> None:
    assert learning_period_samples(360.001) == 108001
    assert learning_period_samples(359.999) == 108000


@pytest.mark.parametrize("fs_hz", [0.0, -360.0, float("nan"), float("inf"), float("-inf")])
def test_parameters_reject_an_unusable_sampling_frequency(fs_hz: float) -> None:
    with pytest.raises(InvalidInputError, match="sampling frequency"):
        match_window_samples(fs_hz)
    with pytest.raises(InvalidInputError, match="sampling frequency"):
        learning_period_samples(fs_hz)


# Episodes


def test_no_annotation_gives_no_episode() -> None:
    assert vf_episodes([], 1000) == ()


def test_annotations_without_onset_give_no_episode() -> None:
    annotations = [annotation(10, "+"), annotation(20, "~"), annotation(30, "!")]
    assert vf_episodes(annotations, 1000) == ()


def test_episode_covers_the_onset_and_the_offset() -> None:
    annotations = [annotation(100, "["), annotation(250, "]")]
    assert vf_episodes(annotations, 1000) == (Episode(start_sample=100, end_sample=250),)


def test_other_annotations_do_not_open_or_close_an_episode() -> None:
    annotations = [
        annotation(50, "+"),
        annotation(100, "["),
        annotation(150, "!"),
        annotation(160, "+"),
        annotation(170, "~"),
        annotation(250, "]"),
        annotation(300, "!"),
    ]
    assert vf_episodes(annotations, 1000) == (Episode(100, 250),)


def test_several_episodes_in_the_order_of_their_onsets() -> None:
    annotations = [
        annotation(100, "["),
        annotation(250, "]"),
        annotation(400, "["),
        annotation(400, "]"),
        annotation(700, "["),
        annotation(900, "]"),
    ]
    assert vf_episodes(annotations, 1000) == (
        Episode(100, 250),
        Episode(400, 400),
        Episode(700, 900),
    )


def test_onset_while_an_episode_is_open_is_ignored() -> None:
    annotations = [annotation(100, "["), annotation(150, "["), annotation(250, "]")]
    assert vf_episodes(annotations, 1000) == (Episode(100, 250),)


def test_offset_while_no_episode_is_open_is_ignored() -> None:
    annotations = [
        annotation(50, "]"),
        annotation(100, "["),
        annotation(250, "]"),
        annotation(300, "]"),
    ]
    assert vf_episodes(annotations, 1000) == (Episode(100, 250),)


def test_episode_open_at_the_end_lasts_until_the_last_sample() -> None:
    annotations = [annotation(100, "["), annotation(250, "]"), annotation(600, "[")]
    assert vf_episodes(annotations, 1000) == (Episode(100, 250), Episode(600, 999))


def test_episodes_are_a_tuple_of_frozen_values() -> None:
    episodes = vf_episodes((annotation(1, "["), annotation(2, "]")), 10)
    assert isinstance(episodes, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        episodes[0].start_sample = 0  # type: ignore[misc]


# Result


def test_result_counts_are_the_lengths_of_its_lists() -> None:
    result = match([108100, 108500, 109000], [108100, 108700, 109010])
    assert result == MatchResult(
        tp=2,
        fn=1,
        fp=1,
        matched=((108100, 108100), (109000, 109010)),
        false_negatives=(108500,),
        false_positives=(108700,),
        reference_excluded=0,
        detections_excluded=0,
    )


def test_result_holds_python_integers() -> None:
    reference = np.array([108100, 108500], dtype=np.int64)
    detections = np.array([108101, 108800], dtype=np.int64)
    result = match(reference, detections)
    values = [*result.matched[0], *result.false_negatives, *result.false_positives]
    values += [result.tp, result.fn, result.fp]
    values += [result.reference_excluded, result.detections_excluded]
    assert all(type(value) is int for value in values)


def test_inputs_are_not_modified() -> None:
    reference = np.array([108100, 108500], dtype=np.int64)
    detections = np.array([108101, 108800], dtype=np.int64)
    match_beats(reference, detections, window_samples=W, start_sample=START)
    assert reference.tolist() == [108100, 108500]
    assert detections.tolist() == [108101, 108800]


@pytest.mark.parametrize("kind", [list, tuple, np.int64, np.int32, np.uint64])
def test_lists_of_any_integer_kind_are_accepted(kind: type) -> None:
    reference: npt.ArrayLike
    detections: npt.ArrayLike
    if kind in (list, tuple):
        reference, detections = kind([108100, 108500]), kind([108101, 108800])
    else:
        reference = np.array([108100, 108500], dtype=kind)
        detections = np.array([108101, 108800], dtype=kind)
    result = match(reference, detections)
    assert outcome(result) == (((108100, 108101),), (108500,), (108800,))


# Window


@pytest.mark.parametrize("offset", [-54, -53, -1, 0, 1, 53, 54])
def test_detection_within_the_window_is_paired(offset: int) -> None:
    beat = 200000
    result = match([beat], [beat + offset])
    assert outcome(result) == (((beat, beat + offset),), (), ())


@pytest.mark.parametrize("offset", [-55, 55, -56, 56, 1000, -1000])
def test_detection_outside_the_window_is_not_paired(offset: int) -> None:
    beat = 200000
    result = match([beat], [beat + offset])
    assert outcome(result) == ((), (beat,), (beat + offset,))


def test_window_of_zero_pairs_only_the_same_sample() -> None:
    result = match([200000, 201000], [200000, 201001], window=0)
    assert outcome(result) == (((200000, 200000),), (201000,), (201001,))


# Two detections near one reference beat


@pytest.mark.parametrize(
    ("detections", "paired", "unpaired"),
    [
        ((199980, 199995), 199995, 199980),  # both before: the closer one
        ((200005, 200020), 200005, 200020),  # both after: the closer one
        ((199990, 200020), 199990, 200020),  # one each side, the earlier is closer
        ((199980, 200010), 200010, 199980),  # one each side, the later is closer
    ],
)
def test_closer_of_two_detections_is_paired(
    detections: tuple[int, int], paired: int, unpaired: int
) -> None:
    result = match([200000], detections)
    assert outcome(result) == (((200000, paired),), (), (unpaired,))


@pytest.mark.parametrize("distance", [1, 10, 54])
def test_later_of_two_equidistant_detections_is_paired(distance: int) -> None:
    result = match([200000], [200000 - distance, 200000 + distance])
    assert outcome(result) == (((200000, 200000 + distance),), (), (200000 - distance,))


# One detection between two reference beats


@pytest.mark.parametrize(
    ("detection", "paired", "unpaired"),
    [(200010, 200000, 200040), (200030, 200040, 200000)],
)
def test_detection_between_two_beats_is_paired_with_the_closer(
    detection: int, paired: int, unpaired: int
) -> None:
    result = match([200000, 200040], [detection])
    assert outcome(result) == (((paired, detection),), (unpaired,), ())


@pytest.mark.parametrize("distance", [1, 20, 54])
def test_detection_equidistant_from_two_beats_is_paired_with_the_later(distance: int) -> None:
    first, detection, second = 200000, 200000 + distance, 200000 + 2 * distance
    result = match([first, second], [detection])
    assert outcome(result) == (((second, detection),), (first,), ())


# Ties and repeated samples


def test_detection_at_the_sample_of_the_beat_is_paired() -> None:
    result = match([200000, 201000], [200000, 201000])
    assert outcome(result) == (((200000, 200000), (201000, 201000)), (), ())


def test_two_reference_beats_at_the_same_sample() -> None:
    # The first is paired (the reference comes first in a tie); the second has no partner.
    result = match([200000, 200000], [200000])
    assert outcome(result) == (((200000, 200000),), (200000,), ())


def test_two_reference_beats_at_the_same_sample_and_two_detections() -> None:
    # The earlier detection is closer than the later one: each beat gets a detection.
    result = match([200000, 200000], [199990, 200011])
    assert outcome(result) == (((200000, 199990), (200000, 200011)), (), ())
    # Equidistant detections: the earlier one is unpaired (the later is as close, and the
    # second beat is no closer to it), then the first beat is unpaired for the same reason
    # (its successor is as close to the detection), and the second beat takes the detection.
    result = match([200000, 200000], [199990, 200010])
    assert outcome(result) == (((200000, 200010),), (200000,), (199990,))


def test_each_item_belongs_to_at_most_one_pair() -> None:
    result = match([200000, 200020, 200040], [200010, 200030])
    references = [pair[0] for pair in result.matched]
    detections = [pair[1] for pair in result.matched]
    assert len(set(references)) == len(references)
    assert len(set(detections)) == len(detections)
    assert result.tp + result.fn == 3
    assert result.tp + result.fp == 2


# Look-ahead


def test_look_ahead_pairs_a_detection_whose_successor_has_a_better_partner() -> None:
    # The next detection (200010) is closer to the beat at 200000 than the current one
    # (199980), but it is closer still to the next beat (200015): the current pair is made.
    result = match([200000, 200015], [199980, 200010])
    assert outcome(result) == (((200000, 199980), (200015, 200010)), (), ())


def test_without_a_better_partner_for_the_successor_the_detection_is_unpaired() -> None:
    # The next beat (200030) is farther from the next detection than the current beat is.
    result = match([200000, 200030], [199980, 200010])
    assert outcome(result) == (((200000, 200010),), (200030,), (199980,))


def test_look_ahead_pairs_a_beat_whose_successor_has_a_better_partner() -> None:
    # The next beat (200030) is closer to the detection at 200020 than the current one
    # (200000), but it is closer still to the next detection (200035).
    result = match([200000, 200030], [200020, 200035])
    assert outcome(result) == (((200000, 200020), (200030, 200035)), (), ())


def test_without_a_better_partner_for_the_successor_the_beat_is_unpaired() -> None:
    result = match([200000, 200030], [200020, 200060])
    assert outcome(result) == (((200030, 200020),), (200000,), (200060,))


def test_look_ahead_needs_a_strictly_closer_partner() -> None:
    # |T2 - t2| = 9 is below |T - t2| = 10: the detection at 199980 is paired.
    result = match([200000, 200019], [199980, 200010])
    assert outcome(result) == (((200000, 199980), (200019, 200010)), (), ())
    # |T2 - t2| equals |T - t2| (both 10): the look-ahead does not apply and 199980 is a
    # false positive. The detection at 200010 is then equidistant from the two beats, so it
    # is paired with the later one.
    result = match([200000, 200020], [199980, 200010])
    assert outcome(result) == (((200020, 200010),), (200000,), (199980,))


def test_look_ahead_does_not_widen_the_window() -> None:
    # The look-ahead condition holds and the current pair is 54 samples apart: paired.
    result = match([200000, 200015], [199946, 200010])
    assert outcome(result) == (((200000, 199946), (200015, 200010)), (), ())
    # At 55 samples the detection is a false positive, whatever the look-ahead says. The
    # detection at 200010 is then closer to the second beat, which takes it.
    result = match([200000, 200015], [199945, 200010])
    assert outcome(result) == (((200015, 200010),), (200000,), (199945,))


def test_pairing_is_sequential_and_not_a_maximum_matching() -> None:
    # A maximum matching would make two pairs: (200000, 200010) and (200020, 200064).
    result = match([200000, 200020], [200010, 200064])
    assert outcome(result) == (((200020, 200010),), (200000,), (200064,))


# Start


def test_reference_beat_just_before_the_start_is_not_scored() -> None:
    result = match([100, 50000, START - 1], [])
    assert outcome(result) == ((), (), ())


def test_reference_beat_at_the_start_is_scored() -> None:
    result = match([START - 1, START, START + 400], [])
    assert outcome(result) == ((), (START, START + 400), ())


def test_detections_before_the_start_are_not_scored() -> None:
    result = match([START + 1000], [100, 50000, START - 500, START - 100])
    assert outcome(result) == ((), (START + 1000,), ())


def test_detection_paired_with_an_unscored_beat_would_be_is_simply_dropped() -> None:
    # A detection on a beat before the start: neither is scored.
    result = match([START - 20, START + 400], [START - 20, START + 400])
    assert outcome(result) == (((START + 400, START + 400),), (), ())


def test_last_detection_before_the_start_is_paired_with_the_first_scored_beat() -> None:
    result = match([START + 10], [START - 20])
    assert outcome(result) == (((START + 10, START - 20),), (), ())


def test_last_detection_before_the_start_at_the_limit_of_the_window() -> None:
    assert match([START + 10], [START - 44]).matched == ((START + 10, START - 44),)
    assert outcome(match([START + 10], [START - 45])) == ((), (START + 10,), ())


def test_only_the_last_detection_before_the_start_can_be_paired() -> None:
    result = match([START + 10], [START - 30, START - 25])
    assert outcome(result) == (((START + 10, START - 25),), (), ())


def test_last_detection_before_the_start_is_dropped_when_the_next_is_closer() -> None:
    result = match([START + 10], [START - 20, START + 25])
    assert outcome(result) == (((START + 10, START + 25),), (), ())


def test_last_detection_before_the_start_is_dropped_when_the_next_is_as_close() -> None:
    result = match([START + 10], [START - 10, START + 30])
    assert outcome(result) == (((START + 10, START + 30),), (), ())


def test_last_detection_before_the_start_is_paired_when_it_is_closer_than_the_next() -> None:
    result = match([START + 10], [START - 10, START + 31])
    assert outcome(result) == (((START + 10, START - 10),), (), (START + 31,))


def test_start_pairing_has_no_look_ahead() -> None:
    # In the loop, the look-ahead would pair the beat at START + 10 with the detection at
    # START - 20, because the next detection (START + 20) has a better partner (START + 25).
    # At the start only the original criterion applies: the detection is dropped.
    reference = [START + 10, START + 25]
    detections = [START - 20, START + 20]
    result = match(reference, detections)
    assert outcome(result) == (((START + 25, START + 20),), (START + 10,), ())
    # The same configuration away from the start makes both pairs.
    shifted = match([beat + 1000 for beat in reference], [d + 1000 for d in detections])
    assert shifted.matched == ((START + 1010, START + 980), (START + 1025, START + 1020))


def test_first_detection_after_the_start_is_dropped_when_the_next_is_closer() -> None:
    result = match([START + 50], [START + 10, START + 45])
    assert outcome(result) == (((START + 50, START + 45),), (), ())


def test_first_detection_after_the_start_is_kept_when_the_next_is_not_closer() -> None:
    # The next detection is as close to the beat as the first one.
    result = match([START + 30], [START + 10, START + 50])
    assert outcome(result) == (((START + 30, START + 50),), (), (START + 10,))


@pytest.mark.parametrize(("offset", "dropped"), [(0, True), (54, True), (55, False)])
def test_first_detection_is_dropped_only_within_the_window_after_the_start(
    offset: int, dropped: bool
) -> None:
    first = START + offset
    result = match([START + 100], [first, START + 95])
    expected_fp = () if dropped else (first,)
    assert outcome(result) == (((START + 100, START + 95),), (), expected_fp)


def test_first_detection_is_dropped_after_a_dropped_detection_before_the_start() -> None:
    result = match([START + 50], [START - 100, START + 10, START + 45])
    assert outcome(result) == (((START + 50, START + 45),), (), ())


def test_first_detection_is_not_dropped_after_a_pair_at_the_start() -> None:
    # The detection before the start is paired, so the rule that drops the first detection
    # after the start does not apply: START + 40 is a false positive.
    result = match([START + 10, START + 50], [START - 5, START + 40, START + 48])
    assert outcome(result) == (
        ((START + 10, START - 5), (START + 50, START + 48)),
        (),
        (START + 40,),
    )


def test_only_one_detection_is_dropped_after_the_start() -> None:
    result = match([START + 50], [START + 10, START + 20, START + 45])
    # START + 10 is dropped (START + 20 is closer); START + 20 is then scored.
    assert outcome(result) == (((START + 50, START + 45),), (), (START + 20,))


def test_start_at_sample_0() -> None:
    assert outcome(match([10, 500], [12, 500], start=0)) == (((10, 12), (500, 500)), (), ())
    # The first detection is within the window after the start and the next one is closer.
    assert outcome(match([10], [5, 12], start=0)) == (((10, 12),), (), ())


# Empty lists


def test_empty_detection_list_gives_every_scored_beat_as_false_negative() -> None:
    result = match([100, START - 1, START, START + 300, START + 600], [])
    assert outcome(result) == ((), (START, START + 300, START + 600), ())


def test_empty_reference_list_gives_every_scored_detection_as_false_positive() -> None:
    result = match([], [100, START - 1, START + 55, START + 300, START + 600])
    assert outcome(result) == ((), (), (START + 55, START + 300, START + 600))


@pytest.mark.parametrize("offset", [0, 1, 54])
def test_empty_reference_list_drops_the_first_detection_within_the_window(offset: int) -> None:
    result = match([], [START - 1, START + offset, START + 60, START + 600])
    assert outcome(result) == ((), (), (START + 60, START + 600))


def test_empty_reference_list_and_a_single_detection_just_after_the_start() -> None:
    assert outcome(match([], [START + 10])) == ((), (), ())
    assert outcome(match([], [START + 55])) == ((), (), (START + 55,))


def test_no_scored_beat_drops_the_first_detection_within_the_window() -> None:
    # Every reference beat is before the start: as with an empty reference list.
    result = match([100, START - 1], [START + 5, START + 30, START + 500])
    assert outcome(result) == ((), (), (START + 30, START + 500))


def test_both_lists_empty() -> None:
    assert match([], []) == MatchResult(0, 0, 0, (), (), (), 0, 0)


def test_empty_numpy_arrays_of_any_dtype() -> None:
    empty_float = np.array([])
    empty_int = np.array([], dtype=np.int64)
    assert match(empty_float, empty_int).tp == 0
    assert match(empty_int, empty_float).tp == 0


# Sentinel


def test_trailing_detections_are_false_positives() -> None:
    result = match([200000], [200000, 200500, 201000, 201500])
    assert outcome(result) == (((200000, 200000),), (), (200500, 201000, 201500))


def test_trailing_beats_are_false_negatives() -> None:
    result = match([200000, 200500, 201000, 201500], [200000])
    assert outcome(result) == (((200000, 200000),), (200500, 201000, 201500), ())


def test_last_items_are_paired_with_the_sentinel_as_their_successor() -> None:
    # Both successors are the sentinel: |T2 - t2| is 0 and the pair is made within the window.
    assert match([200000], [200054]).matched == ((200000, 200054),)
    assert match([200000], [199946]).matched == ((200000, 199946),)


def test_sentinel_never_appears_in_the_result() -> None:
    result = match([200000, 300000], [200100, 300100, 400000], [Episode(250000, 10**9)])
    values = [v for pair in result.matched for v in pair]
    values += [*result.false_negatives, *result.false_positives]
    assert HUGE not in values
    assert max(values) < 10**9
    assert outcome(result) == ((), (200000,), (200100,))
    assert (result.reference_excluded, result.detections_excluded) == (1, 2)


def test_large_samples_below_the_bound_are_handled_exactly() -> None:
    base = 2**61 - 1000
    result = match([base, base + 500], [base + 54, base + 555])
    assert outcome(result) == (((base, base + 54),), (base + 500,), (base + 555,))


# Ventricular flutter and fibrillation episodes


def test_reference_beats_inside_an_episode_are_not_scored() -> None:
    episode = Episode(200000, 201000)
    reference = [199999, 200000, 200500, 201000, 201001]
    result = match(reference, [], [episode])
    assert outcome(result) == ((), (199999, 201001), ())
    assert result.reference_excluded == 3
    assert result.detections_excluded == 0


def test_unpaired_detections_inside_an_episode_are_not_counted() -> None:
    episode = Episode(200000, 201000)
    detections = [199999, 200000, 200500, 201000, 201001]
    result = match([], detections, [episode])
    assert outcome(result) == ((), (), (199999, 201001))
    assert result.detections_excluded == 3
    assert result.reference_excluded == 0


def test_beats_and_detections_inside_an_episode() -> None:
    episode = Episode(200000, 201000)
    reference = [199500, 200100, 200400, 200700, 201500]
    detections = [199500, 200100, 200390, 200900, 201500, 202000]
    result = match(reference, detections, [episode])
    assert outcome(result) == (((199500, 199500), (201500, 201500)), (), (202000,))
    assert (result.reference_excluded, result.detections_excluded) == (3, 3)


def test_detection_inside_an_episode_is_paired_with_a_scored_beat_outside_it() -> None:
    episode = Episode(200000, 201000)
    # Before the episode and after it.
    result = match([199980, 201030], [200010, 200990], [episode])
    assert outcome(result) == (((199980, 200010), (201030, 200990)), (), ())
    assert (result.reference_excluded, result.detections_excluded) == (0, 0)


def test_detection_inside_an_episode_beyond_the_window_of_a_beat_outside_it() -> None:
    episode = Episode(200000, 201000)
    result = match([199980], [200035], [episode])
    assert outcome(result) == ((), (199980,), ())
    assert result.detections_excluded == 1


def test_excluded_beat_does_not_compete_for_a_detection() -> None:
    # Without the episode, the detection at 200010 is paired with the beat at 200005.
    assert match([199980, 200005], [200010]).matched == ((200005, 200010),)
    result = match([199980, 200005], [200010], [Episode(200000, 201000)])
    assert outcome(result) == (((199980, 200010),), (), ())
    assert result.reference_excluded == 1


def test_every_episode_is_checked() -> None:
    episodes = [Episode(200000, 200100), Episode(200200, 200300), Episode(200400, 200500)]
    episodes += [Episode(200600, 200700)]
    detections = [200050, 200250, 200450, 200650, 200850]
    reference = [200060, 200260, 200460, 200660]
    result = match(reference, detections, episodes)
    assert outcome(result) == ((), (), (200850,))
    assert (result.reference_excluded, result.detections_excluded) == (4, 4)


def test_episode_until_the_end_of_the_record() -> None:
    annotations = [annotation(300000, "[")]
    episodes = vf_episodes(annotations, 650000)
    result = match([200000, 300000, 400000, 649999], [200000, 350000, 649999], episodes)
    assert outcome(result) == (((200000, 200000),), (), ())
    assert (result.reference_excluded, result.detections_excluded) == (3, 2)


def test_episode_before_the_start() -> None:
    # Reference beats inside an episode are counted as excluded wherever the episode is;
    # detections before the start are not scored and are not counted.
    episode = Episode(50000, 60000)
    result = match([55000, 56000, START + 100], [55000, 56000, START + 100], [episode])
    assert outcome(result) == (((START + 100, START + 100),), (), ())
    assert (result.reference_excluded, result.detections_excluded) == (2, 0)


def test_episode_across_the_start() -> None:
    episode = Episode(START - 1000, START + 1000)
    reference = [START - 500, START + 500, START + 2000]
    detections = [START - 500, START + 20, START + 500, START + 2000]
    result = match(reference, detections, episode_list := [episode])
    assert episode_list == [episode]
    # START + 20 is the first detection within the window after the start; the next one is
    # closer to the first scored beat (START + 2000), so it is dropped, not counted.
    assert outcome(result) == (((START + 2000, START + 2000),), (), ())
    assert (result.reference_excluded, result.detections_excluded) == (2, 1)


def test_episodes_given_as_a_tuple_or_a_list() -> None:
    episode = Episode(200000, 201000)
    assert match([200500], [200500], (episode,)) == match([200500], [200500], [episode])


# Input errors


@pytest.mark.parametrize("reference", [[200000, 199999], [1, 2, 3, 2], [START + 5, START]])
def test_decreasing_reference_samples_are_rejected(reference: list[int]) -> None:
    with pytest.raises(InvalidInputError, match="reference samples are not non-decreasing"):
        match(reference, [200000])


@pytest.mark.parametrize("detections", [[200000, 199999], [200000, 200000], [1, 2, 3, 3, 4]])
def test_detection_samples_that_do_not_strictly_increase_are_rejected(
    detections: list[int],
) -> None:
    with pytest.raises(InvalidInputError, match="detection samples are not strictly increasing"):
        match([200000], detections)


def test_order_error_names_the_index_and_the_values() -> None:
    with pytest.raises(InvalidInputError) as caught:
        match([200000], [10, 20, 15, 30])
    assert str(caught.value) == (
        "detection samples are not strictly increasing: 15 at index 2 follows 20"
    )


@pytest.mark.parametrize("value", [-1, -54, -(10**9)])
def test_negative_window_is_rejected(value: int) -> None:
    with pytest.raises(InvalidInputError, match="window_samples is negative"):
        match([200000], [200000], window=value)


@pytest.mark.parametrize("value", [-1, -108000])
def test_negative_start_is_rejected(value: int) -> None:
    with pytest.raises(InvalidInputError, match="start_sample is negative"):
        match([200000], [200000], start=value)


@pytest.mark.parametrize("value", [54.0, 53.5, "54", None, True])
def test_window_and_start_that_are_not_integers_are_rejected(value: object) -> None:
    with pytest.raises(InvalidInputError, match="window_samples is not an integer"):
        match([200000], [200000], window=value)  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError, match="start_sample is not an integer"):
        match([200000], [200000], start=value)  # type: ignore[arg-type]


def test_window_and_start_given_as_numpy_integers() -> None:
    result = match(
        [200000],
        [200054],
        window=np.int64(54),  # type: ignore[arg-type]
        start=np.int32(108000),  # type: ignore[arg-type]
    )
    assert result.matched == ((200000, 200054),)


@pytest.mark.parametrize(
    "samples",
    [
        [200000.0, 200100.0],
        np.array([200000.5]),
        np.array([True, False]),
        ["a", "b"],
        [[200000, 200100]],
        np.array(200000),
        [[1, 2], [3]],
        [None],
    ],
)
def test_lists_that_are_not_one_dimensional_integers_are_rejected(samples: object) -> None:
    with pytest.raises(InvalidInputError, match="reference samples"):
        match(samples, [200000])  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError, match="detection samples"):
        match([200000], samples)  # type: ignore[arg-type]


def test_values_that_could_meet_the_sentinel_are_rejected() -> None:
    with pytest.raises(InvalidInputError, match=r"reference samples are not below 2\*\*61"):
        match([200000, 2**61], [200000])
    with pytest.raises(InvalidInputError, match=r"detection samples are not below 2\*\*61"):
        match([200000], [200000, 2**62])
    with pytest.raises(InvalidInputError, match=r"window_samples is not below 2\*\*61"):
        match([200000], [200000], window=2**61)
    with pytest.raises(InvalidInputError, match=r"start_sample is not below 2\*\*61"):
        match([200000], [200000], start=2**62)


def test_input_error_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        match([2, 1], [])


# Comparison with a transcription of the procedure that uses explicit cursors


class _Cursor:
    """A list ended by the sentinel, with its current and next elements."""

    def __init__(self, values: Sequence[int]) -> None:
        self._values = [*values, HUGE]
        self._index = 0

    @property
    def current(self) -> int:
        return self._values[min(self._index, len(self._values) - 1)]

    @property
    def following(self) -> int:
        return self._values[min(self._index + 1, len(self._values) - 1)]

    def advance(self) -> None:
        self._index += 1


def _transcription(
    reference: Sequence[int],
    detections: Sequence[int],
    window: int,
    start: int,
    vf: Sequence[Episode],
) -> tuple[list[tuple[int, int]], list[int], list[int], int, int]:
    def inside(sample: int) -> bool:
        return any(e.start_sample <= sample <= e.end_sample for e in vf)

    scored = [sample for sample in reference if not inside(sample)]
    excluded = len(reference) - len(scored)
    ref = _Cursor(scored)
    while ref.current < start:
        ref.advance()
    before = [sample for sample in detections if sample < start]
    det = _Cursor([*before[-1:], *(sample for sample in detections if sample >= start)])
    pairs: list[tuple[int, int]] = []
    misses: list[int] = []
    extras: list[int] = []
    not_counted = 0

    if (
        before
        and ref.current - det.current <= window
        and ref.current - det.current < abs(ref.current - det.following)
    ):
        pairs.append((ref.current, det.current))
        ref.advance()
        det.advance()
    else:
        if before:
            det.advance()
        if det.current - start <= window and abs(ref.current - det.following) < abs(
            ref.current - det.current
        ):
            det.advance()

    while ref.current != HUGE or det.current != HUGE:
        big_t, big_t2, t, t2 = ref.current, ref.following, det.current, det.following
        if t < big_t:
            if big_t - t <= window and (
                big_t - t < abs(big_t - t2) or abs(big_t2 - t2) < abs(big_t - t2)
            ):
                pairs.append((big_t, t))
                ref.advance()
            elif inside(t):
                not_counted += 1
            else:
                extras.append(t)
            det.advance()
        else:
            if t - big_t <= window and (
                t - big_t < abs(t - big_t2) or abs(t2 - big_t2) < abs(t - big_t2)
            ):
                pairs.append((big_t, t))
                det.advance()
            else:
                misses.append(big_t)
            ref.advance()
    return pairs, misses, extras, excluded, not_counted


def _random_case(
    rng: random.Random,
) -> tuple[list[int], list[int], int, int, list[Episode]]:
    window = rng.choice([0, 1, 5, 20, 54])
    start = rng.choice([0, 300, 1000])
    span = 3000
    reference = sorted(rng.choices(range(span), k=rng.randint(0, 40)))
    detections = sorted(rng.sample(range(span), k=rng.randint(0, 40)))
    if rng.random() < 0.5:
        # Detections close to the beats, as a detector gives them.
        near = {max(0, beat + rng.randint(-60, 60)) for beat in reference}
        detections = sorted(near)
    episodes = []
    for _ in range(rng.randint(0, 3)):
        onset = rng.randrange(span)
        episodes.append(Episode(onset, onset + rng.randint(0, 400)))
    return reference, detections, window, start, episodes


def test_random_cases_agree_with_the_transcription_and_keep_the_invariants() -> None:
    rng = random.Random(20260930)
    for _ in range(3000):
        reference, detections, window, start, episodes = _random_case(rng)
        result = match_beats(
            reference, detections, window_samples=window, start_sample=start, vf=episodes
        )
        expected = _transcription(reference, detections, window, start, episodes)
        assert (
            list(result.matched),
            list(result.false_negatives),
            list(result.false_positives),
            result.reference_excluded,
            result.detections_excluded,
        ) == expected

        def inside(sample: int, episodes: Sequence[Episode] = episodes) -> bool:
            return any(e.start_sample <= sample <= e.end_sample for e in episodes)

        # Counts.
        assert (result.tp, result.fn, result.fp) == (
            len(result.matched),
            len(result.false_negatives),
            len(result.false_positives),
        )
        # Every pair is within the window and in time order, each item used once.
        assert all(abs(beat - d) <= window for beat, d in result.matched)
        paired_detections = [d for _, d in result.matched]
        assert paired_detections == sorted(set(paired_detections))
        assert [beat for beat, _ in result.matched] == sorted(beat for beat, _ in result.matched)
        # Every scored reference beat is a true positive or a false negative, once.
        scored = sorted(beat for beat in reference if beat >= start and not inside(beat))
        assert sorted([beat for beat, _ in result.matched] + list(result.false_negatives)) == scored
        assert result.reference_excluded == sum(1 for beat in reference if inside(beat))
        # A detection is in at most one list; none before the start is a false positive.
        assert not set(paired_detections) & set(result.false_positives)
        assert all(d >= start and not inside(d) for d in result.false_positives)
        assert set(paired_detections) | set(result.false_positives) <= set(detections)
        # At most one detection before the start is paired, and it is the last one.
        early = [d for d in paired_detections if d < start]
        assert early in ([], [max(d for d in detections if d < start)] if early else [])
        # At most one detection at or after the start is neither paired, nor a false
        # positive, nor inside an episode: the one dropped at the start.
        accounted = set(paired_detections) | set(result.false_positives)
        dropped = [d for d in detections if d >= start and d not in accounted and not inside(d)]
        assert len(dropped) <= 1
        assert all(d - start <= window for d in dropped)
