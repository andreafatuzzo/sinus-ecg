"""Requirement tests of SRS-015: exact read-back and the documented file format (RC-012).

SRS-015 (v0.7.2), on format version 2 (architecture, section 13.8; version 2 holds every item
that SRS-015 lists and adds those of SRS-033): "The file format shall be documented in
`architecture.md`. Numeric values shall be written so that reading them back gives exactly
the values computed."

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

The rules of version 2 for `[beats]` (mark, `reported_at`), `[heart_rates]` and
`[quality_windows]` are checked on a 40 s vector with a held stretch, which has detections of
both marks, heart-rate events with and without a detection and windows of both marks.

The files written by the export are tested in `test_srs_015_golden_vector_files.py`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError, MalformedFileError, NonFiniteOutputError
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


# Edge values beyond 1000 mV are refused as input (SRS-003), so they can only reach a file in
# a hand-built `GoldenVector` rendered directly: `test_values_read_back_exactly` builds the
# vector from an in-range signal and then puts the large values into it.


def _ecg_with_edge_values(
    make_synthetic_ecg: Callable[..., Any], fs: float, *, large: bool = False
) -> np.ndarray:
    """10 s of the test's synthetic ECG at 360 Hz (resampled by index for other rates), with
    the edge values in place of the first samples and of samples spread over the signal.

    With `large` false, the values beyond 1000 mV are replaced by in-range ones (the signal
    can be given to `golden_vector`); with `large` true, they are kept.
    """
    n = int(np.ceil(10 * fs))
    signal = np.resize(make_synthetic_ecg(360, 75, n_samples=3600).signal_mv, n).copy()
    for i, value in enumerate(EDGE_VALUES):
        if not large and abs(value) > 1000.0:
            value = value / 1e3 if abs(value) < 1e6 else 999.0 + 1 / 3
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
    the values beyond 1000 mV (123456.78901234567, 1e16, 9007199254740994.0), which SRS-003
    refuses as input, replaced by in-range ones in the signal given to `golden_vector` and put
    into the input and the stage outputs of the vector by `dataclasses.replace` (a hand-built
    vector); rendered with `render_golden_vector`.
    Expected: the test's own reader accepts the text; every float is written as Python's
    `repr()` of its value; the values read back (with `float()`) equal bitwise the input and the
    stage outputs of the hand-built vector, the coefficients of `run_pipeline`, the sampling
    frequency and the reference beats; `parse_golden_vector` gives back the same values,
    bitwise; and rendering the parsed vector gives the same text.
    """
    small = _ecg_with_edge_values(make_synthetic_ecg, fs)
    signal = _ecg_with_edge_values(make_synthetic_ecg, fs, large=True)
    changed = small != signal
    assert changed.any(), "the large edge values must be present"
    reference = [0, 5, 5, small.size - 1]
    computed = golden_vector(
        "edge-values", "test", "case=edge", small, fs, mains, reference, software=SOFTWARE
    )
    expected = run_pipeline(small, fs, mains)
    # Hand-built vector: the input and the stage outputs hold the values beyond 1000 mV.
    stage_outputs = tuple(np.where(changed, signal, out) for out in computed.stage_outputs_mv)
    vector = dataclasses.replace(computed, input_mv=signal, stage_outputs_mv=stage_outputs)
    text = render_golden_vector(vector)

    golden = read_golden_file(text.encode("utf-8"))
    assert golden.not_shortest == ()
    assert float(golden.header["sampling_frequency_hz"]) == fs
    assert _same_float64(golden.input_mv, signal)
    assert _same_float64(golden.stage_mv("baseline"), stage_outputs[0])
    assert _same_float64(golden.stage_mv("mains"), stage_outputs[1])
    for stage, sos in zip(("baseline", "mains"), expected.coefficients, strict=True):
        assert _same_float64(golden.coefficients[stage], np.asarray(sos)[:, [0, 1, 2, 4, 5]])
    assert golden.beats.tolist() == expected.beats.tolist()
    assert golden.beat_startup.tolist() == np.asarray(expected.detections.startup).tolist()
    assert golden.beat_reported_at.tolist() == np.asarray(expected.detections.reported_at).tolist()
    assert list(golden.heart_rates) == [
        (e.sample, e.beat_index, e.status, e.bpm) for e in expected.heart_rate
    ]
    assert golden.window_first.tolist() == np.asarray(expected.quality.first).tolist()
    assert golden.window_usable.tolist() == np.asarray(expected.quality.usable).tolist()
    assert _same_float64(golden.window_index, expected.quality.index)
    assert golden.reference_beats.tolist() == reference
    assert golden.header["software_version"] == SOFTWARE.version
    assert golden.header["source_sha256"] == SOFTWARE.source_sha256

    parsed = parse_golden_vector(text, "edge.golden.txt")
    assert parsed.fs_hz == fs
    assert _same_float64(parsed.input_mv, signal)
    for read, written in zip(parsed.stage_outputs_mv, stage_outputs, strict=True):
        assert _same_float64(read, written)
    for read, coefficients in zip(parsed.coefficients, expected.coefficients, strict=True):
        assert _same_float64(read, coefficients)
    assert render_golden_vector(parsed) == text


