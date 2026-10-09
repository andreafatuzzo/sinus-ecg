"""Unit tests of the golden-vector format, version 2 (architecture §13.8).

The sections ``[beats]`` (with marks and report samples), ``[heart_rates]`` and
``[quality_windows]``: one rejected text per reader rule, with its line; the empty fields; the
round trip; a version 1 file; and the writer's rejection of what the reader would reject.
"""

import dataclasses
from typing import Any

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError, MalformedFileError, NonFiniteOutputError
from sinus_dsp.golden import (
    GoldenVector,
    golden_vector,
    parse_golden_vector,
    render_golden_vector,
)
from sinus_dsp.heart_rate import HeartRateEvent
from sinus_dsp.pipeline import run_pipeline
from sinus_dsp.synthetic import synthetic_event_ecg
from sinus_dsp.version import SoftwareIdentity

DIGEST = "ab" * 32
SOFTWARE = SoftwareIdentity(
    version="0.2.0.dev0", source_sha256=DIGEST, python="3.11", runtime=(("numpy", "2.4.6"),)
)
N = 40


def base_vector(**changes: Any) -> GoldenVector:
    """40 samples, three detections (one start-up), three heart-rate events, three windows."""
    vector = GoldenVector(
        input_id="v2",
        input_source="synthetic",
        input_parameters="a=1",
        fs_hz=250.0,
        mains_hz=50,
        software_version="0.2.0.dev0",
        source_sha256=DIGEST,
        stages=("baseline", "mains"),
        coefficients=(
            np.array([[0.5, -1.0, 0.5, 1.0, -0.25, 0.125]]),
            np.array([[1.0, 2.0, 3.0, 1.0, 4.0, 5.0]]),
        ),
        input_mv=np.linspace(-1.0, 1.0, N),
        stage_outputs_mv=(np.zeros(N), np.ones(N)),
        beats=np.array([5, 20, 30], dtype=np.int64),
        reference_beats=np.array([5, 20, 30], dtype=np.int64),
        beat_startup=np.array([True, False, False]),
        beat_reported_at=np.array([8, 24, 33], dtype=np.int64),
        heart_rates=(
            HeartRateEvent(24, 20, "not_enough_beats", None),
            HeartRateEvent(33, 30, "out_of_range", 25.0),
            HeartRateEvent(36, None, "no_recent_beat", None),
        ),
        window_first=np.array([0, 10, 20], dtype=np.int64),
        window_last=np.array([19, 29, 39], dtype=np.int64),
        window_reported_at=np.array([22, 32, 39], dtype=np.int64),
        window_index=np.array([0.9, 0.25, 0.5]),
        window_usable=np.array([True, False, True]),
    )
    return dataclasses.replace(vector, **changes)


TEXT = render_golden_vector(base_vector())
LINES = TEXT.split("\n")[:-1]


def line_of(line: str) -> int:
    """The 1-based number of the only line of the base text equal to ``line``."""
    assert LINES.count(line) == 1, line
    return LINES.index(line) + 1


def edited(changes: dict[str, str]) -> str:
    """The base text with the given lines replaced (an empty value deletes the line)."""
    lines = []
    for line in LINES:
        replacement = changes.get(line, line)
        if replacement != "":
            lines.append(replacement)
    return "\n".join(lines) + "\n"


def assert_same(actual: GoldenVector, expected: GoldenVector) -> None:
    for field in dataclasses.fields(GoldenVector):
        got = getattr(actual, field.name)
        want = getattr(expected, field.name)
        if isinstance(want, np.ndarray):
            assert isinstance(got, np.ndarray)
            assert got.dtype == want.dtype and got.shape == want.shape, field.name
            assert got.tobytes() == want.tobytes(), field.name
        elif field.name in ("coefficients", "stage_outputs_mv"):
            assert all(g.tobytes() == w.tobytes() for g, w in zip(got, want, strict=True))
        else:
            assert got == want, field.name


# --- the text and the round trip ----------------------------------------------------------------


def test_the_text_of_the_new_sections() -> None:
    assert "n_heart_rates=3\nn_quality_windows=3\n[coefficients]\n" in TEXT
    assert TEXT.endswith(
        "[beats]\nsample_index,mark,reported_at\n5,startup,8\n20,reliable,24\n30,reliable,33\n"
        "[reference_beats]\nsample_index\n5\n20\n30\n"
        "[heart_rates]\nsample_index,beat_index,status,heart_rate_bpm\n"
        "24,20,not_enough_beats,\n33,30,out_of_range,25.0\n36,,no_recent_beat,\n"
        "[quality_windows]\nfirst_sample,last_sample,reported_at,quality_index,usable\n"
        "0,19,22,0.9,usable\n10,29,32,0.25,not_usable\n20,39,39,0.5,usable\n[end]\n"
    )


