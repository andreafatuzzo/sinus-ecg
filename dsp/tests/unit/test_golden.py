"""Unit tests of the golden-vector format of ``sinus_dsp.golden`` (architecture §7.3, §7.4, §8.12).

The writer (``render_golden_vector``), the readers (``parse_golden_vector``,
``read_golden_vector``) and ``golden_vector``. The export is tested in
``test_golden_export.py``.
"""

import dataclasses
import re
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp import golden
from sinus_dsp.errors import InvalidInputError, MalformedFileError, NonFiniteOutputError
from sinus_dsp.golden import (
    FORMAT_NAME,
    FORMAT_VERSION,
    GOLDEN_FILE_SUFFIX,
    GOLDEN_SEGMENT_S,
    GoldenVector,
    golden_vector,
    parse_golden_vector,
    read_golden_vector,
    render_golden_vector,
)
from sinus_dsp.pipeline import STAGES, run_pipeline
from sinus_dsp.synthetic import synthetic_ecg
from sinus_dsp.version import SoftwareIdentity

DIGEST = "0123456789abcdef" * 4
SOFTWARE = SoftwareIdentity(
    version="1.2.3.dev4", source_sha256=DIGEST, python="3.11", runtime=(("numpy", "2.4.6"),)
)
FLOAT_SYNTAX = re.compile(r"-?[0-9]+(\.[0-9]+)?(e[+-][0-9]+)?")
INTEGER_SYNTAX = re.compile(r"0|[1-9][0-9]*")
# A mains setting given as a float equal to 60, which the input checks accept (§8.5).
MAINS_AS_FLOAT: Any = 60.0


def small_vector(**changes: Any) -> GoldenVector:
    """A vector of four samples, with values whose text is known; ``changes`` replace fields."""
    vector = GoldenVector(
        input_id="t_1-A",
        input_source="synthetic",
        input_parameters="a=1;b=0.5",
        fs_hz=360.0,
        mains_hz=60,
        software_version="1.2.3.dev4",
        source_sha256=DIGEST,
        stages=("baseline", "mains"),
        coefficients=(
            np.array([[0.5, -1.0, 0.5, 1.0, -0.25, 0.125]]),
            np.array([[1.0, 2.0, 3.0, 1.0, 4.0, 5.0], [6.0, -7.5, 8e-05, 1.0, 9e20, -0.0]]),
        ),
        input_mv=np.array([0.1, -0.0, 1e16, 5e-324]),
        stage_outputs_mv=(
            np.array([0.30000000000000004, 1.0, -2.5, 3.0]),
            np.array([1.7976931348623157e308, -1e-05, 0.0, 123456.789]),
        ),
        beats=np.array([1, 3], dtype=np.int64),
        reference_beats=np.array([0, 0, 3], dtype=np.int64),
    )
    return dataclasses.replace(vector, **changes)


SMALL_TEXT = """\
format=sinus-golden-vector
format_version=1
input_id=t_1-A
input_source=synthetic
input_parameters=a=1;b=0.5
sampling_frequency_hz=360.0
mains_frequency_hz=60
software_version=1.2.3.dev4
source_sha256=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
stages=baseline,mains
n_samples=4
n_beats=2
n_reference_beats=3
[coefficients]
stage,section,b0,b1,b2,a1,a2
baseline,0,0.5,-1.0,0.5,-0.25,0.125
mains,0,1.0,2.0,3.0,4.0,5.0
mains,1,6.0,-7.5,8e-05,9e+20,-0.0
[signals]
input_mv,baseline_mv,mains_mv
0.1,0.30000000000000004,1.7976931348623157e+308
-0.0,1.0,-1e-05
1e+16,-2.5,0.0
5e-324,3.0,123456.789
[beats]
sample_index
1
3
[reference_beats]
sample_index
0
0
3
[end]
"""


def assert_same_vector(actual: GoldenVector, expected: GoldenVector) -> None:
    """Field by field: equal values, arrays with the same bytes, shape and dtype."""
    for field in dataclasses.fields(GoldenVector):
        got = getattr(actual, field.name)
        want = getattr(expected, field.name)
        if isinstance(want, np.ndarray):
            assert_same_array(got, want)
        elif field.name in ("coefficients", "stage_outputs_mv"):
            assert isinstance(got, tuple)
            assert len(got) == len(want)
            for got_array, want_array in zip(got, want, strict=True):
                assert_same_array(got_array, want_array)
        else:
            assert got == want, field.name
            assert type(got) is type(want), field.name


def assert_same_array(got: Any, want: npt.NDArray[Any]) -> None:
    assert isinstance(got, np.ndarray)
    assert got.dtype == want.dtype
    assert got.shape == want.shape
    assert got.tobytes() == want.tobytes()


def test_constants() -> None:
    assert FORMAT_NAME == "sinus-golden-vector"
    assert FORMAT_VERSION == 1
    assert GOLDEN_SEGMENT_S == 60
    assert GOLDEN_FILE_SUFFIX == ".golden.txt"


# --- writer -------------------------------------------------------------------------------------


def test_render_writes_the_format_literally() -> None:
    assert render_golden_vector(small_vector()) == SMALL_TEXT


