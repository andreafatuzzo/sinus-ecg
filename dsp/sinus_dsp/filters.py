"""Baseline wander and mains interference filters (SRS-004, SRS-005, architecture §8.6).

The filters are causal second-order sections, designed in float64 with closed-form
expressions and applied forward only, from a defined initial state. A row of a
second-order-section matrix is ``[b0, b1, b2, 1.0, a1, a2]`` (a0 = 1), the layout of
``scipy.signal.sosfilt``.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy import signal as _signal

from sinus_dsp._types import FloatArray
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.input_checks import validate_input, validate_mains

BASELINE_CUTOFF_HZ: Final = 0.5
NOTCH_Q: Final = 30.0


def _check_frequency(name: str, value_hz: float, fs_hz: float) -> None:
    """Reject a design frequency outside ``0 < value_hz < fs_hz / 2``."""
    if not (math.isfinite(fs_hz) and math.isfinite(value_hz) and 0.0 < value_hz < fs_hz / 2.0):
        raise InvalidInputError(
            f"{name} is outside 0 Hz to half the sampling frequency (exclusive): "
            f"{value_hz!r} Hz at a sampling frequency of {fs_hz!r} Hz"
        )


def _butterworth2(cutoff_hz: float, fs_hz: float) -> tuple[float, float, float, float]:
    """``(K * K, norm, a1, a2)`` of the second-order Butterworth design (bilinear, prewarped)."""
    _check_frequency("cut-off frequency", cutoff_hz, fs_hz)
    k = math.tan(math.pi * cutoff_hz / fs_hz)
    sqrt2 = math.sqrt(2.0)
    norm = 1.0 / (1.0 + sqrt2 * k + k * k)
    a1 = 2.0 * (k * k - 1.0) * norm
    a2 = (1.0 - sqrt2 * k + k * k) * norm
    return k * k, norm, a1, a2


def butterworth2_highpass_sos(cutoff_hz: float, fs_hz: float) -> FloatArray:
    """Second-order Butterworth high-pass as one second-order section, shape ``(1, 6)``.

    SRS-004: the design of the baseline wander filter. SRS-006: the high-pass section of the
    detection band-pass.

    Bilinear transform with frequency prewarping: ``K = tan(pi * cutoff_hz / fs_hz)``,
    ``norm = 1 / (1 + sqrt(2) * K + K * K)``, ``b = [norm, -2 * norm, norm]``,
    ``a1 = 2 * (K * K - 1) * norm``, ``a2 = (1 - sqrt(2) * K + K * K) * norm``. The gain at
    0 Hz is exactly zero.

    Raises:
        InvalidInputError: Unless ``0 < cutoff_hz < fs_hz / 2``.
    """
    _, norm, a1, a2 = _butterworth2(cutoff_hz, fs_hz)
    return np.array([[norm, -2.0 * norm, norm, 1.0, a1, a2]], dtype=np.float64)


def butterworth2_lowpass_sos(cutoff_hz: float, fs_hz: float) -> FloatArray:
    """Second-order Butterworth low-pass as one second-order section, shape ``(1, 6)``.

    SRS-006: the low-pass section of the detection band-pass.

    Same design as :func:`butterworth2_highpass_sos`, with
    ``b = [K * K * norm, 2 * K * K * norm, K * K * norm]``.

    Raises:
        InvalidInputError: Unless ``0 < cutoff_hz < fs_hz / 2``.
    """
    kk, norm, a1, a2 = _butterworth2(cutoff_hz, fs_hz)
    return np.array([[kk * norm, 2.0 * kk * norm, kk * norm, 1.0, a1, a2]], dtype=np.float64)


def notch_sos(notch_hz: float, q: float, fs_hz: float) -> FloatArray:
    """Second-order notch as one second-order section, shape ``(1, 6)``.

    SRS-005: the design of the mains interference filter.

    The design of ``scipy.signal.iirnotch`` (S. J. Orfanidis, *Introduction to Signal
    Processing*, 1996, eqs. 11.3.4 to 11.3.7), in the same order of operations:
    ``w = 2 * notch_hz / fs_hz``, ``bw = (w / q) * pi``, ``w0 = w * pi``,
    ``beta = tan(bw / 2)``, ``g = 1 / (1 + beta)``, ``b = [g, -2 * cos(w0) * g, g]``,
    ``a1 = -2 * g * cos(w0)``, ``a2 = 2 * g - 1``.

    Raises:
        InvalidInputError: Unless ``0 < notch_hz < fs_hz / 2`` and ``q > 0``.
    """
    _check_frequency("notch frequency", notch_hz, fs_hz)
    if not (math.isfinite(q) and q > 0.0):
        raise InvalidInputError(f"notch quality factor is not a positive finite number: {q!r}")
    w = 2.0 * notch_hz / fs_hz
    bw = (w / q) * math.pi
    w0 = w * math.pi
    beta = math.tan(bw / 2.0)
    g = 1.0 / (1.0 + beta)
    b1 = g * (-2.0 * math.cos(w0))
    a1 = -2.0 * g * math.cos(w0)
    a2 = 2.0 * g - 1.0
    return np.array([[g, b1, g, 1.0, a1, a2]], dtype=np.float64)


def baseline_sos(fs_hz: float) -> FloatArray:
    """Sections of the baseline wander filter: Butterworth high-pass, second order, 0.5 Hz.

    SRS-004: the design of the baseline wander filter.
    """
    return butterworth2_highpass_sos(BASELINE_CUTOFF_HZ, fs_hz)


def mains_sos(fs_hz: float, mains_hz: int) -> FloatArray:
    """Sections of the mains interference filter: notch at ``mains_hz``, Q = 30.

    SRS-005: the design of the mains interference filter, for 50 Hz or 60 Hz.

    Raises:
        InvalidInputError: If ``mains_hz`` is neither 50 nor 60.
    """
    return notch_sos(float(validate_mains(mains_hz)), NOTCH_Q, fs_hz)


def initial_state(sos: FloatArray, first_sample: float) -> FloatArray:
    """Steady state of each section for a constant input equal to ``first_sample``.

    SRS-004, SRS-005: the state in which the filters start, so that a constant offset causes
    no start-up transient.

    Closed form, for section ``i`` with input level ``u_0 = first_sample`` and
    ``G_i = (b0 + b1 + b2) / (1 + a1 + a2)``: ``z1 = (b1 + b2 - (a1 + a2) * G_i) * u_i``,
    ``z2 = (b2 - a2 * G_i) * u_i`` and ``u_{i+1} = G_i * u_i``. For a high-pass section
    ``G`` is exactly zero, so a constant input gives an output of exactly 0.0.

    Args:
        sos: Second-order sections, shape ``(n_sections, 6)``, a0 = 1.
        first_sample: The first input sample.

    Returns:
        The state of ``scipy.signal.sosfilt`` (transposed direct form II), shape
        ``(n_sections, 2)``.
    """
    n_sections = int(sos.shape[0])
    state = np.zeros((n_sections, 2), dtype=np.float64)
    level = float(first_sample)
    for i in range(n_sections):
        b0, b1, b2, _a0, a1, a2 = (float(c) for c in sos[i])
        gain = (b0 + b1 + b2) / (1.0 + a1 + a2)
        state[i, 0] = (b1 + b2 - (a1 + a2) * gain) * level
        state[i, 1] = (b2 - a2 * gain) * level
        level = gain * level
    return state


def apply_sos(sos: FloatArray, x: FloatArray) -> FloatArray:
    """Filter ``x`` forward through the sections, from the state of :func:`initial_state`.

    SRS-004, SRS-005: the causal filtering of the baseline wander and mains interference
    filters.

    The sections run in transposed direct form II (``scipy.signal.sosfilt``), starting in
    the steady state of a constant input equal to ``x[0]``. The output for a given input
    never depends on earlier calls.

    Args:
        sos: Second-order sections, shape ``(n_sections, 6)``, a0 = 1.
        x: The input, one dimension, not empty. It is not modified.

    Returns:
        A new array of the same length.

    Raises:
        InvalidInputError: If ``x`` is empty or not one-dimensional, or ``sos`` does not have
            the shape ``(n_sections, 6)``.
    """
    if sos.ndim != 2 or sos.shape[1] != 6:
        raise InvalidInputError(f"sections do not have the shape (n_sections, 6): {sos.shape}")
    if x.ndim != 1 or x.shape[0] == 0:
        raise InvalidInputError(f"filter input is not a non-empty 1-D array: shape {x.shape}")
    sections = np.ascontiguousarray(sos, dtype=np.float64)
    y, _final_state = _signal.sosfilt(sections, x, zi=initial_state(sections, float(x[0])))
    return np.asarray(y, dtype=np.float64)


def remove_baseline_wander(signal_mv: npt.ArrayLike, fs_hz: float) -> FloatArray:
    """Remove baseline wander and any constant offset from an ECG.

    SRS-004: a constant offset and components at 0.1 Hz and below are attenuated by at least
    20 dB, and components between 1 Hz and 40 Hz change by no more than 0.5 dB. The filter is
    a causal second-order Butterworth high-pass at 0.5 Hz; a constant input gives exactly 0.0.

    Args:
        signal_mv: The ECG, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.

    Returns:
        The filtered signal in mV, a new array of the same length.

    Raises:
        InvalidInputError: If the input is rejected by the input checks.
    """
    x = validate_input(signal_mv, fs_hz)
    return apply_sos(baseline_sos(float(fs_hz)), x)


def remove_mains_interference(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> FloatArray:
    """Remove mains interference at 50 Hz or 60 Hz from an ECG.

    SRS-005: a sinusoid at the configured mains frequency is attenuated by at least 30 dB
    once the filter has settled, and components between 1 Hz and 40 Hz change by no more than
    0.5 dB. The filter is a causal notch with Q = 30.

    Args:
        signal_mv: The ECG, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.
        mains_hz: The mains frequency, 50 or 60 Hz.

    Returns:
        The filtered signal in mV, a new array of the same length.

    Raises:
        InvalidInputError: If the input is rejected by the input checks, or ``mains_hz`` is
            neither 50 nor 60.
    """
    x = validate_input(signal_mv, fs_hz)
    mains = validate_mains(mains_hz)
    return apply_sos(mains_sos(float(fs_hz), mains), x)
