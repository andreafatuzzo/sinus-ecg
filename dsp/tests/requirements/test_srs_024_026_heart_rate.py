"""Requirement tests of SRS-024, SRS-025 and SRS-026, reference part (software item `dsp`).

SRS-024: heart rate from detections marked reliable (within 2 bpm on a regular rhythm of 30 to
200 bpm, and from the fifth interval after a change of rhythm; start-up detections left out).
SRS-025: within 5 bpm with one missed or one added detection. SRS-026: withheld heart rate
("not enough beats", "no recent beat", "out of range").

The documented interface is architecture section 13.5: `heart_rate.track_heart_rate(indices,
startup, fs_hz, n_samples, *, reported_at=None)` returns `HeartRateEvent(sample, beat_index,
status, bpm)` ordered by sample. The sequences of detections are built here from the numbers of
the SRS, positions rounded to the sample; each detection is reported at its own index. The C++
part of the requirements is verified by the requirement tests of `libs/sinus-dsp`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from fractions import Fraction
from typing import Any

import numpy as np
import pytest

from sinus_dsp.heart_rate import HeartRateEvent, track_heart_rate
from sinus_dsp.pipeline import detect_marked, run_pipeline

FS_HZ = [360, 250]
REGULAR_RATES_BPM = [30, 40, 75, 180, 200]
START = 100

VALID = "valid"
NOT_ENOUGH = "not_enough_beats"
NO_RECENT = "no_recent_beat"
OUT_OF_RANGE = "out_of_range"


def rhythm(rate_bpm: float, fs_hz: int, count: int, start: int = START) -> list[int]:
    """`count` detections of a regular rhythm from `start`, positions rounded to the sample."""
    period = Fraction(60 * fs_hz) / Fraction(rate_bpm).limit_denominator(1000)
    return [start + math.floor(k * period + Fraction(1, 2)) for k in range(count)]


def three_s(fs_hz: int) -> int:
    """3 s in samples, the bound kept exact: ceil(3 * fs)."""
    return math.ceil(3 * fs_hz)


def track(
    indices: Sequence[int],
    fs_hz: int,
    *,
    startup: Sequence[bool] | None = None,
    tail: int = 1,
) -> tuple[HeartRateEvent, ...]:
    """Run the tracker; the stream ends `tail` samples after the last detection (1: at it)."""
    idx = np.asarray(indices, dtype=np.int64)
    marks = np.zeros(idx.size, dtype=bool) if startup is None else np.asarray(startup, dtype=bool)
    n_samples = int(idx[-1]) + tail
    return track_heart_rate(idx, marks, float(fs_hz), n_samples)


def valid_rates(events: Sequence[HeartRateEvent]) -> list[float]:
    out: list[float] = []
    for e in events:
        if e.status == VALID:
            assert e.bpm is not None
            out.append(e.bpm)
    return out


def at_detections(events: Sequence[HeartRateEvent]) -> list[HeartRateEvent]:
    return [e for e in events if e.beat_index is not None]


# --------------------------------------------------------------------------- SRS-024


@pytest.mark.requirement("SRS-024")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", REGULAR_RATES_BPM)
def test_regular_rhythm_valid_rates_within_2_bpm(fs_hz: int, rate: int) -> None:
    """SRS-024: a regular rhythm at 30, 40, 75, 180, 200 bpm (rounded to the sample, 360 and
    250 Hz), 40 detections: every valid heart rate within 2 bpm of the true rate, and valid
    heart rates exist."""
    idx = rhythm(rate, fs_hz, 40)
    rates = valid_rates(track(idx, fs_hz))
    assert rates, "no valid heart rate"
    assert all(abs(r - rate) <= 2.0 for r in rates), (min(rates), max(rates))


@pytest.mark.requirement("SRS-024")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 31, 45, 60, 100, 120, 150, 190, 199, 200])
def test_regular_rhythm_in_range_always_valid(fs_hz: int, rate: int) -> None:
    """SRS-024: between 30 and 200 bpm, bounds included, a regular rhythm gives a valid heart
    rate at every detection from the fifth, each within 2 bpm of the true rate."""
    idx = rhythm(rate, fs_hz, 30)
    events = at_detections(track(idx, fs_hz))
    assert len(events) == len(idx)
    for e in events[4:]:
        assert e.status == VALID, e
        assert e.bpm is not None and abs(e.bpm - rate) <= 2.0, e


@pytest.mark.requirement("SRS-024")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_one_event_per_reliable_detection_at_its_sample(fs_hz: int) -> None:
    """SRS-024: a heart rate (or its withholding) is reported at each reliable detection: one
    event per detection, at its sample (each reported at its index), beat_index = its index,
    events ordered by sample; `bpm` is None for withheld events."""
    idx = rhythm(75, fs_hz, 20)
    events = track(idx, fs_hz)
    assert [e.beat_index for e in events] == idx
    assert [e.sample for e in events] == idx
    assert all(a.sample <= b.sample for a, b in zip(events, events[1:], strict=False))
    for e in events:
        assert (e.bpm is not None) == (e.status in (VALID, OUT_OF_RANGE))


CHANGES = [(40, 180), (180, 40), (75, 120), (120, 75)]


def change_sequence(old: int, new: int, fs_hz: int) -> tuple[list[int], int]:
    """12 detections of `old`, then `new` from the last one: the first interval of the new
    rhythm ends at the first detection after the change. Returns the indices and the position
    in the list of that first new detection."""
    first = rhythm(old, fs_hz, 12)
    second = rhythm(new, fs_hz, 16, start=first[-1])[1:]
    return first + second, len(first)


@pytest.mark.requirement("SRS-024")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize(("old", "new"), CHANGES)
def test_valid_rates_follow_a_change_of_rhythm(fs_hz: int, old: int, new: int) -> None:
    """SRS-024: 40->180, 180->40, 75->120, 120->75 bpm: every valid heart rate from the fifth
    interval of the new rhythm onwards is within 2 bpm of the new rate; the last one is
    valid. Before the change the old rate holds."""
    idx, first_new = change_sequence(old, new, fs_hz)
    events = at_detections(track(idx, fs_hz))
    assert len(events) == len(idx)
    fifth = first_new + 4  # the fifth interval of the new rhythm ends at its fifth detection
    for e in events[4:first_new]:
        assert e.status == VALID and e.bpm is not None and abs(e.bpm - old) <= 2.0, e
    for e in events[fifth:]:
        if e.status == VALID:
            assert e.bpm is not None and abs(e.bpm - new) <= 2.0, e
    assert events[-1].status == VALID


@pytest.mark.requirement("SRS-024")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize(("old", "new"), CHANGES)
def test_change_of_rhythm_is_valid_from_the_fifth_interval(fs_hz: int, old: int, new: int) -> None:
    """SRS-024: the heart rate follows the change instead of withholding it: from the fifth
    interval of the new rhythm the status is valid at every detection."""
    idx, first_new = change_sequence(old, new, fs_hz)
    events = at_detections(track(idx, fs_hz))
    for e in events[first_new + 4 :]:
        assert e.status == VALID, e


@pytest.mark.requirement("SRS-024")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [40, 75, 180])
@pytest.mark.parametrize("n_startup", [1, 2, 5])
def test_startup_detections_are_left_out(fs_hz: int, rate: int, n_startup: int) -> None:
    """SRS-024: detections marked start-up (irregular positions, at the beginning) give the
    same heart rates as the sequence of the reliable detections alone: same events (sample,
    beat_index, status, bpm)."""
    reliable = rhythm(rate, fs_hz, 20, start=START + 700)
    startup_idx = [START + 13 * (k + 1) ** 2 + 30 * k for k in range(n_startup)]
    assert startup_idx[-1] < reliable[0]
    full = startup_idx + reliable
    marks = [True] * n_startup + [False] * len(reliable)
    with_startup = track(full, fs_hz, startup=marks)
    alone = track(reliable, fs_hz)
    assert with_startup == alone
    assert all(e.beat_index not in startup_idx for e in with_startup)


@pytest.mark.requirement("SRS-024")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_no_interval_spans_a_startup_detection(fs_hz: int) -> None:
    """SRS-024: only intervals between two consecutive reliable detections count. A start-up
    detection at the beginning, 2 intervals long from the first reliable one, gives no
    interval: the first valid rate still comes with the fourth reliable interval."""
    reliable = rhythm(75, fs_hz, 12, start=START + 400)
    full = [START] + reliable
    events = at_detections(track(full, fs_hz, startup=[True] + [False] * 12))
    statuses = [e.status for e in events]
    assert statuses[:4] == [NOT_ENOUGH] * 4
    assert statuses[4] == VALID


@pytest.mark.requirement("SRS-024")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_only_startup_detections_give_no_event(fs_hz: int) -> None:
    """SRS-024/SRS-026: with only start-up detections (no reliable one), no event is reported
    (no heart rate at start-up detections, and no reliable detection to age)."""
    idx = rhythm(75, fs_hz, 4)
    events = track(idx, fs_hz, startup=[True] * 4, tail=10 * fs_hz)
    assert events == ()


# --------------------------------------------------------------------------- SRS-025


def removals(idx: list[int]) -> list[tuple[int, list[int]]]:
    """Every sequence with one detection removed after the first valid heart rate (position
    5 on) and before the last."""
    return [(j, idx[:j] + idx[j + 1 :]) for j in range(5, len(idx) - 1)]


@pytest.mark.requirement("SRS-025")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", REGULAR_RATES_BPM)
def test_missed_detection_within_5_bpm(fs_hz: int, rate: int) -> None:
    """SRS-025: a regular rhythm (30, 40, 75, 180, 200 bpm) with one detection missing, at each
    position after the first valid heart rate: every valid heart rate within 5 bpm of the true
    rate, and the heart rate is valid again at the end."""
    idx = rhythm(rate, fs_hz, 30)
    for j, seq in removals(idx):
        events = track(seq, fs_hz)
        rates = valid_rates(events)
        assert all(abs(r - rate) <= 5.0 for r in rates), (
            j,
            max(rates, key=lambda r: abs(r - rate)),
        )
        if rate == 30:
            # the missing detection leaves a stretch of 4 s: SRS-026 withholds as "no recent beat"
            assert any(e.status == NO_RECENT for e in events), j
        else:
            assert events[-1].status == VALID, j


@pytest.mark.requirement("SRS-025")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 75, 180, 200])
def test_missed_detection_early_within_5_bpm(fs_hz: int, rate: int) -> None:
    """SRS-025: the statement does not restrict the position: one detection missing at any
    position from the second on, every valid heart rate within 5 bpm of the true rate."""
    idx = rhythm(rate, fs_hz, 24)
    for j in range(1, 5):
        seq = idx[:j] + idx[j + 1 :]
        rates = valid_rates(track(seq, fs_hz))
        assert all(abs(r - rate) <= 5.0 for r in rates), (j, rates)


@pytest.mark.requirement("SRS-025")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 40, 75])
def test_extra_detection_in_the_middle_within_5_bpm(fs_hz: int, rate: int) -> None:
    """SRS-025: one detection added in the middle of an interval (rates whose interval is at
    least 400 ms), at each interval: every valid heart rate within 5 bpm of the true rate."""
    idx = rhythm(rate, fs_hz, 30)
    for j in range(len(idx) - 1):
        extra = (idx[j] + idx[j + 1]) // 2
        assert extra - idx[j] >= math.ceil(0.2 * fs_hz)
        seq = sorted(idx + [extra])
        events = track(seq, fs_hz)
        rates = valid_rates(events)
        assert all(abs(r - rate) <= 5.0 for r in rates), (j, rates)
        assert events[-1].status == VALID


@pytest.mark.requirement("SRS-025")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 40, 75])
def test_extra_detection_200_ms_after_a_detection_within_5_bpm(fs_hz: int, rate: int) -> None:
    """SRS-025: one detection added 200 ms (ceil(0.2*fs) samples) after a detection, at each
    interval: every valid heart rate within 5 bpm of the true rate."""
    idx = rhythm(rate, fs_hz, 30)
    gap = math.ceil(0.2 * fs_hz)
    for j in range(len(idx) - 1):
        seq = sorted(idx + [idx[j] + gap])
        events = track(seq, fs_hz)
        rates = valid_rates(events)
        assert all(abs(r - rate) <= 5.0 for r in rates), (j, rates)
        assert events[-1].status == VALID


@pytest.mark.requirement("SRS-025")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 40, 75])
def test_extra_detection_200_ms_before_a_detection_within_5_bpm(fs_hz: int, rate: int) -> None:
    """SRS-025: one detection added 200 ms before the next detection, at each interval:
    every valid heart rate within 5 bpm of the true rate."""
    idx = rhythm(rate, fs_hz, 30)
    gap = math.ceil(0.2 * fs_hz)
    for j in range(1, len(idx)):
        seq = sorted(idx + [idx[j] - gap])
        rates = valid_rates(track(seq, fs_hz))
        assert all(abs(r - rate) <= 5.0 for r in rates), (j, rates)


# --------------------------------------------------------------------------- SRS-026


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 75, 200])
def test_first_valid_rate_comes_with_the_fourth_interval(fs_hz: int, rate: int) -> None:
    """SRS-026: from the first sample of the stream, "not enough beats" until 4 intervals are
    available: the first four detections (0 to 3 intervals) are withheld with that reason
    and no rate, the fifth detection (fourth interval) is the first valid rate."""
    idx = rhythm(rate, fs_hz, 10)
    events = track(idx, fs_hz)
    assert [e.status for e in events[:4]] == [NOT_ENOUGH] * 4
    assert all(e.bpm is None for e in events[:4])
    assert events[4].status == VALID
    assert events[4].sample == idx[4]
    assert all(e.status == VALID for e in events[4:])


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_no_event_at_the_start_without_detections(fs_hz: int) -> None:
    """SRS-026: with no detection, the heart rate is withheld as "not enough beats" from the
    start and never becomes "no recent beat" (no detection to be recent): no event."""
    events = track_heart_rate(
        np.zeros(0, dtype=np.int64), np.zeros(0, dtype=bool), float(fs_hz), 20 * fs_hz
    )
    assert events == ()


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 75])
@pytest.mark.parametrize("gap_s", [3.1, 3.5, 5.0])
def test_gap_longer_than_3_s_gives_no_recent_beat(fs_hz: int, rate: int, gap_s: float) -> None:
    """SRS-026: after 10 regular detections, a stretch without detection longer than 3 s gives
    "no recent beat" at the first sample at least 3 s after the last detection (one event,
    beat_index None, no rate); the detections after the stretch are withheld as "no recent
    beat" and the next valid rate comes with the fourth interval after the stretch."""
    first = rhythm(rate, fs_hz, 10)
    after = rhythm(rate, fs_hz, 10, start=first[-1] + round(gap_s * fs_hz))
    events = track(first + after, fs_hz)
    fired = three_s(fs_hz) + first[-1]
    nrb_events = [e for e in events if e.beat_index is None]
    assert nrb_events == [HeartRateEvent(fired, None, NO_RECENT, None)]
    by_beat = {e.beat_index: e for e in events if e.beat_index is not None}
    for i in first[4:]:
        assert by_beat[i].status == VALID
    # events are ordered by sample
    assert [e.sample for e in events] == sorted(e.sample for e in events)
    for i in after[:4]:
        assert by_beat[i].status == NO_RECENT and by_beat[i].bpm is None, i
    assert by_beat[after[4]].status == VALID
    assert all(by_beat[i].status == VALID for i in after[4:])
    rates = valid_rates(events)
    assert all(abs(r - rate) <= 2.0 for r in rates)


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 75])
def test_gap_shorter_than_3_s_gives_none(fs_hz: int, rate: int) -> None:
    """SRS-026: a stretch without detections shorter than 3 s (2.9 s, 3 s less one sample,
    and exactly 3 s, where the detection at the sample counts) gives no "no recent beat": no
    event without a detection, and the heart rate stays valid after the stretch."""
    first = rhythm(rate, fs_hz, 10)
    for gap in (round(2.9 * fs_hz), three_s(fs_hz) - 1, three_s(fs_hz)):
        after = rhythm(rate, fs_hz, 6, start=first[-1] + gap)
        events = track(first + after, fs_hz)
        assert all(e.beat_index is not None for e in events), gap
        assert all(e.status != NO_RECENT for e in events), gap
        assert events[-1].status == VALID
        assert all(e.status == VALID for e in events[4:]), gap


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_no_recent_beat_at_the_first_sample_3_s_after(fs_hz: int) -> None:
    """SRS-026: boundary on the end of the stream: with the stream ending exactly 3 s
    (ceil(3 fs) samples) after the last detection, the event is at that sample; one sample
    before, there is none."""
    idx = rhythm(75, fs_hz, 8)
    n3 = three_s(fs_hz)
    with_event = track(idx, fs_hz, tail=1 + n3)
    assert with_event[-1] == HeartRateEvent(idx[-1] + n3, None, NO_RECENT, None)
    assert with_event[:-1] == track(idx, fs_hz)
    without = track(idx, fs_hz, tail=n3)
    assert without == track(idx, fs_hz)


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 75])
def test_no_recent_beat_after_the_second_detection(fs_hz: int, rate: int) -> None:
    """SRS-026: a stretch longer than 3 s after the second detection of the stream, while
    withheld as "not enough beats": "no recent beat" at the first sample at least 3 s after
    that detection; both reasons apply, the reason is "no recent beat" for the detections
    after, until 4 intervals after the stretch, then valid."""
    first = rhythm(rate, fs_hz, 2)
    after = rhythm(rate, fs_hz, 8, start=first[-1] + round(3.4 * fs_hz))
    events = track(first + after, fs_hz)
    assert [e.status for e in events[:2]] == [NOT_ENOUGH, NOT_ENOUGH]
    assert events[2] == HeartRateEvent(first[-1] + three_s(fs_hz), None, NO_RECENT, None)
    later = events[3:]
    assert [e.beat_index for e in later] == after
    assert [e.status for e in later[:4]] == [NO_RECENT] * 4
    assert all(e.status == VALID for e in later[4:])


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_no_recent_beat_after_the_third_detection(fs_hz: int) -> None:
    """SRS-026: same, after the third detection (2 intervals available, not enough beats)."""
    first = rhythm(75, fs_hz, 3)
    after = rhythm(75, fs_hz, 7, start=first[-1] + 4 * fs_hz)
    events = track(first + after, fs_hz)
    assert events[3] == HeartRateEvent(first[-1] + three_s(fs_hz), None, NO_RECENT, None)
    assert [e.status for e in events[4:8]] == [NO_RECENT] * 4
    assert events[8].status == VALID


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_second_stretch_before_four_new_intervals_adds_no_event(fs_hz: int) -> None:
    """SRS-026: "no recent beat" persists until 4 new intervals are available: a second
    stretch longer than 3 s after only 2 new intervals gives no further event (the reason
    does not change), and the next valid rate comes with the fourth interval after it."""
    a = rhythm(75, fs_hz, 8)
    b = rhythm(75, fs_hz, 3, start=a[-1] + 4 * fs_hz)
    c = rhythm(75, fs_hz, 9, start=b[-1] + 4 * fs_hz)
    events = track(a + b + c, fs_hz)
    no_beat = [e for e in events if e.beat_index is None]
    assert [e.sample for e in no_beat] == [a[-1] + three_s(fs_hz)]
    by_beat = {e.beat_index: e for e in events if e.beat_index is not None}
    assert all(by_beat[i].status == NO_RECENT for i in b)
    assert all(by_beat[i].status == NO_RECENT for i in c[:4])
    assert all(by_beat[i].status == VALID for i in c[4:])


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_events_at_each_change_of_reason(fs_hz: int) -> None:
    """SRS-024/SRS-026: valid -> no recent beat -> valid -> no recent beat gives an event at
    each change at no detection, with the reason, once per change; the trailing "no recent
    beat" is reported at the end of the stream."""
    a = rhythm(75, fs_hz, 8)
    b = rhythm(75, fs_hz, 8, start=a[-1] + 4 * fs_hz)
    n3 = three_s(fs_hz)
    events = track(a + b, fs_hz, tail=1 + n3)
    no_beat = [e for e in events if e.beat_index is None]
    assert no_beat == [
        HeartRateEvent(a[-1] + n3, None, NO_RECENT, None),
        HeartRateEvent(b[-1] + n3, None, NO_RECENT, None),
    ]


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_startup_detection_does_not_restart_the_no_recent_beat_timer(fs_hz: int) -> None:
    """SRS-026: the 3 s are counted from the last detection marked reliable: a start-up
    detection 1.5 s after it neither postpones "no recent beat" nor counts as a beat."""
    a = rhythm(75, fs_hz, 8)
    startup = a[-1] + round(1.5 * fs_hz)
    n3 = three_s(fs_hz)
    events = track(a + [startup], fs_hz, startup=[False] * 8 + [True], tail=1 + 2 * n3)
    no_beat = [e for e in events if e.beat_index is None]
    assert no_beat == [HeartRateEvent(a[-1] + n3, None, NO_RECENT, None)]
    assert all(e.beat_index != startup for e in events)


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [29, 201])
def test_rates_outside_the_range_are_out_of_range(fs_hz: int, rate: int) -> None:
    """SRS-026: regular rhythms at 29 and 201 bpm give "out of range" from the fourth
    interval, with the rate (outside 30-200 bpm); never valid."""
    idx = rhythm(rate, fs_hz, 30)
    events = track(idx, fs_hz)
    assert [e.status for e in events[:4]] == [NOT_ENOUGH] * 4
    assert all(e.status == OUT_OF_RANGE for e in events[4:])
    for e in events[4:]:
        assert e.bpm is not None
        assert e.bpm < 30 if rate < 30 else e.bpm > 200


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [30, 200])
def test_limit_rates_are_not_out_of_range(fs_hz: int, rate: int) -> None:
    """SRS-026: regular rhythms at 30 and 200 bpm (bounds included) give valid rates, no
    "out of range" status."""
    events = track(rhythm(rate, fs_hz, 30), fs_hz)
    assert all(e.status == VALID for e in events[4:])


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_out_of_range_then_back_to_valid(fs_hz: int) -> None:
    """SRS-026/SRS-024: a rhythm at 75 bpm followed by one at 250 bpm (intervals 240 ms,
    above the range) and back: status out of range while the window is at 250 bpm, valid
    again at 75 bpm; no valid rate is above 200 bpm."""
    a = rhythm(75, fs_hz, 10)
    b = rhythm(250, fs_hz, 20, start=a[-1])[1:]
    c = rhythm(75, fs_hz, 14, start=b[-1])[1:]
    events = at_detections(track(a + b + c, fs_hz))
    by_beat = {e.beat_index: e for e in events}
    assert by_beat[b[-1]].status == OUT_OF_RANGE
    assert by_beat[c[-1]].status == VALID
    assert all(r <= 200.0 for r in valid_rates(events))