def test_round_trip_gives_an_equal_vector() -> None:
    vector = small_vector()
    assert_same_vector(parse_golden_vector(render_golden_vector(vector), "t"), vector)


def test_numpy_scalars_are_written_as_plain_numbers() -> None:
    vector = small_vector(fs_hz=np.float64(250.0), mains_hz=np.int64(50))
    text = render_golden_vector(vector)
    assert "\nsampling_frequency_hz=250.0\n" in text
    assert "\nmains_frequency_hz=50\n" in text
    assert "np." not in text
    parsed = parse_golden_vector(text, "t")
    assert type(parsed.fs_hz) is float and parsed.fs_hz == 250.0
    assert type(parsed.mains_hz) is int and parsed.mains_hz == 50


def test_integer_sampling_frequency_is_written_as_a_float() -> None:
    text = render_golden_vector(small_vector(fs_hz=360))
    assert "\nsampling_frequency_hz=360.0\n" in text


EDGE_VALUES = [
    5e-324,
    -5e-324,
    1.7976931348623157e308,
    -1.7976931348623157e308,
    -0.0,
    0.0,
    2.2250738585072014e-308,  # smallest normal
    2.225073858507201e-308,  # largest subnormal
    0.1,
    1 / 3,
    0.30000000000000004,
    1.0000000000000002,
    123456789.12345679,
    9007199254740993.0,
    1e-07,
    1e22,
    1e23,
    -2.718281828459045,
    6.02214076e23,
]


def test_exact_read_back_of_edge_values() -> None:
    rng = np.random.default_rng(20261005)
    random_values = rng.standard_normal(40) * 10.0 ** rng.integers(-300, 300, size=40)
    values = np.array([*EDGE_VALUES, *random_values.tolist()])
    n = values.shape[0]
    vector = small_vector(
        input_mv=values,
        stage_outputs_mv=(values[::-1].copy(), -values),
        beats=np.array([], dtype=np.int64),
        reference_beats=np.array([n - 1], dtype=np.int64),
        coefficients=(
            np.array([[5e-324, -0.0, 1.7976931348623157e308, 1.0, 0.1, 1 / 3]]),
            np.array([[2.225073858507201e-308, 1.0000000000000002, -1e-07, 1.0, 1e23, 0.0]]),
        ),
    )
    text = render_golden_vector(vector)
    parsed = parse_golden_vector(text, "t")
    assert_same_vector(parsed, vector)
    assert bool(np.signbit(parsed.input_mv[EDGE_VALUES.index(-0.0)]))
    lines = text.split("\n")
    row = lines[lines.index("input_mv,baseline_mv,mains_mv") + 1]
    assert row.startswith("5e-324,")


def test_every_number_of_a_real_vector_follows_the_syntax() -> None:
    ecg = synthetic_ecg(250.0, 180, "bw-mains50")
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
    text = render_golden_vector(vector)
    assert text.endswith("\n[end]\n")
    assert not any(character in text for character in " \t\r")
    lines = text.split("\n")[:-1]
    assert "" not in lines
    signals = lines.index("[signals]")
    beats = lines.index("[beats]")
    for line in lines[15:17]:
        stage, section, *values = line.split(",")
        assert stage in STAGES and section == "0"
        assert all(FLOAT_SYNTAX.fullmatch(value) for value in values)
    for line in lines[signals + 2 : beats]:
        fields = line.split(",")
        assert len(fields) == 3
        assert all(FLOAT_SYNTAX.fullmatch(field) for field in fields)
    for line in lines[beats + 2 :]:
        if line in ("[reference_beats]", "sample_index", "[end]"):
            continue
        assert INTEGER_SYNTAX.fullmatch(line)
    assert_same_vector(parse_golden_vector(text, "t"), vector)


def test_any_number_of_valid_stages_round_trips() -> None:
    vector = small_vector(
        stages=("a", "b_2", "c"),
        coefficients=(
            np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]]),
            np.array([[1.0, 2.0, 3.0, 1.0, 4.0, 5.0], [0.5, 0.5, 0.5, 1.0, 0.5, 0.5]]),
            np.array([[9.0, 8.0, 7.0, 1.0, 6.0, 5.0]]),
        ),
        stage_outputs_mv=(np.zeros(4), np.ones(4), np.full(4, -1.5)),
    )
    text = render_golden_vector(vector)
    assert "\nstages=a,b_2,c\n" in text
    assert "\ninput_mv,a_mv,b_2_mv,c_mv\n" in text
    assert "\nb_2,1,0.5,0.5,0.5,0.5,0.5\n" in text
    assert_same_vector(parse_golden_vector(text, "t"), vector)
    single = small_vector(
        stages=("baseline",),
        coefficients=(np.array([[0.5, -1.0, 0.5, 1.0, -0.25, 0.125]]),),
        stage_outputs_mv=(np.zeros(4),),
    )
    assert_same_vector(parse_golden_vector(render_golden_vector(single), "t"), single)


def test_no_beats_at_all_round_trips() -> None:
    vector = small_vector(
        beats=np.array([], dtype=np.int64), reference_beats=np.array([], dtype=np.int64)
    )
    text = render_golden_vector(vector)
    assert text.endswith("[beats]\nsample_index\n[reference_beats]\nsample_index\n[end]\n")
    assert_same_vector(parse_golden_vector(text, "t"), vector)


