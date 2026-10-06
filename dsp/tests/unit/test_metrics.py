"""Unit tests of the detection statistics: per record, gross and average."""

import dataclasses
import math
import random
from fractions import Fraction

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.metrics import (
    AggregateStatistics,
    RecordCounts,
    RecordStatistics,
    aggregate_statistics,
    positive_predictivity_percent,
    record_statistics,
    sensitivity_percent,
)

RATIOS = [sensitivity_percent, positive_predictivity_percent]


# Se and +P


@pytest.mark.parametrize("ratio", RATIOS)
@pytest.mark.parametrize(
    ("tp", "other", "expected"),
    [
        (1, 0, 100.0),
        (2000, 0, 100.0),
        (0, 1, 0.0),
        (0, 500, 0.0),
        (1, 1, 50.0),
        (3, 1, 75.0),
        (995, 5, 99.5),
        (1, 2, 100 / 3),
        (2, 1, 200 / 3),
        (2269, 4, 226900 / 2273),
    ],
)
def test_percentage(ratio, tp: int, other: int, expected: float) -> None:  # type: ignore[no-untyped-def]
    value = ratio(tp, other)
    assert type(value) is float
    assert value == expected


@pytest.mark.parametrize("ratio", RATIOS)
def test_zero_denominator_is_not_defined(ratio) -> None:  # type: ignore[no-untyped-def]
    assert ratio(0, 0) is None


@pytest.mark.parametrize("ratio", RATIOS)
def test_value_is_the_float_nearest_to_the_exact_quotient(ratio) -> None:  # type: ignore[no-untyped-def]
    rng = random.Random(11)
    for _ in range(2000):
        tp = rng.randrange(0, 10 ** rng.randint(1, 25))
        other = rng.randrange(1, 10 ** rng.randint(1, 25))
        value = ratio(tp, other)
        exact = Fraction(100 * tp, tp + other)
        assert value is not None
        assert value == exact.numerator / exact.denominator
        # No float64 is closer to the exact quotient.
        error = abs(Fraction(value) - exact)
        assert error <= abs(Fraction(math.nextafter(value, math.inf)) - exact)
        assert error <= abs(Fraction(math.nextafter(value, -math.inf)) - exact)


@pytest.mark.parametrize("ratio", RATIOS)
def test_counts_beyond_float64_integers_are_handled(ratio) -> None:  # type: ignore[no-untyped-def]
    assert ratio(10**30, 10**30) == 50.0
    assert ratio(3 * 10**40, 10**40) == 75.0


@pytest.mark.parametrize("ratio", RATIOS)
def test_numpy_integers_are_accepted(ratio) -> None:  # type: ignore[no-untyped-def]
    value = ratio(np.int64(3), np.int32(1))
    assert value == 75.0
    assert type(value) is float


@pytest.mark.parametrize("ratio", RATIOS)
@pytest.mark.parametrize(("tp", "other"), [(-1, 5), (5, -1), (-1, -1), (0, -3), (-2, 0)])
def test_negative_count_is_rejected(ratio, tp: int, other: int) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(InvalidInputError, match="is negative"):
        ratio(tp, other)


@pytest.mark.parametrize("ratio", RATIOS)
@pytest.mark.parametrize("value", [1.0, 2.5, True, False, None, "3", float("nan")])
def test_count_that_is_not_an_integer_is_rejected(ratio, value: object) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(InvalidInputError, match="tp is not an integer"):
        ratio(value, 1)
    with pytest.raises(InvalidInputError, match="is not an integer"):
        ratio(1, value)


def test_error_names_the_count() -> None:
    with pytest.raises(InvalidInputError, match="^fn is negative: -4$"):
        sensitivity_percent(3, -4)
    with pytest.raises(InvalidInputError, match="^fp is negative: -4$"):
        positive_predictivity_percent(3, -4)
    with pytest.raises(InvalidInputError, match="^tp is negative: -1$"):
        positive_predictivity_percent(-1, 0)


# Per record


def test_record_statistics() -> None:
    statistics = record_statistics(RecordCounts(record="100", tp=2269, fn=4, fp=1))
    assert statistics == RecordStatistics(
        record="100",
        tp=2269,
        fn=4,
        fp=1,
        se_percent=226900 / 2273,
        ppv_percent=226900 / 2270,
    )