def test_round_trip() -> None:
    parsed = parse_golden_vector(TEXT, "t")
    assert_same(parsed, base_vector())
    assert parsed.heart_rates[2].beat_index is None and parsed.heart_rates[2].bpm is None
    assert parsed.beat_startup.dtype == np.bool_ and parsed.window_usable.dtype == np.bool_


def test_empty_sections_round_trip() -> None:
    vector = base_vector(
        beats=np.array([], dtype=np.int64),
        beat_startup=np.array([], dtype=np.bool_),
        beat_reported_at=np.array([], dtype=np.int64),
        heart_rates=(),
        window_first=np.array([], dtype=np.int64),
        window_last=np.array([], dtype=np.int64),
        window_reported_at=np.array([], dtype=np.int64),
        window_index=np.array([]),
        window_usable=np.array([], dtype=np.bool_),
    )
    text = render_golden_vector(vector)
    assert "n_heart_rates=0\nn_quality_windows=0\n" in text
    assert_same(parse_golden_vector(text, "t"), vector)


@pytest.mark.parametrize(("fs_hz", "event"), [(360.0, "held"), (250.0, "artefact")])
def test_round_trip_of_a_pipeline_vector(fs_hz: float, event: str) -> None:
    ecg = synthetic_event_ecg(fs_hz, event)
    vector = golden_vector(
        ecg.input_id,
        "synthetic",
        ecg.parameters,
        ecg.signal_mv,
        ecg.fs_hz,
        ecg.mains_hz,
        ecg.r_peaks,
        software=SOFTWARE,
    )
    result = run_pipeline(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz)
    assert np.array_equal(vector.beats, result.detections.indices)
    assert np.array_equal(vector.beat_startup, result.detections.startup)
    assert np.array_equal(vector.beat_reported_at, result.detections.reported_at)
    assert vector.heart_rates == result.heart_rate
    assert np.array_equal(vector.window_first, result.quality.first)
    assert np.array_equal(vector.window_index, result.quality.index)
    assert np.array_equal(vector.window_usable, result.quality.usable)
    assert_same(parse_golden_vector(render_golden_vector(vector), "t"), vector)


# --- version 1 and the header -------------------------------------------------------------------


def test_a_version_1_file_is_rejected_for_its_version() -> None:
    v1 = "\n".join(
        [
            LINES[0],
            "format_version=1",
            *LINES[2:13],
            "[coefficients]",
            "stage,section,b0,b1,b2,a1,a2",
            "baseline,0,0.5,-1.0,0.5,-0.25,0.125",
        ]
    )
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(v1 + "\n", "old.golden.txt")
    assert caught.value.line == 2
    assert "unknown format version 1" in caught.value.reason
    assert "only version 2 is read" in caught.value.reason


def test_the_new_header_keys_come_last_and_in_order() -> None:
    cases = {
        "n_heart_rates=3": ("", 14, "expected the header key n_heart_rates"),
        "n_quality_windows=3": ("", 15, "expected the header key n_quality_windows"),
    }
    for line, (replacement, number, _reason) in cases.items():
        assert line_of(line) == number
        with pytest.raises(MalformedFileError) as caught:
            parse_golden_vector(edited({line: replacement}), "t")
        assert caught.value.line == number
    swapped = edited(
        {"n_heart_rates=3": "n_quality_windows=3", "n_quality_windows=3": "n_heart_rates=3"}
    )
    with pytest.raises(MalformedFileError, match="out of order: expected n_heart_rates"):
        parse_golden_vector(swapped, "t")
    bad = edited({"n_heart_rates=3": "n_heart_rates=x"})
    with pytest.raises(MalformedFileError, match="n_heart_rates: not an integer"):
        parse_golden_vector(bad, "t")


# --- one rejected text per reader rule ----------------------------------------------------------

BEAT_COLUMNS = "sample_index,mark,reported_at"
HR_COLUMNS = "sample_index,beat_index,status,heart_rate_bpm"
WINDOW_COLUMNS = "first_sample,last_sample,reported_at,quality_index,usable"
B1, B2, B3 = "5,startup,8", "20,reliable,24", "30,reliable,33"
H1, H2, H3 = "24,20,not_enough_beats,", "33,30,out_of_range,25.0", "36,,no_recent_beat,"
W1, W2, W3 = "0,19,22,0.9,usable", "10,29,32,0.25,not_usable", "20,39,39,0.5,usable"