def test_beats_of_other_integer_kinds_are_written() -> None:
    vector = small_vector(
        beats=np.array([1, 3], dtype=np.uint16), reference_beats=np.array([0, 3], dtype=np.int32)
    )
    parsed = parse_golden_vector(render_golden_vector(vector), "t")
    assert parsed.beats.dtype == np.int64 and parsed.beats.tolist() == [1, 3]
    assert parsed.reference_beats.tolist() == [0, 3]


# --- writer: non-finite values ------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"fs_hz": float("inf")},
        {"fs_hz": float("nan")},
        {"fs_hz": np.float64("-inf")},
        {
            "coefficients": (
                np.array([[0.5, -1.0, float("nan"), 1.0, -0.25, 0.125]]),
                small_vector().coefficients[1],
            )
        },
        {"input_mv": np.array([0.1, float("inf"), 0.0, 0.0])},
        {"stage_outputs_mv": (np.zeros(4), np.array([0.0, 0.0, float("-inf"), 0.0]))},
        {"input_mv": np.array([0.0, 0.0, float("nan"), 0.0], dtype=np.float32)},
    ],
)
def test_non_finite_values_are_never_written(changes: dict[str, Any]) -> None:
    with pytest.raises(NonFiniteOutputError) as caught:
        render_golden_vector(small_vector(**changes))
    assert caught.value.input_id == "t_1-A"
    assert str(caught.value) == "t_1-A: output contains a value that is not finite"


def test_non_finite_values_are_checked_before_anything_else() -> None:
    vector = small_vector(
        input_id="not valid",
        mains_hz=55,
        stage_outputs_mv=(np.array([float("nan")] * 4),),
        beats=np.array([3, 1]),
    )
    with pytest.raises(NonFiniteOutputError):
        render_golden_vector(vector)


def test_an_overflowing_filter_output_is_a_non_finite_output_error() -> None:
    """A constant input of extreme amplitude overflows the filters (OP-063)."""
    vector = golden_vector(
        "extreme", "test", "a=1", np.full(3600, 1e308), 360.0, 50, [], software=SOFTWARE
    )
    assert bool(np.isfinite(vector.input_mv).all())
    assert not bool(np.isfinite(vector.stage_outputs_mv[0]).all())
    with pytest.raises(NonFiniteOutputError, match="^extreme: "):
        render_golden_vector(vector)


# --- writer: content the reader would reject ----------------------------------------------------


def _coefficients(*matrices: Any) -> tuple[Any, ...]:
    return tuple(matrices)