@pytest.mark.parametrize(
    ("counts", "se", "ppv"),
    [
        ((0, 0, 0), None, None),
        ((0, 0, 7), None, 0.0),
        ((0, 7, 0), 0.0, None),
        ((0, 3, 7), 0.0, 0.0),
        ((5, 0, 0), 100.0, 100.0),
    ],
)
def test_record_statistics_with_zero_counts(
    counts: tuple[int, int, int], se: float | None, ppv: float | None
) -> None:
    tp, fn, fp = counts
    statistics = record_statistics(RecordCounts("r", tp, fn, fp))
    assert (statistics.tp, statistics.fn, statistics.fp) == counts
    assert statistics.se_percent == se
    assert statistics.ppv_percent == ppv
    assert (statistics.se_percent is None) == (se is None)
    assert (statistics.ppv_percent is None) == (ppv is None)


def test_record_statistics_error_names_the_record() -> None:
    with pytest.raises(InvalidInputError, match="^fp of record '207' is negative: -2$"):
        record_statistics(RecordCounts("207", 10, 1, -2))
    with pytest.raises(InvalidInputError, match="^tp of record '207' is not an integer: 1.5$"):
        record_statistics(RecordCounts("207", 1.5, 1, 2))  # type: ignore[arg-type]


def test_record_statistics_counts_are_python_integers() -> None:
    counts = RecordCounts("r", np.int64(3), np.int64(1), np.int64(0))  # type: ignore[arg-type]
    statistics = record_statistics(counts)
    assert [type(value) for value in (statistics.tp, statistics.fn, statistics.fp)] == [int] * 3


def test_values_are_frozen() -> None:
    counts = RecordCounts("r", 1, 2, 3)
    with pytest.raises(dataclasses.FrozenInstanceError):
        counts.tp = 5  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        record_statistics(counts).se_percent = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        aggregate_statistics([counts]).tp = 5  # type: ignore[misc]


# Aggregate


def test_gross_values_come_from_the_summed_counts_and_averages_from_the_records() -> None:
    counts = [RecordCounts("a", tp=90, fn=10, fp=0), RecordCounts("b", tp=1, fn=1, fp=3)]
    aggregate = aggregate_statistics(counts)
    assert aggregate == AggregateStatistics(
        n_records=2,
        tp=91,
        fn=11,
        fp=3,
        gross_se_percent=9100 / 102,
        gross_ppv_percent=9100 / 94,
        average_se_percent=70.0,  # (90 + 50) / 2
        average_ppv_percent=62.5,  # (100 + 25) / 2
        n_se_defined=2,
        n_ppv_defined=2,
    )
    assert aggregate.gross_se_percent != aggregate.average_se_percent
    assert aggregate.gross_ppv_percent != aggregate.average_ppv_percent


def test_single_record_has_equal_gross_and_average_values() -> None:
    aggregate = aggregate_statistics([RecordCounts("a", 7, 1, 2)])
    assert aggregate.gross_se_percent == aggregate.average_se_percent == 700 / 8
    assert aggregate.gross_ppv_percent == aggregate.average_ppv_percent == 700 / 9
    assert (aggregate.n_records, aggregate.n_se_defined, aggregate.n_ppv_defined) == (1, 1, 1)


def test_record_without_reference_beats_is_left_out_of_the_se_average() -> None:
    counts = [
        RecordCounts("a", tp=3, fn=1, fp=1),
        RecordCounts("b", tp=0, fn=0, fp=4),  # Se not defined, +P = 0
        RecordCounts("c", tp=1, fn=1, fp=0),
    ]
    aggregate = aggregate_statistics(counts)
    assert (aggregate.tp, aggregate.fn, aggregate.fp) == (4, 2, 5)
    assert aggregate.n_records == 3
    assert aggregate.n_se_defined == 2
    assert aggregate.n_ppv_defined == 3
    assert aggregate.average_se_percent == (75.0 + 50.0) / 2
    assert aggregate.average_ppv_percent == math.fsum([75.0, 0.0, 100.0]) / 3
    assert aggregate.gross_se_percent == 400 / 6
    assert aggregate.gross_ppv_percent == 400 / 9


