"""Display low-pass: a linear-phase FIR on the conditioned signal (architecture §16.2, §16.3).

SRS-044: the display output is the conditioned signal (the output of the mains stage) filtered
by a Hamming-windowed sinc low-pass of cut-off 50 Hz at every sampling frequency, of
``2 * M + 1`` taps with ``M = round_samples_ms(30, fs)``, normalised to a sum of 1, so that its
delay is a constant ``M`` samples. The stage feeds nothing: detection, heart rate and signal
quality read the conditioned signal.

The arithmetic is binary64 with one written order of operations (taps in index order, no
library convolution, no fused multiply-add), so that the real-time library can reproduce the
result bit for bit before it rounds the output to binary32.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
import numpy.typing as npt

from sinus_dsp._types import FloatArray
from sinus_dsp._units import round_samples_ms
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.input_checks import validate_fs

#: SRS-044: cut-off of the display low-pass, in Hz, at every sampling frequency.
DISPLAY_CUTOFF_HZ: Final = 50.0  # Hz
#: SRS-044: half length of the filter, in ms; ``M = round_samples_ms(30, fs)``.
DISPLAY_HALF_LENGTH_MS: Final = 30  # ms
#: SRS-044: the largest ``M``, at 1000 Hz.
DISPLAY_MAX_DELAY_SAMPLES: Final = 30


def display_delay_samples(fs_hz: float) -> int:
    """Delay of the display low-pass, in samples: ``M = floor(30 * fs / 1000 + 0.5)``.

    SRS-044: constant at every frequency (11 samples at 360 Hz, 8 samples at 250 Hz).

    Args:
        fs_hz: The sampling frequency, in Hz.

    Returns:
        ``M``.

    Raises:
        InvalidInputError: If ``fs_hz`` is not a real number, is not finite or lies outside
            125 Hz to 1000 Hz.
    """
    return round_samples_ms(DISPLAY_HALF_LENGTH_MS, validate_fs(fs_hz))


def display_lowpass_taps(fs_hz: float) -> FloatArray:
    """The ``2 * M + 1`` taps of the display low-pass (architecture §16.2).

    SRS-044: for ``k = 0 .. N - 1`` and ``j = k - M``, ``ideal = 2 fc / fs`` for ``j = 0``,
    otherwise ``sin(2 pi fc j / fs) / (pi j)``; ``window = 0.54 - 0.46 cos(2 pi k / (N - 1))``;
    ``raw[k] = window * ideal``; the total of ``raw`` is added one term at a time in index
    order, and ``h[k] = raw[k] / total``. Every operation is binary64, in the order written.

    Args:
        fs_hz: The sampling frequency, in Hz.

    Returns:
        A new float64 array of the taps.

    Raises:
        InvalidInputError: As :func:`display_delay_samples`.
    """
    fs = validate_fs(fs_hz)
    half = round_samples_ms(DISPLAY_HALF_LENGTH_MS, fs)
    n_taps = 2 * half + 1
    fc = DISPLAY_CUTOFF_HZ
    pi = math.pi
    raw: list[float] = []
    for k in range(n_taps):
        j = k - half
        ideal = 2.0 * fc / fs if j == 0 else math.sin(2.0 * pi * fc * j / fs) / (pi * j)
        window = 0.54 - 0.46 * math.cos(2.0 * pi * k / (n_taps - 1))
        raw.append(window * ideal)
    total = 0.0
    for value in raw:
        total = total + value
    return np.array([value / total for value in raw], dtype=np.float64)


def apply_display_lowpass(taps: FloatArray, conditioned_mv: FloatArray) -> FloatArray:
    """Filter a conditioned signal with the taps (architecture §16.2).

    SRS-044: ``y[n] = (...((h[0] x[n] + h[1] x[n-1]) + h[2] x[n-2]) + ...) + h[N-1] x[n-N+1]``
    with ``x[i] = x[0]`` for ``i < 0`` (the steady state of a constant first input). Each
    NumPy operation is one correctly rounded binary64 operation per element, so the result
    depends neither on the machine nor on a BLAS library.

    Args:
        taps: The taps, one-dimensional, of odd length, finite.
        conditioned_mv: The signal, one-dimensional, at least one sample, finite. Neither
            argument is modified.

    Returns:
        A new float64 array as long as the signal.

    Raises:
        InvalidInputError: If an argument breaks the checks above.
    """
    h = _checked_array("taps", taps)
    if h.size % 2 == 0:
        raise InvalidInputError(f"taps have an even length: {h.size}")
    x = _checked_array("conditioned signal", conditioned_mv)
    n_taps = h.size
    padded = np.concatenate((np.full(n_taps - 1, x[0]), x))
    y: FloatArray = h[0] * padded[n_taps - 1 :]
    for k in range(1, n_taps):
        y = y + h[k] * padded[n_taps - 1 - k : padded.size - k]
    return y


def display_lowpass(conditioned_mv: npt.ArrayLike, fs_hz: float) -> FloatArray:
    """The display output of a conditioned signal: taps of ``fs_hz``, then the filtering.

    SRS-044: the 10 s minimum and the 1000 mV bound of the pipeline input do not apply.
    The value at index ``n`` belongs to the sample ``n - M`` (architecture §16.4).

    Args:
        conditioned_mv: The conditioned signal, in mV.
        fs_hz: Its sampling frequency, in Hz.

    Returns:
        A new float64 array as long as the signal.

    Raises:
        InvalidInputError: If the sampling frequency or the signal is rejected.
    """
    taps = display_lowpass_taps(fs_hz)
    return apply_display_lowpass(taps, _checked_array("conditioned signal", conditioned_mv))


def _checked_array(name: str, values: object) -> FloatArray:
    """The values as a float64 array, which must be one-dimensional, not empty and finite."""
    try:
        array = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise InvalidInputError(f"{name} does not convert to float64: {error}") from error
    if array.ndim != 1:
        raise InvalidInputError(f"{name} is not one-dimensional: shape {array.shape}")
    if array.size == 0:
        raise InvalidInputError(f"{name} is empty")
    if not bool(np.isfinite(array).all()):
        raise InvalidInputError(f"{name} holds a value that is not finite")
    return array
