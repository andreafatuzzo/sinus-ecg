"""Signal quality on the reference databases: summaries and criteria (architecture §13.7.3).

SRS-029: the windows of the signal quality index (SRS-027) on the noise stress records, on
records 118 and 119 of the MIT-BIH Arrhythmia Database and on the three noise records are
summarised (windows, usable windows, median index) and judged against the criteria of
SRS-029, each SNR and each noise record on its own. SRS-030: the figures per record of the
MIT-BIH Arrhythmia Database, with the false negatives and false positives that lie in windows
marked not usable.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

from sinus_dsp._types import BoolArray, FloatArray
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.matching import learning_period_samples
from sinus_dsp.evaluation.noise_stress import (
    CLEAN_RECORDS,
    NOISE_RECORDS,
    NOISE_STRESS_RECORDS,
    noisy_stretches,
    snr_db,
)
from sinus_dsp.evaluation.run import EvaluationSettings, RecordEvaluation, RecordLoader
from sinus_dsp.quality import QualityWindows

#: (signal_mv, fs_hz, mains_hz) -> the windows of the signal quality index.
QualityFunction = Callable[[FloatArray, float, int], QualityWindows]

#: SRS-029: records 118 and 119 from 5:00, together: at least this share is usable (%).
CLEAN_MIN_USABLE_PERCENT: Final = 95
#: SRS-029: at 24 dB and at 18 dB, each on its own: at least this share is usable (%).
HIGH_SNR_MIN_USABLE_PERCENT: Final = 90
#: SRS-029: at 6, 0 and -6 dB, each on its own: at most this share is usable (%).
LOW_SNR_MAX_USABLE_PERCENT: Final = 20
#: SRS-029: each noise record on its own: at most this share is usable (%).
NOISE_MAX_USABLE_PERCENT: Final = 10
#: SRS-029: the SNRs with a minimum share of usable windows, in dB.
HIGH_SNRS_DB: Final = (24, 18)
#: SRS-029: the SNRs with a maximum share of usable windows, in dB.
LOW_SNRS_DB: Final = (6, 0, -6)
#: The SNRs of the noise stress records, in decreasing order, in dB.
_ALL_SNRS_DB: Final = (24, 18, 12, 6, 0, -6)
_NOISE_NAMES: Final = ("bw", "em", "ma")

#: SRS-029: the criteria, in the order of ``criteria``.
QUALITY_CRITERIA: Final = (
    "median_non_increasing",
    "median_lower_at_lowest_snr",
    "clean_usable",
    "usable_24",
    "usable_18",
    "usable_6",
    "usable_0",
    "usable_-6",
    "noise_bw",
    "noise_em",
    "noise_ma",
)


@dataclass(frozen=True)
class WindowSummary:
    """Count of the selected windows (SRS-029).

    Attributes:
        n_windows: Number of windows selected.
        n_usable: Of those, the number marked usable.
        median_index: ``statistics.median`` of their indices, or ``None`` without windows.
    """

    n_windows: int
    n_usable: int
    median_index: float | None


@dataclass(frozen=True)
class RecordQuality:
    """Signal quality of one record of the MIT-BIH Arrhythmia Database (SRS-030).

    Attributes:
        record: Name of the record.
        from_start: Summary of the windows whose first sample is at or after 5:00.
        fn_in_not_usable: False negatives inside a window marked not usable.
        fp_in_not_usable: False positives inside a window marked not usable.
    """

    record: str
    from_start: WindowSummary
    fn_in_not_usable: int
    fp_in_not_usable: int


@dataclass(frozen=True)
class QualityResults:
    """Signal quality results of the validation (SRS-029, SRS-030).

    Attributes:
        records: The records of the full report, sorted by name.
        by_snr: Summary per SNR (24, 18, 12, 6, 0, -6 dB), the two records pooled.
        clean: Records 118 and 119 from 5:00, together.
        noise_records: Summary of each of ``bw``, ``em`` and ``ma``.
        criteria: ``(criterion, passed)`` in the order of :data:`QUALITY_CRITERIA`.
    """

    records: tuple[RecordQuality, ...]
    by_snr: tuple[tuple[int, WindowSummary], ...]
    clean: WindowSummary
    noise_records: tuple[tuple[str, WindowSummary], ...]
    criteria: tuple[tuple[str, bool], ...]


def summarize_windows(windows: QualityWindows, selected: BoolArray) -> WindowSummary:
    """Count the selected windows and the usable ones, and take the median index.

    SRS-029: ``statistics.median`` of the float64 indices (the mean of the two middle values
    for an even count); ``None`` without selected windows.

    Raises:
        InvalidInputError: If ``selected`` does not have one element per window.
    """
    return summarize_pooled([(windows, selected)])


def summarize_pooled(parts: Sequence[tuple[QualityWindows, BoolArray]]) -> WindowSummary:
    """Summarise the selected windows of several inputs together (SRS-029).

    The two records of an SNR, or records 118 and 119, are summarised as one set: the counts
    are summed and the median is that of all their indices.
    """
    indices: list[float] = []
    n_usable = 0
    for windows, selected in parts:
        mask = np.asarray(selected, dtype=np.bool_)
        if mask.shape != windows.index.shape:
            raise InvalidInputError(
                f"selected has shape {mask.shape}, but there are {windows.index.shape[0]} windows"
            )
        indices.extend(float(value) for value in windows.index[mask])
        n_usable += int(np.count_nonzero(windows.usable[mask]))
    median = statistics.median(indices) if indices else None
    return WindowSummary(n_windows=len(indices), n_usable=n_usable, median_index=median)


def windows_within(windows: QualityWindows, first_sample: int, last_sample: int) -> BoolArray:
    """Select the windows that lie entirely in ``first_sample … last_sample`` (SRS-029).

    A window is selected if ``first >= first_sample`` and ``last <= last_sample``.
    """
    selected: BoolArray = (windows.first >= first_sample) & (windows.last <= last_sample)
    return selected


def windows_from(windows: QualityWindows, first_sample: int) -> BoolArray:
    """Select the windows whose first sample is at or after ``first_sample`` (SRS-029)."""
    selected: BoolArray = windows.first >= first_sample
    return selected


def count_in_not_usable(samples: Sequence[int], windows: QualityWindows) -> int:
    """Count the samples that lie in at least one window marked not usable (SRS-030).

    A sample ``s`` counts if ``first <= s <= last`` for some window marked not usable,
    whatever the start of the window. Each sample is counted once.
    """
    unique = np.unique(np.asarray(list(samples), dtype=np.int64))
    unusable = ~np.asarray(windows.usable, dtype=np.bool_)
    first = windows.first[unusable]
    last = windows.last[unusable]
    if unique.size == 0 or first.size == 0:
        return 0
    # Windows have one length and increasing starts, so ``last`` is increasing too: the
    # first window that ends at or after a sample is the one that starts earliest.
    position = np.searchsorted(last, unique, side="left")
    inside = position < first.size
    covered = np.zeros(unique.shape, dtype=np.bool_)
    covered[inside] = first[position[inside]] <= unique[inside]
    return int(np.count_nonzero(covered))


def record_quality(
    record: str,
    windows: QualityWindows,
    fs_hz: float,
    false_negatives: Sequence[int],
    false_positives: Sequence[int],
) -> RecordQuality:
    """The quality figures of one record of the MIT-BIH Arrhythmia Database (SRS-030).

    The windows from 5:00 (``learning_period_samples``) are summarised; the false negatives
    and false positives are those of the record's evaluation.
    """
    start = learning_period_samples(fs_hz)
    return RecordQuality(
        record=record,
        from_start=summarize_windows(windows, windows_from(windows, start)),
        fn_in_not_usable=count_in_not_usable(false_negatives, windows),
        fp_in_not_usable=count_in_not_usable(false_positives, windows),
    )


def quality_criteria(
    by_snr: Sequence[tuple[int, WindowSummary]],
    clean: WindowSummary,
    noise_records: Sequence[tuple[str, WindowSummary]],
) -> tuple[tuple[str, bool], ...]:
    """Judge the summaries against the criteria of SRS-029.

    Each criterion is true only if every summary it uses has at least one window. Shares
    are compared on integers. The SNRs and the noise records are judged each on its own.

    Returns:
        ``(criterion, passed)`` in the order of :data:`QUALITY_CRITERIA`.
    """
    snr = dict(by_snr)
    noise = dict(noise_records)

    medians: list[float] = []
    for level in _ALL_SNRS_DB:
        summary = snr.get(level)
        if summary is None or summary.n_windows == 0 or summary.median_index is None:
            break
        medians.append(summary.median_index)
    complete = len(medians) == len(_ALL_SNRS_DB)

    def at_least(summary: WindowSummary | None, percent: int) -> bool:
        return (
            summary is not None
            and summary.n_windows > 0
            and 100 * summary.n_usable >= percent * summary.n_windows
        )

    def at_most(summary: WindowSummary | None, percent: int) -> bool:
        return (
            summary is not None
            and summary.n_windows > 0
            and 100 * summary.n_usable <= percent * summary.n_windows
        )

    result: list[tuple[str, bool]] = [
        (
            "median_non_increasing",
            complete and all(a >= b for a, b in zip(medians, medians[1:], strict=False)),
        ),
        ("median_lower_at_lowest_snr", complete and medians[-1] < medians[0]),
        ("clean_usable", at_least(clean, CLEAN_MIN_USABLE_PERCENT)),
    ]
    for level in HIGH_SNRS_DB:
        result.append((f"usable_{level}", at_least(snr.get(level), HIGH_SNR_MIN_USABLE_PERCENT)))
    for level in LOW_SNRS_DB:
        result.append((f"usable_{level}", at_most(snr.get(level), LOW_SNR_MAX_USABLE_PERCENT)))
    for name in _NOISE_NAMES:
        result.append((f"noise_{name}", at_most(noise.get(name), NOISE_MAX_USABLE_PERCENT)))
    return tuple(result)


def evaluate_quality(
    mitdb_dir: Path,
    nstdb_dir: Path,
    evaluations: Sequence[RecordEvaluation],
    settings: EvaluationSettings,
    *,
    quality: QualityFunction,
    loader: RecordLoader,
    noise_loader: RecordLoader,
) -> QualityResults:
    """Run the signal quality index on the reference records and judge the criteria.

    SRS-029, SRS-030 (architecture §13.7.4, step 5): every record of ``evaluations`` is loaded
    again with ``loader`` (one record in memory at a time) and gets its
    :class:`RecordQuality`, with the false negatives and false positives of its evaluation;
    records 118 and 119 also give the windows from 5:00 for the clean summary. Each noise
    stress record gives the windows that lie entirely in a noisy stretch, pooled per SNR. Each
    record of ``NOISE_RECORDS`` is loaded with ``noise_loader`` and summarised over all its
    windows.
    """
    records: list[RecordQuality] = []
    clean_parts: list[tuple[QualityWindows, BoolArray]] = []
    for evaluation in sorted(evaluations, key=lambda entry: entry.record):
        record = loader(Path(mitdb_dir) / evaluation.record, settings.channel)
        windows = quality(record.signal_mv, record.fs_hz, settings.mains_hz)
        records.append(
            record_quality(
                evaluation.record,
                windows,
                record.fs_hz,
                evaluation.false_negatives,
                evaluation.false_positives,
            )
        )
        if evaluation.record in CLEAN_RECORDS:
            start = learning_period_samples(record.fs_hz)
            clean_parts.append((windows, windows_from(windows, start)))

    snr_parts: dict[int, list[tuple[QualityWindows, BoolArray]]] = {}
    for name in NOISE_STRESS_RECORDS:
        record = loader(Path(nstdb_dir) / name, settings.channel)
        windows = quality(record.signal_mv, record.fs_hz, settings.mains_hz)
        selected = np.zeros(windows.index.shape, dtype=np.bool_)
        for first, last in noisy_stretches(record.n_samples, record.fs_hz):
            selected |= windows_within(windows, first, last)
        snr_parts.setdefault(snr_db(name), []).append((windows, selected))
    by_snr = [
        (level, summarize_pooled(snr_parts[level])) for level in sorted(snr_parts, reverse=True)
    ]

    noise_records: list[tuple[str, WindowSummary]] = []
    for name in NOISE_RECORDS:
        record = noise_loader(Path(nstdb_dir) / name, settings.channel)
        windows = quality(record.signal_mv, record.fs_hz, settings.mains_hz)
        everything = np.ones(windows.index.shape, dtype=np.bool_)
        noise_records.append((name, summarize_windows(windows, everything)))

    return build_quality_results(records, by_snr, summarize_pooled(clean_parts), noise_records)


def build_quality_results(
    records: Sequence[RecordQuality],
    by_snr: Sequence[tuple[int, WindowSummary]],
    clean: WindowSummary,
    noise_records: Sequence[tuple[str, WindowSummary]],
) -> QualityResults:
    """Assemble the results: records sorted by name, and the criteria (SRS-029, SRS-030)."""
    return QualityResults(
        records=tuple(sorted(records, key=lambda entry: entry.record)),
        by_snr=tuple(by_snr),
        clean=clean,
        noise_records=tuple(noise_records),
        criteria=quality_criteria(by_snr, clean, noise_records),
    )
