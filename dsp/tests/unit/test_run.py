"""Unit tests of the evaluation run: coverage of episodes, record list, evaluation, targets.

The tests use in-memory records, or small WFDB records written in a temporary folder at
20 Hz (5:00 is sample 6000, the match window 3 samples), and a fake detector. No test uses
the network or the real databases.
"""

import random
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp._types import FloatArray, IndexArray
from sinus_dsp.data.records import Annotation, Record, load_record
from sinus_dsp.errors import InvalidInputError, MalformedFileError
from sinus_dsp.evaluation.matching import (
    Episode,
    learning_period_samples,
    match_beats,
    match_window_samples,
    vf_episodes,
)
from sinus_dsp.evaluation.metrics import RecordCounts
from sinus_dsp.evaluation.run import (
    RECORD_LIST_NAME,
    TARGET_HUNDREDTHS_OF_PERCENT,
    EvaluationSettings,
    RecordEvaluation,
    episode_coverage,
    evaluate_record,
    evaluate_records,
    meets_target,
    read_record_list,
)
from sinus_dsp.pipeline import detect_beats

FS_HZ = 20.0
START = 6000  # learning_period_samples(20)
WINDOW = 3  # match_window_samples(20)


class RecordingDetector:
    """A detector that returns fixed detections and remembers its calls."""

    def __init__(self, detections: npt.ArrayLike = ()) -> None:
        self.detections = np.array(detections, dtype=np.int64)
        self.calls: list[tuple[FloatArray, float, int]] = []

    def __call__(self, signal_mv: FloatArray, fs_hz: float, mains_hz: int) -> IndexArray:
        self.calls.append((signal_mv, fs_hz, mains_hz))
        return self.detections


def make_record(
    *,
    n_samples: int = 7000,
    beats: Sequence[int] = (),
    others: Sequence[tuple[int, str]] = (),
    name: str = "rec",
    channel: int = 0,
    fs_hz: float = FS_HZ,
) -> Record:
    return Record(
        name=name,
        channel=channel,
        signal_name="MLII",
        fs_hz=fs_hz,
        signal_mv=np.zeros(n_samples),
        beat_samples=np.array(beats, dtype=np.int64),
        beat_symbols=tuple("N" for _ in beats),
        other_annotations=tuple(
            Annotation(sample=sample, symbol=symbol, subtype=0, aux_note="")
            for sample, symbol in others
        ),
    )


def test_fixture_parameters() -> None:
    assert learning_period_samples(FS_HZ) == START
    assert match_window_samples(FS_HZ) == WINDOW


# --- episode_coverage -----------------------------------------------------------------------


def test_coverage_without_episodes() -> None:
    assert episode_coverage((), 0, 100) == (0, 0)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (10, 20, (0, 0)),  # ends before the range
        (10, 49, (0, 0)),  # ends on the sample before the range
        (10, 50, (1, 1)),  # ends on the first sample
        (10, 60, (1, 11)),  # contains the first sample: counted from it
        (50, 60, (1, 11)),  # starts on the first sample
        (60, 70, (1, 11)),  # inside
        (60, 60, (1, 1)),  # a single sample inside
        (90, 120, (1, 11)),  # crosses the last sample
        (100, 120, (1, 1)),  # starts on the last sample
        (101, 120, (0, 0)),  # starts after the last sample
        (10, 200, (1, 51)),  # covers the whole range
    ],
)
def test_coverage_of_one_episode(start: int, end: int, expected: tuple[int, int]) -> None:
    assert episode_coverage((Episode(start, end),), 50, 100) == expected


def test_coverage_of_an_empty_range() -> None:
    episodes = (Episode(0, 10), Episode(20, 30))
    assert episode_coverage(episodes, 25, 24) == (0, 0)
    assert episode_coverage(episodes, 100, 0) == (0, 0)


def test_shared_sample_is_counted_once() -> None:
    # "[" at 10, "]" at 20, "[" at 20, "]" at 30: two episodes that share sample 20.
    episodes = (Episode(10, 20), Episode(20, 30))
    assert episode_coverage(episodes, 0, 100) == (2, 21)
    # A single-sample episode on the shared sample adds no sample, but counts.
    assert episode_coverage((Episode(10, 20), Episode(20, 20)), 0, 100) == (2, 11)
    # The first episode ends before the range; the second starts on its last sample.
    assert episode_coverage(episodes, 20, 100) == (2, 11)
    assert episode_coverage(episodes, 21, 100) == (1, 10)