# --------------------------------------------------------------------------- end to end


@pytest.fixture
def pipeline_case(make_synthetic_ecg: Callable[..., Any]) -> Callable[[int, int], Any]:
    def build(fs_hz: int, rate: int) -> Any:
        ecg = make_synthetic_ecg(fs_hz, rate, n_samples=60 * fs_hz)
        return ecg, run_pipeline(ecg.signal_mv, ecg.fs_hz, 50)

    return build


@pytest.mark.requirement("SRS-024", "SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
@pytest.mark.parametrize("rate", [40, 75, 180])
def test_pipeline_heart_rate_on_a_synthetic_ecg(
    pipeline_case: Callable[[int, int], Any], fs_hz: int, rate: int
) -> None:
    """SRS-024/SRS-026: the synthetic ECG (section 7.2, 60 s) through the pipeline: the first
    events are "not enough beats", the heart rate then becomes valid, every valid heart rate
    is within 2 bpm of the true rate, start-up detections (first 2 s) give no event, and the
    result equals tracking the marked detections."""
    ecg, result = pipeline_case(fs_hz, rate)
    events = result.heart_rate
    assert events and events[0].status == NOT_ENOUGH
    statuses = [e.status for e in events]
    assert VALID in statuses
    first_valid = statuses.index(VALID)
    assert all(s == NOT_ENOUGH for s in statuses[:first_valid])
    assert first_valid >= 4
    rates = valid_rates(events)
    assert all(abs(r - rate) <= 2.0 for r in rates), (min(rates), max(rates))
    assert events[-1].status == VALID
    marked = detect_marked(ecg.signal_mv, ecg.fs_hz, 50)
    startup_idx = {int(i) for i, s in zip(marked.indices, marked.startup, strict=True) if s}
    assert startup_idx, "the first 2 s must contain start-up detections"
    assert all(e.beat_index not in startup_idx for e in events)
    assert events == track_heart_rate(
        marked.indices,
        marked.startup,
        ecg.fs_hz,
        len(ecg.signal_mv),
        reported_at=marked.reported_at,
    )


@pytest.mark.requirement("SRS-026")
@pytest.mark.parametrize("fs_hz", FS_HZ)
def test_pipeline_flat_stretch_gives_no_recent_beat(
    make_synthetic_ecg: Callable[..., Any], fs_hz: int
) -> None:
    """SRS-026: a synthetic ECG at 75 bpm whose second half is silent (zeros) is reported
    with "no recent beat" in the end, no valid rate after the last beat is withheld longer
    than needed: the last event is "no recent beat" with no rate."""
    ecg = make_synthetic_ecg(fs_hz, 75, n_samples=40 * fs_hz)
    signal = np.array(ecg.signal_mv, dtype=np.float64)
    signal[20 * fs_hz :] = 0.0
    events = run_pipeline(signal, ecg.fs_hz, 50).heart_rate
    assert events[-1].status == NO_RECENT
    assert events[-1].bpm is None and events[-1].beat_index is None
    assert any(e.status == VALID for e in events)
