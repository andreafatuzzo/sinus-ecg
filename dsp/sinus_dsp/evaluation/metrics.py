"""Detection statistics from the counts of the matching (SRS-011, architecture §8.9).

Sensitivity ``Se = 100 * TP / (TP + FN)`` and positive predictivity
``+P = 100 * TP / (TP + FP)``, in percent, per record; gross values from the summed counts;
and averages of the per-record values. A value whose denominator is zero is not defined: it
is ``None``, never 0 or 100, and it is left out of the averages.

Every value is computed as ``(100 * tp) / denominator`` on Python integers. The integer true
division of Python is correctly rounded, so each value is the float64 nearest to the exact
quotient on every machine. Averages use ``math.fsum``, which is exact before its final
rounding, so they do not depend on the order of the records. Values are not rounded to
decimal places here; reports do that when they format them.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass

from sinus_dsp.errors import InvalidInputError


@dataclass(frozen=True)
class RecordCounts:
    """Counts of one record.

    Attributes:
        record: Name of the record.
        tp: True positives.
        fn: False negatives.
        fp: False positives.
    """

    record: str
    tp: int
    fn: int
    fp: int


@dataclass(frozen=True)
class RecordStatistics:
    """Counts and statistics of one record (SRS-011).

    Attributes:
        record: Name of the record.
        tp: True positives.
        fn: False negatives.
        fp: False positives.
        se_percent: Sensitivity in percent, or ``None`` when not defined (``tp + fn == 0``).
        ppv_percent: Positive predictivity in percent, or ``None`` when not defined
            (``tp + fp == 0``).
    """

    record: str
    tp: int
    fn: int
    fp: int
    se_percent: float | None
    ppv_percent: float | None


@dataclass(frozen=True)
class AggregateStatistics:
    """Statistics of a set of records (SRS-011).

    Attributes:
        n_records: Number of records.
        tp: Sum of the true positives.
        fn: Sum of the false negatives.
        fp: Sum of the false positives.
        gross_se_percent: Sensitivity of the summed counts, or ``None`` when not defined.
        gross_ppv_percent: Positive predictivity of the summed counts, or ``None`` when not
            defined.
        average_se_percent: Mean of the defined per-record sensitivities, or ``None`` when no
            record has a defined value.
        average_ppv_percent: Mean of the defined per-record positive predictivities, or
            ``None`` when no record has a defined value.
        n_se_defined: Number of records included in the sensitivity average.
        n_ppv_defined: Number of records included in the positive predictivity average.
    """

    n_records: int
    tp: int
    fn: int
    fp: int
    gross_se_percent: float | None
    gross_ppv_percent: float | None
    average_se_percent: float | None
    average_ppv_percent: float | None
    n_se_defined: int
    n_ppv_defined: int


def sensitivity_percent(tp: int, fn: int) -> float | None:
    """Return the sensitivity ``100 * tp / (tp + fn)`` in percent.

    SRS-011: the value is not defined, and ``None`` is returned, when ``tp + fn`` is zero.

    Raises:
        InvalidInputError: If a count is negative or is not an integer.
    """
    return _percent(_count(tp, "tp"), _count(fn, "fn"))


def positive_predictivity_percent(tp: int, fp: int) -> float | None:
    """Return the positive predictivity ``100 * tp / (tp + fp)`` in percent.

    SRS-011: the value is not defined, and ``None`` is returned, when ``tp + fp`` is zero.

    Raises:
        InvalidInputError: If a count is negative or is not an integer.
    """
    return _percent(_count(tp, "tp"), _count(fp, "fp"))


def record_statistics(counts: RecordCounts) -> RecordStatistics:
    """Return the counts of a record with its sensitivity and positive predictivity.

    SRS-011: TP, FN, FP, Se and +P of the record; a value whose denominator is zero is
    ``None``.

    Raises:
        InvalidInputError: If a count is negative or is not an integer.
    """
    tp = _count(counts.tp, "tp", counts.record)
    fn = _count(counts.fn, "fn", counts.record)
    fp = _count(counts.fp, "fp", counts.record)
    return RecordStatistics(
        record=counts.record,
        tp=tp,
        fn=fn,
        fp=fp,
        se_percent=_percent(tp, fn),
        ppv_percent=_percent(tp, fp),
    )


def aggregate_statistics(counts: Sequence[RecordCounts]) -> AggregateStatistics:
    """Return the gross and the average statistics of a set of records.

    SRS-011: the gross Se and +P are computed from the summed counts; the average Se and +P
    are the means of the per-record values, from which the values that are not defined are
    left out. An empty set gives zero counts and ``None`` everywhere.

    Raises:
        InvalidInputError: If a count is negative or is not an integer, or if two entries
            have the same record name.
    """
    names: set[str] = set()
    statistics: list[RecordStatistics] = []
    for entry in counts:
        if entry.record in names:
            raise InvalidInputError(f"duplicate record name: {entry.record!r}")
        names.add(entry.record)
        statistics.append(record_statistics(entry))

    tp = sum(entry.tp for entry in statistics)
    fn = sum(entry.fn for entry in statistics)
    fp = sum(entry.fp for entry in statistics)
    se_values = [entry.se_percent for entry in statistics if entry.se_percent is not None]
    ppv_values = [entry.ppv_percent for entry in statistics if entry.ppv_percent is not None]
    return AggregateStatistics(
        n_records=len(statistics),
        tp=tp,
        fn=fn,
        fp=fp,
        gross_se_percent=_percent(tp, fn),
        gross_ppv_percent=_percent(tp, fp),
        average_se_percent=_mean(se_values),
        average_ppv_percent=_mean(ppv_values),
        n_se_defined=len(se_values),
        n_ppv_defined=len(ppv_values),
    )


def _count(value: int, name: str, record: str | None = None) -> int:
    """Check a count and return it as an ``int``."""
    where = name if record is None else f"{name} of record {record!r}"
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise InvalidInputError(f"{where} is not an integer: {value!r}")
    count = int(value)
    if count < 0:
        raise InvalidInputError(f"{where} is negative: {count}")
    return count


def _percent(tp: int, other: int) -> float | None:
    """``100 * tp / (tp + other)``, correctly rounded, or ``None`` for a zero denominator."""
    denominator = tp + other
    if denominator == 0:
        return None
    return (100 * tp) / denominator


def _mean(values: Sequence[float]) -> float | None:
    """Mean of the values, or ``None`` when there is none."""
    if not values:
        return None
    return math.fsum(values) / len(values)