def test_several_episodes_before_inside_and_after() -> None:
    episodes = (Episode(0, 5), Episode(8, 12), Episode(15, 18), Episode(30, 40))
    assert episode_coverage(episodes, 10, 35) == (3, 3 + 4 + 6)


def test_coverage_of_record_207_as_described_in_the_design() -> None:
    """Five episodes end before 5:00 (the last at 280.9 s); one lies from 554682 to 589926."""
    start = learning_period_samples(360.0)
    earlier = (
        Episode(30000, 31000),
        Episode(40000, 42000),
        Episode(60000, 61000),
        Episode(80000, 90000),
        Episode(95000, 101124),
    )
    episodes = (*earlier, Episode(554682, 589926))
    assert episode_coverage(episodes, start, 650000 - 1) == (1, 35245)
    assert round(35245 / 360.0, 1) == 97.9


def _coverage_oracle(episodes: Sequence[Episode], first: int, last: int) -> tuple[int, int]:
    """The two figures from their definitions, with sets of samples."""
    in_range = set(range(first, last + 1))
    count = 0
    covered: set[int] = set()
    for episode in episodes:
        inside = in_range & set(range(episode.start_sample, episode.end_sample + 1))
        count += 1 if inside else 0
        covered |= inside
    return count, len(covered)


def test_coverage_agrees_with_the_definitions_on_random_episodes() -> None:
    generator = random.Random(20260930)
    for _ in range(3000):
        n_samples = generator.randint(1, 60)
        samples = sorted(generator.randint(0, 70) for _ in range(generator.randint(0, 8)))
        annotations = [
            Annotation(sample=sample, symbol=generator.choice("[]+"), subtype=0, aux_note="")
            for sample in samples
        ]
        episodes = vf_episodes(annotations, n_samples)
        first = generator.randint(-5, 70)
        last = generator.randint(first - 3, 75)
        assert episode_coverage(episodes, first, last) == _coverage_oracle(episodes, first, last)


# --- read_record_list ------------------------------------------------------------------------


def write_list(folder: Path, content: bytes) -> Path:
    (folder / RECORD_LIST_NAME).write_bytes(content)
    return folder


def test_record_list_name() -> None:
    assert RECORD_LIST_NAME == "RECORDS"


def test_record_list_in_file_order_is_returned_sorted(tmp_path: Path) -> None:
    write_list(tmp_path, b"119\n100\n118\n")
    assert read_record_list(tmp_path) == ("100", "118", "119")


def test_record_list_blank_lines_spaces_and_carriage_returns(tmp_path: Path) -> None:
    write_list(tmp_path, b"\n  105 \r\n\r\n\t\n100\r\n  \n118e_6")
    assert read_record_list(tmp_path) == ("100", "105", "118e_6")


def test_record_list_is_sorted_in_code_point_order(tmp_path: Path) -> None:
    write_list(tmp_path, b"b\nB\n_\n9\n10\n")
    assert read_record_list(tmp_path) == ("10", "9", "B", "_", "b")


@pytest.mark.parametrize(
    ("content", "line", "reason"),
    [
        (b"100\n../100\n", 2, "invalid record name: '../100'"),
        (b"100.dat\n", 1, "invalid record name: '100.dat'"),
        (b"100\n\n10 0\n", 3, "invalid record name: '10 0'"),
        (b"100\n101\n100\n", 3, "record listed twice: 100"),
        (b"100\n 100\r\n", 2, "record listed twice: 100"),
    ],
)
def test_malformed_record_list(tmp_path: Path, content: bytes, line: int, reason: str) -> None:
    write_list(tmp_path, content)
    with pytest.raises(MalformedFileError) as caught:
        read_record_list(tmp_path)
    assert caught.value.path == str(tmp_path / RECORD_LIST_NAME)
    assert caught.value.line == line
    assert caught.value.reason == reason


@pytest.mark.parametrize("content", [b"", b"\n\n", b"  \r\n\t\n"])
def test_record_list_without_records(tmp_path: Path, content: bytes) -> None:
    write_list(tmp_path, content)
    with pytest.raises(MalformedFileError) as caught:
        read_record_list(tmp_path)
    assert caught.value.line is None
    assert caught.value.reason == "the record list has no record"


def test_record_list_not_utf8(tmp_path: Path) -> None:
    write_list(tmp_path, b"100\n\xff\n")
    with pytest.raises(MalformedFileError, match="not UTF-8 text"):
        read_record_list(tmp_path)


def test_absent_record_list_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_record_list(tmp_path)


# --- evaluate_record ------------------------------------------------------------------------


