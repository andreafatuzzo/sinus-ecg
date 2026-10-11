"""Signal quality index per window (architecture §13.6).

SRS-027: for each window of ten blocks of about 1 s, starting every block from the first
sample, a signal quality index between 0 and 1, a mark (usable at or above
:data:`USABLE_THRESHOLD`), the first and last sample of the window and the sample at which
it is reported, at most 0.5 s after its last sample. SRS-028: a flat line, noise without ECG
and a held input are marked not usable, a clean ECG usable.

The index is ``S / (S + K * B)``, with ``S`` the mean of the squared derivative of the
detection band inside the zones of the accepted detections of the window and ``B`` its mean
outside them. Two gates set it to 0: an input held at one value for half the window, and an
implausible number of detections.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

from sinus_dsp._types import BoolArray, FloatArray, IndexArray
from sinus_dsp._units import floor_samples_ms, round_samples_ms
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.input_checks import validate_fs, validate_input
from sinus_dsp.qrs import QrsTrace, detector_samples

BLOCK_MS: Final = 1000
WINDOW_BLOCKS: Final = 10
HELD_BLOCKS: Final = 5
REPORT_DELAY_MS: Final = 500
MIN_DETECTIONS: Final = 4
MAX_DETECTIONS: Final = 34
BACKGROUND_WEIGHT: Final = 16.0
USABLE_THRESHOLD: Final = 0.5


@dataclass(frozen=True)
class QualitySamples:
    """The parameters of the index in samples, at one sampling frequency."""

    block: int  # H
    window: int  # W = WINDOW_BLOCKS * H
    held: int  # HELD_BLOCKS * H
    report_delay: int  # floor(500 * fs_hz / 1000)
    zone: int  # N of the detector


@dataclass(frozen=True)
class QualityWindows:
    """The windows of one input, with their index and mark.

    One element per window, in increasing order of ``first``.

    Attributes:
        first: First sample of each window, ``k * H``. int64.
        last: ``first + W - 1``. int64.
        reported_at: ``last + report_delay``; never beyond the last sample of the stream.
        index: The signal quality index, in [0, 1].
        usable: ``index >= USABLE_THRESHOLD``.
        held: The gate of the held input (diagnostic).
        n_detections: Detections with an index in the window, reported by ``reported_at``.
        signal_power: ``S``, in (mV/s)^2; NaN when no zone lies in the window.
        background_power: ``B``, in (mV/s)^2; NaN when no zone lies in the window.
    """

    first: IndexArray
    last: IndexArray
    reported_at: IndexArray
    index: FloatArray
    usable: BoolArray
    held: BoolArray
    n_detections: IndexArray
    signal_power: FloatArray
    background_power: FloatArray


def quality_samples(fs_hz: float) -> QualitySamples:
    """Convert the parameters of the index to samples at ``fs_hz``.

    SRS-027: the block of 1 s is rounded half up to a whole number of samples and the window
    is ten blocks; the report delay is rounded down so that it never exceeds 0.5 s.

    Raises:
        InvalidInputError: If ``fs_hz`` is not a finite number in 125 Hz to 1000 Hz.
    """
    fs = validate_fs(fs_hz)
    block = round_samples_ms(BLOCK_MS, fs)
    return QualitySamples(
        block=block,
        window=WINDOW_BLOCKS * block,
        held=HELD_BLOCKS * block,
        report_delay=floor_samples_ms(REPORT_DELAY_MS, fs),
        zone=detector_samples(fs).window,
    )


def _run_lengths(x: FloatArray) -> IndexArray:
    """Length of the run of equal consecutive samples that ends at each sample."""
    n = x.size
    positions = np.arange(n, dtype=np.int64)
    start = np.zeros(n, dtype=np.int64)
    if n > 1:
        start[1:] = np.where(x[1:] != x[:-1], positions[1:], 0)
    return positions - np.maximum.accumulate(start) + 1


def assess_quality(input_mv: npt.ArrayLike, trace: QrsTrace) -> QualityWindows:
    """Compute the signal quality index of every window of a stream.

    SRS-027: windows of ten blocks every block from the first sample, each reported at its
    last sample plus the report delay, and only if that sample lies in the stream. SRS-028:
    the index is 0 when the input is held for five blocks inside the window, or when fewer
    than :data:`MIN_DETECTIONS` or more than :data:`MAX_DETECTIONS` detections have an index
    in the window.

    Args:
        input_mv: The checked input of the stream, in mV, as given to the conditioning.
        trace: The detector trace of the conditioned input (carries the sampling frequency).

    Returns:
        The windows; empty arrays when the stream is shorter than ``W + report_delay``.

    Raises:
        InvalidInputError: If the input is rejected by the input checks, or its length differs
            from that of the trace.
    """
    x = validate_input(input_mv, trace.fs_hz)
    derivative = trace.signals.derivative_mv_per_s
    n = x.size
    if derivative.size != n:
        raise InvalidInputError(
            f"input has {n} samples but the detector trace has {derivative.size}"
        )
    p = quality_samples(trace.fs_hz)
    h_len, w_len = p.block, p.window
    s = derivative * derivative

    held_run = _run_lengths(x)
    n_blocks = n // h_len
    block_energy: list[float] = []
    block_hmax = np.zeros(n_blocks, dtype=np.int64)
    block_hend = np.zeros(n_blocks, dtype=np.int64)
    for j in range(n_blocks):
        lo, hi = j * h_len, (j + 1) * h_len
        block_energy.append(math.fsum(s[lo:hi].tolist()))
        block_hmax[j] = held_run[lo:hi].max()
        block_hend[j] = held_run[hi - 1]

    det = trace.detections
    indices = det.indices
    report = det.reported_at
    # Zone parts: (block, energy, samples, reported_at), in increasing order of block.
    part_block: list[int] = []
    part_energy: list[float] = []
    part_count: list[int] = []
    part_report: list[int] = []
    for peak, rep in zip(det.peaks.tolist(), report.tolist(), strict=True):
        z_lo, z_hi = max(0, peak - p.zone + 1), min(peak, n - 1)
        for j in range(z_lo // h_len, z_hi // h_len + 1):
            if j >= n_blocks:
                continue
            lo, hi = max(z_lo, j * h_len), min(z_hi, (j + 1) * h_len - 1)
            part_block.append(j)
            part_energy.append(math.fsum(s[lo : hi + 1].tolist()))
            part_count.append(hi - lo + 1)
            part_report.append(rep)
    blocks = np.array(part_block, dtype=np.int64)
    reports = np.array(part_report, dtype=np.int64)
    order = np.argsort(blocks, kind="stable")
    blocks, reports = blocks[order], reports[order]
    energies = [part_energy[i] for i in order.tolist()]
    counts = [part_count[i] for i in order.tolist()]

    n_windows = 0
    if n >= w_len + p.report_delay:
        n_windows = (n - 1 - p.report_delay - w_len + 1) // h_len + 1
    first = np.arange(n_windows, dtype=np.int64) * h_len
    last = first + (w_len - 1)
    reported = last + p.report_delay
    index = np.zeros(n_windows)
    usable = np.zeros(n_windows, dtype=np.bool_)
    held = np.zeros(n_windows, dtype=np.bool_)
    n_det = np.zeros(n_windows, dtype=np.int64)
    s_power = np.full(n_windows, np.nan)
    b_power = np.full(n_windows, np.nan)

    for k in range(n_windows):
        window_report = int(reported[k])
        # Held input: a run of 5 H equal samples ending from first + 5H - 1 to last.
        run = max(
            int(block_hend[k + HELD_BLOCKS - 1]),
            int(block_hmax[k + HELD_BLOCKS : k + WINDOW_BLOCKS].max()),
        )
        held[k] = run >= p.held
        lo_i = int(np.searchsorted(indices, first[k], side="left"))
        hi_i = int(np.searchsorted(indices, last[k], side="right"))
        n_det[k] = int(np.count_nonzero(report[lo_i:hi_i] <= window_report))
        lo_p = int(np.searchsorted(blocks, k, side="left"))
        hi_p = int(np.searchsorted(blocks, k + WINDOW_BLOCKS - 1, side="right"))
        chosen = [i for i in range(lo_p, hi_p) if reports[i] <= window_report]
        n_z = sum(counts[i] for i in chosen)
        if n_z == 0:
            continue
        e_total = math.fsum(block_energy[k : k + WINDOW_BLOCKS])
        e_zone = math.fsum(energies[i] for i in chosen)
        signal = e_zone / n_z
        background = max(0.0, e_total - e_zone) / (w_len - n_z)
        s_power[k], b_power[k] = signal, background
        denominator = signal + BACKGROUND_WEIGHT * background
        if held[k] or not MIN_DETECTIONS <= n_det[k] <= MAX_DETECTIONS or denominator <= 0.0:
            continue
        index[k] = signal / denominator
    usable[:] = index >= USABLE_THRESHOLD
    return QualityWindows(
        first=first,
        last=last,
        reported_at=reported,
        index=index,
        usable=usable,
        held=held,
        n_detections=n_det,
        signal_power=s_power,
        background_power=b_power,
    )


def quality_windows(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> QualityWindows:
    """The quality windows of a raw ECG: ``run_pipeline(...).quality``.

    SRS-027, SRS-028: conditions the signal and detects as :func:`~sinus_dsp.pipeline.run_pipeline`
    does, and assesses the quality of the stream.

    Raises:
        InvalidInputError: If the input is rejected by the input checks, or ``mains_hz`` is
            neither 50 nor 60.
    """
    from sinus_dsp.pipeline import run_pipeline  # noqa: PLC0415 (pipeline imports this module)

    return run_pipeline(signal_mv, fs_hz, mains_hz).quality
