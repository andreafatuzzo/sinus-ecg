"""Unit tests: signal quality summaries and criteria (architecture §13.7.3)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.signal_quality import (
    QUALITY_CRITERIA,
    WindowSummary,
    build_quality_results,
    count_in_not_usable,
    quality_criteria,
    record_quality,
    summarize_pooled,
    summarize_windows,
    windows_from,
    windows_within,
)
from sinus_dsp.quality import QualityWindows

W = 3600
H = 360


def make_windows(
    index: Sequence[float], usable: Sequence[bool] | None = None, step: int = H, offset: int = 0
) -> QualityWindows:
    n = len(index)
    first = offset + step * np.arange(n, dtype=np.int64)
    flags = [value >= 0.5 for value in index] if usable is None else list(usable)
    return QualityWindows(
        first=first,
        last=first + W - 1,
        reported_at=first + W - 1 + 180,
        index=np.array(index, dtype=np.float64),
        usable=np.array(flags, dtype=np.bool_),
        held=np.zeros(n, dtype=np.bool_),
        n_detections=np.zeros(n, dtype=np.int64),
        signal_power=np.zeros(n),
        background_power=np.zeros(n),
    )


def summary(n: int, usable: int, median: float | None = 0.5) -> WindowSummary:
    return WindowSummary(n_windows=n, n_usable=usable, median_index=median if n else None)


def test_summary_counts_and_median() -> None:
    windows = make_windows([0.9, 0.1, 0.7, 0.4])
    chosen = np.array([True, True, True, False])
    assert summarize_windows(windows, chosen) == WindowSummary(3, 2, 0.7)


def test_median_of_an_even_count_is_the_mean_of_the_middle_values() -> None:
    windows = make_windows([0.2, 0.4, 0.6, 1.0])
    result = summarize_windows(windows, np.ones(4, dtype=np.bool_))
    assert result.median_index == pytest.approx(0.5)


def test_summary_without_windows() -> None:
    windows = make_windows([0.9])
    assert summarize_windows(windows, np.zeros(1, dtype=np.bool_)) == WindowSummary(0, 0, None)
    empty = make_windows([])
    assert summarize_windows(empty, np.zeros(0, dtype=np.bool_)) == WindowSummary(0, 0, None)


def test_selection_of_the_wrong_length_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="shape"):
        summarize_windows(make_windows([0.9, 0.1]), np.ones(3, dtype=np.bool_))


def test_pooled_summary_uses_the_indices_of_all_the_parts() -> None:
    a = make_windows([0.1, 0.2])
    b = make_windows([0.9, 0.8, 0.7])
    pooled = summarize_pooled([(a, np.ones(2, dtype=np.bool_)), (b, np.ones(3, dtype=np.bool_))])
    assert pooled == WindowSummary(5, 3, 0.7)


def test_windows_within_needs_the_whole_window() -> None:
    windows = make_windows([0.5] * 5)  # first 0, 360, 720, 1080, 1440
    lo, hi = 360, 360 + W + 360 - 1  # window 1 and 2 fit exactly, 3 ends one sample later
    assert windows_within(windows, lo, hi).tolist() == [False, True, True, False, False]
    assert windows_within(windows, lo, hi + H - 1).tolist() == [False, True, True, False, False]
    assert windows_within(windows, lo + 1, hi + H).tolist() == [False, False, True, True, False]


def test_windows_from_uses_the_first_sample() -> None:
    windows = make_windows([0.5] * 4)
    assert windows_from(windows, 360).tolist() == [False, True, True, True]
    assert windows_from(windows, 361).tolist() == [False, False, True, True]


def test_count_in_not_usable_by_sample() -> None:
    windows = make_windows([0.9, 0.1, 0.9, 0.9], usable=[True, False, True, True])
    # the not usable window 1 covers 360 .. 360 + W - 1
    inside = [360, 360 + W - 1]
    outside = [359, 360 + W]
    assert count_in_not_usable(inside + outside, windows) == 2
    assert count_in_not_usable(outside, windows) == 0


def test_sample_in_two_not_usable_windows_counts_once() -> None:
    windows = make_windows([0.1, 0.1], usable=[False, False])
    assert count_in_not_usable([400, 400], windows) == 1
    assert count_in_not_usable([400, 500, W + 100], windows) == 3


def test_count_in_not_usable_edge_cases() -> None:
    windows = make_windows([0.9, 0.9], usable=[True, True])
    assert count_in_not_usable([5, 10], windows) == 0
    assert count_in_not_usable([], make_windows([0.1], usable=[False])) == 0
    assert count_in_not_usable([10**9], make_windows([0.1], usable=[False])) == 0
    assert count_in_not_usable([5], make_windows([])) == 0


def test_count_in_not_usable_matches_a_direct_scan() -> None:
    rng = np.random.default_rng(3)
    flags = rng.random(60) > 0.5
    windows = make_windows(list(rng.random(60)), usable=list(flags))
    samples = sorted(set(int(v) for v in rng.integers(0, 60 * H + W + 500, 400)))
    expected = sum(
        any(not flags[i] and windows.first[i] <= s <= windows.last[i] for i in range(60))
        for s in samples
    )
    assert count_in_not_usable(samples, windows) == expected


def test_record_quality_counts_windows_from_five_minutes() -> None:
    start = 300 * 360
    windows = make_windows([0.9, 0.1, 0.9, 0.2], step=H, offset=start - 2 * H)
    # windows start at 5:00 - 2H, 5:00 - H, 5:00, 5:00 + H
    fn = [start - H + 5, start - 2 * H + 1, 50]
    result = record_quality("100", windows, 360.0, fn, [start + 10])
    assert result.record == "100"
    assert result.from_start == WindowSummary(2, 1, 0.55)
    assert result.fn_in_not_usable == 1  # only start - H + 5 lies in a not usable window
    assert (
        result.fp_in_not_usable == 1
    )  # window at 5:00 + H is not usable but 5:00 + 10 is in window 1 too


ALL_OK = [(24, summary(100, 95, 0.9)), (18, summary(100, 90, 0.8)), (12, summary(100, 50, 0.6))] + [
    (6, summary(100, 20, 0.4)),
    (0, summary(100, 10, 0.3)),
    (-6, summary(100, 0, 0.1)),
]
NOISE_OK = [("bw", summary(100, 10)), ("em", summary(100, 0)), ("ma", summary(100, 5))]
CLEAN_OK = summary(100, 95)


def passed(result: tuple[tuple[str, bool], ...]) -> dict[str, bool]:
    assert tuple(name for name, _ in result) == QUALITY_CRITERIA
    return dict(result)


def test_all_criteria_pass_at_the_limits() -> None:
    assert all(passed(quality_criteria(ALL_OK, CLEAN_OK, NOISE_OK)).values())


def replace(snr: int, new: WindowSummary) -> list[tuple[int, WindowSummary]]:
    return [(s, new if s == snr else value) for s, value in ALL_OK]


@pytest.mark.parametrize(
    ("snr", "bad", "criterion"),
    [
        (24, summary(100, 89, 0.9), "usable_24"),
        (18, summary(100, 89, 0.8), "usable_18"),
        (6, summary(100, 21, 0.4), "usable_6"),
        (0, summary(100, 21, 0.3), "usable_0"),
        (-6, summary(100, 21, 0.1), "usable_-6"),
    ],
)
def test_each_snr_is_judged_on_its_own(snr: int, bad: WindowSummary, criterion: str) -> None:
    result = passed(quality_criteria(replace(snr, bad), CLEAN_OK, NOISE_OK))
    assert not result[criterion]
    assert sum(not value for value in result.values()) == 1


def test_pooled_good_result_does_not_make_up_for_a_bad_one() -> None:
    bad = replace(24, summary(100, 80, 0.9))
    bad = [(s, v) if s != 18 else (s, summary(100, 100, 0.8)) for s, v in bad]
    assert not passed(quality_criteria(bad, CLEAN_OK, NOISE_OK))["usable_24"]


@pytest.mark.parametrize("name", ["bw", "em", "ma"])
def test_each_noise_record_is_judged_on_its_own(name: str) -> None:
    noise = [(n, summary(100, 11) if n == name else v) for n, v in NOISE_OK]
    result = passed(quality_criteria(ALL_OK, CLEAN_OK, noise))
    assert [k for k, v in result.items() if not v] == [f"noise_{name}"]


def test_clean_records_threshold() -> None:
    assert not passed(quality_criteria(ALL_OK, summary(100, 94), NOISE_OK))["clean_usable"]


def test_percentages_are_compared_on_integers() -> None:
    # 90 % of 3 windows is 2.7: 2 of 3 fails, 3 of 3 passes
    assert not passed(quality_criteria(replace(24, summary(3, 2, 0.9)), CLEAN_OK, NOISE_OK))[
        "usable_24"
    ]
    assert passed(quality_criteria(replace(24, summary(3, 3, 0.9)), CLEAN_OK, NOISE_OK))[
        "usable_24"
    ]
    # 20 % of 5 windows is exactly 1
    assert passed(quality_criteria(replace(6, summary(5, 1, 0.4)), CLEAN_OK, NOISE_OK))["usable_6"]
    assert not passed(quality_criteria(replace(6, summary(5, 2, 0.4)), CLEAN_OK, NOISE_OK))[
        "usable_6"
    ]


def levels(medians: tuple[float, ...]) -> list[tuple[int, WindowSummary]]:
    snrs = (24, 18, 12, 6, 0, -6)
    return [(s, summary(100, 50, m)) for s, m in zip(snrs, medians, strict=True)]


def test_medians_must_not_increase_and_must_be_lower_at_the_lowest_snr() -> None:
    rise = levels((0.9, 0.8, 0.7, 0.6, 0.5, 0.55))
    result = passed(quality_criteria(rise, CLEAN_OK, NOISE_OK))
    assert not result["median_non_increasing"]
    assert result["median_lower_at_lowest_snr"]
    flat = levels((0.5,) * 6)
    result = passed(quality_criteria(flat, CLEAN_OK, NOISE_OK))
    assert result["median_non_increasing"]
    assert not result["median_lower_at_lowest_snr"]


def test_equal_neighbouring_medians_are_allowed() -> None:
    steady = levels((0.9, 0.9, 0.5, 0.5, 0.2, 0.2))
    assert passed(quality_criteria(steady, CLEAN_OK, NOISE_OK))["median_non_increasing"]


def test_criteria_without_windows_are_false() -> None:
    empty = summary(0, 0)
    result = passed(quality_criteria([], empty, []))
    assert not any(result.values())
    result = passed(quality_criteria(replace(-6, empty), CLEAN_OK, NOISE_OK))
    assert not result["usable_-6"]
    assert not result["median_non_increasing"]
    assert not result["median_lower_at_lowest_snr"]
    assert result["usable_24"]
    result = passed(quality_criteria(ALL_OK, empty, NOISE_OK))
    assert not result["clean_usable"]
    result = passed(quality_criteria(ALL_OK, CLEAN_OK, NOISE_OK[:2]))
    assert not result["noise_ma"] and result["noise_bw"]


def test_missing_twelve_db_level_makes_the_median_criteria_false() -> None:
    levels = [(s, v) for s, v in ALL_OK if s != 12]
    result = passed(quality_criteria(levels, CLEAN_OK, NOISE_OK))
    assert not result["median_non_increasing"]
    assert result["usable_24"]


def test_results_sort_the_records_and_hold_the_criteria() -> None:
    records = [
        record_quality(name, make_windows([0.9]), 360.0, [], []) for name in ("119", "100", "118")
    ]
    result = build_quality_results(records, ALL_OK, CLEAN_OK, NOISE_OK)
    assert [r.record for r in result.records] == ["100", "118", "119"]
    assert result.criteria == quality_criteria(ALL_OK, CLEAN_OK, NOISE_OK)
    assert result.by_snr == tuple(ALL_OK)
    assert result.clean == CLEAN_OK
    assert result.noise_records == tuple(NOISE_OK)
