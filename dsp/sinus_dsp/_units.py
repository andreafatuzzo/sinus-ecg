"""Conversions of times to numbers of samples (architecture §8.2). Private: no public interface.

Parameters are stated in seconds or in milliseconds and converted to samples at
configuration, from the sampling frequency. Times that are not a whole number of seconds are
given as an integer number of milliseconds, and the product is computed as
``t_ms * fs_hz / 1000``: the multiplication is exact in binary64 for every integer sampling
frequency up to 1000 Hz, so the result never depends on the rounding of a decimal fraction of
a second.
"""

from __future__ import annotations

import math


def round_samples(t_s: float, fs_hz: float) -> int:
    """Samples in ``t_s`` seconds, rounded half up: ``floor(t_s * fs_hz + 0.5)``.

    This is the rule of the WFDB function ``strtim``. It is used unless a section of the
    design states another conversion.
    """
    return math.floor(t_s * fs_hz + 0.5)


def round_samples_ms(t_ms: int, fs_hz: float) -> int:
    """Samples in ``t_ms`` milliseconds, rounded half up: ``floor(t_ms * fs_hz / 1000 + 0.5)``."""
    return math.floor(t_ms * fs_hz / 1000 + 0.5)


def floor_samples_ms(t_ms: int, fs_hz: float) -> int:
    """Largest number of samples that lasts at most ``t_ms`` milliseconds.

    ``floor(t_ms * fs_hz / 1000)``: keeps a bound stated as "at most" exact.
    """
    return math.floor(t_ms * fs_hz / 1000)


def ceil_samples_ms(t_ms: int, fs_hz: float) -> int:
    """Smallest number of samples that lasts at least ``t_ms`` milliseconds.

    ``ceil(t_ms * fs_hz / 1000)``: keeps a bound stated as "at least" exact.
    """
    return math.ceil(t_ms * fs_hz / 1000)
