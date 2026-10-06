"""Requirement tests of SRS-015: the synthetic inputs of the golden-vector export (RC-012).

SRS-015 (v0.7.2): the export writes one file for each synthetic ECG "generated
deterministically by the software from documented parameters: sampling frequencies of 250 Hz
and 360 Hz; heart rates of 40, 75 and 180 bpm; each without interference, and with the
baseline wander and mains interference of SRS-010 at 50 Hz and at 60 Hz".

The documented parameters are those of architecture section 7.2 (interface in section 8.12):
30 s at t_n = n / fs; beat k exists if 60 k <= 29 hr, centred on r_k = (hr (fs + 1) + 120 k
fs) // (2 hr) (20, 37 and 88 beats at 40, 75 and 180 bpm); five Gaussian waves per beat; the
interference variants add 1.0 mV sin(2 pi 0.3 Hz t), then 0.2 mV sin(2 pi f t) with f = 50 or
60 Hz. A test of the waveform compares it with the formulas within 1e-9 mV, and the beat
count and positions exactly.

The expected values come from the test's own generator (`make_synthetic_ecg`, written from
section 7.2 with exact rational beat positions) and from the integer rule (`golden_r_peaks`),
never from `sinus_dsp.synthetic`. The files themselves are tested in
`test_srs_015_golden_vector_files.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.synthetic import (
    SYNTHETIC_FS_HZ,
    SYNTHETIC_HEART_RATES_BPM,
    SYNTHETIC_VARIANTS,
    synthetic_ecg,
    synthetic_set,
)

# The synthetic inputs of SRS-015, in the documented order: sampling frequency, then heart
# rate, then variant (architecture, section 8.12).
INPUTS = tuple(
    (fs, hr, variant)
    for fs in (250, 360)
    for hr in (40, 75, 180)
    for variant in ("clean", "bw-mains50", "bw-mains60")
)
WAVEFORM_TOLERANCE_MV = 1e-9
EXPECTED_BEATS = {40: 20, 75: 37, 180: 88}


def _input_id(fs: int, hr: int, variant: str) -> str:
    return f"syn-fs{fs}-hr{hr:03d}-{variant}"


def _mains_hz(variant: str) -> int:
    return 60 if variant == "bw-mains60" else 50


def _parameters(hr: int, variant: str) -> str:
    wander, mains = ("0.0", "0.0") if variant == "clean" else ("1.0", "0.2")
    return (
        f"duration_s=30;heart_rate_bpm={hr};baseline_wander_hz=0.3;"
        f"baseline_wander_mv={wander};mains_hz={_mains_hz(variant)};mains_mv={mains}"
    )


@pytest.fixture(scope="module")
def the_set() -> tuple[Any, ...]:
    return synthetic_set()


@pytest.mark.requirement("SRS-015")
def test_synthetic_set_is_the_documented_set(the_set: tuple[Any, ...]) -> None:
    """The software generates exactly the synthetic inputs that SRS-015 lists.

    Input: `synthetic_set()` and the documented constants.
    Expected: 18 inputs, sampling frequency first (250, 360 Hz), then heart rate (40, 75,
    180 bpm), then variant (`clean`, `bw-mains50`, `bw-mains60`); identifiers
    `syn-fs<fs>-hr<hr, three digits>-<variant>`; the sampling frequency as a float; mains
    setting 50 Hz for `clean` and `bw-mains50`, 60 Hz for `bw-mains60`; the constants
    `SYNTHETIC_FS_HZ`, `SYNTHETIC_HEART_RATES_BPM` and `SYNTHETIC_VARIANTS` are the documented
    values.
    """
    assert SYNTHETIC_FS_HZ == (250.0, 360.0)
    assert SYNTHETIC_HEART_RATES_BPM == (40, 75, 180)
    assert SYNTHETIC_VARIANTS == ("clean", "bw-mains50", "bw-mains60")
    assert [
        (ecg.input_id, ecg.fs_hz, ecg.heart_rate_bpm, ecg.variant, ecg.mains_hz) for ecg in the_set
    ] == [
        (_input_id(fs, hr, variant), float(fs), hr, variant, _mains_hz(variant))
        for fs, hr, variant in INPUTS
    ]
    assert all(type(ecg.fs_hz) is float for ecg in the_set)


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize(("fs", "hr", "variant"), INPUTS, ids=[_input_id(*i) for i in INPUTS])
def test_synthetic_beats_follow_the_documented_rule(
    fs: int,
    hr: int,
    variant: str,
    the_set: tuple[Any, ...],
    golden_r_peaks: Callable[[int, int], list[int]],
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """The true beat positions of each synthetic input are those of the documented rule.

    Input: the entry of `synthetic_set()` for the input.
    Expected: `r_peaks` is an `int64` array equal to the r_k of the integer rule of
    architecture section 7.2, which equals the rational rule r_k = floor((0.5 + k RR) fs +
    0.5) for every k with 0.5 + k RR <= 29.5 s (computed separately); 20, 37 and 88 beats at
    40, 75 and 180 bpm. At 180 bpm the last beat (k = 87) lies exactly at 29.5 s and exists.
    """
    ecg = next(e for e in the_set if e.input_id == _input_id(fs, hr, variant))
    integer_rule = golden_r_peaks(fs, hr)
    rational_rule = make_synthetic_ecg(fs, hr).qrs_samples.tolist()

    assert integer_rule == rational_rule
    assert len(integer_rule) == EXPECTED_BEATS[hr]
    assert ecg.r_peaks.dtype == np.int64
    assert ecg.r_peaks.tolist() == integer_rule
    if hr == 180:
        assert ecg.r_peaks[-1] == round(29.5 * fs)


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize(("fs", "hr", "variant"), INPUTS, ids=[_input_id(*i) for i in INPUTS])
def test_synthetic_waveform_follows_the_documented_formulas(
    fs: int,
    hr: int,
    variant: str,
    the_set: tuple[Any, ...],
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """The samples of each synthetic input are those of the documented formulas.

    Input: the entry of `synthetic_set()` for the input; the test's own synthetic ECG of
    section 7.2 (five Gaussian waves per beat), with, for the interference variants, the
    0.3 Hz baseline wander of 1 mV and the mains sinusoid of 0.2 mV at 50 or 60 Hz.
    Expected: a one-dimensional float64 array of 30 fs samples (7500 at 250 Hz, 10800 at
    360 Hz), within 1e-9 mV of the test's signal on every sample. The variants differ from
    `clean` by the interference only: `bw-mains50` minus `clean` is within 1e-9 mV of
    1.0 sin(2 pi 0.3 t) + 0.2 sin(2 pi 50 t), and likewise at 60 Hz.
    """
    ecg = next(e for e in the_set if e.input_id == _input_id(fs, hr, variant))
    mains = None if variant == "clean" else _mains_hz(variant)
    expected = make_synthetic_ecg(fs, hr, mains_hz=mains).signal_mv

    assert ecg.signal_mv.dtype == np.float64
    assert ecg.signal_mv.shape == (30 * fs,)
    worst = float(np.max(np.abs(ecg.signal_mv - expected)))
    assert worst <= WAVEFORM_TOLERANCE_MV, f"largest difference {worst} mV"
    if variant != "clean":
        clean = next(e for e in the_set if e.input_id == _input_id(fs, hr, "clean"))
        t = np.arange(30 * fs, dtype=np.float64) / fs
        interference = 1.0 * np.sin(2 * np.pi * 0.3 * t) + 0.2 * np.sin(2 * np.pi * mains * t)
        added = ecg.signal_mv - clean.signal_mv
        assert float(np.max(np.abs(added - interference))) <= WAVEFORM_TOLERANCE_MV


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize(("fs", "hr", "variant"), INPUTS, ids=[_input_id(*i) for i in INPUTS])
def test_synthetic_input_is_generated_deterministically(
    fs: int, hr: int, variant: str, the_set: tuple[Any, ...]
) -> None:
    """Each synthetic input is the same on every call.

    Input: `synthetic_ecg(fs, hr, variant)` called twice, with the sampling frequency as a
    float and as an integer, and the entry of `synthetic_set()`.
    Expected: the four results are equal in every field; the samples are bitwise identical
    and the beat positions equal.
    """
    entry = next(e for e in the_set if e.input_id == _input_id(fs, hr, variant))
    results = [synthetic_ecg(float(fs), hr, variant), synthetic_ecg(fs, hr, variant), entry]
    results.append(synthetic_ecg(float(fs), hr, variant))

    for result in results:
        assert (result.input_id, result.fs_hz, result.heart_rate_bpm) == (
            entry.input_id,
            entry.fs_hz,
            entry.heart_rate_bpm,
        )
        assert (result.variant, result.mains_hz, result.parameters) == (
            entry.variant,
            entry.mains_hz,
            entry.parameters,
        )
        assert result.signal_mv.tobytes() == entry.signal_mv.tobytes()
        assert result.r_peaks.tolist() == entry.r_peaks.tolist()


@pytest.mark.requirement("SRS-015")
@pytest.mark.parametrize(("fs", "hr", "variant"), INPUTS, ids=[_input_id(*i) for i in INPUTS])
def test_synthetic_parameters_are_documented_with_the_input(
    fs: int, hr: int, variant: str, the_set: tuple[Any, ...]
) -> None:
    """Each synthetic input carries the documented parameters it was generated from.

    Input: the entry of `synthetic_set()` for the input.
    Expected: `parameters` (the value of the header key `input_parameters`) is
    `duration_s=30;heart_rate_bpm=<hr>;baseline_wander_hz=0.3;baseline_wander_mv=<a>;
    mains_hz=<mains>;mains_mv=<m>`, with a = 1.0 and m = 0.2 for the interference variants
    and 0.0 for `clean`, mains = 50 or 60 (architecture, sections 7.3 and 8.12).
    """
    entry = next(e for e in the_set if e.input_id == _input_id(fs, hr, variant))

    assert entry.parameters == _parameters(hr, variant)
