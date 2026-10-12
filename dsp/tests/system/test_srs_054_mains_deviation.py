"""System test of SRS-054: mains interference removal under a deviation of the mains frequency.

Design: architecture-m3.md section 16.9. The synthetic ECGs of SRS-006 (30, 40, 75, 180 and
200 bpm, 30 s, at 360 Hz and at 250 Hz) get a baseline wander of 1 mV at 0.3 Hz and an
interference of 0.2 mV at 49.5 and 50.5 Hz (mains setting 50 Hz) or at 59.5 and 60.5 Hz
(setting 60 Hz): 40 runs of ``run_pipeline``. In each run the criteria of SRS-006 as SRS-010
applies them must hold: exactly one detection within floor(0.150 * fs) samples of every true R
centre and no other detection; indices strictly increasing and at least ceil(0.200 * fs)
samples apart. The waveform is rebuilt here from the formulas of architecture section 7.2.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp.pipeline import run_pipeline

SAMPLING_FREQUENCIES_HZ = [360, 250]
HEART_RATES_BPM = [30, 40, 75, 180, 200]
# (mains setting in Hz, interference frequency in Hz)
MAINS_CASES = [(50, 49.5), (50, 50.5), (60, 59.5), (60, 60.5)]

# (offset from the R centre in ms, amplitude in mV, sigma in ms, scaled with sqrt(RR))
_WAVES = [
    (-200.0, 0.15, 25.0, True),  # P
    (-30.0, -0.10, 10.0, False),  # Q
    (0.0, 1.00, 10.0, False),  # R
    (30.0, -0.20, 10.0, False),  # S
    (280.0, 0.30, 45.0, True),  # T
]


def _synthetic(
    fs: int, hr: int, interference_hz: float
) -> tuple[npt.NDArray[np.float64], list[int]]:
    n = 30 * fs
    t = np.arange(n, dtype=np.float64) / fs
    rr = 60.0 / hr
    s = math.sqrt(rr)
    centres: list[int] = []
    k = 0
    while 60 * k <= 29 * hr:
        centres.append((hr * (fs + 1) + 120 * k * fs) // (2 * hr))
        k += 1
    x = np.zeros(n, dtype=np.float64)
    for r in centres:
        for offset_ms, amp, sigma_ms, scaled in _WAVES:
            f = s if scaled else 1.0
            tc = r / fs + offset_ms * f / 1000.0
            sg = sigma_ms * f / 1000.0
            x += amp * np.exp(-((t - tc) ** 2) / (2.0 * sg**2))
    x += 1.0 * np.sin(2.0 * np.pi * 0.3 * t)
    x += 0.2 * np.sin(2.0 * np.pi * interference_hz * t)
    return x, centres


def _violations(det: npt.NDArray[np.int64], centres: list[int], fs: int) -> list[str]:
    window = 150 * fs // 1000
    spacing = -(-200 * fs // 1000)
    out: list[str] = []
    qrs = np.asarray(centres, dtype=np.int64)
    for r in centres:
        n = int(np.sum(np.abs(det - r) <= window))
        if n != 1:
            out.append(f"QRS {r}: {n} detections")
    for d in det.tolist():
        if not np.any(np.abs(qrs - d) <= window):
            out.append(f"detection {d}: no QRS within {window} samples")
    for a, b in zip(det[:-1].tolist(), det[1:].tolist(), strict=True):
        if b <= a:
            out.append(f"indices {a}, {b}: not increasing")
        elif b - a < spacing:
            out.append(f"indices {a}, {b}: {b - a} apart, minimum {spacing}")
    return out


def test_waveform_matches_known_beat_counts() -> None:
    """Self-check of the rebuilt input: 15, 20, 37, 88, 97 beats at the five rates."""
    expected = {30: 15, 40: 20, 75: 37, 180: 88, 200: 97}
    for hr, count in expected.items():
        assert len(_synthetic(250, hr, 50.5)[1]) == count


@pytest.mark.requirement("SRS-054")
def test_detection_meets_srs_010_criteria_under_a_mains_deviation_of_half_a_hertz() -> None:
    failures: list[str] = []
    runs = 0
    for fs in SAMPLING_FREQUENCIES_HZ:
        for hr in HEART_RATES_BPM:
            for setting, f in MAINS_CASES:
                x, centres = _synthetic(fs, hr, f)
                det = np.asarray(run_pipeline(x, float(fs), setting).beats, dtype=np.int64)
                runs += 1
                v = _violations(det, centres, fs)
                if v:
                    failures.append(
                        f"fs={fs} Hz, {hr} bpm, setting {setting} Hz, interference {f} Hz: "
                        f"{len(v)} violations, first: {v[:3]}"
                    )
    assert runs == 40
    assert not failures, "\n".join(failures)