def test_settings_defaults() -> None:
    assert EvaluationSettings() == EvaluationSettings(channel=0, mains_hz=60)
    assert TARGET_HUNDREDTHS_OF_PERCENT == 9950


def test_default_detector_is_the_pipeline() -> None:
    assert evaluate_record.__defaults__ == (detect_beats,)
    assert evaluate_records.__kwdefaults__ == {"detector": detect_beats, "loader": load_record}


def test_counts_of_a_record_and_the_call_of_the_detector() -> None:
    record = make_record(beats=[5990, 6100, 6200, 6300, 6400])
    detector = RecordingDetector([5991, 6101, 6202, 6350])
    evaluation = evaluate_record(record, EvaluationSettings(mains_hz=50), detector)
    # 5990 is before 5:00; 5991 is the last detection before 5:00 and is dropped, because
    # the first scored beat 6100 is not within 3 samples of it.
    assert evaluation.counts == RecordCounts(record="rec", tp=2, fn=2, fp=1)
    assert len(detector.calls) == 1
    signal, fs_hz, mains_hz = detector.calls[0]
    assert signal is record.signal_mv
    assert fs_hz == 20.0
    assert mains_hz == 50
    assert evaluation.record == "rec"
    assert evaluation.signal_name == "MLII"
    assert evaluation.fs_hz == 20.0


def test_counts_equal_the_matching() -> None:
    generator = np.random.default_rng(7)
    beats = np.unique(generator.integers(5000, 7000, size=80))
    detections = np.unique(generator.integers(5000, 7000, size=80))
    others = [(5500, "["), (5800, "]"), (6400, "["), (6600, "]")]
    record = make_record(beats=beats.tolist(), others=others)
    evaluation = evaluate_record(record, EvaluationSettings(), RecordingDetector(detections))
    expected = match_beats(
        beats,
        detections,
        window_samples=WINDOW,
        start_sample=START,
        vf=(Episode(5500, 5800), Episode(6400, 6600)),
    )
    assert evaluation.counts == RecordCounts("rec", expected.tp, expected.fn, expected.fp)
    assert evaluation.reference_excluded == expected.reference_excluded
    assert evaluation.detections_excluded == expected.detections_excluded


def test_figures_on_what_is_not_scored() -> None:
    others = [
        (50, "!"),  # outside every episode
        (100, "["),
        (150, "!"),  # inside the first episode
        (200, "]"),
        (6500, "["),
        (6550, "!"),  # inside the second episode
        (6600, "]"),
        (6700, "!"),  # outside
        (6700, "+"),
    ]
    record = make_record(beats=[120, 180, 6300, 6520, 6580, 6900], others=others)
    detector = RecordingDetector([130, 6301, 6540, 6901])
    evaluation = evaluate_record(record, EvaluationSettings(), detector)
    assert evaluation.counts == RecordCounts("rec", tp=2, fn=0, fp=0)
    assert evaluation.vf_episodes == 2
    assert evaluation.vf_episodes_scored == 1
    assert evaluation.vf_samples_scored == 101
    assert evaluation.reference_excluded == 2
    assert evaluation.detections_excluded == 1
    assert evaluation.flutter_waves_outside_vf == 2


def test_episode_that_contains_five_minutes_counts_from_five_minutes() -> None:
    record = make_record(others=[(5900, "["), (6100, "]")])
    evaluation = evaluate_record(record, EvaluationSettings(), RecordingDetector())
    assert (evaluation.vf_episodes, evaluation.vf_episodes_scored) == (1, 1)
    assert evaluation.vf_samples_scored == 101


def test_episode_without_offset_lasts_until_the_end_of_the_record() -> None:
    record = make_record(n_samples=7000, beats=[6850, 6950], others=[(6800, "[")])
    evaluation = evaluate_record(record, EvaluationSettings(), RecordingDetector([6900]))
    assert (evaluation.vf_episodes, evaluation.vf_episodes_scored) == (1, 1)
    assert evaluation.vf_samples_scored == 200
    assert evaluation.reference_excluded == 2
    assert evaluation.detections_excluded == 1
    assert evaluation.counts == RecordCounts("rec", tp=0, fn=0, fp=0)


def test_record_of_five_minutes_or_less_has_no_scored_part() -> None:
    record = make_record(n_samples=START, beats=[100, 5000], others=[(4000, "["), (4500, "]")])
    evaluation = evaluate_record(record, EvaluationSettings(), RecordingDetector([100, 5000]))
    assert evaluation.counts == RecordCounts("rec", tp=0, fn=0, fp=0)
    assert (evaluation.vf_episodes, evaluation.vf_episodes_scored) == (1, 0)
    assert evaluation.vf_samples_scored == 0


