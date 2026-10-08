"""The conditioning chain and the detection, in their fixed order (architecture §7.1, §8.7).

Baseline wander removal (SRS-004), then mains interference removal (SRS-005), then QRS
detection (SRS-006) on the output of the mains stage, with the mark of each detection
(SRS-022, architecture §13.3). The chain is defined once, here, and every user of the
detector on a raw ECG goes through it: the evaluation, and the golden-vector export
(SRS-015), which writes everything :func:`run_pipeline` returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy.typing as npt

from sinus_dsp._types import FloatArray, IndexArray
from sinus_dsp.filters import apply_sos, baseline_sos, mains_sos
from sinus_dsp.heart_rate import HeartRateEvent, track_heart_rate
from sinus_dsp.input_checks import validate_input, validate_mains
from sinus_dsp.qrs import Detections, _trace

#: SRS-015: names of the conditioning stages, in the order applied, as golden-vector files
#: state them.
STAGES: Final = ("baseline", "mains")


@dataclass(frozen=True)
class PipelineResult:
    """Everything the chain computes for one input.

    ``beats`` is ``detections.indices`` (SRS-022: the marks change no detection).
    """

    fs_hz: float
    mains_hz: int
    coefficients: tuple[FloatArray, FloatArray]  # baseline_sos, mains_sos
    input_mv: FloatArray
    baseline_mv: FloatArray
    mains_mv: FloatArray
    beats: IndexArray
    detections: Detections
    heart_rate: tuple[HeartRateEvent, ...]


@dataclass(frozen=True)
class _Conditioned:
    """The checked input and the conditioning stages, before the detection."""

    fs_hz: float
    mains_hz: int
    coefficients: tuple[FloatArray, FloatArray]
    input_mv: FloatArray
    baseline_mv: FloatArray
    mains_mv: FloatArray


def _condition(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> _Conditioned:
    """Check the input and the mains setting once, then apply the stages of :data:`STAGES`."""
    input_mv = validate_input(signal_mv, fs_hz)
    mains = validate_mains(mains_hz)
    fs = float(fs_hz)
    baseline_sections = baseline_sos(fs)
    mains_sections = mains_sos(fs, mains)
    baseline_mv = apply_sos(baseline_sections, input_mv)
    mains_mv = apply_sos(mains_sections, baseline_mv)
    return _Conditioned(
        fs_hz=fs,
        mains_hz=mains,
        coefficients=(baseline_sections, mains_sections),
        input_mv=input_mv,
        baseline_mv=baseline_mv,
        mains_mv=mains_mv,
    )


def run_pipeline(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> PipelineResult:
    """Condition a raw ECG and detect its QRS complexes.

    SRS-006: the detected QRS sample indices, in the time base of the input. SRS-010: the
    baseline wander and the mains interference are removed before the detection, so that the
    detection criteria hold on an ECG with both. SRS-015: the result holds the checked input,
    the coefficients and the output of each conditioning stage in the order of
    :data:`STAGES`, and the beats, which a golden-vector file states. SRS-022: the result
    also holds the detections with their marks (:class:`~sinus_dsp.qrs.Detections`), whose
    indices are the beats. SRS-024, SRS-025, SRS-026: and the heart rate events of those
    detections (:func:`~sinus_dsp.heart_rate.track_heart_rate`).

    The input and the mains setting are checked once, before any other computation; then the
    baseline filter, the mains filter and the detection on the mains output run in this
    order.

    Args:
        signal_mv: The raw ECG, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.
        mains_hz: The mains frequency, 50 or 60 Hz.

    Returns:
        The checked input, the coefficients and the output of each conditioning stage, the
        detected QRS sample indices and the detections with their trace.

    Raises:
        InvalidInputError: If the input is rejected by the input checks, or ``mains_hz`` is
            neither 50 nor 60.
    """
    conditioned = _condition(signal_mv, fs_hz, mains_hz)
    detections = _trace(conditioned.mains_mv, conditioned.fs_hz).detections
    heart_rate = track_heart_rate(
        detections.indices,
        detections.startup,
        conditioned.fs_hz,
        conditioned.input_mv.size,
        reported_at=detections.reported_at,
    )
    return PipelineResult(
        fs_hz=conditioned.fs_hz,
        mains_hz=conditioned.mains_hz,
        coefficients=conditioned.coefficients,
        input_mv=conditioned.input_mv,
        baseline_mv=conditioned.baseline_mv,
        mains_mv=conditioned.mains_mv,
        beats=detections.indices,
        detections=detections,
        heart_rate=heart_rate,
    )


def detect_marked(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> Detections:
    """Detect the QRS complexes of a raw ECG, each with its mark and trace.

    SRS-022: each detection is marked start-up if its index lies in a stretch of 2 s from
    which the detector learns its signal levels, reliable otherwise; the indices are those of
    :func:`detect_beats` on the same input (SRS-006, SRS-010), which the marks do not change.

    The input and the mains setting are checked once; the signal is conditioned as by
    :func:`run_pipeline`, and the detector runs on the mains output. Nothing else is
    computed (architecture §13.3).

    Args:
        signal_mv: The raw ECG, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.
        mains_hz: The mains frequency, 50 or 60 Hz.

    Returns:
        The detections, with their marks, report samples, peaks and paths, and the samples
        of the initialisations.

    Raises:
        InvalidInputError: If the input is rejected by the input checks, or ``mains_hz`` is
            neither 50 nor 60.
    """
    conditioned = _condition(signal_mv, fs_hz, mains_hz)
    return _trace(conditioned.mains_mv, conditioned.fs_hz).detections


def detect_beats(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> IndexArray:
    """Detect the QRS complexes of a raw ECG: ``detect_marked(...).indices``.

    SRS-006: returns the sample indices of the detected QRS complexes in the time base of
    the input, strictly increasing and at least 200 ms apart; a flat input gives an empty
    array and no error. SRS-010: the same holds with baseline wander and mains interference
    at the configured mains frequency added to the ECG.

    The result equals ``run_pipeline(...).beats``; it is computed through
    :func:`detect_marked`, so that nothing else is computed.

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
    return detect_marked(signal_mv, fs_hz, mains_hz).indices
