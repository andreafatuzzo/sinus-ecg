"""Unit tests of the golden-vector format, version 3: the display stage (architecture §16.5).

One rejected text per reader rule added in version 3, with its line; the round trip; a version 2
file rejected at its version line; the export of the display output of a pipeline vector.
"""

import dataclasses
from typing import Any

import numpy as np
import pytest

from sinus_dsp.display import display_lowpass, display_lowpass_taps
from sinus_dsp.errors import MalformedFileError
from sinus_dsp.golden import GoldenVector, golden_vector, parse_golden_vector, render_golden_vector
from sinus_dsp.heart_rate import HeartRateEvent
from sinus_dsp.pipeline import run_pipeline
from sinus_dsp.synthetic import synthetic_ecg
from sinus_dsp.version import SoftwareIdentity

DIGEST = "cd" * 32
SOFTWARE = SoftwareIdentity(
    version="0.3.0.dev0", source_sha256=DIGEST, python="3.14", runtime=(("numpy", "2.5.3"),)
)
N = 6


def vector(**changes: Any) -> GoldenVector:
    base = GoldenVector(
        input_id="v3",
        input_source="synthetic",
        input_parameters="a=1",
        fs_hz=125.0,
        mains_hz=50,
        software_version="0.3.0.dev0",
        source_sha256=DIGEST,
        stages=("baseline", "mains"),
        coefficients=(
            np.array([[0.5, -1.0, 0.5, 1.0, -0.25, 0.125]]),
            np.array([[1.0, 2.0, 3.0, 1.0, 4.0, 5.0]]),
        ),
        input_mv=np.linspace(-1.0, 1.0, N),
        stage_outputs_mv=(np.zeros(N), np.ones(N)),
        beats=np.array([2], dtype=np.int64),
        reference_beats=np.array([2], dtype=np.int64),
        beat_startup=np.array([True]),
        beat_reported_at=np.array([3], dtype=np.int64),
        heart_rates=(HeartRateEvent(5, None, "no_recent_beat", None),),
        window_first=np.array([0], dtype=np.int64),
        window_last=np.array([5], dtype=np.int64),
        window_reported_at=np.array([5], dtype=np.int64),
        window_index=np.array([0.5]),
        window_usable=np.array([True]),
        display_delay_samples=2,
        display_taps=np.array([0.1, 0.2, 0.4, 0.2, 0.1]),
        display_mv=np.linspace(0.0, 0.5, N),
    )
    return dataclasses.replace(base, **changes)


TEXT = render_golden_vector(vector())
LINES = TEXT.split("\n")[:-1]


def number(line: str) -> int:
    assert LINES.count(line) == 1, line
    return LINES.index(line) + 1


def edit(changes: dict[str, str | None]) -> str:
    out = []
    for line in LINES:
        replacement = changes.get(line, line)
        if replacement is not None:
            out.append(replacement)
    return "\n".join(out) + "\n"


def test_text_layout() -> None:
    assert "n_quality_windows=1\ndisplay_delay_samples=2\n[coefficients]\n" in TEXT
    assert "mains,0,1.0,2.0,3.0,4.0,5.0\n[display_coefficients]\ntap,h\n0,0.1\n" in TEXT
    assert "4,0.1\n[signals]\ninput_mv,baseline_mv,mains_mv,display_mv\n" in TEXT
    assert number("[display_coefficients]") < number("[signals]")


def test_round_trip() -> None:
    parsed = parse_golden_vector(TEXT, "t")
    expected = vector()
    assert parsed.display_delay_samples == 2 and type(parsed.display_delay_samples) is int
    assert parsed.display_taps.tobytes() == expected.display_taps.tobytes()
    assert parsed.display_mv.tobytes() == expected.display_mv.tobytes()
    assert [o.tobytes() for o in parsed.stage_outputs_mv] == [
        o.tobytes() for o in expected.stage_outputs_mv
    ]
    assert render_golden_vector(parsed) == TEXT


