"""Unit tests of the input checks: order of the checks, messages and the returned copy."""

from typing import Any

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError
from sinus_dsp.input_checks import (
    MAINS_FREQUENCIES_HZ,
    MAX_FS_HZ,
    MIN_DURATION_S,
    MIN_FS_HZ,
    validate_input,
    validate_mains,
)


def test_constants() -> None:
    assert MIN_FS_HZ == 125.0
    assert MAX_FS_HZ == 1000.0
    assert MIN_DURATION_S == 10.0
    assert MAINS_FREQUENCIES_HZ == (50, 60)


# --- each check -------------------------------------------------------------------------------


@pytest.mark.parametrize("fs_hz", [True, False, "360", None, 360 + 0j, [360.0], np.bool_(True)])
def test_sampling_frequency_must_be_a_real_number(fs_hz: Any) -> None:
    with pytest.raises(InvalidInputError, match="sampling frequency is not a real number"):
        validate_input(np.zeros(4000), fs_hz)


@pytest.mark.parametrize("fs_hz", [float("nan"), float("inf"), float("-inf")])
def test_sampling_frequency_must_be_finite(fs_hz: float) -> None:
    with pytest.raises(InvalidInputError, match="sampling frequency is not finite"):
        validate_input(np.zeros(4000), fs_hz)


@pytest.mark.parametrize("fs_hz", [124.9, 1000.1, 0.0, -360.0, 124.99999999999999])
def test_sampling_frequency_out_of_range(fs_hz: float) -> None:
    with pytest.raises(InvalidInputError, match="sampling frequency is outside") as excinfo:
        validate_input(np.zeros(20000), fs_hz)
    assert repr(fs_hz) in str(excinfo.value)


@pytest.mark.parametrize(
    "signal",
    [
        np.zeros(4000, dtype=bool),
        np.zeros(4000, dtype=complex),
        np.array(["a"] * 4000),
        np.array([None] * 4000, dtype=object),
    ],
)
def test_signal_kind_must_be_integer_or_float(signal: Any) -> None:
    with pytest.raises(InvalidInputError, match="not of integer or floating-point kind"):
        validate_input(signal, 360.0)


@pytest.mark.parametrize("signal", [np.zeros((2, 4000)), np.zeros((4000, 1)), 1.0])
def test_signal_must_be_one_dimensional(signal: Any) -> None:
    with pytest.raises(InvalidInputError, match="not one-dimensional"):
        validate_input(signal, 360.0)


def test_signal_that_does_not_convert_is_rejected() -> None:
    with pytest.raises(InvalidInputError, match="does not convert to an array"):
        validate_input([[1.0, 2.0], [3.0]], 360.0)


