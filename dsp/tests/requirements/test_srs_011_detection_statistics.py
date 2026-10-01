"""Requirement tests of SRS-011: detection statistics (risk control RC-004).

From the counts of a record (TP, FN, FP), SRS-011 requires Se = TP / (TP + FN) and
+P = TP / (TP + FP) in percent; for a set of records, gross values from the summed counts and
average values as the mean of the per-record values. A value whose denominator is zero is
reported as not defined (``None`` in the interface) and is left out of the averages.

Expected values are worked out by hand from these formulas, or with exact rational arithmetic
in the test. They are compared with the pass criterion of SRS-011: equal to within 0.01
percentage points.
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
import pytest

from sinus_dsp.evaluation.metrics import (
    RecordCounts,
    aggregate_statistics,
    positive_predictivity_percent,
    record_statistics,
    sensitivity_percent,
)

# Pass criterion of SRS-011, in percentage points.
TOLERANCE = 0.01

# Per-record counts whose statistics are known: (tp, fn, fp, Se in %, +P in %).
DEFINED_COUNTS = [
    pytest.param(90, 10, 30, 90.0, 75.0, id="tp90-fn10-fp30"),
    pytest.param(2000, 1, 3, 99.950025, 99.850225, id="tp2000-fn1-fp3"),
    pytest.param(1, 2, 0, 33.333333, 100.0, id="tp1-fn2-fp0"),
    pytest.param(1, 0, 2, 100.0, 33.333333, id="tp1-fn0-fp2"),
    pytest.param(2271, 2, 0, 99.912011, 100.0, id="tp2271-fn2-fp0"),
    pytest.param(1859, 3, 187, 99.838883, 90.860215, id="tp1859-fn3-fp187"),
    pytest.param(7, 0, 0, 100.0, 100.0, id="tp7-fn0-fp0"),
    pytest.param(0, 5, 8, 0.0, 0.0, id="tp0-fn5-fp8"),
    pytest.param(109000, 300, 500, 99.725526, 99.543379, id="tp109000-fn300-fp500"),
]


def _close(actual: float | None, expected: float) -> bool:
    """True when ``actual`` is a number within 0.01 percentage points of ``expected``."""
    return actual is not None and math.isfinite(actual) and abs(actual - expected) <= TOLERANCE


@pytest.mark.requirement("SRS-011")
@pytest.mark.parametrize(("tp", "fn", "fp", "se", "ppv"), DEFINED_COUNTS)
def test_record_statistics_report_counts_se_and_ppv(
    tp: int, fn: int, fp: int, se: float, ppv: float
) -> None:
    """Per-record values.

    Input: the counts TP, FN and FP of one record, with TP + FN > 0 and TP + FP > 0.
    Expected: the record statistics report the same record name and counts, Se equal to
    100 * TP / (TP + FN) and +P equal to 100 * TP / (TP + FP), each within 0.01 percentage
    points of the value worked out by hand.
    """
    stats = record_statistics(RecordCounts(record="100", tp=tp, fn=fn, fp=fp))

    assert stats.record == "100"
    assert (stats.tp, stats.fn, stats.fp) == (tp, fn, fp)
    assert _close(stats.se_percent, se), f"Se {stats.se_percent}, expected {se}"
    assert _close(stats.ppv_percent, ppv), f"+P {stats.ppv_percent}, expected {ppv}"


@pytest.mark.requirement("SRS-011")
@pytest.mark.parametrize(("tp", "fn", "fp", "se", "ppv"), DEFINED_COUNTS)
def test_se_and_ppv_functions_follow_the_formulas(
    tp: int, fn: int, fp: int, se: float, ppv: float
) -> None:
    """Se and +P from counts.

    Input: TP and FN for the sensitivity, TP and FP for the positive predictivity.
    Expected: 100 * TP / (TP + FN) and 100 * TP / (TP + FP), within 0.01 percentage points.
    """
    assert _close(sensitivity_percent(tp, fn), se)
    assert _close(positive_predictivity_percent(tp, fp), ppv)


@pytest.mark.requirement("SRS-011")
def test_se_uses_false_negatives_and_ppv_uses_false_positives() -> None:
    """Se and +P are not swapped.

    Input: TP = 60, FN = 40, FP = 20.
    Expected: Se = 60.00% (from FN) and +P = 75.00% (from FP); the values differ by 15
    percentage points, so that exchanging FN and FP cannot pass.
    """
    stats = record_statistics(RecordCounts(record="200", tp=60, fn=40, fp=20))

    assert _close(stats.se_percent, 60.0)
    assert _close(stats.ppv_percent, 75.0)


@pytest.mark.requirement("SRS-011")
def test_values_are_in_percent() -> None:
    """Se and +P are reported in percent, not as fractions.

    Input: TP = 1, FN = 1, FP = 3.
    Expected: Se = 50.00 and +P = 25.00 (not 0.5 and 0.25).
    """
    stats = record_statistics(RecordCounts(record="101", tp=1, fn=1, fp=3))

    assert _close(stats.se_percent, 50.0)
    assert _close(stats.ppv_percent, 25.0)


@pytest.mark.requirement("SRS-011")
def test_record_without_reference_beats_has_undefined_se() -> None:
    """TP + FN = 0: Se is not defined.

    Input: a record with TP = 0, FN = 0 and FP = 4 (no scored reference beat, four false
    detections).
    Expected: Se is reported as not defined (``None``), neither 0 nor 100; +P has a non-zero
    denominator and is 0.00%.
    """
    stats = record_statistics(RecordCounts(record="300", tp=0, fn=0, fp=4))

    assert stats.se_percent is None
    assert _close(stats.ppv_percent, 0.0)
    assert sensitivity_percent(0, 0) is None


@pytest.mark.requirement("SRS-011")
def test_record_without_detections_has_undefined_ppv() -> None:
    """TP + FP = 0: +P is not defined.

    Input: a record with TP = 0, FN = 7 and FP = 0 (seven scored reference beats, no scored
    detection).
    Expected: +P is reported as not defined (``None``), neither 0 nor 100; Se has a non-zero
    denominator and is 0.00%.
    """
    stats = record_statistics(RecordCounts(record="301", tp=0, fn=7, fp=0))

    assert stats.ppv_percent is None
    assert _close(stats.se_percent, 0.0)
    assert positive_predictivity_percent(0, 0) is None


@pytest.mark.requirement("SRS-011")
def test_record_with_all_counts_zero_has_both_values_undefined() -> None:
    """TP = FN = FP = 0: neither value is defined.

    Input: a record with no scored reference beat and no scored detection.
    Expected: Se and +P are both reported as not defined (``None``); the counts are reported
    as zero.
    """
    stats = record_statistics(RecordCounts(record="302", tp=0, fn=0, fp=0))

    assert stats.se_percent is None
    assert stats.ppv_percent is None
    assert (stats.tp, stats.fn, stats.fp) == (0, 0, 0)


@pytest.mark.requirement("SRS-011")
@pytest.mark.parametrize(
    ("tp", "fn", "fp"),
    [
        pytest.param(0, 1, 0, id="one-false-negative"),
        pytest.param(0, 0, 1, id="one-false-positive"),
        pytest.param(1, 0, 0, id="one-true-positive"),
    ],
)
def test_smallest_non_zero_denominator_gives_a_defined_value(tp: int, fn: int, fp: int) -> None:
    """Boundary of "denominator is zero": a denominator of 1 is defined.

    Input: counts with exactly one event (one FN, one FP or one TP).
    Expected: Se is defined exactly when TP + FN = 1 and +P exactly when TP + FP = 1; the
    defined value is 0.00% without a true positive and 100.00% with one. The value whose
    denominator is 0 is not defined.
    """
    stats = record_statistics(RecordCounts(record="303", tp=tp, fn=fn, fp=fp))

    if tp + fn == 0:
        assert stats.se_percent is None
    else:
        assert _close(stats.se_percent, 100.0 * tp)
    if tp + fp == 0:
        assert stats.ppv_percent is None
    else:
        assert _close(stats.ppv_percent, 100.0 * tp)


@pytest.mark.requirement("SRS-011")
def test_gross_values_come_from_summed_counts_and_averages_from_record_values() -> None:
    """Gross and average statistics differ, and each follows its own formula.

    Input: two records, A with TP = 1000, FN = 0, FP = 0 (Se 100%, +P 100%) and B with
    TP = 10, FN = 10, FP = 30 (Se 50%, +P 25%).
    Expected: summed counts TP = 1010, FN = 10, FP = 30; gross Se = 1010 / 1020 = 99.0196%
    and gross +P = 1010 / 1040 = 97.1154%; average Se = (100 + 50) / 2 = 75.00% and average
    +P = (100 + 25) / 2 = 62.50%. Both records count in both averages.
    """
    aggregate = aggregate_statistics(
        [
            RecordCounts(record="A", tp=1000, fn=0, fp=0),
            RecordCounts(record="B", tp=10, fn=10, fp=30),
        ]
    )

    assert aggregate.n_records == 2
    assert (aggregate.tp, aggregate.fn, aggregate.fp) == (1010, 10, 30)
    assert _close(aggregate.gross_se_percent, 99.019608)
    assert _close(aggregate.gross_ppv_percent, 97.115385)
    assert _close(aggregate.average_se_percent, 75.0)
    assert _close(aggregate.average_ppv_percent, 62.5)
    assert aggregate.n_se_defined == 2
    assert aggregate.n_ppv_defined == 2


@pytest.mark.requirement("SRS-011")
def test_record_with_undefined_se_is_excluded_from_the_se_average() -> None:
    """The verification case of SRS-011: a record with TP + FN = 0 in the set.

    Input: three records, A with TP = 900, FN = 100, FP = 100 (Se 90%, +P 90%), B with
    TP = 80, FN = 20, FP = 0 (Se 80%, +P 100%) and C with TP = 0, FN = 0, FP = 4 (Se not
    defined, +P 0%).
    Expected: the Se of C is not defined; average Se = (90 + 80) / 2 = 85.00%, over two
    records (it would be 56.67% with C counted as 0% and 90.00% with C counted as 100%);
    average +P = (90 + 100 + 0) / 3 = 63.3333%, over three records; gross Se =
    980 / 1100 = 89.0909% and gross +P = 980 / 1084 = 90.4059%, with the counts of C
    included in the sums.
    """
    counts = [
        RecordCounts(record="A", tp=900, fn=100, fp=100),
        RecordCounts(record="B", tp=80, fn=20, fp=0),
        RecordCounts(record="C", tp=0, fn=0, fp=4),
    ]

    per_record = [record_statistics(c) for c in counts]
    aggregate = aggregate_statistics(counts)

    assert per_record[2].se_percent is None
    assert _close(per_record[2].ppv_percent, 0.0)
    assert aggregate.n_records == 3
    assert (aggregate.tp, aggregate.fn, aggregate.fp) == (980, 120, 104)
    assert _close(aggregate.average_se_percent, 85.0)
    assert aggregate.n_se_defined == 2
    assert _close(aggregate.average_ppv_percent, 63.333333)
    assert aggregate.n_ppv_defined == 3
    assert _close(aggregate.gross_se_percent, 89.090909)
    assert _close(aggregate.gross_ppv_percent, 90.405904)


@pytest.mark.requirement("SRS-011")
def test_record_with_undefined_ppv_is_excluded_from_the_ppv_average() -> None:
    """A record with TP + FP = 0 in the set.

    Input: three records, A with TP = 900, FN = 100, FP = 100 (Se 90%, +P 90%), B with
    TP = 80, FN = 20, FP = 0 (Se 80%, +P 100%) and D with TP = 0, FN = 7, FP = 0 (Se 0%, +P
    not defined).
    Expected: the +P of D is not defined; average +P = (90 + 100) / 2 = 95.00%, over two
    records; average Se = (90 + 80 + 0) / 3 = 56.6667%, over three records; gross Se =
    980 / 1107 = 88.5276% and gross +P = 980 / 1080 = 90.7407%.
    """
    counts = [
        RecordCounts(record="A", tp=900, fn=100, fp=100),
        RecordCounts(record="B", tp=80, fn=20, fp=0),
        RecordCounts(record="D", tp=0, fn=7, fp=0),
    ]

    aggregate = aggregate_statistics(counts)

    assert record_statistics(counts[2]).ppv_percent is None
    assert (aggregate.tp, aggregate.fn, aggregate.fp) == (980, 127, 100)
    assert _close(aggregate.average_ppv_percent, 95.0)
    assert aggregate.n_ppv_defined == 2
    assert _close(aggregate.average_se_percent, 56.666667)
    assert aggregate.n_se_defined == 3
    assert _close(aggregate.gross_se_percent, 88.527552)
    assert _close(aggregate.gross_ppv_percent, 90.740741)


@pytest.mark.requirement("SRS-011")
def test_undefined_record_does_not_change_the_average_wherever_it_stands() -> None:
    """The exclusion does not depend on the position of the undefined record.

    Input: the records A (Se 90%), B (Se 80%) and C (Se not defined) of the verification
    case, with C first, in the middle and last.
    Expected: average Se = 85.00% and two records in the Se average, in the three orders.
    """
    a = RecordCounts(record="A", tp=900, fn=100, fp=100)
    b = RecordCounts(record="B", tp=80, fn=20, fp=0)
    c = RecordCounts(record="C", tp=0, fn=0, fp=4)

    for counts in ([c, a, b], [a, c, b], [a, b, c]):
        aggregate = aggregate_statistics(counts)
        assert _close(aggregate.average_se_percent, 85.0)
        assert aggregate.n_se_defined == 2


@pytest.mark.requirement("SRS-011")
def test_aggregate_of_records_without_any_defined_value_is_undefined() -> None:
    """No record has a defined value: gross and average values are not defined.

    Input: two records with TP = FN = FP = 0.
    Expected: the summed counts are zero, so gross Se and gross +P have a zero denominator and
    are not defined; no per-record value exists, so average Se and average +P are not defined
    either (``None``, neither 0 nor 100), with no record in either average.
    """
    aggregate = aggregate_statistics(
        [
            RecordCounts(record="A", tp=0, fn=0, fp=0),
            RecordCounts(record="B", tp=0, fn=0, fp=0),
        ]
    )

    assert aggregate.n_records == 2
    assert (aggregate.tp, aggregate.fn, aggregate.fp) == (0, 0, 0)
    assert aggregate.gross_se_percent is None
    assert aggregate.gross_ppv_percent is None
    assert aggregate.average_se_percent is None
    assert aggregate.average_ppv_percent is None
    assert aggregate.n_se_defined == 0
    assert aggregate.n_ppv_defined == 0


@pytest.mark.requirement("SRS-011")
def test_gross_se_is_undefined_when_no_record_has_a_reference_beat() -> None:
    """Gross Se with a zero denominator, while gross +P is defined.

    Input: two records without scored reference beats, with 3 and 5 false positives.
    Expected: gross Se and average Se are not defined; gross +P = 0 / 8 = 0.00% and average
    +P = 0.00% over two records.
    """
    aggregate = aggregate_statistics(
        [
            RecordCounts(record="A", tp=0, fn=0, fp=3),
            RecordCounts(record="B", tp=0, fn=0, fp=5),
        ]
    )

    assert aggregate.gross_se_percent is None
    assert aggregate.average_se_percent is None
    assert aggregate.n_se_defined == 0
    assert _close(aggregate.gross_ppv_percent, 0.0)
    assert _close(aggregate.average_ppv_percent, 0.0)
    assert aggregate.n_ppv_defined == 2


@pytest.mark.requirement("SRS-011")
def test_aggregate_of_a_single_record_equals_that_record() -> None:
    """A set of one record.

    Input: one record with TP = 1859, FN = 3, FP = 187.
    Expected: gross and average values are both equal to the record values, Se = 99.8389%
    and +P = 90.8602%.
    """
    aggregate = aggregate_statistics([RecordCounts(record="108", tp=1859, fn=3, fp=187)])

    assert aggregate.n_records == 1
    assert _close(aggregate.gross_se_percent, 99.838883)
    assert _close(aggregate.average_se_percent, 99.838883)
    assert _close(aggregate.gross_ppv_percent, 90.860215)
    assert _close(aggregate.average_ppv_percent, 90.860215)


@pytest.mark.requirement("SRS-011")
def test_statistics_of_48_records_match_exact_rational_arithmetic() -> None:
    """A set of the size of the reference database, with one undefined record of each kind.

    Input: 48 records with counts drawn with a fixed seed (TP 1500 to 3000, FN 0 to 40, FP 0
    to 60); record 10 is given TP = FN = 0 (Se not defined) and record 20 TP = FP = 0 (+P not
    defined).
    Expected: every per-record value, the gross values and the average values equal, within
    0.01 percentage points, the values computed from the formulas of SRS-011 in exact rational
    arithmetic; the averages are taken over the 47 records that have a defined value.
    """
    rng = np.random.default_rng(11)
    tp = rng.integers(1500, 3001, size=48).tolist()
    fn = rng.integers(0, 41, size=48).tolist()
    fp = rng.integers(0, 61, size=48).tolist()
    tp[10], fn[10], fp[10] = 0, 0, 12
    tp[20], fn[20], fp[20] = 0, 9, 0
    counts = [RecordCounts(record=f"{100 + i}", tp=tp[i], fn=fn[i], fp=fp[i]) for i in range(48)]

    def percent(numerator: int, denominator: int) -> Fraction | None:
        return Fraction(100 * numerator, denominator) if denominator else None

    expected_se = [percent(tp[i], tp[i] + fn[i]) for i in range(48)]
    expected_ppv = [percent(tp[i], tp[i] + fp[i]) for i in range(48)]
    defined_se = [v for v in expected_se if v is not None]
    defined_ppv = [v for v in expected_ppv if v is not None]

    for c, se, ppv in zip(counts, expected_se, expected_ppv, strict=True):
        stats = record_statistics(c)
        if se is None:
            assert stats.se_percent is None
        else:
            assert _close(stats.se_percent, float(se)), c.record
        if ppv is None:
            assert stats.ppv_percent is None
        else:
            assert _close(stats.ppv_percent, float(ppv)), c.record

    aggregate = aggregate_statistics(counts)

    assert aggregate.n_records == 48
    assert (aggregate.tp, aggregate.fn, aggregate.fp) == (sum(tp), sum(fn), sum(fp))
    assert _close(aggregate.gross_se_percent, float(Fraction(100 * sum(tp), sum(tp) + sum(fn))))
    assert _close(aggregate.gross_ppv_percent, float(Fraction(100 * sum(tp), sum(tp) + sum(fp))))
    assert len(defined_se) == 47
    assert len(defined_ppv) == 47
    assert aggregate.n_se_defined == 47
    assert aggregate.n_ppv_defined == 47
    assert _close(aggregate.average_se_percent, float(sum(defined_se) / 47))
    assert _close(aggregate.average_ppv_percent, float(sum(defined_ppv) / 47))
