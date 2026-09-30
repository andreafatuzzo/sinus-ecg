"""Input validation before filtering or detection (SRS-003, architecture §8.5).

Every public function that filters or detects calls :func:`validate_input` before any other
computation, so a rejected input never produces a filtered signal or detections.
"""

from __future__ import annotations

import math
import numbers
from typing import Final

import numpy as np
import numpy.typing as npt

from sinus_dsp._types import FloatArray
from sinus_dsp.errors import InvalidInputError

MIN_FS_HZ: Final = 125.0
MAX_FS_HZ: Final = 1000.0
MIN_DURATION_S: Final = 10.0
MAINS_FREQUENCIES_HZ: Final = (50, 60)


def validate_input(signal_mv: npt.ArrayLike, fs_hz: float) -> FloatArray:
    """Check a signal and its sampling frequency, and return the signal as a float64 copy.

    SRS-003: the input is rejected with :class:`~sinus_dsp.errors.InvalidInputError` if it is
    empty, contains a value that is not finite, lasts less than 10 s, or has a sampling
    frequency that is not finite or lies outside 125 Hz to 1000 Hz (bounds included).

    The checks run in this order, and the first failure raises, with a message naming the
    check and the offending value:

    1. ``fs_hz`` is a real number (not ``bool``) and finite;
    2. ``125.0 <= fs_hz <= 1000.0``;
    3. the signal converts to a one-dimensional array of integer or floating-point kind;
    4. the signal is not empty;
    5. every sample is finite;
    6. the signal lasts at least 10 s (``n_samples >= 10.0 * fs_hz``).

    Args:
        signal_mv: The signal, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.

    Returns:
        A new contiguous one-dimensional float64 array with the samples of ``signal_mv``.

    Raises:
        InvalidInputError: At the first check that fails.
    """
    if isinstance(fs_hz, bool) or not isinstance(fs_hz, numbers.Real):
        raise InvalidInputError(f"sampling frequency is not a real number: {fs_hz!r}")
    fs = float(fs_hz)
    if not math.isfinite(fs):
        raise InvalidInputError(f"sampling frequency is not finite: {fs!r} Hz")
    if not MIN_FS_HZ <= fs <= MAX_FS_HZ:
        raise InvalidInputError(
            f"sampling frequency is outside {MIN_FS_HZ!r} Hz to {MAX_FS_HZ!r} Hz: {fs!r} Hz"
        )

    try:
        array = np.asarray(signal_mv)
    except (TypeError, ValueError) as error:
        raise InvalidInputError(f"signal does not convert to an array: {error}") from error
    if array.dtype.kind not in "iuf":
        raise InvalidInputError(
            f"signal is not of integer or floating-point kind: dtype {array.dtype}"
        )
    if array.ndim != 1:
        raise InvalidInputError(
            f"signal is not one-dimensional: {array.ndim} dimensions, shape {array.shape}"
        )

    n_samples = int(array.shape[0])
    if n_samples == 0:
        raise InvalidInputError("signal is empty: 0 samples")

    signal = np.array(array, dtype=np.float64, order="C", copy=True)
    finite = np.isfinite(signal)
    if not bool(finite.all()):
        count = n_samples - int(np.count_nonzero(finite))
        first = int(np.argmin(finite))
        raise InvalidInputError(
            f"signal contains non-finite samples: {count} of {n_samples}, "
            f"the first at index {first}"
        )

    if n_samples < MIN_DURATION_S * fs:
        raise InvalidInputError(
            f"signal is shorter than {MIN_DURATION_S!r} s: {n_samples} samples at {fs!r} Hz "
            f"({n_samples / fs!r} s)"
        )
    return signal


def validate_mains(mains_hz: int) -> int:
    """Check the mains frequency setting and return it as an ``int``.

    SRS-005: the mains interference filter is configurable for 50 Hz or 60 Hz. The values 50
    and 60 are accepted as ``int`` or as a ``float`` equal to them; anything else is rejected.

    Args:
        mains_hz: The mains frequency, in Hz.

    Returns:
        50 or 60.

    Raises:
        InvalidInputError: If ``mains_hz`` is neither 50 nor 60.
    """
    if (
        isinstance(mains_hz, bool)
        or not isinstance(mains_hz, numbers.Real)
        or mains_hz not in MAINS_FREQUENCIES_HZ
    ):
        raise InvalidInputError(
            f"mains frequency is not one of {MAINS_FREQUENCIES_HZ} Hz: {mains_hz!r}"
        )
    return int(mains_hz)
