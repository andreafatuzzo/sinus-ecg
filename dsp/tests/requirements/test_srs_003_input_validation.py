"""Requirement tests of SRS-003: input validation (risk control RC-003).

SRS-003 is verified through the filters of SRS-004 and SRS-005 and the detection of SRS-006:
every public function that filters or detects must reject an invalid input with an explicit
error and return nothing, and must return an output for an input at the limits of what is
accepted.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError, SinusError
from sinus_dsp.filters import remove_baseline_wander, remove_mains_interference
from sinus_dsp.pipeline import detect_beats, run_pipeline
from sinus_dsp.qrs import detect_qrs

Operation = Callable[[Any, float], Any]


def _baseline(signal: Any, fs_hz: float) -> Any:
    return remove_baseline_wander(signal, fs_hz)


def _mains_50(signal: Any, fs_hz: float) -> Any:
    return remove_mains_interference(signal, fs_hz, 50)


def _mains_60(signal: Any, fs_hz: float) -> Any:
    return remove_mains_interference(signal, fs_hz, 60)


def _detect_qrs(signal: Any, fs_hz: float) -> Any:
    return detect_qrs(signal, fs_hz)


def _detect_beats_50(signal: Any, fs_hz: float) -> Any:
    return detect_beats(signal, fs_hz, 50)


def _detect_beats_60(signal: Any, fs_hz: float) -> Any:
    return detect_beats(signal, fs_hz, 60)


def _run_pipeline_50(signal: Any, fs_hz: float) -> Any:
    return run_pipeline(signal, fs_hz, 50)


def _run_pipeline_60(signal: Any, fs_hz: float) -> Any:
    return run_pipeline(signal, fs_hz, 60)


FILTERS = [
    pytest.param(_baseline, id="remove_baseline_wander"),
    pytest.param(_mains_50, id="remove_mains_interference-50Hz"),
    pytest.param(_mains_60, id="remove_mains_interference-60Hz"),
]
DETECTORS = [
    pytest.param(_detect_qrs, id="detect_qrs"),
    pytest.param(_detect_beats_50, id="detect_beats-50Hz"),
    pytest.param(_detect_beats_60, id="detect_beats-60Hz"),
]
PIPELINES = [
    pytest.param(_run_pipeline_50, id="run_pipeline-50Hz"),
    pytest.param(_run_pipeline_60, id="run_pipeline-60Hz"),
]
ALL_OPERATIONS = FILTERS + DETECTORS + PIPELINES

NON_FINITE_VALUES = [
    pytest.param(math.nan, id="NaN"),
    pytest.param(math.inf, id="+inf"),
    pytest.param(-math.inf, id="-inf"),
]

# 9.99 s in samples is floor(9.99 * fs_hz); "one sample short" is 10 * fs_hz - 1 samples.
TOO_SHORT = [
    pytest.param(125.0, 1248, id="9.99s-at-125Hz"),
    pytest.param(250.0, 2497, id="9.99s-at-250Hz"),
    pytest.param(360.0, 3596, id="9.99s-at-360Hz"),
    pytest.param(1000.0, 9990, id="9.99s-at-1000Hz"),
    pytest.param(125.0, 1249, id="10s-minus-1-sample-at-125Hz"),
    pytest.param(250.0, 2499, id="10s-minus-1-sample-at-250Hz"),
    pytest.param(360.0, 3599, id="10s-minus-1-sample-at-360Hz"),
    pytest.param(1000.0, 9999, id="10s-minus-1-sample-at-1000Hz"),
]

# Sampling frequency outside 125-1000 Hz, with the number of samples of a finite signal. At
# 124.9 Hz and at 1000.1 Hz the signal lasts 20 s, so that the sampling frequency is the only
# reason to reject it.
FS_OUT_OF_RANGE = [
    pytest.param(124.9, 2500, id="124.9Hz"),
    pytest.param(1000.1, 20002, id="1000.1Hz"),
    pytest.param(0.0, 3600, id="0Hz"),
    pytest.param(-360.0, 7200, id="-360Hz"),
]

FS_NON_FINITE = [
    pytest.param(math.nan, id="NaN"),
    pytest.param(math.inf, id="+inf"),
    pytest.param(-math.inf, id="-inf"),
]

# Exactly 10 s: the two limits of the sampling frequency named by SRS-003, and the two
# sampling frequencies at which the other requirements are verified.
ACCEPTED = [
    pytest.param(125, 1250, id="10s-at-125Hz"),
    pytest.param(1000, 10000, id="10s-at-1000Hz"),
    pytest.param(250, 2500, id="10s-at-250Hz"),
    pytest.param(360, 3600, id="10s-at-360Hz"),
]


def _assert_rejected(operation: Operation, signal: Any, fs_hz: float) -> None:
    """The call raises the explicit error of SRS-003, so it returns no output."""
    with pytest.raises(InvalidInputError) as excinfo:
        operation(signal, fs_hz)
    assert str(excinfo.value).strip(), "the error carries no message"


@pytest.mark.requirement("SRS-003")
def test_rejection_error_is_an_explicit_sinus_error() -> None:
    """The error of a rejected input is explicit and catchable as documented.

    Input: the class `InvalidInputError` of the public interface.
    Expected: it is a `SinusError` (every error raised on purpose) and a `ValueError`.
    """
    assert issubclass(InvalidInputError, SinusError)
    assert issubclass(InvalidInputError, ValueError)


@pytest.mark.requirement("SRS-003")
@pytest.mark.parametrize("operation", ALL_OPERATIONS)
@pytest.mark.parametrize(
    "empty",
    [pytest.param(np.array([], dtype=np.float64), id="empty-array"), pytest.param([], id="[]")],
)
def test_empty_input_is_rejected(operation: Operation, empty: Any) -> None:
    """An empty input is rejected by every filter and by the detection.

    Input: a signal with no sample (an empty float64 array, an empty list), at 360 Hz.
    Expected: `InvalidInputError` with a message; no filtered signal and no detections.
    """
    _assert_rejected(operation, empty, 360.0)


@pytest.mark.requirement("SRS-003")
@pytest.mark.parametrize("operation", ALL_OPERATIONS)
@pytest.mark.parametrize("value", NON_FINITE_VALUES)
@pytest.mark.parametrize("position", ["first", "middle", "last"])
def test_non_finite_sample_is_rejected(
    operation: Operation,
    value: float,
    position: str,
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """An input with one non-finite sample is rejected by every filter and by the detection.

    Input: a synthetic ECG of 20 s at 360 Hz (otherwise valid) in which one sample is NaN,
    +infinity or -infinity; the sample is the first, the middle or the last one.
    Expected: `InvalidInputError` with a message; no filtered signal and no detections.
    """
    signal = make_synthetic_ecg(360, 75, n_samples=7200).signal_mv
    index = {"first": 0, "middle": signal.size // 2, "last": signal.size - 1}[position]
    signal[index] = value
    _assert_rejected(operation, signal, 360.0)


@pytest.mark.requirement("SRS-003")
@pytest.mark.parametrize("operation", ALL_OPERATIONS)
@pytest.mark.parametrize(("fs_hz", "n_samples"), TOO_SHORT)
def test_input_shorter_than_10_s_is_rejected(
    operation: Operation,
    fs_hz: float,
    n_samples: int,
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """An input shorter than 10 s is rejected by every filter and by the detection.

    Input: a finite synthetic ECG of 9.99 s (floor(9.99 * fs) samples) and one of 10 s minus
    one sample, at 125, 250, 360 and 1000 Hz.
    Expected: `InvalidInputError` with a message; no filtered signal and no detections.
    """
    signal = make_synthetic_ecg(int(fs_hz), 75, n_samples=n_samples).signal_mv
    assert signal.size == n_samples
    _assert_rejected(operation, signal, fs_hz)


@pytest.mark.requirement("SRS-003")
@pytest.mark.parametrize("operation", ALL_OPERATIONS)
@pytest.mark.parametrize(("fs_hz", "n_samples"), FS_OUT_OF_RANGE)
def test_sampling_frequency_outside_125_to_1000_hz_is_rejected(
    operation: Operation,
    fs_hz: float,
    n_samples: int,
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """A sampling frequency outside 125-1000 Hz is rejected by every filter and the detection.

    Input: a finite synthetic ECG with a sampling frequency of 124.9 Hz and of 1000.1 Hz
    (just outside each bound; the signal lasts 20 s at that frequency), and of 0 Hz and
    -360 Hz.
    Expected: `InvalidInputError` with a message; no filtered signal and no detections.
    """
    signal = make_synthetic_ecg(360, 75, n_samples=n_samples).signal_mv
    _assert_rejected(operation, signal, fs_hz)


@pytest.mark.requirement("SRS-003")
@pytest.mark.parametrize("operation", ALL_OPERATIONS)
@pytest.mark.parametrize("fs_hz", FS_NON_FINITE)
def test_non_finite_sampling_frequency_is_rejected(
    operation: Operation, fs_hz: float, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """A non-finite sampling frequency is rejected by every filter and by the detection.

    Input: a finite synthetic ECG of 7200 samples, with a sampling frequency of NaN,
    +infinity or -infinity.
    Expected: `InvalidInputError` with a message; no filtered signal and no detections.
    """
    signal = make_synthetic_ecg(360, 75, n_samples=7200).signal_mv
    _assert_rejected(operation, signal, fs_hz)


@pytest.mark.requirement("SRS-003")
@pytest.mark.parametrize("operation", FILTERS)
@pytest.mark.parametrize(("fs_hz", "n_samples"), ACCEPTED)
def test_input_of_10_s_is_accepted_by_the_filters(
    operation: Operation,
    fs_hz: int,
    n_samples: int,
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """An input of exactly 10 s at the limits of the sampling frequency is filtered.

    Input: a finite synthetic ECG of exactly 10 s at 125 Hz (1250 samples) and at 1000 Hz
    (10000 samples), the bounds of the accepted range, and at 250 Hz and 360 Hz.
    Expected: no error; each filter returns a finite float64 signal with one output sample
    per input sample.
    """
    signal = make_synthetic_ecg(fs_hz, 75, n_samples=n_samples).signal_mv
    assert signal.size == n_samples

    filtered = operation(signal, float(fs_hz))

    assert isinstance(filtered, np.ndarray)
    assert filtered.dtype == np.float64
    assert filtered.shape == (n_samples,)
    assert np.all(np.isfinite(filtered))


@pytest.mark.requirement("SRS-003")
@pytest.mark.parametrize("operation", DETECTORS)
@pytest.mark.parametrize(("fs_hz", "n_samples"), ACCEPTED)
def test_input_of_10_s_is_accepted_by_the_detection(
    operation: Operation,
    fs_hz: int,
    n_samples: int,
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """An input of exactly 10 s at the limits of the sampling frequency is searched for QRS.

    Input: a finite synthetic ECG of exactly 10 s at 125 Hz (1250 samples) and at 1000 Hz
    (10000 samples), the bounds of the accepted range, and at 250 Hz and 360 Hz.
    Expected: no error; the detection returns a one-dimensional int64 array of sample indices
    that all lie inside the input.
    """
    signal = make_synthetic_ecg(fs_hz, 75, n_samples=n_samples).signal_mv
    assert signal.size == n_samples

    beats = operation(signal, float(fs_hz))

    assert isinstance(beats, np.ndarray)
    assert beats.dtype == np.int64
    assert beats.ndim == 1
    assert np.all((beats >= 0) & (beats < n_samples))


@pytest.mark.requirement("SRS-003")
@pytest.mark.parametrize("operation", PIPELINES)
@pytest.mark.parametrize(("fs_hz", "n_samples"), ACCEPTED)
def test_input_of_10_s_is_accepted_by_the_pipeline(
    operation: Operation,
    fs_hz: int,
    n_samples: int,
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """An input of exactly 10 s at the limits of the sampling frequency runs the whole chain.

    Input: a finite synthetic ECG of exactly 10 s at 125 Hz (1250 samples) and at 1000 Hz
    (10000 samples), the bounds of the accepted range, and at 250 Hz and 360 Hz.
    Expected: no error; the result holds the two filtered signals (finite, one sample per
    input sample) and the detected sample indices (int64, inside the input).
    """
    signal = make_synthetic_ecg(fs_hz, 75, n_samples=n_samples).signal_mv
    assert signal.size == n_samples

    result = operation(signal, float(fs_hz))

    for filtered in (result.baseline_mv, result.mains_mv):
        assert isinstance(filtered, np.ndarray)
        assert filtered.dtype == np.float64
        assert filtered.shape == (n_samples,)
        assert np.all(np.isfinite(filtered))
    assert isinstance(result.beats, np.ndarray)
    assert result.beats.dtype == np.int64
    assert result.beats.ndim == 1
    assert np.all((result.beats >= 0) & (result.beats < n_samples))
