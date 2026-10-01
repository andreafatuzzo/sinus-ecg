"""Shared fixtures of the requirement tests.

The helpers here are independent of the software under test: they build the test inputs
(synthetic ECGs with known QRS positions, sinusoids) and apply the pass criteria of the
requirements to its outputs. Each helper is exposed as a fixture that returns a function.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import numpy.typing as npt
import pytest

FloatArray = npt.NDArray[np.float64]
IndexArray = npt.NDArray[np.int64]

# Synthetic ECG of docs/regulatory/architecture.md, section 7.2: each beat is the sum of five
# Gaussian waves. Columns: offset from the R centre (ms), amplitude (mV), width sigma (ms),
# and whether the offset and the width scale with sqrt(RR / 1 s).
_WAVES: tuple[tuple[str, float, float, float, bool], ...] = (
    ("P", -200.0, 0.15, 25.0, True),
    ("Q", -30.0, -0.10, 10.0, False),
    ("R", 0.0, 1.00, 10.0, False),
    ("S", 30.0, -0.20, 10.0, False),
    ("T", 280.0, 0.30, 45.0, True),
)

BASELINE_WANDER_HZ = 0.3
BASELINE_WANDER_MV = 1.0
MAINS_INTERFERENCE_MV = 0.2


@dataclass(frozen=True)
class SyntheticEcg:
    """A synthetic ECG and the true positions of its QRS complexes."""

    fs_hz: float
    signal_mv: FloatArray
    qrs_samples: IndexArray


def _synthetic_ecg(
    fs_hz: int,
    heart_rate_bpm: int,
    *,
    n_samples: int | None = None,
    mains_hz: int | None = None,
) -> SyntheticEcg:
    """Deterministic synthetic ECG with known QRS positions.

    - Sample instants t_n = n / fs_hz, for n = 0 .. n_samples - 1 (30 s by default).
    - RR = 60 / heart rate. The R wave of beat k is centred on the sample
      r_k = floor((0.5 + k * RR) * fs_hz + 0.5), for every k >= 0 with
      0.5 + k * RR <= duration - 0.5 s. The r_k are computed in exact rational arithmetic.
    - Each beat is the sum of the five Gaussian waves of ``_WAVES``, centred at
      r_k / fs_hz + offset; the R wave has an amplitude of 1 mV.
    - With ``mains_hz``, a 0.3 Hz sinusoidal baseline wander of 1 mV and a sinusoid of 0.2 mV
      at ``mains_hz`` are added (the interference of SRS-010).
    """
    if n_samples is None:
        n_samples = 30 * fs_hz
    t_s = np.arange(n_samples, dtype=np.float64) / fs_hz

    rr = Fraction(60, heart_rate_bpm)
    last_centre_s = Fraction(n_samples, fs_hz) - Fraction(1, 2)
    n_beats = max(0, math.floor((last_centre_s - Fraction(1, 2)) / rr) + 1)
    qrs = [math.floor((Fraction(1, 2) + k * rr) * fs_hz + Fraction(1, 2)) for k in range(n_beats)]

    scale = math.sqrt(60.0 / heart_rate_bpm)
    signal = np.zeros(n_samples, dtype=np.float64)
    for r in qrs:
        for _name, offset_ms, amplitude_mv, sigma_ms, scaled in _WAVES:
            factor = scale if scaled else 1.0
            centre_s = r / fs_hz + offset_ms * factor / 1000.0
            sigma_s = sigma_ms * factor / 1000.0
            signal += amplitude_mv * np.exp(-((t_s - centre_s) ** 2) / (2.0 * sigma_s**2))

    if mains_hz is not None:
        signal += BASELINE_WANDER_MV * np.sin(2.0 * np.pi * BASELINE_WANDER_HZ * t_s)
        signal += MAINS_INTERFERENCE_MV * np.sin(2.0 * np.pi * mains_hz * t_s)

    return SyntheticEcg(
        fs_hz=float(fs_hz), signal_mv=signal, qrs_samples=np.asarray(qrs, dtype=np.int64)
    )


def _sinusoid(
    frequency_hz: float,
    fs_hz: float,
    duration_s: float,
    *,
    phase_rad: float = 0.0,
    amplitude_mv: float = 1.0,
) -> FloatArray:
    """``amplitude_mv * sin(2 pi f n / fs + phase)`` for n = 0 .. round(duration * fs) - 1."""
    n = np.arange(round(duration_s * fs_hz), dtype=np.float64)
    out: FloatArray = amplitude_mv * np.sin(2.0 * np.pi * frequency_hz * n / fs_hz + phase_rad)
    return out


def _second_half_rms(signal_mv: npt.ArrayLike) -> float:
    """RMS of the second half of a signal (samples n // 2 to the end)."""
    x = np.asarray(signal_mv, dtype=np.float64)
    half = x[x.size // 2 :]
    return float(np.sqrt(np.mean(half**2)))


def _match_window_samples(fs_hz: float) -> int:
    """'Within 150 ms' in samples: the bound is kept exact, floor(0.150 * fs_hz)."""
    return math.floor(150 * fs_hz / 1000)


def _min_spacing_samples(fs_hz: float) -> int:
    """'No closer than 200 ms' in samples: the bound is kept exact, ceil(0.200 * fs_hz)."""
    return math.ceil(200 * fs_hz / 1000)


def _detection_errors(
    detections: npt.ArrayLike, qrs_samples: npt.ArrayLike, fs_hz: float
) -> list[str]:
    """Violations of 'exactly one detection within 150 ms of every QRS, and no other detection'.

    Returns one message per QRS that does not have exactly one detection within
    floor(0.150 * fs_hz) samples, and one per detection that lies within that distance of no
    QRS. An empty list means that the criterion holds.
    """
    window = _match_window_samples(fs_hz)
    det = np.asarray(detections, dtype=np.int64).reshape(-1)
    qrs = np.asarray(qrs_samples, dtype=np.int64).reshape(-1)
    errors: list[str] = []
    for r in qrs.tolist():
        near = det[np.abs(det - r) <= window]
        if near.size != 1:
            errors.append(
                f"QRS at sample {r}: {near.size} detections within {window} samples "
                f"{near.tolist()}, expected exactly 1"
            )
    for d in det.tolist():
        if not np.any(np.abs(qrs - d) <= window):
            errors.append(f"detection at sample {d}: no QRS within {window} samples")
    return errors


def _ordering_errors(detections: npt.ArrayLike, fs_hz: float) -> list[str]:
    """Violations of 'strictly increasing, and no two indices closer than 200 ms'.

    Returns one message per pair of consecutive indices that is not increasing or whose
    distance is below ceil(0.200 * fs_hz) samples. An empty list means that the criterion holds.
    """
    spacing = _min_spacing_samples(fs_hz)
    det = np.asarray(detections, dtype=np.int64).reshape(-1).tolist()
    errors: list[str] = []
    for previous, current in zip(det[:-1], det[1:], strict=True):
        if current <= previous:
            errors.append(f"indices {previous}, {current}: not strictly increasing")
        elif current - previous < spacing:
            errors.append(
                f"indices {previous}, {current}: {current - previous} samples apart, "
                f"minimum {spacing}"
            )
    return errors


@pytest.fixture(scope="session")
def make_synthetic_ecg() -> Callable[..., SyntheticEcg]:
    """``make_synthetic_ecg(fs_hz, heart_rate_bpm, *, n_samples=None, mains_hz=None)``."""
    return _synthetic_ecg


@pytest.fixture(scope="session")
def make_sinusoid() -> Callable[..., FloatArray]:
    """``make_sinusoid(frequency_hz, fs_hz, duration_s, *, phase_rad=0.0, amplitude_mv=1.0)``."""
    return _sinusoid


@pytest.fixture(scope="session")
def second_half_rms() -> Callable[[npt.ArrayLike], float]:
    """``second_half_rms(signal_mv)``: RMS of the second half of a signal."""
    return _second_half_rms


@pytest.fixture(scope="session")
def match_window_samples() -> Callable[[float], int]:
    """``match_window_samples(fs_hz)``: 150 ms in samples, rounded down."""
    return _match_window_samples


@pytest.fixture(scope="session")
def min_spacing_samples() -> Callable[[float], int]:
    """``min_spacing_samples(fs_hz)``: 200 ms in samples, rounded up."""
    return _min_spacing_samples


@pytest.fixture(scope="session")
def detection_errors() -> Callable[[npt.ArrayLike, npt.ArrayLike, float], list[str]]:
    """``detection_errors(detections, qrs_samples, fs_hz)``: see ``_detection_errors``."""
    return _detection_errors


@pytest.fixture(scope="session")
def ordering_errors() -> Callable[[npt.ArrayLike, float], list[str]]:
    """``ordering_errors(detections, fs_hz)``: see ``_ordering_errors``."""
    return _ordering_errors