# (name, changes, line replaced (the error is on it), reason)
REJECTED: list[tuple[str, dict[str, str], str, str]] = [
    (
        "beats column line",
        {BEAT_COLUMNS: "sample_index"},
        BEAT_COLUMNS,
        "expected sample_index,mark",
    ),
    ("beat with two fields", {B1: "5,startup"}, B1, "row with 2 fields, expected 3"),
    ("beat with four fields", {B1: "5,startup,8,1"}, B1, "row with 4 fields, expected 3"),
    ("beat index equal", {B3: "20,reliable,33"}, B3, "not greater than the one before it, 20"),
    ("beat index outside", {B3: "40,reliable,40"}, B3, "sample 40 is outside 0 to 39"),
    ("mark unknown", {B2: "20,Reliable,24"}, B2, "mark is not startup or reliable"),
    ("mark empty", {B2: "20,,24"}, B2, "mark is not startup or reliable"),
    ("reported before its index", {B2: "20,reliable,19"}, B2, "before the sample_index 20"),
    ("reported_at outside", {B3: "30,reliable,40"}, B3, "reported_at 40 is outside 0 to 39"),
    (
        "reported_at decreasing",
        {B2: "20,reliable,31", B3: "30,reliable,30"},
        B3,
        "reported_at 30 is before the one above it, 31",
    ),
    ("reported_at empty", {B2: "20,reliable,"}, B2, "not an integer"),
    ("reported_at float", {B2: "20,reliable,24.0"}, B2, "not an integer"),
    ("heart_rates column line", {HR_COLUMNS: "sample_index,beat_index"}, HR_COLUMNS, "expected"),
    ("heart rate with three fields", {H1: "24,20,not_enough_beats"}, H1, "3 fields, expected 4"),
    ("heart rate sample outside", {H3: "40,,no_recent_beat,"}, H3, "sample 40 is outside 0 to 39"),
    (
        "heart rate sample decreasing",
        {H3: "30,,no_recent_beat,"},
        H3,
        "sample 30 is before the one above it, 33",
    ),
    ("heart rate sample not an integer", {H1: "x,20,not_enough_beats,"}, H1, "not an integer"),
    ("beat_index not a detection", {H1: "24,21,not_enough_beats,"}, H1, "not the sample_index"),
    ("beat_index not an integer", {H1: "24,2.0,not_enough_beats,"}, H1, "not an integer"),
    ("beat_index names a start-up detection", {H1: "24,5,not_enough_beats,"}, H1, "marked startup"),
    (
        "beat_index out of order",
        {H1: "33,30,not_enough_beats,"},
        H1,
        "not the next reliable detection (20)",
    ),
    (
        "beat_index named twice",
        {H2: "33,20,out_of_range,25.0"},
        H2,
        "not the next reliable detection (30)",
    ),
    (
        "beat_index does not match reported_at",
        {H1: "25,20,not_enough_beats,"},
        H1,
        "sample_index 25 is not the reported_at of the detection 20, 24",
    ),
    ("status unknown", {H3: "36,,gone,"}, H3, "status is not one of"),
    ("status empty", {H3: "36,,,"}, H3, "status is not one of"),
    (
        "valid without a rate",
        {H2: "33,30,valid,"},
        H2,
        "heart_rate_bpm is empty for the status valid",
    ),
    (
        "out_of_range without a rate",
        {H2: "33,30,out_of_range,"},
        H2,
        "empty for the status out_of_range",
    ),
    ("rate for not_enough_beats", {H1: "24,20,not_enough_beats,70.0"}, H1, "given for the status"),
    ("rate for no_recent_beat", {H3: "36,,no_recent_beat,70.0"}, H3, "given for the status"),
    ("rate zero", {H2: "33,30,out_of_range,0.0"}, H2, "not greater than 0"),
    ("rate negative zero", {H2: "33,30,out_of_range,-0.0"}, H2, "not greater than 0"),
    ("rate negative", {H2: "33,30,out_of_range,-5.0"}, H2, "not greater than 0"),
    ("rate not a float", {H2: "33,30,out_of_range,abc"}, H2, "not a float"),
    ("rate infinite", {H2: "33,30,out_of_range,1e+999"}, H2, "not a finite float"),
    ("rate underflow", {H2: "33,30,out_of_range,1e-400"}, H2, "converts to zero"),
    (
        "windows column line",
        {WINDOW_COLUMNS: "first_sample"},
        WINDOW_COLUMNS,
        "expected first_sample",
    ),
    ("window with four fields", {W1: "0,19,22,0.9"}, W1, "row with 4 fields, expected 5"),
    ("first_sample equal", {W2: "0,29,32,0.25,not_usable"}, W2, "not greater than the one above"),
    ("last before first", {W2: "10,9,32,0.25,not_usable"}, W2, "last_sample 9 is before"),
    ("reported before last", {W2: "10,29,28,0.25,not_usable"}, W2, "reported_at 28 is before"),
    (
        "window reported outside",
        {W3: "20,39,40,0.5,usable"},
        W3,
        "reported_at 40 is outside 0 to 39",
    ),
    ("index above 1", {W1: "0,19,22,1.5,usable"}, W1, "quality_index is outside 0 to 1"),
    ("index below 0", {W1: "0,19,22,-0.1,not_usable"}, W1, "quality_index is outside 0 to 1"),
    ("index not a float", {W1: "0,19,22,high,usable"}, W1, "not a float"),
    ("usable token unknown", {W1: "0,19,22,0.9,yes"}, W1, "usable is not usable or not_usable"),
    (
        "usable for a low index",
        {W2: "10,29,32,0.25,usable"},
        W2,
        "does not match the quality_index",
    ),
    ("not usable for a high index", {W1: "0,19,22,0.9,not_usable"}, W1, "does not match"),
    ("not usable at exactly 0.5", {W3: "20,39,39,0.5,not_usable"}, W3, "does not match"),
    ("usable just below 0.5", {W3: "20,39,39,0.49999999999999994,usable"}, W3, "does not match"),
]


