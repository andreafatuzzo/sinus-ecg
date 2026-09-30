"""The conditioning chain and the detection, in their fixed order (architecture §7.1, §8.7).

Baseline wander removal (SRS-004), then mains interference removal (SRS-005), then QRS
detection (SRS-006) on the output of the mains stage. The chain is defined once, here, and
every user of the detector on a raw ECG goes through it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy.typing as npt

from sinus_dsp._types import FloatArray, IndexArray
from sinus_dsp.filters import apply_sos, baseline_sos, mains_sos
from sinus_dsp.input_checks import validate_input, validate_mains
from sinus_dsp.qrs import _detect

STAGES: Final = ("baseline", "mains")


@dataclass(frozen=True)
class PipelineResult:
    """Everything the chain computes for one input."""

    fs_hz: float
    mains_hz: int
    coefficients: tuple[FloatArray, FloatArray]  # baseline_sos, mains_sos
    input_mv: FloatArray
    baseline_mv: FloatArray
    mains_mv: FloatArray
    beats: IndexArray


def run_pipeline(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> PipelineResult:
    """Condition a raw ECG and detect its QRS complexes.

    SRS-006: the detected QRS sample indices, in the time base of the input. SRS-010: the
    baseline wander and the mains interference are removed before the detection, so that the
    detection criteria hold on an ECG with both.

    The input and the mains setting are checked once, before any other computation; then the
    baseline filter, the mains filter and the detection on the mains output run in this
    order.

    Args:
        signal_mv: The raw ECG, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.
        mains_hz: The mains frequency, 50 or 60 Hz.

    Returns:
        The checked input, the coefficients and the output of each conditioning stage, and
        the detected QRS sample indices.

    Raises:
        InvalidInputError: If the input is rejected by the input checks, or ``mains_hz`` is
            neither 50 nor 60.
    """
    input_mv = validate_input(signal_mv, fs_hz)
    mains = validate_mains(mains_hz)
    fs = float(fs_hz)
    baseline_sections = baseline_sos(fs)
    mains_sections = mains_sos(fs, mains)
    baseline_mv = apply_sos(baseline_sections, input_mv)
    mains_mv = apply_sos(mains_sections, baseline_mv)
    beats = _detect(mains_mv, fs)
    return PipelineResult(
        fs_hz=fs,
        mains_hz=mains,
        coefficients=(baseline_sections, mains_sections),
        input_mv=input_mv,
        baseline_mv=baseline_mv,
        mains_mv=mains_mv,
        beats=beats,
    )


def detect_beats(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> IndexArray:
    """Detect the QRS complexes of a raw ECG: ``run_pipeline(...).beats``.

    SRS-006: returns the sample indices of the detected QRS complexes in the time base of
    the input, strictly increasing and at least 200 ms apart; a flat input gives an empty
    array and no error. SRS-010: the same holds with baseline wander and mains interference
    at the configured mains frequency added to the ECG.

    Args:
        signal_mv: The raw ECG, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.
        mains_hz: The mains frequency, 50 or 60 Hz.

    Returns:
        A new int64 array of sample indices, possibly empty.

    Raises:
        InvalidInputError: If the input is rejected by the input checks, or ``mains_hz`` is
            neither 50 nor 60.
    """
    return run_pipeline(signal_mv, fs_hz, mains_hz).beats
