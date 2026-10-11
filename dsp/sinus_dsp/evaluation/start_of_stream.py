"""Detection at the start of real recordings: segments of 60 s (architecture §13.7.2).

SRS-023: 60 s segments of the records of the MIT-BIH Arrhythmia Database, starting at the
first sample of each record and at each whole minute up to 29:00, are each processed as a
stream of its own. The detections marked reliable are scored with the rules of SRS-008 and
SRS-011, with the start-up period of the segment in place of the first 5 minutes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

from sinus_dsp._types import FloatArray
from sinus_dsp._units import round_samples
from sinus_dsp.data.records import Record, load_record
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.matching import (
    Episode,
    MatchResult,
    match_beats,
    match_window_samples,
    vf_episodes,
)
from sinus_dsp.evaluation.metrics import AggregateStatistics, RecordCounts, aggregate_statistics
from sinus_dsp.evaluation.run import (
    EvaluationSettings,
    RecordLoader,
    checked_record_names,
)
from sinus_dsp.pipeline import detect_marked
from sinus_dsp.qrs import Detections, detector_samples

#: SRS-023: the length of a segment, in s.
SEGMENT_S: Final = 60

#: SRS-023: the starts of the segments, in s from the record start: 0:00, 1:00, ..., 29:00.
SEGMENT_STARTS_S: Final = tuple(range(0, 1800, 60))

#: (signal_mv, fs_hz, mains_hz) -> the detections with their marks.
MarkedDetector = Callable[[FloatArray, float, int], Detections]


@dataclass(frozen=True)
class StartOfStreamRecord:
    """Start-of-stream counts of one record (SRS-023).

    Attributes:
        record: Name of the record.
        signal_name: Name of the signal evaluated, e.g. ``MLII``.
        n_segments: Number of segments evaluated.
        counts: TP, FN and FP summed over the segments of the record.
        continuation_samples: :func:`continuation_samples` at the sampling frequency of the
            record (0 when not filled).
        short_continuations: Number of segments whose continuation the end of the record
            cuts short.
    """

    record: str
    signal_name: str
    n_segments: int
    counts: RecordCounts
    continuation_samples: int = 0
    short_continuations: int = 0


@dataclass(frozen=True)
class StartOfStreamResults:
    """Results of the start-of-stream evaluation (SRS-023).

    Attributes:
        segment_s: Length of a segment, in s (:data:`SEGMENT_S`).
        starts_s: The starts used, in s from the record start.
        records: One entry per record, sorted by record name.
        statistics: :func:`aggregate_statistics` of the per-record counts: gross values over
            all the segments, averages over the records.
    """

    segment_s: int
    starts_s: tuple[int, ...]
    records: tuple[StartOfStreamRecord, ...]
    statistics: AggregateStatistics


def continuation_samples(fs_hz: float) -> int:
    """Samples of input fed after a segment: the longest delay of a detection.

    SRS-023: ``G + N + D + 1 - R`` (architecture §13.4), 2876 at 360 Hz and 1998 at 250 Hz.

    Raises:
        InvalidInputError: If ``fs_hz`` is not a positive finite number.
    """
    samples = detector_samples(fs_hz)
    return samples.relearn_after + samples.window + samples.band_delay + 1 - samples.refractory


def evaluate_segment(
    record: Record,
    start_sample: int,
    settings: EvaluationSettings,
    detector: MarkedDetector = detect_marked,
) -> MatchResult:
    """Detect and score one segment of 60 s of a record, as a stream of its own.

    SRS-023: the segment ``start_sample … start_sample + n_seg - 1`` (``n_seg`` = 60 s) is
    processed from its first sample, followed by its continuation (the record's next
    :func:`continuation_samples` samples, fewer at the record end); only the detections marked
    reliable with an index in the segment are scored. The
    reference beats are those of the record inside the segment, shifted by ``start_sample``;
    the flutter and fibrillation episodes are those of the whole record, each one that
    overlaps the segment clipped to it. The start-up period is ``[0, L - 1]`` with ``L`` the
    learning period of the detector.

    Raises:
        InvalidInputError: If the channel of the record is not the one of ``settings``, if
            the start is negative, or if the segment does not fit in the record.
    """
    if record.channel != settings.channel:
        raise InvalidInputError(
            f"record {record.name} holds channel {record.channel}, but the settings name "
            f"channel {settings.channel}"
        )
    fs_hz = record.fs_hz
    n_seg = round_samples(SEGMENT_S, fs_hz)
    if start_sample < 0 or start_sample + n_seg > record.n_samples:
        raise InvalidInputError(
            f"the segment of record {record.name} that starts at sample {start_sample} "
            f"does not fit in the record: {n_seg} samples needed, {record.n_samples} in all"
        )
    end_sample = start_sample + n_seg - 1
    extra = min(continuation_samples(fs_hz), record.n_samples - (start_sample + n_seg))
    segment = np.array(
        record.signal_mv[start_sample : start_sample + n_seg + extra], dtype=np.float64
    )
    detections = detector(segment, fs_hz, settings.mains_hz)
    reliable = detections.indices[~detections.startup & (detections.indices < n_seg)]

    beats = record.beat_samples
    reference = beats[(beats >= start_sample) & (beats <= end_sample)] - start_sample
    clipped = tuple(
        Episode(
            max(episode.start_sample, start_sample) - start_sample,
            min(episode.end_sample, end_sample) - start_sample,
        )
        for episode in vf_episodes(record.other_annotations, record.n_samples)
        if episode.start_sample <= end_sample and episode.end_sample >= start_sample
    )
    return match_beats(
        reference,
        reliable,
        window_samples=match_window_samples(fs_hz),
        start_sample=detector_samples(fs_hz).learning,
        vf=clipped,
    )


def evaluate_start_of_stream(
    database_dir: Path,
    records: Sequence[str],
    settings: EvaluationSettings,
    *,
    detector: MarkedDetector = detect_marked,
    loader: RecordLoader = load_record,
    starts_s: Sequence[int] = SEGMENT_STARTS_S,
) -> StartOfStreamResults:
    """Evaluate the segments of every record and aggregate them.

    SRS-023: each record is loaded once with ``loader(database_dir / name, settings.channel)``
    and its segments are evaluated with :func:`evaluate_segment`; the counts are summed per
    record. The records are returned sorted by name, with the aggregate statistics of the
    per-record counts (SRS-011).

    Args:
        database_dir: Folder of the database, e.g. ``data/mitdb``.
        records: Names of the records, each a valid record name given once.
        settings: Settings of the detection.
        detector: Detection function with marks.
        loader: Function that loads a record.
        starts_s: Starts of the segments, in s: non-empty, distinct non-negative integers in
            increasing order. ``run_validation`` always uses :data:`SEGMENT_STARTS_S`.

    Raises:
        InvalidInputError: If the names or the starts are invalid (before any record is
            loaded), or if a segment does not fit in its record.
    """
    names = checked_record_names(records)
    starts = _checked_starts(starts_s)
    directory = Path(database_dir)
    results: list[StartOfStreamRecord] = []
    for name in sorted(names):
        record = loader(directory / name, settings.channel)
        tp = fn = fp = short = 0
        n_seg = round_samples(SEGMENT_S, record.fs_hz)
        extra = continuation_samples(record.fs_hz)
        for start in starts:
            first = round_samples(start, record.fs_hz)
            if record.n_samples - (first + n_seg) < extra:
                short += 1
            result = evaluate_segment(record, first, settings, detector)
            tp += result.tp
            fn += result.fn
            fp += result.fp
        results.append(
            StartOfStreamRecord(
                record=record.name,
                signal_name=record.signal_name,
                n_segments=len(starts),
                counts=RecordCounts(record=record.name, tp=tp, fn=fn, fp=fp),
                continuation_samples=extra,
                short_continuations=short,
            )
        )
    return StartOfStreamResults(
        segment_s=SEGMENT_S,
        starts_s=starts,
        records=tuple(results),
        statistics=aggregate_statistics([entry.counts for entry in results]),
    )


def _checked_starts(starts_s: Sequence[int]) -> tuple[int, ...]:
    """Check the starts of the segments and return them as a tuple."""
    if isinstance(starts_s, str):
        raise InvalidInputError(f"starts_s is a string, not a sequence of starts: {starts_s!r}")
    starts = tuple(starts_s)
    if not starts:
        raise InvalidInputError("starts_s is empty")
    for value in starts:
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
            raise InvalidInputError(f"a start is not a non-negative integer: {value!r}")
    for previous, current in zip(starts, starts[1:], strict=False):
        if current <= previous:
            raise InvalidInputError(f"the starts are not in increasing order: {starts!r}")
    return tuple(int(value) for value in starts)