@pytest.mark.parametrize(
    ("changes", "line", "reason"),
    [pytest.param(c, ln, r, id=name) for name, c, ln, r in REJECTED],
)
def test_each_new_reader_rule_rejects_with_the_line_number(
    changes: dict[str, str], line: str, reason: str
) -> None:
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(edited(changes), "f.golden.txt")
    assert caught.value.line == line_of(line)
    assert reason in caught.value.reason


def test_a_missing_reliable_detection_is_named_at_the_last_heart_rate_row() -> None:
    text = edited({H2: "", "n_heart_rates=3": "n_heart_rates=2"})
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(text, "t")
    assert caught.value.line == line_of(H3) - 1
    assert "reliable detection 30 has no row in [heart_rates]" in caught.value.reason


def test_a_missing_reliable_detection_with_no_heart_rate_row() -> None:
    text = edited({H1: "", H2: "", H3: "", "n_heart_rates=3": "n_heart_rates=0"})
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(text, "t")
    assert "reliable detection 20 has no row" in caught.value.reason
    assert caught.value.line == line_of(HR_COLUMNS)


def test_counts_and_sections() -> None:
    text = edited({"n_heart_rates=3": "n_heart_rates=4"})
    with pytest.raises(MalformedFileError, match=r"\[heart_rates\] has 3 rows, n_heart_rates is 4"):
        parse_golden_vector(text, "t")
    text = edited({"n_heart_rates=3": "n_heart_rates=2"})
    with pytest.raises(MalformedFileError, match="more rows than n_heart_rates"):
        parse_golden_vector(text, "t")
    text = edited({"n_quality_windows=3": "n_quality_windows=4"})
    with pytest.raises(MalformedFileError, match="has 3 rows, n_quality_windows is 4"):
        parse_golden_vector(text, "t")
    text = edited({"n_quality_windows=3": "n_quality_windows=2"})
    with pytest.raises(MalformedFileError, match="more rows than n_quality_windows"):
        parse_golden_vector(text, "t")
    text = edited({"[quality_windows]": "[windows]"})
    with pytest.raises(
        MalformedFileError, match="expected \\[quality_windows\\], found \\[windows\\]"
    ):
        parse_golden_vector(text, "t")
    text = edited({"[heart_rates]": ""})
    with pytest.raises(MalformedFileError, match="more rows than n_reference_beats"):
        parse_golden_vector(text, "t")


def test_empty_fields_are_accepted_only_where_allowed() -> None:
    # beat_index and heart_rate_bpm may be empty; every other empty field is rejected.
    ok = parse_golden_vector(edited({H3: "36,,no_recent_beat,"}), "t")
    assert ok.heart_rates[2].beat_index is None
    for changes in ({H3: ",,no_recent_beat,"}, {H3: "36,,,"}, {W1: "0,,22,0.9,usable"}):
        with pytest.raises(MalformedFileError):
            parse_golden_vector(edited(changes), "t")


def test_accepted_boundaries() -> None:
    # reported_at equal to the index and to the last sample; indexes 0 and 1; rate of any size.
    text = edited(
        {
            B1: "5,startup,5",
            B3: "30,reliable,39",
            H2: "39,30,out_of_range,1e-05",
            H3: "39,,no_recent_beat,",
            W1: "0,19,19,0.0,not_usable",
            W2: "10,29,29,1.0,usable",
        }
    )
    parsed = parse_golden_vector(text, "t")
    assert parsed.window_index.tolist() == [0.0, 1.0, 0.5]
    assert parsed.heart_rates[1].bpm == 1e-05