@pytest.fixture(scope="module")
def base_vector(make_synthetic_ecg: Callable[..., Any]) -> Any:
    """A golden vector of 40 s of synthetic ECG at 360 Hz, 75 bpm, mains 60 Hz, whose samples
    from 15 s to the end are held at the value of the sample at 15 s (built by the test), so
    that the last heart-rate event is a change of status at no detection; it holds start-up
    and reliable marks, heart-rate events with and without a detection and windows of both
    marks."""
    ecg = make_synthetic_ecg(360, 75, n_samples=14400)
    signal = ecg.signal_mv.copy()
    signal[5400:] = signal[5400]
    return golden_vector(
        "syn-test",
        "synthetic",
        "duration_s=40",
        signal,
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
    "n-heart-rates": "n_heart_rates",
    "n-quality-windows": "n_quality_windows",
}
NEXT_SECTION = {
    "n_samples": "[beats]",
    "n_beats": "[reference_beats]",
    "n_reference_beats": "[heart_rates]",
    "n_heart_rates": "[quality_windows]",
    "n_quality_windows": "[end]",
}
# Integers at the bound of architecture section 7.3: 2**63 - 1 is the largest one accepted.
LIMIT_TOKENS = {
    "at": "9223372036854775807",
    "above": "9223372036854775808",
    "far-above": "100000000000000000000000000000",
}


# Cases of the rules that version 2 adds (architecture, section 13.8), by the section they
# concern. Each is built by `_mutate_v2` from the text of the base vector.
V2_CASES = [
    "beat-row-with-two-fields",
    "beat-unknown-mark",
    "beat-mark-empty",
    "beat-reported-before-its-index",
    "beat-reported-at-n-samples",
    "beat-reported-decreases",
    "beat-reported-above-the-integer-limit",
    "beats-columns-in-another-order",
    "heart-rate-row-with-three-fields",
    "heart-rate-unknown-status",
    "heart-rate-status-empty",
    "heart-rate-sample-empty",
    "heart-rate-with-a-status-that-has-no-rate",
    "heart-rate-valid-without-a-rate",
    "heart-rate-zero",
    "heart-rate-negative",
    "heart-rate-beat-index-names-a-start-up-detection",
    "heart-rate-beat-index-names-no-detection",
    "heart-rate-reported-at-another-sample-than-the-detection",
    "heart-rate-reliable-detection-missing",
    "heart-rate-reliable-detection-named-twice",
    "heart-rate-sample-decreases",
    "heart-rate-sample-at-n-samples",
    "heart-rates-columns-in-another-order",
    "window-row-with-four-fields",
    "window-first-sample-repeated",
    "window-last-before-first",
    "window-reported-before-last",
    "window-reported-at-n-samples",
    "window-index-above-one",
    "window-index-negative",
    "window-index-empty",
    "window-unknown-mark",
    "window-usable-with-a-low-index",
    "window-not-usable-with-a-high-index",
    "window-exactly-half-marked-not-usable",
    "window-just-below-half-marked-usable",
    "quality-windows-columns-in-another-order",
    "heart-rates-section-missing",
    "quality-windows-section-missing",
    "sections-heart-rates-and-windows-swapped",
]


def _section(lines: list[str], name: str) -> tuple[int, int]:
    """Index of the first row and index after the last row of section ``name``."""
    start = lines.index(f"[{name}]") + 2
    end = start
    while not lines[end].startswith("["):
        end += 1
    return start, end


