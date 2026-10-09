"""Unit tests: start-of-stream evaluation (architecture §13.7.2)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sinus_dsp._types import FloatArray
from sinus_dsp.data.records import Annotation, Record
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.run import EvaluationSettings
from sinus_dsp.evaluation.start_of_stream import (
    SEGMENT_S,
    SEGMENT_STARTS_S,
    continuation_samples,
    evaluate_segment,
    evaluate_start_of_stream,
)
from sinus_dsp.qrs import Detections

FS = 360.0
SEG = 21600
L = 720
CONT = 2876
SETTINGS = EvaluationSettings()


def make_record(
    name: str = "r",
    n_samples: int = 3 * SEG,
    beats: Sequence[int] = (),
    others: Sequence[tuple[int, str]] = (),
    channel: int = 0,
) -> Record:
    return Record(
        name=name,
        channel=channel,
        signal_name="MLII",
        fs_hz=FS,
        signal_mv=np.arange(n_samples, dtype=np.float64),
        beat_samples=np.array(beats, dtype=np.int64),
        beat_symbols=tuple("N" for _ in beats),
        other_annotations=tuple(Annotation(s, sym, 0, "") for s, sym in others),
    )


def detections(indices: Sequence[int], startup: Sequence[bool] | None = None) -> Detections:
    n = len(indices)
    flags = [False] * n if startup is None else list(startup)
    idx = np.array(indices, dtype=np.int64)
    return Detections(
        indices=idx,
        startup=np.array(flags, dtype=np.bool_),
        reported_at=idx.copy(),
        peaks=idx.copy(),
        paths=("regular",) * n,
        initialisations=np.array([L - 1], dtype=np.int64),
    )


class Recorder:
    """A detector that reports the given segment-relative detections and records its calls."""

    def __init__(self, result: Detections) -> None:
        self.result = result
        self.calls: list[tuple[FloatArray, float, int]] = []

    def __call__(self, signal_mv: FloatArray, fs_hz: float, mains_hz: int) -> Detections:
        self.calls.append((signal_mv, fs_hz, mains_hz))
        return self.result


def test_constants() -> None:
    assert SEGMENT_S == 60
    assert SEGMENT_STARTS_S == tuple(range(0, 1800, 60))
    assert len(SEGMENT_STARTS_S) == 30


@pytest.mark.parametrize(
    ("fs", "expected"), [(125.0, 1000), (250.0, 1998), (360.0, 2876), (1000.0, 7987)]
)
def test_continuation_samples_is_the_documented_maximum_delay(fs: float, expected: int) -> None:
    assert continuation_samples(fs) == expected


def test_continuation_samples_refuses_a_bad_rate() -> None:
    with pytest.raises(InvalidInputError):
        continuation_samples(0.0)


def test_input_is_the_segment_plus_its_continuation() -> None:
    record = make_record()
    detector = Recorder(detections([]))
    evaluate_segment(record, 0, SETTINGS, detector)
    assert detector.calls[0][0].shape == (SEG + CONT,)


def test_continuation_is_cut_at_the_record_end() -> None:
    record = make_record(n_samples=2 * SEG + 100)
    detector = Recorder(detections([]))
    evaluate_segment(record, SEG, SETTINGS, detector)
    assert detector.calls[0][0].shape == (SEG + 100,)
    assert detector.calls[0][0][-1] == 2 * SEG + 99


def test_segment_ending_at_the_last_sample_has_no_continuation() -> None:
    record = make_record(n_samples=2 * SEG)
    detector = Recorder(detections([]))
    evaluate_segment(record, SEG, SETTINGS, detector)
    assert detector.calls[0][0].shape == (SEG,)


def test_detection_at_the_last_sample_is_scored_and_the_next_one_is_not() -> None:
    record = make_record(beats=[SEG - 1])
    inside = evaluate_segment(record, 0, SETTINGS, Recorder(detections([SEG - 1])))
    assert (inside.tp, inside.fn, inside.fp) == (1, 0, 0)
    # index n_seg lies in the continuation: neither a true nor a false positive
    outside = evaluate_segment(record, 0, SETTINGS, Recorder(detections([SEG - 1, SEG])))
    assert (outside.tp, outside.fn, outside.fp) == (1, 0, 0)
    only = evaluate_segment(make_record(), 0, SETTINGS, Recorder(detections([SEG, SEG + 500])))
    assert (only.tp, only.fn, only.fp) == (0, 0, 0)


def test_beat_detected_only_in_the_continuation_window_is_a_true_positive() -> None:
    # the detection index lies in the segment but is reported after its end: the fake returns
    # it as the longer input allows
    record = make_record(beats=[SEG - 50])
    det = detections([SEG - 50])
    det = Detections(
        indices=det.indices,
        startup=det.startup,
        reported_at=det.indices + 1000,
        peaks=det.peaks,
        paths=det.paths,
        initialisations=det.initialisations,
    )
    result = evaluate_segment(record, 0, SETTINGS, Recorder(det))
    assert (result.tp, result.fn, result.fp) == (1, 0, 0)


def test_startup_detection_in_the_segment_stays_unscored() -> None:
    record = make_record(beats=[3000])
    det = detections([3000, SEG + 10], [True, True])
    result = evaluate_segment(record, 0, SETTINGS, Recorder(det))
    assert (result.tp, result.fn, result.fp) == (0, 1, 0)


def test_reference_beats_of_the_continuation_are_not_scored() -> None:
    record = make_record(beats=[SEG + 100, SEG + 200])
    result = evaluate_segment(record, 0, SETTINGS, Recorder(detections([])))
    assert (result.tp, result.fn, result.fp) == (0, 0, 0)


def test_record_fields_of_the_continuation(tmp_path: Path) -> None:
    # 3 segments of 60 s in a record of 3 * SEG + 3000: only the last one has a full continuation
    record = make_record("a", n_samples=3 * SEG + 1000)
    result = evaluate_start_of_stream(
        tmp_path,
        ["a"],
        SETTINGS,
        detector=SegmentDetector([]),
        loader=Loader({"a": record}),
        starts_s=[0, 60, 120],
    )
    (entry,) = result.records
    assert entry.continuation_samples == CONT
    assert entry.short_continuations == 1  # the third segment has 1000 samples left


def test_short_continuation_is_counted_only_when_below_the_full_length(tmp_path: Path) -> None:
    record = make_record("a", n_samples=SEG + CONT)
    result = evaluate_start_of_stream(
        tmp_path,
        ["a"],
        SETTINGS,
        detector=SegmentDetector([]),
        loader=Loader({"a": record}),
        starts_s=[0],
    )
    assert result.records[0].short_continuations == 0


def test_record_defaults_of_the_new_fields() -> None:
    from sinus_dsp.evaluation.metrics import RecordCounts
    from sinus_dsp.evaluation.start_of_stream import StartOfStreamRecord

    entry = StartOfStreamRecord("a", "MLII", 1, RecordCounts("a", 0, 0, 0))
    assert (entry.continuation_samples, entry.short_continuations) == (0, 0)


def test_segment_is_processed_on_its_own() -> None:
    record = make_record()
    detector = Recorder(detections([]))
    evaluate_segment(record, SEG, SETTINGS, detector)
    ((signal, fs, mains),) = detector.calls
    assert signal.shape == (SEG + CONT,)
    assert signal[0] == SEG and signal[-1] == 2 * SEG + CONT - 1
    assert (fs, mains) == (FS, 60)


def test_reference_beats_are_those_inside_the_segment() -> None:
    # beats at -1, 0, last and one past the segment (in segment samples)
    beats = [SEG - 1, SEG + 1000, 2 * SEG - 1, 2 * SEG]
    record = make_record(beats=beats)
    detector = Recorder(detections([1000, SEG - 1]))
    result = evaluate_segment(record, SEG, SETTINGS, detector)
    assert (result.tp, result.fn, result.fp) == (2, 0, 0)


def test_only_reliable_detections_count() -> None:
    record = make_record(beats=[3000, 4000, 5000])
    # 3000 and 4000 detected as start-up (not scored), 5000 reliable; false positive marked
    # start-up does not count either
    det = detections([3000, 4000, 5000, 9000], [True, True, False, True])
    result = evaluate_segment(record, 0, SETTINGS, Recorder(det))
    assert (result.tp, result.fn, result.fp) == (1, 2, 0)


def test_reliable_false_positive_is_counted() -> None:
    record = make_record(beats=[3000])
    result = evaluate_segment(record, 0, SETTINGS, Recorder(detections([3000, 9000])))
    assert (result.tp, result.fn, result.fp) == (1, 0, 1)


def test_startup_period_is_not_scored() -> None:
    record = make_record(beats=[100, L + 200, L + 400])
    result = evaluate_segment(record, 0, SETTINGS, Recorder(detections([])))
    assert result.fn == 2  # the beat inside [0, L - 1] is not scored


def test_segment_start_shifts_the_start_up_period() -> None:
    record = make_record(beats=[SEG + 100, SEG + L + 100])
    result = evaluate_segment(record, SEG, SETTINGS, Recorder(detections([])))
    assert (result.tp, result.fn, result.fp) == (0, 1, 0)


def test_episode_before_the_segment_is_clipped_to_it() -> None:
    # episode from 0.5 segment before to 2000 samples into the segment
    record = make_record(
        beats=[SEG + 1500, SEG + 3000],
        others=[(SEG // 2, "["), (SEG + 2000, "]")],
    )
    result = evaluate_segment(record, SEG, SETTINGS, Recorder(detections([])))
    assert (result.tp, result.fn, result.fp) == (0, 1, 0)
    assert result.reference_excluded == 1


def test_episode_after_the_segment_start_is_clipped_to_its_end() -> None:
    record = make_record(
        beats=[SEG + 1500, 2 * SEG - 10],
        others=[(SEG + 20000, "["), (2 * SEG + 5000, "]")],
    )
    result = evaluate_segment(record, SEG, SETTINGS, Recorder(detections([1500])))
    assert (result.tp, result.fn, result.fp) == (1, 0, 0)
    assert result.reference_excluded == 1


def test_episode_outside_the_segment_has_no_effect() -> None:
    record = make_record(beats=[5000], others=[(100, "["), (300, "]")])
    result = evaluate_segment(record, SEG, SETTINGS, Recorder(detections([])))
    assert result.reference_excluded == 0 and result.fn == 0


def test_unfinished_episode_runs_to_the_end_of_the_record() -> None:
    record = make_record(beats=[SEG + 5000], others=[(SEG - 5, "[")])
    result = evaluate_segment(record, SEG, SETTINGS, Recorder(detections([])))
    assert result.reference_excluded == 1


@pytest.mark.parametrize("start", [-1, 2 * SEG + 1, 10**9])
def test_segment_that_does_not_fit_is_refused(start: int) -> None:
    record = make_record(name="rec")
    with pytest.raises(InvalidInputError, match=f"rec.*{start}"):
        evaluate_segment(record, start, SETTINGS, Recorder(detections([])))


def test_last_segment_that_just_fits() -> None:
    record = make_record()
    evaluate_segment(record, 2 * SEG, SETTINGS, Recorder(detections([])))


def test_wrong_channel_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="channel"):
        evaluate_segment(make_record(channel=1), 0, SETTINGS, Recorder(detections([])))


def test_default_detector_runs_on_a_real_input() -> None:
    record = make_record(n_samples=SEG)
    record = Record(**{**record.__dict__, "signal_mv": np.zeros(SEG)})
    result = evaluate_segment(record, 0, SETTINGS)
    assert (result.tp, result.fn, result.fp) == (0, 0, 0)


class Loader:
    def __init__(self, records: dict[str, Record]) -> None:
        self.records = records
        self.calls: list[tuple[Path, int]] = []

    def __call__(self, path: Path, channel: int) -> Record:
        self.calls.append((path, channel))
        return self.records[path.name]


class SegmentDetector:
    """Detects, in every segment, the beats at the given segment-relative samples."""

    def __init__(self, relative: Sequence[int]) -> None:
        self.relative = relative
        self.n_calls = 0

    def __call__(self, signal_mv: FloatArray, fs_hz: float, mains_hz: int) -> Detections:
        self.n_calls += 1
        return detections(self.relative)


def test_records_are_sorted_summed_and_loaded_once(tmp_path: Path) -> None:
    beats_b = [1000, SEG + 1000, 2 * SEG + 1000]
    records = {"b": make_record("b", beats=beats_b), "a": make_record("a", beats=[1000])}
    loader = Loader(records)
    detector = SegmentDetector([1000])
    result = evaluate_start_of_stream(
        tmp_path, ["b", "a"], SETTINGS, detector=detector, loader=loader, starts_s=[0, 60, 120]
    )
    assert [entry.record for entry in result.records] == ["a", "b"]
    assert [(p.name, c) for p, c in loader.calls] == [("a", 0), ("b", 0)]
    assert all(p.parent == tmp_path for p, _ in loader.calls)
    assert detector.n_calls == 6
    a, b = result.records
    assert (a.counts.tp, a.counts.fn, a.counts.fp) == (1, 0, 2)
    assert (b.counts.tp, b.counts.fn, b.counts.fp) == (3, 0, 0)
    assert a.n_segments == b.n_segments == 3
    assert a.signal_name == "MLII"
    assert result.segment_s == 60
    assert result.starts_s == (0, 60, 120)
    assert (result.statistics.tp, result.statistics.fn, result.statistics.fp) == (4, 0, 2)
    assert result.statistics.n_records == 2
    assert result.statistics.average_ppv_percent == pytest.approx((100 / 3 + 100) / 2)
    assert result.statistics.gross_ppv_percent == pytest.approx(100 * 4 / 6)


def test_default_starts_are_those_of_the_requirement(tmp_path: Path) -> None:
    short = make_record("a", n_samples=3 * SEG)
    with pytest.raises(InvalidInputError, match="does not fit"):
        evaluate_start_of_stream(
            tmp_path, ["a"], SETTINGS, detector=SegmentDetector([]), loader=Loader({"a": short})
        )
    full = make_record("a", n_samples=30 * SEG)
    detector = SegmentDetector([])
    result = evaluate_start_of_stream(
        tmp_path, ["a"], SETTINGS, detector=detector, loader=Loader({"a": full})
    )
    assert detector.n_calls == 30
    assert result.starts_s == SEGMENT_STARTS_S
    assert result.records[0].n_segments == 30


@pytest.mark.parametrize(
    "starts",
    [[], [-1], [0, 0], [60, 0], [0.5], [True], "0", [None]],
)
def test_invalid_starts_are_refused_before_loading(tmp_path: Path, starts: Any) -> None:
    loader = Loader({})
    with pytest.raises(InvalidInputError):
        evaluate_start_of_stream(tmp_path, ["a"], SETTINGS, loader=loader, starts_s=starts)
    assert loader.calls == []


@pytest.mark.parametrize("names", ["abc", ["a", "a"], ["a/b"], [1]])
def test_invalid_names_are_refused_before_loading(tmp_path: Path, names: Any) -> None:
    loader = Loader({})
    with pytest.raises(InvalidInputError):
        evaluate_start_of_stream(tmp_path, names, SETTINGS, loader=loader)
    assert loader.calls == []


def test_numpy_integer_starts_are_accepted(tmp_path: Path) -> None:
    result = evaluate_start_of_stream(
        tmp_path,
        ["a"],
        SETTINGS,
        detector=SegmentDetector([]),
        loader=Loader({"a": make_record("a")}),
        starts_s=list(np.array([0, 60])),
    )
    assert result.starts_s == (0, 60)
    assert all(type(value) is int for value in result.starts_s)