# --- the writer ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"beat_startup": np.array([True, False])}, "beat_startup has 2 elements"),
        ({"beat_startup": np.array([1, 0, 0])}, "beat_startup is not"),
        ({"beat_reported_at": np.array([8, 24], dtype=np.int64)}, "beat_reported_at has 2"),
        ({"beat_reported_at": np.array([8.0, 24.0, 33.0])}, "beat_reported_at is not"),
        ({"beat_reported_at": np.array([4, 24, 33], dtype=np.int64)}, "before the sample_index 5"),
        ({"beat_reported_at": np.array([8, 24, 40], dtype=np.int64)}, "reported_at 40 is outside"),
        ({"beat_reported_at": np.array([8, 34, 33], dtype=np.int64)}, "before the one above it"),
        ({"heart_rates": [HeartRateEvent(24, 20, "not_enough_beats", None)]}, "not a tuple"),
        ({"heart_rates": ("x",)}, "heart_rates[0] is not a HeartRateEvent"),
        (
            {"heart_rates": (HeartRateEvent(24, 5, "not_enough_beats", None),)},
            "marked startup",
        ),
        (
            {"heart_rates": (HeartRateEvent(24, 20, "not_enough_beats", None),)},
            "reliable detection 30 has no row",
        ),
        (
            {"heart_rates": (HeartRateEvent(25, 20, "not_enough_beats", None),)},
            "not the reported_at",
        ),
        (
            {"heart_rates": (HeartRateEvent(24, 20, "weird", None),)},
            "status is not one of",
        ),
        (
            {"heart_rates": (HeartRateEvent(24, 20, "valid", None),)},
            "empty for the status valid",
        ),
        (
            {"heart_rates": (HeartRateEvent(24, 20, "not_enough_beats", 70.0),)},
            "given for the status",
        ),
        (
            {"heart_rates": (HeartRateEvent(24, 20, "valid", 0.0),)},
            "not greater than 0",
        ),
        (
            {"heart_rates": (HeartRateEvent(24, 20, "valid", -1.0),)},
            "not greater than 0",
        ),
        ({"heart_rates": (HeartRateEvent(24.5, 20, "valid", 1.0),)}, "not integer"),  # type: ignore[arg-type]
        ({"window_first": np.array([0, 10], dtype=np.int64)}, "window_last has 3"),
        ({"window_last": np.array([19, 29], dtype=np.int64)}, "window_last has 2"),
        ({"window_index": np.array([0.9, 0.25, 1.5])}, "outside 0 to 1"),
        ({"window_index": np.array([0.9, 0.25, -0.5])}, "outside 0 to 1"),
        ({"window_usable": np.array([True, True, True])}, "does not match the quality_index"),
        ({"window_usable": np.array([1, 0, 1])}, "window_usable is not"),
        ({"window_last": np.array([19, 9, 39], dtype=np.int64)}, "before the first_sample"),
        ({"window_reported_at": np.array([22, 32, 40], dtype=np.int64)}, "outside 0 to 39"),
        ({"window_first": np.array([0, 0, 20], dtype=np.int64)}, "not greater than"),
    ],
)
def test_the_writer_rejects_what_the_reader_would_reject(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidInputError) as caught:
        render_golden_vector(base_vector(**changes))
    assert message in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"heart_rates": (HeartRateEvent(24, 20, "valid", float("nan")),)},
        {"heart_rates": (HeartRateEvent(24, 20, "valid", float("inf")),)},
        {"window_index": np.array([0.9, float("nan"), 0.5])},
    ],
)
def test_non_finite_outputs_are_never_written(changes: dict[str, Any]) -> None:
    with pytest.raises(NonFiniteOutputError):
        render_golden_vector(base_vector(**changes))


def test_every_text_written_is_accepted() -> None:
    # A rate as a NumPy scalar and an index given as NumPy integers.
    vector = base_vector(
        heart_rates=(
            HeartRateEvent(np.int64(24), np.int64(20), "not_enough_beats", None),  # type: ignore[arg-type]
            HeartRateEvent(33, 30, "valid", np.float64(72.5)),
        ),
    )
    text = render_golden_vector(vector)
    assert "33,30,valid,72.5\n" in text and "np." not in text
    parsed = parse_golden_vector(text, "t")
    assert parsed.heart_rates[1].bpm == 72.5