def test_record_without_detections_is_left_out_of_the_ppv_average() -> None:
    counts = [RecordCounts("a", tp=3, fn=1, fp=1), RecordCounts("b", tp=0, fn=6, fp=0)]
    aggregate = aggregate_statistics(counts)
    assert (aggregate.n_se_defined, aggregate.n_ppv_defined) == (2, 1)
    assert aggregate.average_se_percent == (75.0 + 0.0) / 2
    assert aggregate.average_ppv_percent == 75.0


def test_record_with_no_count_changes_only_the_number_of_records() -> None:
    counts = [RecordCounts("a", 3, 1, 1), RecordCounts("c", 1, 1, 0)]
    with_empty = aggregate_statistics([*counts, RecordCounts("empty", 0, 0, 0)])
    without = aggregate_statistics(counts)
    assert with_empty == dataclasses.replace(without, n_records=3)


def test_no_defined_value_gives_none_everywhere() -> None:
    aggregate = aggregate_statistics([RecordCounts("a", 0, 0, 0), RecordCounts("b", 0, 0, 0)])
    assert aggregate == AggregateStatistics(2, 0, 0, 0, None, None, None, None, 0, 0)


def test_empty_sequence_gives_zero_counts_and_none_everywhere() -> None:
    expected = AggregateStatistics(0, 0, 0, 0, None, None, None, None, 0, 0)
    assert aggregate_statistics([]) == expected
    assert aggregate_statistics(()) == expected


def test_undefined_values_are_not_counted_as_0_or_100() -> None:
    counts = [RecordCounts("a", 1, 1, 1), RecordCounts("b", 0, 0, 0)]
    aggregate = aggregate_statistics(counts)
    # Counted as 0 the averages would be 25, counted as 100 they would be 75.
    assert aggregate.average_se_percent == 50.0
    assert aggregate.average_ppv_percent == 50.0


def test_average_is_the_correctly_rounded_mean_of_the_record_values() -> None:
    counts = [RecordCounts(str(index), tp=1, fn=index, fp=2 * index) for index in range(1, 40)]
    aggregate = aggregate_statistics(counts)
    se_values = [100 / (1 + index) for index in range(1, 40)]
    ppv_values = [100 / (1 + 2 * index) for index in range(1, 40)]
    assert aggregate.average_se_percent == math.fsum(se_values) / 39
    assert aggregate.average_ppv_percent == math.fsum(ppv_values) / 39


def test_result_does_not_depend_on_the_order_of_the_records() -> None:
    rng = random.Random(5)
    counts = [
        RecordCounts(f"r{index}", rng.randrange(3000), rng.randrange(50), rng.randrange(50))
        for index in range(48)
    ]
    expected = aggregate_statistics(counts)
    for _ in range(50):
        rng.shuffle(counts)
        assert aggregate_statistics(counts) == expected


def test_aggregate_accepts_a_tuple() -> None:
    counts = (RecordCounts("a", 3, 1, 1), RecordCounts("b", 1, 1, 0))
    assert aggregate_statistics(counts) == aggregate_statistics(list(counts))


def test_duplicate_record_name_is_rejected() -> None:
    counts = [
        RecordCounts("100", 3, 1, 1),
        RecordCounts("101", 1, 1, 0),
        RecordCounts("100", 1, 0, 0),
    ]
    with pytest.raises(InvalidInputError, match="^duplicate record name: '100'$"):
        aggregate_statistics(counts)


@pytest.mark.parametrize("field", ["tp", "fn", "fp"])
def test_negative_count_in_a_record_is_rejected(field: str) -> None:
    values = {"tp": 1, "fn": 1, "fp": 1} | {field: -1}
    bad = RecordCounts("b", values["tp"], values["fn"], values["fp"])
    with pytest.raises(InvalidInputError, match=f"^{field} of record 'b' is negative: -1$"):
        aggregate_statistics([RecordCounts("a", 3, 1, 1), bad])


def test_errors_are_value_errors() -> None:
    with pytest.raises(ValueError):
        sensitivity_percent(-1, 0)