BASELINE_ROW = [[0.5, -1.0, 0.5, 1.0, -0.25, 0.125]]
MAINS_ROWS = small_vector().coefficients[1]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"input_id": ""}, "input_id"),
        ({"input_id": "a b"}, "input_id"),
        ({"input_id": "a/b"}, "input_id"),
        ({"input_id": "é"}, "input_id"),
        ({"input_id": 5}, "input_id"),
        ({"input_source": ""}, "input_source is empty"),
        ({"input_source": "a b"}, "input_source holds a space"),
        ({"input_source": "a\tb"}, "input_source holds a tab"),
        ({"input_source": "a\rb"}, "input_source holds a carriage return"),
        ({"input_source": "a\nb"}, "input_source holds a line feed"),
        ({"input_source": "a\ud800"}, "input_source is not encodable as UTF-8"),
        ({"input_source": None}, "input_source is not a string"),
        ({"input_parameters": ""}, "input_parameters is empty"),
        ({"input_parameters": "a=1; b=2"}, "input_parameters holds a space"),
        ({"fs_hz": 0.0}, "sampling frequency"),
        ({"fs_hz": -360.0}, "sampling frequency"),
        ({"fs_hz": True}, "sampling frequency"),
        ({"fs_hz": "360"}, "sampling frequency"),
        ({"mains_hz": 55}, "mains setting is not 50 or 60"),
        ({"mains_hz": True}, "mains setting is not an integer"),
        ({"mains_hz": 60.0}, "mains setting is not an integer"),
        ({"mains_hz": "60"}, "mains setting is not an integer"),
        ({"software_version": ""}, "software_version is empty"),
        ({"software_version": "1.0 dev"}, "software_version holds a space"),
        ({"source_sha256": DIGEST.upper()}, "source_sha256"),
        ({"source_sha256": DIGEST[:-1]}, "source_sha256"),
        ({"source_sha256": DIGEST + "0"}, "source_sha256"),
        ({"source_sha256": None}, "source_sha256"),
        ({"stages": ()}, "no stage given"),
        ({"stages": ["baseline", "mains"]}, "stages is not a tuple"),
        ({"stages": ("Baseline", "mains")}, "invalid stage name"),
        ({"stages": ("baseline", "baseline")}, "given twice"),
        ({"stages": ("baseline", "")}, "invalid stage name"),
        ({"stages": ("baseline",)}, "coefficients is not a tuple of one matrix per stage"),
        ({"coefficients": [np.array(BASELINE_ROW), MAINS_ROWS]}, "coefficients is not a tuple"),
        (
            {"coefficients": _coefficients(np.array(BASELINE_ROW, dtype=np.float32), MAINS_ROWS)},
            "not a float64 array",
        ),
        (
            {"coefficients": _coefficients(np.array([BASELINE_ROW[0][:5]]), MAINS_ROWS)},
            "shape",
        ),
        ({"coefficients": _coefficients(np.zeros((0, 6)), MAINS_ROWS)}, "shape"),
        ({"coefficients": _coefficients(np.array(BASELINE_ROW[0]), MAINS_ROWS)}, "shape"),
        (
            {
                "coefficients": _coefficients(
                    np.array([[0.5, -1.0, 0.5, 2.0, 0.0, 0.0]]), MAINS_ROWS
                )
            },
            "a0 other than 1",
        ),
        ({"input_mv": np.zeros(0)}, "input_mv is empty"),
        ({"input_mv": np.zeros((2, 2))}, "input_mv is not a one-dimensional float64 array"),
        ({"input_mv": np.zeros(4, dtype=np.float32)}, "input_mv is not"),
        ({"input_mv": [0.0, 0.0, 0.0, 0.0]}, "input_mv is not"),
        ({"stage_outputs_mv": (np.zeros(4),)}, "stage_outputs_mv is not a tuple"),
        ({"stage_outputs_mv": [np.zeros(4), np.zeros(4)]}, "stage_outputs_mv is not a tuple"),
        ({"stage_outputs_mv": (np.zeros(4), np.zeros(5))}, "output of the stage mains has 5"),
        ({"stage_outputs_mv": (np.zeros(4, dtype=np.float32), np.zeros(4))}, "stage baseline"),
        ({"beats": np.array([3, 1])}, "beats: sample 1 at index 1 is not greater than"),
        ({"beats": np.array([1, 1])}, "beats: sample 1 at index 1 is not greater than"),
        ({"beats": np.array([1, 4])}, "beats: sample 4 at index 1 is outside 0 to 3"),
        ({"beats": np.array([-1])}, "beats: sample -1 at index 0 is outside 0 to 3"),
        ({"beats": np.array([1.0, 3.0])}, "beats is not a one-dimensional array of integers"),
        ({"beats": np.array([[1, 3]])}, "beats is not a one-dimensional array of integers"),
        ({"beats": [1, 3]}, "beats is not a one-dimensional array of integers"),
        ({"reference_beats": np.array([3, 0])}, "reference_beats: sample 0 at index 1 is not at"),
        ({"reference_beats": np.array([4])}, "reference_beats: sample 4 at index 0 is outside"),
        ({"reference_beats": np.array([True])}, "reference_beats is not"),
    ],
)
def test_content_the_reader_would_reject_is_not_written(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidInputError, match=re.escape(message)):
        render_golden_vector(small_vector(**changes))


# --- reader: one rejected text per rule ---------------------------------------------------------

LINES = SMALL_TEXT.split("\n")[:-1]


