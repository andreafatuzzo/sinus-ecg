"""Helpers of the unit tests: a small synthetic ECG with known R-wave centres."""

import math
from collections.abc import Callable, Mapping

import numpy as np
import numpy.typing as npt
import pytest

EcgFactory = Callable[..., tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]]

# (offset from the R centre in s, amplitude in mV, width in s, scales with sqrt(RR / 1 s))
_WAVES = (
    (-0.200, 0.15, 0.025, True),  # P
    (-0.030, -0.10, 0.010, False),  # Q
    (0.000, 1.00, 0.010, False),  # R
    (0.030, -0.20, 0.010, False),  # S
    (0.280, 0.30, 0.045, True),  # T
)


def _synthetic_ecg(
    fs_hz: float,
    heart_rate_bpm: float,
    variant: str = "clean",
    duration_s: float = 30.0,
    beat_gains: Mapping[int, float] | None = None,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]:
    """Sum of five Gaussian waves per beat; returns the signal in mV and the R-wave centres.

    Beat ``k`` is centred on the sample ``floor((0.5 + k * RR) * fs_hz + 0.5)``, for every
    ``k`` with ``0.5 + k * RR <= duration_s - 0.5``. ``variant`` is ``clean``, ``bw-mains50``
    or ``bw-mains60``: the last two add 1 mV of 0.3 Hz baseline wander and 0.2 mV of mains
    interference. ``beat_gains`` scales the whole waveform of single beats.
    """
    n_samples = int(round(duration_s * fs_hz))
    t = np.arange(n_samples) / fs_hz
    rr_s = 60.0 / heart_rate_bpm
    scale = math.sqrt(rr_s)
    signal = np.zeros(n_samples)
    r_peaks: list[int] = []
    k = 0
    while 0.5 + k * rr_s <= duration_s - 0.5:
        r_k = math.floor((0.5 + k * rr_s) * fs_hz + 0.5)
        r_peaks.append(r_k)
        gain = 1.0 if beat_gains is None else beat_gains.get(k, 1.0)
        for offset_s, amplitude_mv, width_s, scaled in _WAVES:
            centre_s = r_k / fs_hz + (offset_s * scale if scaled else offset_s)
            sigma_s = width_s * scale if scaled else width_s
            signal += gain * amplitude_mv * np.exp(-((t - centre_s) ** 2) / (2.0 * sigma_s**2))
        k += 1
    if variant != "clean":
        mains_hz = {"bw-mains50": 50.0, "bw-mains60": 60.0}[variant]
        signal += 1.0 * np.sin(2.0 * np.pi * 0.3 * t) + 0.2 * np.sin(2.0 * np.pi * mains_hz * t)
    return signal, np.array(r_peaks, dtype=np.int64)


@pytest.fixture(scope="session")
def synthetic_ecg() -> EcgFactory:
    """The synthetic ECG generator of the unit tests."""
    return _synthetic_ecg