@pytest.mark.parametrize("signal", [[], (), np.zeros(0), np.zeros(0, dtype=np.int16)])
def test_empty_signal(signal: Any) -> None:
    with pytest.raises(InvalidInputError, match="signal is empty"):
        validate_input(signal, 360.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_sample(bad: float) -> None:
    signal = np.zeros(4000)
    signal[1234] = bad
    with pytest.raises(InvalidInputError, match="non-finite") as excinfo:
        validate_input(signal, 360.0)
    assert "1 of 4000" in str(excinfo.value)
    assert "first at index 1234" in str(excinfo.value)


def test_non_finite_message_counts_and_locates() -> None:
    signal = np.zeros(4000)
    signal[[7, 100, 3999]] = [np.inf, np.nan, -np.inf]
    with pytest.raises(InvalidInputError) as excinfo:
        validate_input(signal, 360.0)
    assert str(excinfo.value) == (
        "signal contains non-finite samples: 3 of 4000, the first at index 7"
    )


@pytest.mark.parametrize(
    ("fs_hz", "n_short"),
    [(125.0, 1249), (360.0, 3599), (360.0, 3596), (250.0, 2499), (1000.0, 9999), (125.5, 1254)],
)
def test_too_short(fs_hz: float, n_short: int) -> None:
    with pytest.raises(InvalidInputError, match="shorter than 10.0 s") as excinfo:
        validate_input(np.zeros(n_short), fs_hz)
    assert f"{n_short} samples" in str(excinfo.value)


@pytest.mark.parametrize(
    ("fs_hz", "n_min"),
    [(125.0, 1250), (360.0, 3600), (250.0, 2500), (1000.0, 10000), (125.5, 1255)],
)
def test_exactly_ten_seconds_is_accepted(fs_hz: float, n_min: int) -> None:
    assert validate_input(np.zeros(n_min), fs_hz).shape == (n_min,)


# --- order of the checks ----------------------------------------------------------------------


def test_order_frequency_type_before_everything() -> None:
    with pytest.raises(InvalidInputError, match="not a real number"):
        validate_input([[float("nan")]], "x")  # type: ignore[arg-type]


def test_order_frequency_finite_before_range_and_signal() -> None:
    with pytest.raises(InvalidInputError, match="sampling frequency is not finite"):
        validate_input([], float("inf"))


def test_order_frequency_range_before_signal() -> None:
    with pytest.raises(InvalidInputError, match="sampling frequency is outside"):
        validate_input(np.zeros((2, 2), dtype=complex), 100.0)


def test_order_kind_and_dimensions_before_empty() -> None:
    with pytest.raises(InvalidInputError, match="not one-dimensional"):
        validate_input(np.zeros((0, 3)), 360.0)
    with pytest.raises(InvalidInputError, match="not of integer or floating-point kind"):
        validate_input(np.zeros(0, dtype=bool), 360.0)


def test_order_empty_before_duration() -> None:
    with pytest.raises(InvalidInputError, match="signal is empty"):
        validate_input([], 360.0)


def test_order_non_finite_before_duration() -> None:
    with pytest.raises(InvalidInputError, match="non-finite"):
        validate_input([1.0, float("nan"), 2.0], 360.0)


# --- the returned array -----------------------------------------------------------------------


def test_returns_a_new_contiguous_float64_copy() -> None:
    signal = np.linspace(-1.0, 1.0, 3600)
    before = signal.copy()
    out = validate_input(signal, 360.0)
    assert out is not signal
    assert not np.shares_memory(out, signal)
    assert out.dtype == np.float64
    assert out.flags["C_CONTIGUOUS"]
    assert np.array_equal(out, signal)
    out[0] = 99.0
    assert np.array_equal(signal, before)


def test_non_contiguous_view_is_copied_contiguous() -> None:
    base = np.arange(8000, dtype=np.float64)
    view = base[::2]
    out = validate_input(view, 360.0)
    assert out.flags["C_CONTIGUOUS"]
    assert np.array_equal(out, view)


@pytest.mark.parametrize("dtype", [np.int16, np.uint8, np.int64, np.float32])
def test_integer_and_float_kinds_are_converted(dtype: Any) -> None:
    signal = (np.arange(3600) % 100).astype(dtype)
    out = validate_input(signal, 360.0)
    assert out.dtype == np.float64
    assert np.array_equal(out, signal.astype(np.float64))


def test_list_input_and_integer_frequency() -> None:
    out = validate_input([0.5] * 3600, 360)
    assert out.dtype == np.float64
    assert out.shape == (3600,)


def test_numpy_scalar_frequency_is_accepted() -> None:
    assert validate_input(np.zeros(3600), np.float64(360.0)).shape == (3600,)
    assert validate_input(np.zeros(3600), np.int32(360)).shape == (3600,)


# --- mains setting ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"), [(50, 50), (60, 60), (50.0, 50), (60.0, 60), (np.int64(60), 60)]
)
def test_validate_mains_accepts(value: Any, expected: int) -> None:
    result = validate_mains(value)
    assert result == expected
    assert type(result) is int


@pytest.mark.parametrize(
    "value", [0, 55, 50.5, 59.99, -50, 100, "50", None, True, float("nan"), float("inf"), [50]]
)
def test_validate_mains_rejects(value: Any) -> None:
    with pytest.raises(InvalidInputError, match="mains frequency") as excinfo:
        validate_mains(value)
    assert repr(value) in str(excinfo.value)
