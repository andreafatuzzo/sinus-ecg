"""Requirement tests of SRS-015: exact read-back and the documented file format (RC-012).

SRS-015 (v0.7.2): "The file format shall be documented in `architecture.md`. Numeric values
shall be written so that reading them back gives exactly the values computed."

The format is architecture section 7.3: a float64 is written as Python's `repr()` of it (the
shortest decimal string that converts back to the same value), with the syntax
`-?[0-9]+(\\.[0-9]+)?(e[+-][0-9]+)?`; non-finite values are never written, and the export
fails with an error naming the input instead; readers reject a file that breaks a rule of the
format, naming the first offending line. Since architecture v0.2.11 the readers also reject an
integer greater than 2**63 - 1 at its own line, header counts included (rule C3), and a float
that converts to zero although a digit of its significand is not zero, such as `1e-400`
(rule C4; `0.0e-400` and `-0.0` are zero and accepted), so that the Python and C++ readers
accept the same texts; and "The line named" fixes where a row count that differs from the
header is named (the line of the next section when rows are missing, the first row after the
count when there are more). The interfaces are those of section 8.12:
`golden_vector`, `render_golden_vector`, `parse_golden_vector`, `read_golden_vector`, and the
errors `NonFiniteOutputError(input_id)` and `MalformedFileError(path, line, reason)`.

Why the reader cases belong to SRS-015: the read-back of the requirement is only exact if a
file that is not what the writer wrote (truncated, altered, converted to CR LF line endings)
is refused rather than read as other values. Each case is checked with the reader of the
software and with the test's own reader of section 7.3 (`read_golden_file`).

The files written by the export are tested in `test_srs_015_golden_vector_files.py`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sinus_dsp.errors import MalformedFileError, NonFiniteOutputError
from sinus_dsp.golden import (
    golden_vector,
    parse_golden_vector,
    read_golden_vector,
    render_golden_vector,
)
from sinus_dsp.pipeline import run_pipeline
from sinus_dsp.version import SoftwareIdentity

# A made-up software identity: `golden_vector` copies it into the file.
SOFTWARE = SoftwareIdentity(
    version="9.8.7.dev6", source_sha256="0123456789abcdef" * 4, python="3.11", runtime=()
)

# Values that need care to read back exactly: the smallest subnormal and the smallest normal
# value, negative zero, values that need 17 significant digits, very small and large
# magnitudes, a value whose shortest form has an exponent.
EDGE_VALUES = (
    5e-324,
    -5e-324,
    2.2250738585072014e-308,
    -0.0,
    0.1 + 0.2,
    1 / 3,
    -2 / 3,
    1e-300,
    -1.2345e-05,
    123456.78901234567,
    1e16,
    9007199254740994.0,
    0.1,
)


def _same_float64(a: Any, b: Any) -> bool:
    """Bitwise equality of two float64 arrays (so -0.0 differs from 0.0)."""
    x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return x.shape == y.shape and x.tobytes() == y.tobytes()


def _ecg_with_edge_values(make_synthetic_ecg: Callable[..., Any], fs: float) -> np.ndarray:
    """10 s of the test's synthetic ECG at 360 Hz (resampled by index for other rates), with
    the edge values in place of the first samples and of samples spread over the signal."""
    n = int(np.ceil(10 * fs))
    signal = np.resize(make_synthetic_ecg(360, 75, n_samples=3600).signal_mv, n).copy()
    for i, value in enumerate(EDGE_VALUES):
        signal[i] = value
        signal[(i + 1) * (n // (len(EDGE_VALUES) + 1))] = value
    return signal


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize(
    ("fs", "mains"), [(125.0, 50), (333.3, 60), (360.0, 60), (1000.0, 50), (1000.0, 60)]
)
def test_values_read_back_exactly(
    fs: float,
    mains: int,
    make_synthetic_ecg: Callable[..., Any],
    read_golden_file: Callable[[bytes], Any],
) -> None:
    """Every number of a file reads back as exactly the value computed, edge values included.

    Input: `golden_vector` on 10 s of synthetic ECG holding the edge values (5e-324,
    -5e-324, 2.2250738585072014e-308, -0.0, 0.1 + 0.2, 1/3, -2/3, 1e-300, -1.2345e-05,
    123456.78901234567, 1e16, 9007199254740994.0, 0.1) at the start and spread over it, at
    125, 333.3, 360 and 1000 Hz, mains 50 or 60 Hz, reference beats with a repeated sample;
    rendered with `render_golden_vector`.
    Expected: the test's own reader accepts the text; every float is written as Python's
    `repr()` of its value; the values read back (with `float()`) equal bitwise the input, the
    stage outputs and coefficients of `run_pipeline` on the same input, the sampling frequency
    and the reference beats; `parse_golden_vector` gives back the same values, bitwise; and
    rendering the parsed vector gives the same text.
    """
    signal = _ecg_with_edge_values(make_synthetic_ecg, fs)
    reference = [0, 5, 5, signal.size - 1]
    vector = golden_vector(
        "edge-values", "test", "case=edge", signal, fs, mains, reference, software=SOFTWARE
    )
    text = render_golden_vector(vector)
    expected = run_pipeline(signal, fs, mains)

    golden = read_golden_file(text.encode("utf-8"))
    assert golden.not_shortest == ()
    assert float(golden.header["sampling_frequency_hz"]) == fs
    assert _same_float64(golden.input_mv, signal)
    assert _same_float64(golden.stage_mv("baseline"), expected.baseline_mv)
    assert _same_float64(golden.stage_mv("mains"), expected.mains_mv)
    for stage, sos in zip(("baseline", "mains"), expected.coefficients, strict=True):
        assert _same_float64(golden.coefficients[stage], np.asarray(sos)[:, [0, 1, 2, 4, 5]])
    assert golden.beats.tolist() == expected.beats.tolist()
    assert golden.reference_beats.tolist() == reference
    assert golden.header["software_version"] == SOFTWARE.version
    assert golden.header["source_sha256"] == SOFTWARE.source_sha256

    parsed = parse_golden_vector(text, "edge.golden.txt")
    assert parsed.fs_hz == fs
    assert _same_float64(parsed.input_mv, signal)
    for read, computed in zip(
        parsed.stage_outputs_mv, (expected.baseline_mv, expected.mains_mv), strict=True
    ):
        assert _same_float64(read, computed)
    for read, computed in zip(parsed.coefficients, expected.coefficients, strict=True):
        assert _same_float64(read, computed)
    assert render_golden_vector(parsed) == text


@pytest.fixture(scope="module")
def base_vector(make_synthetic_ecg: Callable[..., Any]) -> Any:
    """A golden vector of 10 s of synthetic ECG at 360 Hz, 75 bpm, mains 60 Hz."""
    ecg = make_synthetic_ecg(360, 75, n_samples=3600)
    return golden_vector(
        "syn-test",
        "synthetic",
        "duration_s=10",
        ecg.signal_mv,
        360.0,
        60,
        ecg.qrs_samples,
        software=SOFTWARE,
    )


def _with_value(array: Any, index: int, value: float) -> np.ndarray:
    copy = np.array(array, dtype=np.float64, copy=True)
    copy.flat[index] = value
    return copy


NON_FINITE_CASES = ["input-inf", "input-nan", "baseline-nan", "mains-minus-inf", "coefficient-inf"]


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("case", [*NON_FINITE_CASES, "sampling-frequency-inf"])
def test_non_finite_value_is_never_written(case: str, base_vector: Any) -> None:
    """A value that is not finite is never written: rendering fails, naming the input.

    Input: the base vector with one value replaced: +inf in the input (sample 7), NaN in
    the baseline output (sample 0), -inf in the mains output (last sample), +inf in a
    baseline coefficient, or an infinite sampling frequency.
    Expected: `render_golden_vector` raises `NonFiniteOutputError` whose `input_id` is that of
    the vector (`syn-test`), and returns no text.
    """
    baseline, mains = base_vector.stage_outputs_mv
    changes: dict[str, Any] = {
        "input-inf": {"input_mv": _with_value(base_vector.input_mv, 7, np.inf)},
        "input-nan": {"input_mv": _with_value(base_vector.input_mv, 7, np.nan)},
        "baseline-nan": {"stage_outputs_mv": (_with_value(baseline, 0, np.nan), mains)},
        "mains-minus-inf": {"stage_outputs_mv": (baseline, _with_value(mains, -1, -np.inf))},
        "coefficient-inf": {
            "coefficients": (
                _with_value(base_vector.coefficients[0], 1, np.inf),
                base_vector.coefficients[1],
            )
        },
        "sampling-frequency-inf": {"fs_hz": float("inf")},
    }
    vector = dataclasses.replace(base_vector, **changes[case])

    with pytest.raises(NonFiniteOutputError) as excinfo:
        render_golden_vector(vector)

    assert excinfo.value.input_id == "syn-test"


# --------------------------------------------------------------------------------------------
# Files that break the format are refused, naming the first offending line
# --------------------------------------------------------------------------------------------


def _line_of(lines: list[str], text: str) -> int:
    """The 1-based number of the first line equal to ``text``."""
    return lines.index(text) + 1


def _replace_field(line: str, index: int, value: str) -> str:
    fields = line.split(",")
    fields[index] = value
    return ",".join(fields)


def _set_header(lines: list[str], key: str, value: str) -> int:
    n = next(i for i, line in enumerate(lines) if line.startswith(f"{key}=")) + 1
    lines[n - 1] = f"{key}={value}"
    return n


# The header counts, by the prefix of their case names, and the section that follows the
# rows of each count.
COUNT_KEYS = {
    "n-samples": "n_samples",
    "n-beats": "n_beats",
    "n-reference-beats": "n_reference_beats",
}
NEXT_SECTION = {
    "n_samples": "[beats]",
    "n_beats": "[reference_beats]",
    "n_reference_beats": "[end]",
}
# Integers at the bound of architecture section 7.3: 2**63 - 1 is the largest one accepted.
LIMIT_TOKENS = {
    "at": "9223372036854775807",
    "above": "9223372036854775808",
    "far-above": "100000000000000000000000000000",
}


def _count(lines: list[str], key: str) -> int:
    return int(next(x for x in lines if x.startswith(f"{key}=")).split("=")[1])


def _mutate(text: str, case: str) -> tuple[str, int | None]:
    """The text of a case and the line that must be named (None: not asserted)."""
    lines = text.split("\n")[:-1]
    beats = _line_of(lines, "[beats]") + 2  # first row of [beats]
    reference = _line_of(lines, "[reference_beats]") + 2
    n_samples = int(next(x for x in lines if x.startswith("n_samples=")).split("=")[1])
    n: int | None
    if case == "carriage-returns":
        return text.replace("\n", "\r\n"), 1
    if case == "no-final-line-feed":
        return text[:-1], len(lines)
    if case == "text-after-end":
        return text + "x\n", len(lines) + 1
    if case == "truncated":
        return "\n".join(lines[:100]) + "\n", 100
    if case == "byte-order-mark":
        return "﻿" + text, 1
    if case == "space-in-a-row":
        lines[19], n = lines[19].replace(",", ", ", 1), 20
    elif case == "tab-in-the-header":
        lines[2], n = lines[2] + "\t", 3
    elif case == "empty-line":
        lines.insert(14, "")
        n = 15
    elif case == "unknown-format":
        n = _set_header(lines, "format", "sinus-golden-vectors")
    elif case == "unknown-version":
        n = _set_header(lines, "format_version", "2")
    elif case == "keys-out-of-order":
        lines[5], lines[6], n = lines[6], lines[5], 6
    elif case == "key-missing":
        del lines[7]
        n = 8
    elif case == "key-twice":
        lines.insert(3, lines[2])
        n = 4
    elif case == "digest-in-uppercase":
        n = _set_header(lines, "source_sha256", SOFTWARE.source_sha256.upper())
    elif case == "mains-55":
        n = _set_header(lines, "mains_frequency_hz", "55")
    elif case == "sampling-frequency-zero":
        n = _set_header(lines, "sampling_frequency_hz", "0.0")
    elif case == "sampling-frequency-1e999":
        n = _set_header(lines, "sampling_frequency_hz", "1e999")
    elif case == "empty-software-version":
        n = _set_header(lines, "software_version", "")
    elif case == "invalid-input-id":
        n = _set_header(lines, "input_id", "syn.test")
    elif case == "stage-twice":
        n = _set_header(lines, "stages", "baseline,baseline")
    elif case == "count-with-leading-zero":
        value = next(x for x in lines if x.startswith("n_beats=")).split("=")[1]
        n = _set_header(lines, "n_beats", "0" + value)
    elif case == "no-sample":
        n = _set_header(lines, "n_samples", "0")
    elif case.startswith("float-"):
        token = {
            "float-with-plus-sign": "+1.0",
            "float-1e999": "1e999",
            "float-nan": "nan",
            "float-inf": "inf",
            "float-uppercase-exponent": "1E-05",
            "float-without-leading-digit": ".5",
            "float-with-trailing-point": "1.",
            "float-with-underscore": "1_0",
            "float-hexadecimal": "0x1p-3",
            # Rule C4: the value converts to zero, a digit of the significand is not zero.
            "float-1e-400": "1e-400",
            "float-minus-1e-400": "-1e-400",
            "float-0.5e-400": "0.5e-400",
            "float-0.00001e-320": "0.00001e-320",
            "float-just-below-half-of-the-smallest-subnormal": "2.4703282292062327e-324",
            "float-minus-just-below-half-of-the-smallest-subnormal": "-2.4703282292062327e-324",
        }[case]
        lines[20], n = _replace_field(lines[20], 0, token), 21
    elif case == "coefficient-1e999":
        lines[15], n = _replace_field(lines[15], 3, "1e999"), 16
    elif case == "row-missing-a-field":
        lines[21], n = lines[21].rsplit(",", 1)[0], 22
    elif case == "row-with-an-extra-field":
        lines[21], n = lines[21] + ",0.0", 22
    elif case == "coefficient-row-of-another-stage":
        lines[15], n = _replace_field(lines[15], 0, "mains"), 16
    elif case == "coefficient-section-from-1":
        lines[15], n = _replace_field(lines[15], 1, "1"), 16
    elif case == "coefficient-row-with-six-fields":
        lines[16], n = lines[16].rsplit(",", 1)[0], 17
    elif case == "signal-columns-in-another-order":
        lines[18], n = "input_mv,mains_mv,baseline_mv", 19
    elif case == "section-missing":
        n = _line_of(lines, "[beats]")
        del lines[n - 1]
    elif case == "beat-not-greater":
        lines[beats], n = lines[beats - 1], beats + 1
    elif case == "beat-at-n-samples":
        last = reference - 3  # last row of [beats]
        lines[last - 1], n = str(n_samples), last
    elif case == "beat-with-leading-zero":
        lines[beats - 1], n = "0" + lines[beats - 1], beats
    elif case == "reference-beat-smaller":
        lines[reference], n = str(int(lines[reference - 1]) - 1), reference + 1
    elif case == "reference-beat-negative":
        lines[reference - 1], n = "-1", reference
    elif case.endswith("-in-the-header"):
        # e.g. "more-beats-in-the-header": the header count one more or one less than the rows.
        change, key = case.removesuffix("-in-the-header").split("-", 1)
        key = COUNT_KEYS["n-" + key]
        _set_header(lines, key, str(_count(lines, key) + (1 if change == "more" else -1)))
        following = _line_of(lines, NEXT_SECTION[key])
        # Fewer rows than the count: the line of the next section, found where the next row is
        # expected. More rows: the first row after the count, where that line is expected.
        n = following if change == "more" else following - 1
    elif case.endswith("-integer-limit") and case.startswith(tuple(COUNT_KEYS)):
        # e.g. "n-beats-above-the-integer-limit": the header count at 2**63 or 2**63 - 1.
        prefix = next(p for p in sorted(COUNT_KEYS, key=len, reverse=True) if case.startswith(p))
        bound = case.removeprefix(prefix + "-").removesuffix("-the-integer-limit")
        key = COUNT_KEYS[prefix]
        line = _set_header(lines, key, LIMIT_TOKENS[bound])
        # Above the limit: refused at its own header line (rule C3). At the limit: the integer
        # rule holds, and the file is refused where its rows end, as with any larger count.
        n = line if bound in ("above", "far-above") else _line_of(lines, NEXT_SECTION[key])
    elif case == "beat-above-the-integer-limit":
        lines[beats - 1], n = LIMIT_TOKENS["above"], beats
    elif case == "reference-beat-above-the-integer-limit":
        last = _line_of(lines, "[end]") - 1
        lines[last - 1], n = LIMIT_TOKENS["above"], last
    elif case == "coefficient-section-above-the-integer-limit":
        lines[16], n = _replace_field(lines[16], 1, LIMIT_TOKENS["above"]), 17
    elif case == "coefficient-1e-400":
        lines[15], n = _replace_field(lines[15], 3, "1e-400"), 16
    elif case == "sampling-frequency-1e-400":
        n = _set_header(lines, "sampling_frequency_hz", "1e-400")
    elif case == "mains-output-1e-400":
        lines[20], n = _replace_field(lines[20], 2, "1e-400"), 21
    else:
        raise AssertionError(case)
    return "\n".join(lines) + "\n", n


MALFORMED_CASES = [
    "carriage-returns",
    "no-final-line-feed",
    "text-after-end",
    "truncated",
    "byte-order-mark",
    "space-in-a-row",
    "tab-in-the-header",
    "empty-line",
    "unknown-format",
    "unknown-version",
    "keys-out-of-order",
    "key-missing",
    "key-twice",
    "digest-in-uppercase",
    "mains-55",
    "sampling-frequency-zero",
    "sampling-frequency-1e999",
    "empty-software-version",
    "invalid-input-id",
    "stage-twice",
    "count-with-leading-zero",
    "no-sample",
    "float-with-plus-sign",
    "float-1e999",
    "float-nan",
    "float-inf",
    "float-uppercase-exponent",
    "float-without-leading-digit",
    "float-with-trailing-point",
    "float-with-underscore",
    "float-hexadecimal",
    "coefficient-1e999",
    "row-missing-a-field",
    "row-with-an-extra-field",
    "coefficient-row-of-another-stage",
    "coefficient-section-from-1",
    "coefficient-row-with-six-fields",
    "signal-columns-in-another-order",
    "section-missing",
    "beat-not-greater",
    "beat-at-n-samples",
    "beat-with-leading-zero",
    "reference-beat-smaller",
    "reference-beat-negative",
    "more-samples-in-the-header",
    "fewer-samples-in-the-header",
    "more-beats-in-the-header",
    "fewer-beats-in-the-header",
    "more-reference-beats-in-the-header",
    "fewer-reference-beats-in-the-header",
    # Rule C3 (architecture v0.2.11): integers above 2**63 - 1, and the bound itself.
    "n-samples-above-the-integer-limit",
    "n-beats-above-the-integer-limit",
    "n-reference-beats-above-the-integer-limit",
    "n-reference-beats-far-above-the-integer-limit",
    "n-samples-at-the-integer-limit",
    "n-beats-at-the-integer-limit",
    "n-reference-beats-at-the-integer-limit",
    "beat-above-the-integer-limit",
    "reference-beat-above-the-integer-limit",
    "coefficient-section-above-the-integer-limit",
    # Rule C4 (architecture v0.2.11): a float that converts to zero, its significand not zero.
    "float-1e-400",
    "float-minus-1e-400",
    "float-0.5e-400",
    "float-0.00001e-320",
    "float-just-below-half-of-the-smallest-subnormal",
    "float-minus-just-below-half-of-the-smallest-subnormal",
    "mains-output-1e-400",
    "coefficient-1e-400",
    "sampling-frequency-1e-400",
]


@pytest.mark.requirement("SRS-015")
def test_reader_accepts_the_file_as_written(
    base_vector: Any, tmp_path: Path, read_golden_file: Callable[[bytes], Any]
) -> None:
    """The text of the base vector, unchanged, is read back by both readers.

    Input: `render_golden_vector(base vector)`, parsed as text and written to a file and
    read with `read_golden_vector`; the same bytes read by the test's reader.
    Expected: no error; the input read back equals the base vector's, bitwise.
    """
    text = render_golden_vector(base_vector)
    path = tmp_path / "base.golden.txt"
    path.write_bytes(text.encode("utf-8"))

    assert _same_float64(parse_golden_vector(text, "base").input_mv, base_vector.input_mv)
    assert _same_float64(read_golden_vector(path).input_mv, base_vector.input_mv)
    assert _same_float64(read_golden_file(text.encode("utf-8")).input_mv, base_vector.input_mv)


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("case", MALFORMED_CASES)
def test_file_that_breaks_the_format_is_refused(
    case: str,
    base_vector: Any,
    tmp_path: Path,
    read_golden_file: Callable[[bytes], Any],
    golden_format_error: type[Exception],
) -> None:
    """A text that breaks a rule of the documented format is refused, naming the line.

    Input: the text of the base vector changed in one way: CR LF line endings; no final line
    feed; text after `[end]`; cut after line 100; a byte-order mark; a space, a tab, an
    empty line; an unknown format or version; header keys out of order, missing or given
    twice; header values that break their rule (digest in uppercase, mains 55, sampling
    frequency 0.0 or 1e999, empty software version, `.` in the input identifier, a stage
    given twice, `n_beats` with a leading zero, `n_samples=0`); a float written `+1.0`,
    `1e999`, `nan`, `inf`, `1E-05`, `.5`, `1.`, `1_0` or `0x1p-3`; a coefficient 1e999; a row
    with a field missing or added; coefficient rows of the wrong stage, numbered from 1, or
    with six fields; signal columns in another order; the `[beats]` line missing; a detected
    beat equal to the previous one, equal to `n_samples`, or with a leading zero; a reference
    beat smaller than the previous one or negative; each header count (`n_samples`, `n_beats`,
    `n_reference_beats`) one more or one less than its rows; rule C3: a header count of
    9223372036854775808 (2**63) or of 10**29, a detected beat, a reference beat or a
    coefficient section number of 9223372036854775808, and the bound itself, a header count
    of 9223372036854775807; rule C4: a float written `1e-400`, `-1e-400`, `0.5e-400`,
    `0.00001e-320`, `2.4703282292062327e-324` or `-2.4703282292062327e-324` (each converts to
    zero) in the input, the mains output, a coefficient or the sampling frequency.
    Expected: `parse_golden_vector(text, "case.golden.txt")` raises `MalformedFileError` with
    `path` "case.golden.txt" and the 1-based number of the first offending line (the last line
    for a text that ends too early); for a row count that differs from the header, the line
    where the rows and the count disagree: the line of the next section with fewer rows than
    the count, the first row after the count with more rows; for an integer above 2**63 - 1,
    its own line, also in the header; for a header count of exactly 2**63 - 1, which the
    integer rule accepts, the line of the next section, where the rows end (no reader sizes
    anything from that count first); for a float of rule C4, its own line.
    `read_golden_vector` on the same bytes in a file raises it with the path of the file and
    the same line; the test's own reader of section 7.3 also refuses it, at the same line.
    """
    text, line = _mutate(render_golden_vector(base_vector), case)
    path = tmp_path / "case.golden.txt"
    path.write_bytes(text.encode("utf-8"))

    with pytest.raises(MalformedFileError) as parsed:
        parse_golden_vector(text, "case.golden.txt")
    with pytest.raises(MalformedFileError) as read:
        read_golden_vector(path)
    with pytest.raises(golden_format_error) as own:
        read_golden_file(text.encode("utf-8"))

    assert parsed.value.path == "case.golden.txt"
    assert read.value.path == str(path)
    assert parsed.value.reason
    own_line = getattr(own.value, "line", None)
    if line is not None:
        assert (parsed.value.line, read.value.line, own_line) == (line, line, line)
    else:
        assert read.value.line == parsed.value.line


# Floats that the rules of architecture section 7.3 accept although they are written in no file
# by the writer (it writes `repr()`): zero with an exponent beyond the range of float64 (every
# digit of the significand is zero, rule C4), signed zeros, the smallest subnormal and the
# texts just above half of it, which round to it rather than to zero.
ACCEPTED_TOKENS = [
    "0.0e-400",
    "-0.0e-400",
    "0e-400",
    "0.000e+999",
    "-0.0",
    "0.0",
    "5e-324",
    "2.4703282292062328e-324",
    "-2.4703282292062328e-324",
]


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("place", ["input", "mains-output", "coefficient"])
@pytest.mark.parametrize("token", ACCEPTED_TOKENS)
def test_float_that_is_zero_or_does_not_convert_to_zero_is_accepted(
    token: str,
    place: str,
    base_vector: Any,
    tmp_path: Path,
    read_golden_file: Callable[[bytes], Any],
) -> None:
    """Rule C4 accepts a float that is zero, whatever its exponent, and a float that converts
    to a non-zero value, however small (architecture section 7.3, v0.2.11).

    Input: the text of the base vector with one float replaced by `0.0e-400`, `-0.0e-400`,
    `0e-400`, `0.000e+999`, `-0.0`, `0.0`, `5e-324`, `2.4703282292062327e-324` plus one unit
    in the last digit (`…28e-324`) or its negative: the input of the second sample, the mains
    output of the second sample, or the coefficient b1 of the baseline stage.
    Expected: `parse_golden_vector`, `read_golden_vector` and the test's own reader accept the
    text; the value read at that place is `float(token)`, bitwise (negative zero keeps its
    sign; `…28e-324` reads as 5e-324); every other value equals that of the base vector,
    bitwise.
    """
    lines = render_golden_vector(base_vector).split("\n")
    if place == "coefficient":
        lines[15] = _replace_field(lines[15], 3, token)
    else:
        lines[20] = _replace_field(lines[20], 0 if place == "input" else 2, token)
    text = "\n".join(lines)
    path = tmp_path / "case.golden.txt"
    path.write_bytes(text.encode("utf-8"))
    expected = np.float64(float(token))
    baseline, mains = base_vector.stage_outputs_mv
    want_input, want_mains = np.array(base_vector.input_mv), np.array(mains)
    want_coefficients = np.array(base_vector.coefficients[0])
    if place == "input":
        want_input[1] = expected
    elif place == "mains-output":
        want_mains[1] = expected
    else:
        want_coefficients[0, 1] = expected

    for vector in (parse_golden_vector(text, "case.golden.txt"), read_golden_vector(path)):
        assert _same_float64(vector.input_mv, want_input)
        assert _same_float64(vector.stage_outputs_mv[0], baseline)
        assert _same_float64(vector.stage_outputs_mv[1], want_mains)
        assert _same_float64(vector.coefficients[0], want_coefficients)
        assert _same_float64(vector.coefficients[1], base_vector.coefficients[1])
    own = read_golden_file(text.encode("utf-8"))
    assert _same_float64(own.input_mv, want_input)
    assert _same_float64(own.stage_mv("mains"), want_mains)
    assert _same_float64(own.coefficients["baseline"], want_coefficients[:, [0, 1, 2, 4, 5]])


@pytest.mark.requirement("SRS-015")
def test_file_that_is_not_utf8_is_refused(base_vector: Any, tmp_path: Path) -> None:
    """A file whose bytes are not UTF-8 text is refused as such.

    Input: the bytes of the base vector's text with the byte 0xFF in place of a digit of
    the first signal row, read with `read_golden_vector`.
    Expected: `MalformedFileError` with `path` the path of the file, `line` None and the
    reason `not UTF-8 text` (architecture, section 8.12).
    """
    data = render_golden_vector(base_vector).encode("utf-8")
    position = data.index(b"[signals]") + len(b"[signals]\ninput_mv,baseline_mv,mains_mv\n")
    path = tmp_path / "bytes.golden.txt"
    path.write_bytes(data[:position] + b"\xff" + data[position + 1 :])

    with pytest.raises(MalformedFileError) as excinfo:
        read_golden_vector(path)

    assert (excinfo.value.path, excinfo.value.line, excinfo.value.reason) == (
        str(path),
        None,
        "not UTF-8 text",
    )
