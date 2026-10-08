"""Unit tests of the heart rate module: estimator, range bounds, tracking, input checks."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from sinus_dsp import heart_rate as hr
from sinus_dsp import pipeline
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.heart_rate import HeartRateEvent, IntervalEstimate

FS = 360.0


def _rhythm(bpm: float, count: int, fs_hz: float = FS, start: int = 0) -> list[int]:
    """Positions of a regular rhythm, each rounded to the sample."""
    return [start + math.floor(i * 60.0 * fs_hz / bpm + 0.5) for i in range(count)]


def _track(
    indices: list[int],
    fs_hz: float = FS,
    n_samples: int | None = None,
    startup: list[bool] | None = None,
    reported_at: list[int] | None = None,
) -> tuple[HeartRateEvent, ...]:
    n = n_samples if n_samples is not None else max([*indices, *(reported_at or [])]) + 1
    marks = startup if startup is not None else [False] * len(indices)
    return hr.track_heart_rate(indices, marks, fs_hz, n, reported_at=reported_at)


def _at_beats(events: tuple[HeartRateEvent, ...]) -> list[HeartRateEvent]:
    return [e for e in events if e.beat_index is not None]


def _valid(events: tuple[HeartRateEvent, ...]) -> list[HeartRateEvent]:
    return [e for e in events if e.status == hr.STATUS_VALID]


def test_constants_and_statuses() -> None:
    assert hr.HEART_RATE_STATUSES == ("valid", "not_enough_beats", "no_recent_beat", "out_of_range")
    assert (hr.MIN_INTERVALS, hr.ROBUST_WINDOW, hr.MEAN_WINDOW) == (4, 5, 6)
    assert (hr.INLIER_LOW_PERCENT, hr.INLIER_HIGH_PERCENT) == (92, 116)
    assert (hr.MIN_INTERVAL_MS, hr.MAX_INTERVAL_MS, hr.NO_RECENT_BEAT_MS) == (300, 2000, 3000)


@pytest.mark.parametrize(("fs", "expected"), [(360.0, 1080), (250.0, 750), (125.0, 375)])
def test_no_recent_beat_samples(fs: float, expected: int) -> None:
    assert hr.no_recent_beat_samples(fs) == expected


def test_no_recent_beat_samples_rounds_up_and_checks_fs() -> None:
    assert hr.no_recent_beat_samples(256.3) == math.ceil(3 * 256.3)
    assert hr.no_recent_beat_samples(333.0) == 999
    with pytest.raises(InvalidInputError):
        hr.no_recent_beat_samples(100.0)


# estimate_intervals -------------------------------------------------------------------------


def _est(intervals: list[int]) -> tuple[int, int, str]:
    e = hr.estimate_intervals(intervals)
    return e.n_intervals, e.span_samples, e.method


@pytest.mark.parametrize(
    ("intervals", "expected"),
    [
        ([100, 100, 100, 100], (4, 400, "robust")),
        ([100, 101, 100, 99, 100], (5, 500, "robust")),
        # a missed detection: one interval about twice as long, at any place of the window
        ([200, 100, 100, 100, 100], (4, 400, "robust")),
        ([100, 100, 200, 100, 100], (4, 400, "robust")),
        ([100, 100, 100, 100, 200], (4, 400, "robust")),
        ([100, 100, 100, 200], (3, 300, "robust")),
        # an added detection: two adjacent short intervals, in the middle or at either end
        ([100, 50, 50, 100, 100], (3, 300, "robust")),
        ([50, 50, 100, 100, 100], (3, 300, "robust")),
        ([100, 100, 100, 50, 50], (3, 300, "robust")),
        # a premature beat with its compensatory pause
        ([100, 100, 60, 140, 100], (3, 300, "robust")),
        # two outliers that are not adjacent, three outliers: the mean of the intervals given
        ([50, 100, 100, 100, 200], (5, 550, "mean")),
        ([50, 100, 50, 100, 100], (5, 400, "mean")),
        ([60, 90, 60, 90, 60, 90], (6, 450, "mean")),
        ([100, 50, 100, 50, 100], (5, 400, "mean")),
        ([100, 60, 60, 60, 100], (5, 380, "mean")),
    ],
)
def test_estimate_intervals_patterns(intervals: list[int], expected: tuple[int, int, str]) -> None:
    assert _est(intervals) == expected


def test_the_window_of_the_robust_estimate_is_the_last_five() -> None:
    # the sixth (oldest) interval is outside the window of the robust estimate...
    assert _est([500, 100, 100, 100, 100, 100]) == (5, 500, "robust")
    # ... and inside the mean
    assert _est([500, 50, 100, 50, 100, 100]) == (6, 900, "mean")


def test_inlier_limits_are_92_and_116_percent_of_the_middle_interval() -> None:
    # middle = 100: 92 and 116 are inliers, 91 and 117 are outliers
    assert _est([92, 100, 100, 100, 116]) == (5, 508, "robust")
    assert _est([91, 100, 100, 100, 100]) == (4, 400, "robust")
    assert _est([100, 100, 100, 100, 117]) == (4, 400, "robust")
    # two outliers at the two ends are not adjacent
    assert _est([91, 100, 100, 100, 117]) == (5, 508, "mean")


def test_the_middle_of_four_is_the_upper_middle() -> None:
    # sorted [100, 100, 110, 120]: the third smallest is 110, so the two 100s (below 101.2) are
    # adjacent outliers and 120 (at most 127.6) is an inlier; with 100 as the middle it would be
    # (3, 310)
    assert _est([100, 100, 110, 120]) == (2, 230, "robust")


@pytest.mark.parametrize("bad", [[], [1, 2, 3], [1] * 7, [1, 2, 3, 0], [1, 2, 3, -4]])
def test_estimate_intervals_rejects_a_bad_count_or_value(bad: list[int]) -> None:
    with pytest.raises(InvalidInputError):
        hr.estimate_intervals(bad)


@pytest.mark.parametrize("bad", [1.5, True, "3", None])
def test_estimate_intervals_rejects_a_non_integer(bad: Any) -> None:
    with pytest.raises(InvalidInputError):
        hr.estimate_intervals([100, 100, 100, bad])


def test_estimate_intervals_accepts_numpy_integers_and_rejects_non_sequences() -> None:
    assert _est(list(np.array([100, 100, 100, 100], dtype=np.int32))) == (4, 400, "robust")
    with pytest.raises(InvalidInputError):
        hr.estimate_intervals(5)  # type: ignore[arg-type]


# range and rate -----------------------------------------------------------------------------


def test_rate_formula() -> None:
    e = IntervalEstimate(4, 1440, hr.METHOD_ROBUST)
    assert hr.interval_rate_bpm(e, 360.0) == 60.0 * 360.0 * 4 / 1440 == 60.0
    assert hr.interval_rate_bpm(IntervalEstimate(1, 3, "robust"), 250.0) == 5000.0


@pytest.mark.parametrize("fs", [125.0, 250.0, 360.0, 1000.0, 257.0, 333.0])
@pytest.mark.parametrize("k", [1, 3, 4, 5, 6])
def test_range_bounds_are_exact_for_every_k(fs: float, k: int) -> None:
    f = int(fs)
    low = -(-300 * k * f // 1000)  # ceil
    high = 2000 * k * f // 1000  # floor
    method = hr.METHOD_ROBUST
    assert hr.interval_in_range(IntervalEstimate(k, low, method), fs)
    assert not hr.interval_in_range(IntervalEstimate(k, low - 1, method), fs)
    assert hr.interval_in_range(IntervalEstimate(k, high, method), fs)
    assert not hr.interval_in_range(IntervalEstimate(k, high + 1, method), fs)


def test_range_at_125_hz_bound_cases() -> None:
    # 300 ms = 37.5 samples: 4 intervals need 150 samples, not 149
    assert hr.interval_in_range(IntervalEstimate(4, 150, "robust"), 125.0)
    assert not hr.interval_in_range(IntervalEstimate(4, 149, "robust"), 125.0)
    # one interval: 300 ms = 37.5 samples, so 38 is in range and 37 is not
    assert hr.interval_in_range(IntervalEstimate(1, 38, "robust"), 125.0)
    assert not hr.interval_in_range(IntervalEstimate(1, 37, "robust"), 125.0)


def test_rate_and_range_check_fs() -> None:
    e = IntervalEstimate(4, 1440, "robust")
    for fn in (hr.interval_rate_bpm, hr.interval_in_range):
        with pytest.raises(InvalidInputError):
            fn(e, 124.0)


# regular rhythms ----------------------------------------------------------------------------


@pytest.mark.parametrize("fs", [250.0, 360.0])
@pytest.mark.parametrize("bpm", [30.0, 40.0, 75.0, 180.0, 200.0])
def test_regular_rhythm_first_valid_rate_at_the_fourth_interval(bpm: float, fs: float) -> None:
    indices = _rhythm(bpm, 14, fs)
    events = _track(indices, fs)
    at_beats = _at_beats(events)
    assert [e.beat_index for e in at_beats] == indices
    assert [e.status for e in at_beats[:4]] == [hr.STATUS_NOT_ENOUGH_BEATS] * 4
    assert all(e.bpm is None for e in at_beats[:4])
    assert all(e.status == hr.STATUS_VALID for e in at_beats[4:])
    assert all(e.bpm is not None and abs(e.bpm - bpm) <= 2.0 for e in at_beats[4:])
    assert [e.sample for e in at_beats] == indices


def test_no_event_at_sample_zero_unless_a_reliable_detection_is_reported_there() -> None:
    assert _track([100, 460], n_samples=2000)[0].sample == 100
    assert _track([0, 360], n_samples=2000)[0] == HeartRateEvent(
        0, 0, hr.STATUS_NOT_ENOUGH_BEATS, None
    )


def test_empty_stream_gives_no_event() -> None:
    assert hr.track_heart_rate([], [], FS, 5000) == ()


@pytest.mark.parametrize(
    ("first", "second"), [(40.0, 180.0), (180.0, 40.0), (75.0, 120.0), (120.0, 75.0)]
)
@pytest.mark.parametrize("fs", [250.0, 360.0])
def test_a_change_of_rhythm_is_followed_from_the_fifth_interval(
    first: float, second: float, fs: float
) -> None:
    a = _rhythm(first, 12, fs)
    b = _rhythm(second, 14, fs, start=a[-1])[1:]
    indices = a + b
    events = _at_beats(_track(indices, fs))
    # the fifth interval of the new rhythm ends at the fifth detection after a[-1]
    from_fifth = [e for e in events if e.beat_index is not None and e.beat_index >= b[4]]
    assert from_fifth
    assert all(e.status == hr.STATUS_VALID for e in from_fifth)
    assert all(e.bpm is not None and abs(e.bpm - second) <= 2.0 for e in from_fifth)


@pytest.mark.parametrize("fs", [250.0, 360.0])
@pytest.mark.parametrize("bpm", [30.0, 40.0, 75.0, 180.0, 200.0])
def test_one_missed_detection(bpm: float, fs: float) -> None:
    indices = _rhythm(bpm, 20, fs)
    for missing in range(6, 18):
        kept = indices[:missing] + indices[missing + 1 :]
        for e in _valid(_track(kept, fs)):
            assert e.bpm is not None and abs(e.bpm - bpm) <= 5.0, (missing, e)


@pytest.mark.parametrize("fs", [250.0, 360.0])
@pytest.mark.parametrize("bpm", [30.0, 40.0, 75.0, 150.0])
def test_one_added_detection(bpm: float, fs: float) -> None:
    indices = _rhythm(bpm, 20, fs)
    for k in range(6, 17):
        gap = indices[k + 1] - indices[k]
        for offset in (gap // 2, int(0.2 * fs)):
            extra = sorted([*indices, indices[k] + offset])
            for e in _valid(_track(extra, fs)):
                assert e.bpm is not None and abs(e.bpm - bpm) <= 5.0, (k, offset, e)


# range statuses -----------------------------------------------------------------------------


@pytest.mark.parametrize(("bpm", "status"), [(29.0, "out_of_range"), (201.0, "out_of_range")])
@pytest.mark.parametrize("fs", [250.0, 360.0])
def test_rates_outside_the_range(bpm: float, status: str, fs: float) -> None:
    events = _at_beats(_track(_rhythm(bpm, 12, fs), fs))
    assert [e.status for e in events[4:]] == [status] * 8
    assert all(e.bpm is not None for e in events[4:])
    assert all(abs(e.bpm - bpm) < 2.0 for e in events[4:] if e.bpm is not None)


@pytest.mark.parametrize("bpm", [30.0, 200.0])
def test_rates_on_the_bounds_are_valid(bpm: float) -> None:
    events = _at_beats(_track(_rhythm(bpm, 12)))
    assert [e.status for e in events[4:]] == ["valid"] * 8


def test_exact_interval_bounds_at_360_hz() -> None:
    # 300 ms = 108 samples, 2000 ms = 720 samples
    assert {e.status for e in _at_beats(_track(list(range(0, 108 * 10, 108))))[4:]} == {"valid"}
    assert {e.status for e in _at_beats(_track(list(range(0, 107 * 10, 107))))[4:]} == {
        "out_of_range"
    }
    assert {e.status for e in _at_beats(_track(list(range(0, 720 * 8, 720))))[4:]} == {"valid"}
    assert {e.status for e in _at_beats(_track(list(range(0, 721 * 8, 721))))[4:]} == {
        "out_of_range"
    }


def test_out_of_range_event_carries_the_rate() -> None:
    e = _at_beats(_track(list(range(0, 100 * 8, 100))))[-1]
    assert e.status == "out_of_range" and e.bpm == 60.0 * FS / 100


# start-up detections ------------------------------------------------------------------------


def test_startup_detections_give_no_event_and_no_interval() -> None:
    reliable = _rhythm(75, 12, start=1000)
    lead = [100, 460, 820]
    n = reliable[-1] + 1 + 3600
    both = _track(lead + reliable, n_samples=n, startup=[True] * 3 + [False] * 12)
    assert both == _track(reliable, n_samples=n)


def test_no_interval_spans_a_startup_detection() -> None:
    # reliable, start-up, reliable: the interval across the start-up detection is not used
    events = _track(
        [0, 360, 500, 720, 1080, 1440, 1800], startup=[False, False, True] + [False] * 4
    )
    assert [e.beat_index for e in _at_beats(events)] == [0, 360, 720, 1080, 1440, 1800]
    # intervals: 360 (0-360), none for 720, then 360, 360, 360: four at 1800
    assert [e.status for e in _at_beats(events)] == ["not_enough_beats"] * 5 + ["valid"]


def test_startup_detections_do_not_keep_no_recent_beat_from_firing() -> None:
    events = _track([0, 360, 720, 1000, 1100], n_samples=3000, startup=[False] * 3 + [True] * 2)
    wait = hr.no_recent_beat_samples(FS)
    fired = [e for e in events if e.status == "no_recent_beat"]
    assert [e.sample for e in fired] == [720 + wait]


# no recent beat -----------------------------------------------------------------------------


@pytest.mark.parametrize("fs", [250.0, 360.0])
@pytest.mark.parametrize("bpm", [30.0, 75.0])
def test_no_recent_beat_after_a_gap_and_recovery(bpm: float, fs: float) -> None:
    wait = hr.no_recent_beat_samples(fs)
    first = _rhythm(bpm, 8, fs)
    gap = wait + 200
    second = _rhythm(bpm, 10, fs, start=first[-1] + gap)
    events = _track(first + second, fs)
    fired = [e for e in events if e.beat_index is None]
    assert fired == [HeartRateEvent(first[-1] + wait, None, "no_recent_beat", None)]
    after = [e for e in _at_beats(events) if e.beat_index is not None and e.beat_index >= second[0]]
    assert [e.status for e in after[:5]] == ["no_recent_beat"] * 4 + ["valid"]
    assert all(e.bpm is None for e in after[:4])
    assert after[4].beat_index == second[4]
    assert after[4].bpm is not None and abs(after[4].bpm - bpm) <= 2.0


def test_gap_just_under_and_at_the_limit() -> None:
    wait = hr.no_recent_beat_samples(FS)
    first = _rhythm(75, 8)
    under = _track(first + [first[-1] + wait - 1, first[-1] + wait - 1 + 288])
    assert [e for e in under if e.status == "no_recent_beat"] == []
    # the detection at exactly 3 s: "no recent beat" has started at that sample (the detection
    # updates `last` first, so it does not)
    at = _track([*first, first[-1] + wait])
    assert [e for e in at if e.status == "no_recent_beat"] == []
    just_after = _track([*first, first[-1] + wait + 1])
    assert [e.sample for e in just_after if e.beat_index is None] == [first[-1] + wait]


def test_no_recent_beat_after_the_second_detection_while_not_enough_beats() -> None:
    wait = hr.no_recent_beat_samples(FS)
    events = _track([0, 360, 360 + wait + 500])
    assert events[0].status == "not_enough_beats"
    assert events[1] == HeartRateEvent(360, 360, "not_enough_beats", None)
    assert events[2] == HeartRateEvent(360 + wait, None, "no_recent_beat", None)
    assert events[3] == HeartRateEvent(360 + wait + 500, 360 + wait + 500, "no_recent_beat", None)


def test_no_recent_beat_at_the_end_of_the_stream_only_if_the_sample_exists() -> None:
    wait = hr.no_recent_beat_samples(FS)
    assert [e.status for e in _track([0, 360], n_samples=360 + wait + 1)][-1] == "no_recent_beat"
    assert [e.status for e in _track([0, 360], n_samples=360 + wait)][-1] == "not_enough_beats"


def test_a_second_gap_moves_the_reset_without_an_event() -> None:
    wait = hr.no_recent_beat_samples(FS)
    first = _rhythm(75, 8)
    a = first[-1] + wait + 400
    second = [a, a + 360]  # fewer than four new intervals
    b = second[-1] + wait + 400
    events = _track([*first, *second, b, b + 360, b + 720, b + 1080, b + 1440, b + 1800])
    assert [e.sample for e in events if e.beat_index is None] == [first[-1] + wait]
    assert [e.sample for e in events if e.status == "valid" and e.sample > a] == [
        b + 1440,
        b + 1800,
    ]


def test_a_detection_with_an_earlier_index_reported_later_does_not_count() -> None:
    wait = hr.no_recent_beat_samples(FS)
    base = _rhythm(75, 6)
    reset = base[-1] + wait
    late = reset - 100  # index before the reset, reported after it
    indices = [*base, late, late + 500, late + 860, late + 1220, late + 1580, late + 1940]
    reported = [*base, reset + 50, late + 500, late + 860, late + 1220, late + 1580, late + 1940]
    events = _track(indices, reported_at=reported)
    at_beats = {e.beat_index: e for e in _at_beats(events)}
    assert [e.sample for e in events if e.beat_index is None] == [reset]
    # no interval to `late`; intervals: 360, 360, 360, 360 end at late + 1940
    assert at_beats[late].status == "no_recent_beat"
    assert at_beats[late + 1580].status == "no_recent_beat"
    assert at_beats[late + 1940].status == "valid"


def test_report_delay_makes_a_stretch_shorter_than_three_seconds_withheld() -> None:
    wait = hr.no_recent_beat_samples(FS)
    first = _rhythm(75, 8)
    nxt = first[-1] + wait - 30  # the next detection, 30 samples under 3 s after the last
    events = _track([*first, nxt], reported_at=[*first, nxt + 60])
    assert [e.sample for e in events if e.beat_index is None] == [first[-1] + wait]
    assert events[-1] == HeartRateEvent(nxt + 60, nxt, "no_recent_beat", None)


def test_detections_reported_at_the_same_sample_are_processed_in_order() -> None:
    events = _track([0, 360, 720], reported_at=[0, 800, 800], n_samples=1500)
    assert [(e.sample, e.beat_index) for e in events] == [(0, 0), (800, 360), (800, 720)]


def test_events_are_in_order_of_sample() -> None:
    wait = hr.no_recent_beat_samples(FS)
    first = _rhythm(75, 8)
    second = _rhythm(75, 8, start=first[-1] + wait + 300)
    samples = [e.sample for e in _track(first + second)]
    assert samples == sorted(samples)


# input checks -------------------------------------------------------------------------------


def _call(**changes: Any) -> Any:
    args: dict[str, Any] = {
        "indices": [10, 400, 800],
        "startup": [False, False, False],
        "fs_hz": 360.0,
        "n_samples": 1500,
    }
    args.update(changes)
    return hr.track_heart_rate(**args)


def test_the_basic_call_is_valid() -> None:
    assert len(_call()) == 3
    assert len(_call(reported_at=[10, 400, 800])) == 3
    assert len(_call(indices=np.array([10, 400, 800], dtype=np.uint16))) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"fs_hz": 124.9},
        {"fs_hz": float("nan")},
        {"fs_hz": True},
        {"n_samples": 0},
        {"n_samples": True},
        {"n_samples": 2000.0},
        {"n_samples": 400},
        {"indices": [10, 400, 400]},
        {"indices": [400, 10, 800]},
        {"indices": [-1, 400, 800]},
        {"indices": [10, 400, 2000]},
        {"indices": [10.0, 400.0, 800.0]},
        {"indices": [[10, 400, 800]]},
        {"startup": [False, False]},
        {"startup": [0, 0, 0]},
        {"startup": [[False, False, False]]},
        {"reported_at": [10, 400]},
        {"reported_at": [10, 800, 400]},
        {"reported_at": [10, 399, 800]},
        {"reported_at": [10, 400, 2000]},
        {"reported_at": [10.0, 400.0, 800.0]},
    ],
)
def test_input_checks(changes: dict[str, Any]) -> None:
    with pytest.raises(InvalidInputError):
        _call(**changes)


# pipeline -----------------------------------------------------------------------------------


@pytest.mark.parametrize("fs", [250.0, 360.0])
def test_the_pipeline_result_holds_the_heart_rate_of_its_detections(
    fs: float, synthetic_ecg: Any
) -> None:
    x, _ = synthetic_ecg(fs, 75, "bw-mains50")
    result = pipeline.run_pipeline(x, fs, 50)
    d = result.detections
    assert isinstance(result.heart_rate, tuple)
    assert result.heart_rate == hr.track_heart_rate(
        d.indices, d.startup, fs, x.size, reported_at=d.reported_at
    )
    valid = _valid(result.heart_rate)
    assert valid
    assert all(e.bpm is not None and abs(e.bpm - 75.0) <= 2.0 for e in valid)
    reliable = {int(i) for i, s in zip(d.indices, d.startup, strict=True) if not s}
    assert {e.beat_index for e in result.heart_rate if e.beat_index is not None} == reliable