def test_record_without_episodes() -> None:
    record = make_record(beats=[6100], others=[(6000, "+"), (6200, "!")])
    evaluation = evaluate_record(record, EvaluationSettings(), RecordingDetector([6100]))
    assert evaluation.vf_episodes == 0
    assert evaluation.vf_episodes_scored == 0
    assert evaluation.vf_samples_scored == 0
    assert evaluation.reference_excluded == 0
    assert evaluation.detections_excluded == 0
    assert evaluation.flutter_waves_outside_vf == 1


def test_channel_other_than_the_settings_is_rejected_before_detection() -> None:
    detector = RecordingDetector()
    with pytest.raises(InvalidInputError, match="holds channel 1, but the settings name channel 0"):
        evaluate_record(make_record(channel=1), EvaluationSettings(), detector)
    assert detector.calls == []


def test_annotations_out_of_order_are_rejected_before_detection() -> None:
    detector = RecordingDetector()
    record = make_record(others=[(200, "+"), (100, "+")])
    with pytest.raises(InvalidInputError, match="not non-decreasing"):
        evaluate_record(record, EvaluationSettings(), detector)
    assert detector.calls == []


def test_detections_out_of_order_are_rejected() -> None:
    with pytest.raises(InvalidInputError, match="strictly increasing"):
        evaluate_record(make_record(), EvaluationSettings(), RecordingDetector([6200, 6100]))


def test_evaluation_is_a_frozen_value() -> None:
    evaluation = evaluate_record(make_record(), EvaluationSettings(), RecordingDetector())
    assert isinstance(evaluation, RecordEvaluation)
    with pytest.raises(AttributeError):
        evaluation.vf_episodes = 3  # type: ignore[misc]