def _mutate_v2(text: str, case: str) -> tuple[str, int]:
    """The text of a case of ``V2_CASES`` and the line that must be named."""
    lines = text.split("\n")[:-1]
    b0, b1 = _section(lines, "beats")
    h0, h1 = _section(lines, "heart_rates")
    w0, w1 = _section(lines, "quality_windows")
    n_samples = int(next(x for x in lines if x.startswith("n_samples=")).split("=")[1])
    beats = [row.split(",") for row in lines[b0:b1]]
    rates = [row.split(",") for row in lines[h0:h1]]
    windows = [row.split(",") for row in lines[w0:w1]]
    n: int

    def set_field(row: int, index: int, value: str) -> None:
        lines[row] = _replace_field(lines[row], index, value)

    def first(rows: list[list[str]], base: int, field: int, value: str) -> int:
        return base + next(i for i, row in enumerate(rows) if row[field] == value)

    if case == "beat-row-with-two-fields":
        lines[b0], n = lines[b0].rsplit(",", 1)[0], b0 + 1
    elif case == "beat-unknown-mark":
        set_field(b0, 1, "start-up")
        n = b0 + 1
    elif case == "beat-mark-empty":
        set_field(b0, 1, "")
        n = b0 + 1
    elif case == "beat-reported-before-its-index":
        row = next(i for i, r in enumerate(beats) if int(r[0]) > 0)
        set_field(b0 + row, 2, str(int(beats[row][0]) - 1))
        n = b0 + row + 1
    elif case == "beat-reported-at-n-samples":
        set_field(b0, 2, str(n_samples))
        n = b0 + 1
    elif case == "beat-reported-decreases":
        row = next(i for i in range(1, len(beats)) if int(beats[i - 1][2]) - 1 >= int(beats[i][0]))
        set_field(b0 + row, 2, str(int(beats[row - 1][2]) - 1))
        n = b0 + row + 1
    elif case == "beat-reported-above-the-integer-limit":
        set_field(b0, 2, LIMIT_TOKENS["above"])
        n = b0 + 1
    elif case == "beats-columns-in-another-order":
        n = lines.index("[beats]") + 2
        lines[n - 1] = "sample_index,reported_at,mark"
    elif case == "heart-rate-row-with-three-fields":
        lines[h0], n = lines[h0].rsplit(",", 1)[0], h0 + 1
    elif case == "heart-rate-unknown-status":
        set_field(h0, 2, "unknown")
        n = h0 + 1
    elif case == "heart-rate-status-empty":
        set_field(h0, 2, "")
        n = h0 + 1
    elif case == "heart-rate-sample-empty":
        set_field(h0, 0, "")
        n = h0 + 1
    elif case == "heart-rate-with-a-status-that-has-no-rate":
        row = first(rates, h0, 2, "not_enough_beats")
        set_field(row, 3, "70.0")
        n = row + 1
    elif case == "heart-rate-valid-without-a-rate":
        row = first(rates, h0, 2, "valid")
        set_field(row, 3, "")
        n = row + 1
    elif case in ("heart-rate-zero", "heart-rate-negative"):
        row = first(rates, h0, 2, "valid")
        set_field(row, 3, "0.0" if case == "heart-rate-zero" else "-60.0")
        n = row + 1
    elif case == "heart-rate-beat-index-names-a-start-up-detection":
        startup = next(r[0] for r in beats if r[1] == "startup")
        set_field(h0, 1, startup)
        n = h0 + 1
    elif case == "heart-rate-beat-index-names-no-detection":
        set_field(h0, 1, str(int(rates[0][1]) + 1))
        n = h0 + 1
    elif case == "heart-rate-reported-at-another-sample-than-the-detection":
        row = next(
            i
            for i, r in enumerate(rates)
            if r[1] != "" and (i + 1 == len(rates) or int(rates[i + 1][0]) > int(r[0]) + 1)
        )
        set_field(h0 + row, 0, str(int(rates[row][0]) + 1))
        n = h0 + row + 1
    elif case == "heart-rate-reliable-detection-missing":
        named = [i for i, r in enumerate(rates) if r[1] != ""]
        del lines[h0 + named[0]]
        _set_header(lines, "n_heart_rates", str(len(rates) - 1))
        n = h0 + named[1]  # the next detection named, now on the line of the deleted row
    elif case == "heart-rate-reliable-detection-named-twice":
        row = next(i for i, r in enumerate(rates) if r[1] != "")
        lines.insert(h0 + row + 1, lines[h0 + row])
        _set_header(lines, "n_heart_rates", str(len(rates) + 1))
        n = h0 + row + 2
    elif case == "heart-rate-sample-decreases":
        row = next(
            i for i, r in enumerate(rates) if r[1] == "" and i > 0 and int(rates[i - 1][0]) > 0
        )
        set_field(h0 + row, 0, str(int(rates[row - 1][0]) - 1))
        n = h0 + row + 1
    elif case == "heart-rate-sample-at-n-samples":
        row = next(i for i, r in enumerate(rates) if r[1] == "")
        set_field(h0 + row, 0, str(n_samples))
        n = h0 + row + 1
    elif case == "heart-rates-columns-in-another-order":
        n = lines.index("[heart_rates]") + 2
        lines[n - 1] = "sample_index,status,beat_index,heart_rate_bpm"
    elif case == "window-row-with-four-fields":
        lines[w0], n = lines[w0].rsplit(",", 1)[0], w0 + 1
    elif case == "window-first-sample-repeated":
        set_field(w0 + 1, 0, windows[0][0])
        n = w0 + 2
    elif case == "window-last-before-first":
        set_field(w0 + 1, 1, str(int(windows[1][0]) - 1))
        n = w0 + 2
    elif case == "window-reported-before-last":
        set_field(w0, 2, str(int(windows[0][1]) - 1))
        n = w0 + 1
    elif case == "window-reported-at-n-samples":
        set_field(w0, 2, str(n_samples))
        n = w0 + 1
    elif case == "window-index-above-one":
        set_field(w0, 3, "1.5")
        n = w0 + 1
    elif case == "window-index-negative":
        set_field(w0, 3, "-0.25")
        n = w0 + 1
    elif case == "window-index-empty":
        set_field(w0, 3, "")
        n = w0 + 1
    elif case == "window-unknown-mark":
        set_field(w0, 4, "yes")
        n = w0 + 1
    elif case == "window-usable-with-a-low-index":
        row = first(windows, w0, 4, "usable")
        set_field(row, 3, "0.25")
        n = row + 1
    elif case == "window-not-usable-with-a-high-index":
        row = first(windows, w0, 4, "not_usable")
        set_field(row, 3, "0.75")
        n = row + 1
    elif case == "window-exactly-half-marked-not-usable":
        row = first(windows, w0, 4, "not_usable")
        set_field(row, 3, "0.5")
        n = row + 1
    elif case == "window-just-below-half-marked-usable":
        row = first(windows, w0, 4, "usable")
        set_field(row, 3, "0.49999999999999994")
        n = row + 1
    elif case == "quality-windows-columns-in-another-order":
        n = lines.index("[quality_windows]") + 2
        lines[n - 1] = "first_sample,last_sample,reported_at,usable,quality_index"
    elif case == "heart-rates-section-missing":
        n = lines.index("[heart_rates]") + 1
        del lines[n - 1]
    elif case == "quality-windows-section-missing":
        n = lines.index("[quality_windows]") + 1
        del lines[n - 1]
    elif case == "sections-heart-rates-and-windows-swapped":
        head = lines.index("[heart_rates]")
        windows_head = lines.index("[quality_windows]")
        end = lines.index("[end]")
        lines = lines[:head] + lines[windows_head:end] + lines[head:windows_head] + lines[end:]
        n = head + 1
    else:
        raise AssertionError(case)
    return "\n".join(lines) + "\n", n