def test_a_version_2_file_is_rejected_at_its_version_line() -> None:
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(edit({"format_version=3": "format_version=2"}), "old")
    assert caught.value.line == 2
    assert "unknown format version 2" in caught.value.reason
    assert "only version 3 is read" in caught.value.reason


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("0", "outside 1 to 30"),
        ("31", "outside 1 to 30"),
        ("x", "not an integer"),
        ("02", "not an integer"),
        ("-1", "not an integer"),
        ("2.0", "not an integer"),
    ],
)
def test_display_delay_header_rules(value: str, reason: str) -> None:
    text = edit({"display_delay_samples=2": f"display_delay_samples={value}"})
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(text, "t")
    assert caught.value.line == number("display_delay_samples=2")
    assert reason in caught.value.reason


def test_display_delay_header_key_is_last_and_required() -> None:
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(edit({"display_delay_samples=2": None}), "t")
    assert caught.value.line == number("display_delay_samples=2")
    assert "display_delay_samples" in caught.value.reason


def test_a_wrong_delay_changes_the_expected_number_of_tap_rows() -> None:
    text = edit({"display_delay_samples=2": "display_delay_samples=3"})
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(text, "t")
    assert caught.value.line == number("[signals]")
    assert "[display_coefficients] has 5 rows" in caught.value.reason


def _fails(text: str, line: int, reason: str) -> None:
    with pytest.raises(MalformedFileError) as caught:
        parse_golden_vector(text, "t")
    assert caught.value.line == line
    assert reason in caught.value.reason


def test_display_column_line() -> None:
    _fails(edit({"tap,h": "tap,coefficient"}), number("tap,h"), "expected tap,h")


def test_section_line_of_the_display_coefficients() -> None:
    _fails(
        edit({"[display_coefficients]": "[display_coefficient]"}),
        number("[display_coefficients]"),
        "expected [display_coefficients]",
    )


def test_missing_tap_row() -> None:
    _fails(edit({"4,0.1": None}), number("[signals]") - 1, "has 4 rows")


def test_extra_tap_row() -> None:
    _fails(
        edit({"[signals]": "5,0.1\n[signals]"}),
        number("[signals]"),
        "more rows than 2 * display_delay_samples + 1 (5)",
    )


def test_tap_number_out_of_order() -> None:
    _fails(edit({"2,0.4": "3,0.4"}), number("2,0.4"), "tap 3, expected tap 2")


def test_tap_row_fields_and_values() -> None:
    _fails(edit({"2,0.4": "2,0.4,1.0"}), number("2,0.4"), "3 fields, expected 2")
    _fails(edit({"2,0.4": "2,x"}), number("2,0.4"), "not a float")
    _fails(edit({"2,0.4": "2,1e-400"}), number("2,0.4"), "converts to zero")


def test_signal_column_line_must_end_with_display_mv() -> None:
    _fails(
        edit({"input_mv,baseline_mv,mains_mv,display_mv": "input_mv,baseline_mv,mains_mv"}),
        number("input_mv,baseline_mv,mains_mv,display_mv"),
        "expected input_mv,baseline_mv,mains_mv,display_mv",
    )


def test_signal_row_of_three_fields() -> None:
    row = TEXT.split("\n")[number("input_mv,baseline_mv,mains_mv,display_mv")]
    short = row.rsplit(",", 1)[0]
    _fails(edit({row: short}), number(row), "row with 3 fields, expected 4")


def test_display_values_are_exported_for_a_pipeline_input() -> None:
    ecg = synthetic_ecg(250.0, 75, "bw-mains50")
    exported = golden_vector(
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
    assert exported.display_delay_samples == 8
    assert exported.display_taps.tolist() == display_lowpass_taps(250.0).tolist()
    assert exported.display_mv.tolist() == display_lowpass(result.mains_mv, 250.0).tolist()
    parsed = parse_golden_vector(render_golden_vector(exported), "t")
    assert parsed.display_mv.tolist() == exported.display_mv.tolist()
    assert parsed.display_taps.tolist() == exported.display_taps.tolist()