def _text(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def replaced(number: int, line: str) -> str:
    lines = list(LINES)
    lines[number - 1] = line
    return _text(lines)


def inserted(number: int, line: str) -> str:
    lines = list(LINES)
    lines.insert(number - 1, line)
    return _text(lines)


def deleted(*numbers: int) -> str:
    return _text([line for index, line in enumerate(LINES, start=1) if index not in numbers])


def swapped(first: int, second: int) -> str:
    lines = list(LINES)
    lines[first - 1], lines[second - 1] = lines[second - 1], lines[first - 1]
    return _text(lines)


REJECTED: list[tuple[str, str, int | None, str]] = [
    # Lines: UTF-8 text without spaces, tabs, carriage returns or empty lines.
    ("space", replaced(22, "-0.0, 1.0,-1e-05"), 22, "the line holds a space"),
    ("tab", replaced(5, "input_parameters=a=1;\tb=0.5"), 5, "the line holds a tab"),
    ("CR LF", SMALL_TEXT.replace("\n", "\r\n"), 1, "the line holds a carriage return"),
    ("CR in a row", replaced(27, "1\r"), 27, "the line holds a carriage return"),
    ("empty line", inserted(20, ""), 20, "empty line"),
    ("empty text", "", 1, "the file ends before the header key format"),
    ("byte-order mark", "﻿" + SMALL_TEXT, 1, "byte-order mark"),
    ("no line feed after [end]", SMALL_TEXT[:-1], 34, "no line feed after [end]"),
    ("a line after [end]", SMALL_TEXT + "x\n", 35, "text after [end]"),
    ("an empty line after [end]", SMALL_TEXT + "\n", 35, "text after [end]"),
    ("text without line feed after [end]", SMALL_TEXT + "x", 35, "text after [end]"),
    ("[end] twice", SMALL_TEXT + "[end]\n", 35, "text after [end]"),
    # Format and version.
    ("unknown format", replaced(1, "format=other"), 1, "unknown format other"),
    ("unknown version", replaced(2, "format_version=2"), 2, "unknown format version 2"),
    ("version with a zero", replaced(2, "format_version=01"), 2, "unknown format version"),
    # Header keys.
    ("not key=value", replaced(3, "input_id"), 3, "not a key=value line"),
    ("unknown key", replaced(4, "source=synthetic"), 4, "unknown header key source"),
    ("empty key", replaced(4, "=synthetic"), 4, "unknown header key"),
    ("missing key", deleted(4), 4, "header key input_parameters out of order"),
    ("key twice", replaced(4, "input_id=t_1-A"), 4, "header key input_id given twice"),
    ("keys swapped", swapped(6, 7), 6, "out of order: expected sampling_frequency_hz"),
    ("extra key", inserted(14, "extra=1"), 14, "expected [coefficients], found extra=1"),
    ("format first", swapped(1, 2), 1, "out of order: expected format"),
    # Header values.
    ("input_id with a slash", replaced(3, "input_id=a/b"), 3, "input_id does not match"),
    ("empty input_id", replaced(3, "input_id="), 3, "input_id does not match"),
    ("non-ASCII input_id", replaced(3, "input_id=é"), 3, "input_id does not match"),
    ("empty input_source", replaced(4, "input_source="), 4, "input_source is empty"),
    ("empty parameters", replaced(5, "input_parameters="), 5, "input_parameters is empty"),
    ("empty version", replaced(8, "software_version="), 8, "software_version is empty"),
    ("fs not a number", replaced(6, "sampling_frequency_hz=abc"), 6, "not a float: abc"),
    ("fs inf", replaced(6, "sampling_frequency_hz=inf"), 6, "not a float: inf"),
    ("fs nan", replaced(6, "sampling_frequency_hz=nan"), 6, "not a float: nan"),
    ("fs overflow", replaced(6, "sampling_frequency_hz=1e+999"), 6, "not a finite float"),
    ("fs zero", replaced(6, "sampling_frequency_hz=0.0"), 6, "not positive"),
    ("fs negative zero", replaced(6, "sampling_frequency_hz=-0.0"), 6, "not positive"),
    ("fs negative", replaced(6, "sampling_frequency_hz=-360.0"), 6, "not positive"),
    ("fs trailing dot", replaced(6, "sampling_frequency_hz=360."), 6, "not a float"),
    ("fs leading dot", replaced(6, "sampling_frequency_hz=.5"), 6, "not a float"),
    ("fs plus sign", replaced(6, "sampling_frequency_hz=+360.0"), 6, "not a float"),
    ("fs capital E", replaced(6, "sampling_frequency_hz=3.6E+2"), 6, "not a float"),
    ("fs unsigned exponent", replaced(6, "sampling_frequency_hz=3.6e2"), 6, "not a float"),
    ("fs underscore", replaced(6, "sampling_frequency_hz=3_60.0"), 6, "not a float"),
    ("fs hexadecimal", replaced(6, "sampling_frequency_hz=0x1p3"), 6, "not a float"),
    ("fs other digits", replaced(6, "sampling_frequency_hz=٣٦٠"), 6, "not a float"),
    ("mains 55", replaced(7, "mains_frequency_hz=55"), 7, "mains_frequency_hz is not 50 or 60"),
    ("mains 060", replaced(7, "mains_frequency_hz=060"), 7, "mains_frequency_hz is not 50"),
    ("mains 60.0", replaced(7, "mains_frequency_hz=60.0"), 7, "mains_frequency_hz is not 50"),
    ("digest uppercase", replaced(9, "source_sha256=" + DIGEST.upper()), 9, "source_sha256"),
    ("digest short", replaced(9, "source_sha256=" + DIGEST[:-1]), 9, "source_sha256"),
    ("digest long", replaced(9, "source_sha256=" + DIGEST + "a"), 9, "source_sha256"),
    ("no stage", replaced(10, "stages="), 10, "stages: no stage given"),
    ("stage name", replaced(10, "stages=Baseline,mains"), 10, "invalid stage name 'Baseline'"),
    ("stage twice", replaced(10, "stages=mains,mains"), 10, "stage mains given twice"),
    ("empty stage", replaced(10, "stages=baseline,,mains"), 10, "invalid stage name ''"),
    ("stage digit", replaced(10, "stages=1x"), 10, "invalid stage name '1x'"),
    ("n_samples zero", replaced(11, "n_samples=0"), 11, "n_samples is not at least 1"),
    ("n_samples leading zero", replaced(11, "n_samples=04"), 11, "n_samples: not an integer"),
    ("n_samples negative", replaced(11, "n_samples=-4"), 11, "n_samples: not an integer"),
    ("n_samples float", replaced(11, "n_samples=4.0"), 11, "n_samples: not an integer"),
    ("n_beats text", replaced(12, "n_beats=x"), 12, "n_beats: not an integer"),
    ("n_beats huge", replaced(12, "n_beats=" + "1" * 5000), 12, "integer with too many digits"),
    ("n_reference plus", replaced(13, "n_reference_beats=+3"), 13, "n_reference_beats: not an"),
    # Sections and column lines.
    ("section name", replaced(14, "[coefficient]"), 14, "expected [coefficients]"),
    ("coefficient columns", replaced(15, "stage,section,b0,b1,b2,a0,a1,a2"), 15, "expected stage"),
    ("signal columns", replaced(20, "input_mv,mains_mv,baseline_mv"), 20, "expected input_mv"),
    ("beat column", replaced(26, "sample"), 26, "expected sample_index"),
    ("reference column", replaced(30, "sample"), 30, "expected sample_index"),
    ("no [signals]", deleted(19), 19, "coefficient row with 3 fields, expected 7"),
    ("misnamed [signals]", replaced(19, "[signal]"), 19, "expected [signals], found [signal]"),
    ("no [beats]", deleted(25), 25, "[signals] has more rows than n_samples (4)"),
    ("misnamed [beats]", replaced(25, "[beat]"), 25, "expected [beats], found [beat]"),
    ("[signals] twice", replaced(25, "[signals]"), 25, "expected [beats], found [signals]"),
    (
        "sections swapped",
        _text([*LINES[:24], *LINES[28:33], *LINES[24:28], LINES[33]]),
        25,
        "expected [beats], found [reference_beats]",
    ),
    ("no [end]", deleted(34), 33, "the file ends before [end]"),
    ("[end] elsewhere", replaced(29, "[end]"), 29, "expected [reference_beats], found [end]"),
    # Coefficient rows.
    ("six fields", replaced(16, "baseline,0,0.5,-1.0,0.5,-0.25"), 16, "6 fields, expected 7"),
    ("eight fields", replaced(16, "baseline,0,0.5,-1.0,0.5,1.0,-0.25,0.125"), 16, "8 fields"),
    ("section 1 first", replaced(16, "baseline,1,0.5,-1.0,0.5,-0.25,0.125"), 16, "section 1"),
    (
        "section skipped",
        replaced(18, "mains,2,6.0,-7.5,8e-05,9e+20,-0.0"),
        18,
        "expected section 1",
    ),
    ("section 01", replaced(18, "mains,01,6.0,-7.5,8e-05,9e+20,-0.0"), 18, "not an integer: 01"),
    ("stages swapped", swapped(16, 17), 16, "stage mains, expected baseline"),
    ("first stage missing", deleted(16), 16, "stage mains, expected baseline"),
    ("last stage missing", deleted(17, 18), 17, "no coefficient row for the stage mains"),
    ("stage back", replaced(18, "baseline,1,6.0,-7.5,8e-05,9e+20,-0.0"), 18, "expected mains or"),
    ("unknown stage", replaced(18, "other,0,6.0,-7.5,8e-05,9e+20,-0.0"), 18, "or [signals]"),
    ("coefficient float", replaced(16, "baseline,0,0x1p3,-1.0,0.5,-0.25,0.125"), 16, "not a float"),
    ("coefficient inf", replaced(17, "mains,0,1.0,2.0,3.0,1e+400,5.0"), 17, "not a finite float"),
    # Rows and counts.
    ("signal row fields", replaced(22, "-0.0,1.0"), 22, "row with 2 fields, expected 3"),
    ("signal row empty field", replaced(22, "-0.0,,1.0"), 22, "not a float: "),
    ("signal float syntax", replaced(23, "1e16,-2.5,0.0"), 23, "not a float: 1e16"),
    ("signal float overflow", replaced(23, "1e+999,-2.5,0.0"), 23, "not a finite float"),
    ("signal NaN", replaced(23, "NaN,-2.5,0.0"), 23, "not a float: NaN"),
    ("fewer signal rows", replaced(11, "n_samples=5"), 25, "[signals] has 4 rows, n_samples is 5"),
    ("more signal rows", replaced(11, "n_samples=3"), 24, "[signals] has more rows than n_samples"),
    ("fewer beats", replaced(12, "n_beats=3"), 29, "[beats] has 2 rows, n_beats is 3"),
    ("more beats", replaced(12, "n_beats=1"), 28, "[beats] has more rows than n_beats (1)"),
    ("fewer references", replaced(13, "n_reference_beats=4"), 34, "has 3 rows, n_reference_beats"),
    (
        "more references",
        replaced(13, "n_reference_beats=2"),
        33,
        "more rows than n_reference_beats",
    ),
    ("beat row fields", replaced(27, "1,2"), 27, "row with 2 fields, expected 1"),
    ("beat syntax", replaced(27, "01"), 27, "not an integer: 01"),
    ("beat negative", replaced(27, "-1"), 27, "not an integer: -1"),
    ("beat equal", replaced(28, "1"), 28, "sample 1 is not greater than the one before it, 1"),
    ("beat smaller", replaced(28, "0"), 28, "sample 0 is not greater than the one before it, 1"),
    ("beat outside", replaced(28, "4"), 28, "sample 4 is outside 0 to 3"),
    ("reference smaller", replaced(33, "0").replace("\n0\n0\n0\n", "\n0\n3\n0\n"), 33, "at least"),
    ("reference outside", replaced(33, "4"), 33, "sample 4 is outside 0 to 3"),
    # Text ending too early.
    (
        "ends in the header",
        "format=sinus-golden-vector\n",
        1,
        "ends before the header key format_v",
    ),
    ("ends in the rows", _text(LINES[:22]), 22, "the file ends before row 3 of [signals]"),
    ("ends in a row", _text(LINES[:21]) + "-0.0,1.0,-1e-05", 22, "ends before row 3 of [signals]"),
    ("ends in the beats", _text(LINES[:27]), 27, "the file ends before row 2 of [beats]"),
]


@pytest.mark.parametrize(
    ("text", "line", "reason"),
    [pytest.param(text, line, reason, id=name) for name, text, line, reason in REJECTED],
)
def test_each_reader_rule_rejects_with_the_line_number(
    text: str, line: int | None, reason: str
) -> None:
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(text, "fixture.golden.txt")
    assert caught.value.path == "fixture.golden.txt"
    assert caught.value.line == line
    assert reason in caught.value.reason
    assert str(caught.value).startswith(f"fixture.golden.txt, line {line}: ")


def test_the_reference_smaller_case_is_built_as_intended() -> None:
    """Guard for the parametrized case: reference beats 0, 3, 0 at lines 31 to 33."""
    case = next(text for name, text, _, _ in REJECTED if name == "reference smaller")
    assert case.split("\n")[30:33] == ["0", "3", "0"]


def test_valid_variations_are_accepted() -> None:
    # Equal reference beats, an integer-looking float, an empty beat section.
    text = replaced(6, "sampling_frequency_hz=360")
    assert parse_golden_vector(text, "t").fs_hz == 360.0
    text = replaced(32, "0")
    assert parse_golden_vector(text, "t").reference_beats.tolist() == [0, 0, 3]
    text = _text([*LINES[:11], "n_beats=0", *LINES[12:26], *LINES[28:]])
    assert parse_golden_vector(text, "t").beats.tolist() == []


def test_first_offending_line_is_named() -> None:
    text = replaced(22, "-0.0, 1.0,-1e-05").replace("format_version=1", "format_version=9")
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(text, "t")
    assert caught.value.line == 2


def test_parsed_types() -> None:
    vector = parse_golden_vector(SMALL_TEXT, "t")
    assert type(vector.fs_hz) is float
    assert type(vector.mains_hz) is int
    assert vector.stages == ("baseline", "mains")
    assert vector.input_mv.dtype == np.float64
    assert all(matrix.dtype == np.float64 for matrix in vector.coefficients)
    assert vector.coefficients[1].shape == (2, 6)
    assert vector.coefficients[1][:, 3].tolist() == [1.0, 1.0]
    assert vector.beats.dtype == np.int64
    assert vector.reference_beats.dtype == np.int64


# --- read_golden_vector -------------------------------------------------------------------------


def test_read_a_file(tmp_path: Path) -> None:
    path = tmp_path / "x.golden.txt"
    path.write_bytes(SMALL_TEXT.encode("utf-8"))
    assert_same_vector(read_golden_vector(path), small_vector())


def test_read_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "x.golden.txt"
    path.write_bytes(SMALL_TEXT.encode("utf-8") + b"\xff")
    with pytest.raises(MalformedFileError) as caught:
        read_golden_vector(path)
    assert (caught.value.path, caught.value.line, caught.value.reason) == (
        str(path),
        None,
        "not UTF-8 text",
    )


def test_read_a_file_with_cr_lf_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "x.golden.txt"
    path.write_bytes(SMALL_TEXT.replace("\n", "\r\n").encode("utf-8"))
    with pytest.raises(MalformedFileError) as caught:
        read_golden_vector(path)
    assert (caught.value.path, caught.value.line) == (str(path), 1)


def test_read_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_golden_vector(tmp_path / "absent.golden.txt")


# --- golden_vector ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ecg() -> Any:
    return synthetic_ecg(360.0, 75, "bw-mains60")


def test_golden_vector_holds_what_the_pipeline_computes(ecg: Any) -> None:
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
    assert vector.input_id == ecg.input_id
    assert vector.input_source == "synthetic"
    assert vector.input_parameters == ecg.parameters
    assert vector.fs_hz == 360.0 and vector.mains_hz == 60
    assert vector.software_version == "1.2.3.dev4"
    assert vector.source_sha256 == DIGEST
    assert vector.stages == STAGES == ("baseline", "mains")
    assert_same_array(vector.input_mv, result.input_mv)
    assert_same_array(vector.stage_outputs_mv[0], result.baseline_mv)
    assert_same_array(vector.stage_outputs_mv[1], result.mains_mv)
    for got, want in zip(vector.coefficients, result.coefficients, strict=True):
        assert_same_array(got, want)
    assert_same_array(vector.beats, result.beats)
    assert_same_array(vector.reference_beats, ecg.r_peaks)


def test_golden_vector_runs_the_pipeline_once(ecg: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []

    def counting(*args: Any) -> Any:
        calls.append(args)
        return run_pipeline(*args)

    monkeypatch.setattr(golden, "run_pipeline", counting)
    golden_vector("x", "s", "p=1", ecg.signal_mv, 360, MAINS_AS_FLOAT, [], software=SOFTWARE)
    assert len(calls) == 1


def test_golden_vector_takes_the_checked_settings(ecg: Any) -> None:
    vector = golden_vector(
        "x", "s", "p=1", ecg.signal_mv.tolist(), 360, MAINS_AS_FLOAT, [], software=SOFTWARE
    )
    assert type(vector.fs_hz) is float and vector.fs_hz == 360.0
    assert type(vector.mains_hz) is int and vector.mains_hz == 60


def test_golden_vector_does_not_modify_its_inputs(ecg: Any) -> None:
    signal = ecg.signal_mv.copy()
    reference = ecg.r_peaks.copy()
    vector = golden_vector("x", "s", "p=1", signal, 360.0, 60, reference, software=SOFTWARE)
    assert signal.tobytes() == ecg.signal_mv.tobytes()
    assert reference.tobytes() == ecg.r_peaks.tobytes()
    reference[0] = 1
    assert int(vector.reference_beats[0]) == int(ecg.r_peaks[0])


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ([], []),
        (np.array([], dtype=np.float64), []),
        ([5, 5, 7], [5, 5, 7]),
        (np.array([0, 10799], dtype=np.uint32), [0, 10799]),
        ((1, 2), [1, 2]),
    ],
)
def test_golden_vector_accepts_reference_beats(
    ecg: Any, reference: Any, expected: list[int]
) -> None:
    vector = golden_vector("x", "s", "p=1", ecg.signal_mv, 360.0, 60, reference, software=SOFTWARE)
    assert vector.reference_beats.dtype == np.int64
    assert vector.reference_beats.tolist() == expected


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ([[1, 2]], "not one-dimensional"),
        (5, "not one-dimensional"),
        ([1.0, 2.0], "not integers"),
        ([True], "not integers"),
        (["1"], "not integers"),
        ([2**70], "not integers"),
        ([3, 1], "sample 1 at index 1 is not at least the one before it, 3"),
        ([-1], "sample -1 at index 0 is outside 0 to 10799"),
        ([10800], "sample 10800 at index 0 is outside 0 to 10799"),
        (np.array([10800], dtype=np.uint64), "outside 0 to 10799"),
        ([[1], [2, 3]], "do not convert to an array"),
    ],
)
def test_golden_vector_rejects_reference_beats(ecg: Any, reference: Any, message: str) -> None:
    with pytest.raises(InvalidInputError, match=re.escape(message)):
        golden_vector("x", "s", "p=1", ecg.signal_mv, 360.0, 60, reference, software=SOFTWARE)