def _count(lines: list[str], key: str) -> int:
    return int(next(x for x in lines if x.startswith(f"{key}=")).split("=")[1])


def _mutate(text: str, case: str) -> tuple[str, int | None]:
    """The text of a case and the line that must be named (None: not asserted)."""
    lines = text.split("\n")[:-1]
    beats = _line_of(lines, "[beats]") + 2  # first row of [beats]
    reference = _line_of(lines, "[reference_beats]") + 2
    n_samples = int(next(x for x in lines if x.startswith("n_samples=")).split("=")[1])
    n: int | None
    if case in V2_CASES:
        return _mutate_v2(text, case)
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
        lines[21], n = lines[21].replace(",", ", ", 1), 22
    elif case == "tab-in-the-header":
        lines[2], n = lines[2] + "\t", 3
    elif case == "empty-line":
        lines.insert(14, "")
        n = 15
    elif case == "unknown-format":
        n = _set_header(lines, "format", "sinus-golden-vectors")
    elif case == "version-3":
        n = _set_header(lines, "format_version", "3")
    elif case == "unknown-version":
        n = _set_header(lines, "format_version", "1")
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
        lines[22], n = _replace_field(lines[22], 0, token), 23
    elif case == "coefficient-1e999":
        lines[17], n = _replace_field(lines[17], 3, "1e999"), 18
    elif case == "row-missing-a-field":
        lines[23], n = lines[23].rsplit(",", 1)[0], 24
    elif case == "row-with-an-extra-field":
        lines[23], n = lines[23] + ",0.0", 24
    elif case == "coefficient-row-of-another-stage":
        lines[17], n = _replace_field(lines[17], 0, "mains"), 18
    elif case == "coefficient-section-from-1":
        lines[17], n = _replace_field(lines[17], 1, "1"), 18
    elif case == "coefficient-row-with-six-fields":
        lines[18], n = lines[18].rsplit(",", 1)[0], 19
    elif case == "signal-columns-in-another-order":
        lines[20], n = "input_mv,mains_mv,baseline_mv", 21
    elif case == "section-missing":
        n = _line_of(lines, "[beats]")
        del lines[n - 1]
    elif case == "beat-not-greater":
        lines[beats], n = lines[beats - 1], beats + 1
    elif case == "beat-at-n-samples":
        last = reference - 3  # last row of [beats]
        lines[last - 1], n = _replace_field(lines[last - 1], 0, str(n_samples)), last
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
        lines[beats - 1], n = _replace_field(lines[beats - 1], 0, LIMIT_TOKENS["above"]), beats
    elif case == "reference-beat-above-the-integer-limit":
        last = _line_of(lines, "[heart_rates]") - 1
        lines[last - 1], n = LIMIT_TOKENS["above"], last
    elif case == "coefficient-section-above-the-integer-limit":
        lines[18], n = _replace_field(lines[18], 1, LIMIT_TOKENS["above"]), 19
    elif case == "coefficient-1e-400":
        lines[17], n = _replace_field(lines[17], 3, "1e-400"), 18
    elif case == "sampling-frequency-1e-400":
        n = _set_header(lines, "sampling_frequency_hz", "1e-400")
    elif case == "mains-output-1e-400":
        lines[22], n = _replace_field(lines[22], 2, "1e-400"), 23
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
    "version-3",
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
    "more-heart-rates-in-the-header",
    "fewer-heart-rates-in-the-header",
    "more-quality-windows-in-the-header",
    "fewer-quality-windows-in-the-header",
    "n-heart-rates-above-the-integer-limit",
    "n-quality-windows-above-the-integer-limit",
    "n-heart-rates-at-the-integer-limit",
    "n-quality-windows-at-the-integer-limit",
    *V2_CASES,
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
    empty line; an unknown format, a version 1 file (the readers accept version 2 only) or a
    version 3; header keys out of order, missing or given twice; header values that break
    their rule (digest in uppercase, mains 55, sampling
    frequency 0.0 or 1e999, empty software version, `.` in the input identifier, a stage
    given twice, `n_beats` with a leading zero, `n_samples=0`); a float written `+1.0`,
    `1e999`, `nan`, `inf`, `1E-05`, `.5`, `1.`, `1_0` or `0x1p-3`; a coefficient 1e999; a row
    with a field missing or added; coefficient rows of the wrong stage, numbered from 1, or
    with six fields; signal columns in another order; the `[beats]` line missing;
    the rules of version 2 listed in `V2_CASES` (marks, report samples, heart-rate rows and
    their links to the detections, windows and their marks); a detected
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
        lines[17] = _replace_field(lines[17], 3, token)
    else:
        lines[22] = _replace_field(lines[22], 0 if place == "input" else 2, token)
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