def _tiled_ecg(fs_hz: float, n_beats: int) -> tuple[FloatArray, list[int]]:
    """One beat per second, R wave at the middle of each second, built from one template."""
    period = int(fs_hz)
    t = (np.arange(period) - period // 2) / fs_hz
    template = np.zeros(period)
    for offset_s, amplitude_mv, width_s in (
        (-0.200, 0.15, 0.025),
        (-0.030, -0.10, 0.010),
        (0.000, 1.00, 0.010),
        (0.030, -0.20, 0.010),
        (0.280, 0.30, 0.045),
    ):
        template += amplitude_mv * np.exp(-((t - offset_s) ** 2) / (2.0 * width_s**2))
    return np.tile(template, n_beats), [k * period + period // 2 for k in range(n_beats)]


def test_default_detector_on_a_clean_ecg_of_six_minutes() -> None:
    signal, r_peaks = _tiled_ecg(360.0, 360)
    record = Record(
        name="clean",
        channel=0,
        signal_name="MLII",
        fs_hz=360.0,
        signal_mv=signal,
        beat_samples=np.array(r_peaks, dtype=np.int64),
        beat_symbols=tuple("N" for _ in r_peaks),
        other_annotations=(),
    )
    evaluation = evaluate_record(record, EvaluationSettings())
    scored = sum(1 for sample in r_peaks if sample >= learning_period_samples(360.0))
    assert evaluation.counts == RecordCounts("clean", tp=scored, fn=0, fp=0)
    assert scored == 60


# --- evaluate_records -----------------------------------------------------------------------


class RecordingLoader:
    """The record loader, remembering its calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, int]] = []

    def __call__(self, path: Path, channel: int) -> Record:
        self.calls.append((path, channel))
        return load_record(path, channel)


@pytest.fixture
def three_records(tmp_path: Path, write_fixture_record: Callable[..., None]) -> Path:
    write_fixture_record(tmp_path, "100", n_samples=6600, beats=[6100, 6200], detections=[6100])
    write_fixture_record(tmp_path, "118", n_samples=6600, beats=[6100], detections=[6101, 6300])
    write_fixture_record(tmp_path, "207", n_samples=6600, others=[(6200, "["), (6300, "]")])
    return tmp_path


def test_records_in_the_order_given(
    three_records: Path, fake_detector: Callable[..., npt.NDArray[np.int64]]
) -> None:
    loader = RecordingLoader()
    evaluations = evaluate_records(
        three_records,
        ["207", "100", "118"],
        EvaluationSettings(),
        detector=fake_detector,
        loader=loader,
    )
    assert [evaluation.record for evaluation in evaluations] == ["207", "100", "118"]
    assert loader.calls == [(three_records / name, 0) for name in ("207", "100", "118")]
    assert [evaluation.counts for evaluation in evaluations] == [
        RecordCounts("207", 0, 0, 0),
        RecordCounts("100", 1, 1, 0),
        RecordCounts("118", 1, 0, 1),
    ]
    assert evaluations[0].vf_samples_scored == 101
    assert isinstance(evaluations, tuple)


def test_records_with_another_channel(
    three_records: Path, fake_detector: Callable[..., npt.NDArray[np.int64]]
) -> None:
    loader = RecordingLoader()
    (evaluation,) = evaluate_records(
        three_records,
        ["100"],
        EvaluationSettings(channel=1),
        detector=fake_detector,
        loader=loader,
    )
    assert loader.calls == [(three_records / "100", 1)]
    assert evaluation.signal_name == "V1"
    # Channel 1 is 0.5 mV everywhere: the fake detector reports nothing.
    assert evaluation.counts == RecordCounts("100", 0, 2, 0)


def test_no_records(three_records: Path) -> None:
    loader = RecordingLoader()
    assert evaluate_records(three_records, [], EvaluationSettings(), loader=loader) == ()
    assert loader.calls == []


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ("100", "records is a string"),
        (["100", "../100"], "invalid record name: '../100'"),
        (["100", "100.dat"], "invalid record name"),
        (["100", ""], "invalid record name: ''"),
        (["100", 100], "invalid record name: 100"),
        (["100", "118", "100"], "record given twice: 100"),
    ],
)
def test_invalid_record_selection_is_rejected_before_loading(
    three_records: Path, records: Any, message: str
) -> None:
    loader = RecordingLoader()
    with pytest.raises(InvalidInputError, match=message):
        evaluate_records(three_records, records, EvaluationSettings(), loader=loader)
    assert loader.calls == []


def test_absent_record_propagates_the_error_of_wfdb(three_records: Path) -> None:
    with pytest.raises(FileNotFoundError):
        evaluate_records(three_records, ["999"], EvaluationSettings())


# --- meets_target ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tp", "other", "expected"),
    [
        (199, 1, True),  # 99.50 % exactly
        (198, 1, False),  # 99.497 %
        (1990, 10, True),  # 99.50 % exactly
        (1989, 10, False),  # 99.497 %
        (1991, 10, True),  # 99.500 2 %
        (5, 0, True),  # 100 %
        (0, 5, False),  # 0 %
    ],
)
def test_target_of_99_50_percent(tp: int, other: int, expected: bool) -> None:
    assert meets_target(tp, other) is expected


def test_target_is_compared_exactly_on_integers() -> None:
    # 99.50 % minus one part in 10**19: the float64 quotient rounds to 99.5 exactly.
    tp = 995 * 10**16 - 1
    total = 10**19
    assert (100 * tp) / total == 99.5
    assert meets_target(tp, total - tp) is False
    assert meets_target(tp + 1, total - tp - 1) is True


def test_target_agrees_with_the_integer_formula() -> None:
    generator = random.Random(9950)
    for _ in range(5000):
        tp = generator.randint(0, 3000)
        other = generator.randint(0, 30)
        expected = tp + other > 0 and 10000 * tp >= 9950 * (tp + other)
        assert meets_target(tp, other) is expected


def test_target_not_defined_fails() -> None:
    assert meets_target(0, 0) is False
    assert meets_target(0, 0, 0) is False


@pytest.mark.parametrize(
    ("tp", "other", "target", "expected"),
    [
        (5, 0, 10000, True),
        (5, 1, 10000, False),
        (0, 1, 0, True),
        (1, 1, 5000, True),
        (1, 2, 5000, False),
    ],
)
def test_other_targets(tp: int, other: int, target: int, expected: bool) -> None:
    assert meets_target(tp, other, target) is expected


def test_numpy_integers_are_counts() -> None:
    counts: tuple[Any, Any] = (np.int64(199), np.int32(1))
    assert meets_target(*counts) is True


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((-1, 0), "tp is negative: -1"),
        ((1, -1), "other is negative: -1"),
        ((1.0, 0), "tp is not an integer"),
        ((1, True), "other is not an integer"),
        ((1, 0, -1), "target_hundredths is negative"),
        ((1, 0, 10001), "target_hundredths is above 10000: 10001"),
        ((1, 0, 99.5), "target_hundredths is not an integer"),
    ],
)
def test_invalid_arguments_of_the_target(args: tuple[Any, ...], message: str) -> None:
    with pytest.raises(InvalidInputError, match=message):
        meets_target(*args)