@pytest.mark.parametrize(
    ("identifiers", "message"),
    [
        (("", "s", "p=1"), "input_id"),
        (("a b", "s", "p=1"), "input_id"),
        (("x\n", "s", "p=1"), "input_id"),
        ((None, "s", "p=1"), "input_id"),
        (("x", "", "p=1"), "input_source is empty"),
        (("x", "a b", "p=1"), "input_source holds a space"),
        (("x", "s", ""), "input_parameters is empty"),
        (("x", "s", "p=1\tq=2"), "input_parameters holds a tab"),
        (("x", "s", "p=1\r"), "input_parameters holds a carriage return"),
        (("x", "s", "p=1\nq=2"), "input_parameters holds a line feed"),
        (("x", 7, "p=1"), "input_source is not a string"),
    ],
)
def test_golden_vector_checks_the_identifiers_first(
    identifiers: tuple[Any, Any, Any], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: Any) -> Any:
        raise AssertionError("the pipeline runs after the identifier checks")

    monkeypatch.setattr(golden, "run_pipeline", never)
    with pytest.raises(InvalidInputError, match=re.escape(message)):
        golden_vector(*identifiers, [0.0] * 5, 1.0, 55, [[]], software=SOFTWARE)


@pytest.mark.parametrize(
    ("signal", "fs", "mains", "message"),
    [
        (np.zeros(3600), 360.0, 55, "mains frequency"),
        (np.zeros(100), 360.0, 50, "shorter than"),
        (np.zeros(3600), 100.0, 50, "sampling frequency"),
        (np.array([0.0, float("nan")] * 1800), 360.0, 50, "non-finite"),
    ],
)
def test_golden_vector_rejects_what_the_pipeline_rejects(
    signal: npt.NDArray[np.float64], fs: float, mains: int, message: str
) -> None:
    with pytest.raises(InvalidInputError, match=message):
        golden_vector("x", "s", "p=1", signal, fs, mains, [], software=SOFTWARE)


def test_golden_vector_checks_the_reference_beats_after_the_pipeline() -> None:
    with pytest.raises(InvalidInputError, match="mains frequency"):
        golden_vector("x", "s", "p=1", np.zeros(3600), 360.0, 55, [-1], software=SOFTWARE)


def test_every_vector_of_golden_vector_is_written_and_read_back(ecg: Any) -> None:
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
    text = render_golden_vector(vector)
    assert_same_vector(parse_golden_vector(text, "t"), vector)
    assert text.startswith(
        "format=sinus-golden-vector\nformat_version=1\ninput_id=syn-fs360-hr075-bw-mains60\n"
        "input_source=synthetic\ninput_parameters=duration_s=30;heart_rate_bpm=75;"
        "baseline_wander_hz=0.3;baseline_wander_mv=1.0;mains_hz=60;mains_mv=0.2\n"
        "sampling_frequency_hz=360.0\nmains_frequency_hz=60\nsoftware_version=1.2.3.dev4\n"
        f"source_sha256={DIGEST}\nstages=baseline,mains\nn_samples=10800\nn_beats=37\n"
        "n_reference_beats=37\n[coefficients]\n"
    )