ACCEPTED_V2_CASES = [
    "window-exactly-half-usable",
    "window-just-below-half-not-usable",
    "window-index-one-usable",
    "window-index-zero-not-usable",
    "heart-rate-without-detection-has-empty-index-and-rate",
]


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize("case", ACCEPTED_V2_CASES)
def test_version_2_boundaries_are_accepted(
    case: str,
    base_vector: Any,
    tmp_path: Path,
    read_golden_file: Callable[[bytes], Any],
) -> None:
    """The limits of the rules of version 2 are accepted, and read back as written.

    Input: the text of the base vector with the quality index of one window written `0.5` and
    marked `usable`; `0.49999999999999994` marked `not_usable`; `1.0` marked `usable`; `0.0`
    marked `not_usable` (a window that is usable exactly when its index is at least 0.5); or
    unchanged, whose `no_recent_beat` event has an empty `beat_index` and an empty rate.
    Expected: `parse_golden_vector`, `read_golden_vector` and the test's own reader accept the
    text; the window has the index and the mark written; the event without a detection reads
    back with `beat_index` None and `bpm` None.
    """
    lines = render_golden_vector(base_vector).split("\n")
    w0 = lines.index("[quality_windows]") + 2
    windows = [row.split(",") for row in lines[w0 : lines.index("[end]")]]
    row = 0
    if case != "heart-rate-without-detection-has-empty-index-and-rate":
        index, mark = {
            "window-exactly-half-usable": ("0.5", "usable"),
            "window-just-below-half-not-usable": ("0.49999999999999994", "not_usable"),
            "window-index-one-usable": ("1.0", "usable"),
            "window-index-zero-not-usable": ("0.0", "not_usable"),
        }[case]
        row = next(i for i, w in enumerate(windows) if w[4] == mark)
        lines[w0 + row] = _replace_field(_replace_field(lines[w0 + row], 3, index), 4, mark)
    text = "\n".join(lines)
    path = tmp_path / "case.golden.txt"
    path.write_bytes(text.encode("utf-8"))

    own = read_golden_file(text.encode("utf-8"))
    for vector in (parse_golden_vector(text, "case.golden.txt"), read_golden_vector(path)):
        if case.startswith("window"):
            assert vector.window_index[row] == float(index)
            assert bool(vector.window_usable[row]) is (mark == "usable")
        else:
            events = [e for e in vector.heart_rates if e.beat_index is None]
            assert events and all(e.bpm is None for e in events)
    if case.startswith("window"):
        assert own.window_index[row] == float(index)
        assert bool(own.window_usable[row]) is (mark == "usable")
    else:
        assert any(h[1] is None and h[3] is None for h in own.heart_rates)


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize(
    "case",
    [
        "marks-shorter-than-the-detections",
        "report-samples-before-the-detections",
        "unknown-heart-rate-status",
        "valid-heart-rate-without-a-rate",
        "window-mark-against-its-index",
        "window-index-above-one",
    ],
)
def test_render_refuses_a_vector_that_breaks_a_rule_of_version_2(
    case: str, base_vector: Any
) -> None:
    """The writer does not produce a text that its own readers refuse (architecture 13.8).

    Input: the base vector changed in one field: one mark fewer than detections; every report
    sample one less than its detection's index; a heart-rate event with status `unknown`; a
    `valid` event without a rate; the mark of the first window opposite to its index; an index
    of 1.5.
    Expected: `render_golden_vector` raises `InvalidInputError` and returns no text.
    """
    event = base_vector.heart_rates[0]
    changes: dict[str, Any] = {
        "marks-shorter-than-the-detections": {"beat_startup": base_vector.beat_startup[:-1]},
        "report-samples-before-the-detections": {"beat_reported_at": base_vector.beats - 1},
        "unknown-heart-rate-status": {
            "heart_rates": (
                dataclasses.replace(event, status="unknown"),
                *base_vector.heart_rates[1:],
            )
        },
        "valid-heart-rate-without-a-rate": {
            "heart_rates": (
                dataclasses.replace(event, status="valid", bpm=None),
                *base_vector.heart_rates[1:],
            )
        },
        "window-mark-against-its-index": {
            "window_usable": np.concatenate(
                [~base_vector.window_usable[:1], base_vector.window_usable[1:]]
            )
        },
        "window-index-above-one": {
            "window_index": np.concatenate([[1.5], base_vector.window_index[1:]])
        },
    }
    vector = dataclasses.replace(base_vector, **changes[case])

    with pytest.raises(InvalidInputError):
        render_golden_vector(vector)
