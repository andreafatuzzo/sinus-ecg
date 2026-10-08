"""Requirement tests of SRS-027 and SRS-028, reference part (software item `dsp`): signal quality.

SRS-027: windows of 10 s every 1 s from the first sample, with first/last sample indices, an
index in [0, 1], a mark usable when the index is at or above the documented threshold (0.5),
each reported at most 0.5 s after its last sample.
SRS-028: windows that begin at least 2 s after the first sample of a clean regular ECG
(30..200 bpm, with or without the interference of SRS-010) are usable; windows of a flat line
or of white noise (0.01..1 mV RMS) are not usable; windows containing at least 5 s of one
held value are not usable.

The documented interface is architecture section 13.6: `quality.quality_windows`,
`quality.quality_samples` and `pipeline.run_pipeline(...).quality`. The ECGs come from the QA
generator of section 7.2 (fixture `make_synthetic_ecg`). The C++ part is verified by the
requirement tests of `libs/sinus-dsp`, not here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.pipeline import run_pipeline
from sinus_dsp.quality import QualityWindows, quality_samples, quality_windows

SAMPLING_FREQUENCIES_HZ = [360, 250]
HEART_RATES_BPM = [30, 40, 75, 180, 200]
MAINS = [None, 50, 60]
THRESHOLD = 0.5
DURATION_S = 60

MakeEcg = Callable[..., Any]


def _ecg(make: MakeEcg, fs_hz: int, bpm: int, mains_hz: int | None = None) -> np.ndarray:
    return np.asarray(
        make(fs_hz, bpm, n_samples=DURATION_S * fs_hz, mains_hz=mains_hz).signal_mv,
        dtype=np.float64,
    )


def _windows(signal: np.ndarray, fs_hz: int, mains_hz: int | None = None) -> QualityWindows:
    return quality_windows(signal, float(fs_hz), mains_hz if mains_hz is not None else 50)


def _expected_count(n: int, fs_hz: int) -> int:
    """Windows k = 0, 1, ... with k*H + W - 1 + delta <= n - 1."""
    q = quality_samples(float(fs_hz))
    count = 0
    while count * q.block + q.window - 1 + q.report_delay <= n - 1:
        count += 1
    return count


@pytest.mark.requirement("SRS-027")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_timing_constants(fs_hz: int) -> None:
    """Spacing 1 s, window 10 s, report delay at most 0.5 s (360 Hz: 360/3600/180)."""
    q = quality_samples(float(fs_hz))
    assert q.block == fs_hz
    assert q.window == 10 * fs_hz
    assert q.report_delay <= fs_hz // 2
    assert q.report_delay == fs_hz * 500 // 1000


@pytest.mark.requirement("SRS-027")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("mains_hz", [50, 60])
def test_windows_are_10_s_every_second(
    make_synthetic_ecg: MakeEcg, fs_hz: int, mains_hz: int
) -> None:
    """60 s ECG: window k has first = k*fs, last = first + 10 s - 1, reported at most 0.5 s
    after its last sample (and within the stream); no window is missed or added."""
    signal = _ecg(make_synthetic_ecg, fs_hz, 75)
    w = _windows(signal, fs_hz, mains_hz)
    n = len(signal)
    count = _expected_count(n, fs_hz)
    assert count == 50  # starts 0..49 s
    assert len(w.first) == len(w.last) == len(w.reported_at) == count
    assert len(w.index) == len(w.usable) == count
    k = np.arange(count, dtype=np.int64)
    assert np.array_equal(w.first, k * fs_hz)
    assert np.array_equal(w.last, w.first + 10 * fs_hz - 1)
    delay = w.reported_at - w.last
    assert np.all(delay >= 0)
    assert np.all(delay * 2 <= fs_hz)  # at most 0.5 s
    assert np.all(w.reported_at <= n - 1)
    for arr in (w.first, w.last, w.reported_at):
        assert arr.dtype == np.int64


@pytest.mark.requirement("SRS-027")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_window_not_reported_before_its_report_sample(
    make_synthetic_ecg: MakeEcg, fs_hz: int
) -> None:
    """Streams of 10 s + delay - 1 samples have no window; of 10 s + delay samples, one window;
    a stream one block longer has the window of the next second only at its own report sample."""
    q = quality_samples(float(fs_hz))
    base = _ecg(make_synthetic_ecg, fs_hz, 75)
    short = q.window + q.report_delay
    assert len(_windows(base[: short - 1], fs_hz).first) == 0
    assert len(_windows(base[:short], fs_hz).first) == 1
    assert len(_windows(base[: short + q.block - 1], fs_hz).first) == 1
    assert len(_windows(base[: short + q.block], fs_hz).first) == 2


@pytest.mark.requirement("SRS-027")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_windows_do_not_depend_on_the_stream_length(
    make_synthetic_ecg: MakeEcg, fs_hz: int
) -> None:
    """The windows of a prefix of the stream are those of the whole stream (same first, last,
    and same index for the windows reported within the prefix)."""
    signal = _ecg(make_synthetic_ecg, fs_hz, 75)
    full = _windows(signal, fs_hz)
    part = _windows(signal[: 30 * fs_hz], fs_hz)
    m = len(part.first)
    assert m > 0
    assert np.array_equal(part.first, full.first[:m])
    assert np.array_equal(part.last, full.last[:m])
    assert np.allclose(part.index, full.index[:m], atol=1e-12)


@pytest.mark.requirement("SRS-027")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("bpm", HEART_RATES_BPM)
def test_index_in_range_and_mark_follows_threshold(
    make_synthetic_ecg: MakeEcg, fs_hz: int, bpm: int
) -> None:
    """Every index lies in [0, 1], is finite, and usable == (index >= 0.5)."""
    w = _windows(_ecg(make_synthetic_ecg, fs_hz, bpm), fs_hz)
    assert np.all(np.isfinite(w.index))
    assert np.all(w.index >= 0.0)
    assert np.all(w.index <= 1.0)
    assert np.array_equal(w.usable, w.index >= THRESHOLD)


@pytest.mark.requirement("SRS-027")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("kind", ["flat", "noise", "held"])
def test_index_in_range_on_other_inputs(make_synthetic_ecg: MakeEcg, fs_hz: int, kind: str) -> None:
    """Index in [0, 1] and mark consistent with the threshold also on a flat line, white noise
    and an ECG held at 2 mV from 20 s to 40 s."""
    n = DURATION_S * fs_hz
    if kind == "flat":
        signal = np.full(n, 1.0)
    elif kind == "noise":
        signal = np.random.default_rng(5).normal(0.0, 0.1, n)
    else:
        signal = _ecg(make_synthetic_ecg, fs_hz, 75)
        signal[20 * fs_hz : 40 * fs_hz] = 2.0
    w = _windows(signal, fs_hz)
    assert len(w.index) == 50
    assert np.all((w.index >= 0.0) & (w.index <= 1.0))
    assert np.array_equal(w.usable, w.index >= THRESHOLD)


@pytest.mark.requirement("SRS-027")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_pipeline_quality_equals_quality_windows(make_synthetic_ecg: MakeEcg, fs_hz: int) -> None:
    """`run_pipeline(...).quality` gives the same windows, indices and marks as
    `quality_windows` on the same input."""
    signal = _ecg(make_synthetic_ecg, fs_hz, 75, 50)
    a = run_pipeline(signal, float(fs_hz), 50).quality
    b = quality_windows(signal, float(fs_hz), 50)
    assert np.array_equal(a.first, b.first)
    assert np.array_equal(a.last, b.last)
    assert np.array_equal(a.reported_at, b.reported_at)
    assert np.array_equal(a.index, b.index)
    assert np.array_equal(a.usable, b.usable)


@pytest.mark.requirement("SRS-027")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_quality_is_deterministic(make_synthetic_ecg: MakeEcg, fs_hz: int) -> None:
    """Two runs on the same input give identical indices."""
    signal = _ecg(make_synthetic_ecg, fs_hz, 75)
    assert np.array_equal(_windows(signal, fs_hz).index, _windows(signal, fs_hz).index)


@pytest.mark.requirement("SRS-028")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", MAINS)
def test_clean_ecg_is_usable_from_2_s(
    make_synthetic_ecg: MakeEcg, fs_hz: int, bpm: int, mains_hz: int | None
) -> None:
    """Every window beginning at 2 s or later of the 60 s ECG at 30, 40, 75, 180 and 200 bpm
    (clean, and with the interference of SRS-010 at 50 and 60 Hz) is usable."""
    w = _windows(_ecg(make_synthetic_ecg, fs_hz, bpm, mains_hz), fs_hz, mains_hz)
    sel = w.first >= 2 * fs_hz
    assert sel.sum() == 48
    assert np.all(w.usable[sel]), np.round(w.index[sel], 3)


@pytest.mark.requirement("SRS-028")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("level_mv", [0.0, 1.0])
def test_flat_input_is_not_usable(fs_hz: int, level_mv: float) -> None:
    """A constant input of 60 s at 0 mV and at 1 mV: every window is not usable, index 0."""
    w = _windows(np.full(DURATION_S * fs_hz, level_mv), fs_hz)
    assert len(w.usable) == 50
    assert not np.any(w.usable)
    assert np.all(w.index < THRESHOLD)


@pytest.mark.requirement("SRS-028")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("rms_mv", [0.01, 0.1, 1.0])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_white_noise_is_not_usable(fs_hz: int, rms_mv: float, seed: int) -> None:
    """White Gaussian noise of RMS 0.01, 0.1 and 1 mV (fixed seeds), 60 s: no window usable."""
    noise = np.random.default_rng(seed).normal(0.0, rms_mv, DURATION_S * fs_hz)
    w = _windows(noise, fs_hz)
    assert len(w.usable) == 50
    assert not np.any(w.usable), np.round(w.index.max(), 3)


@pytest.mark.requirement("SRS-028")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("bpm", [40, 75])
def test_held_input_windows_not_usable(make_synthetic_ecg: MakeEcg, fs_hz: int, bpm: int) -> None:
    """ECG of 60 s held at 2 mV from 20 s to 40 s: every window with at least 5 s of the held
    stretch (start 15 s to 35 s) is not usable; windows with no held sample (start 2..10 s and
    40..49 s) stay usable."""
    signal = _ecg(make_synthetic_ecg, fs_hz, bpm)
    signal[20 * fs_hz : 40 * fs_hz] = 2.0
    w = _windows(signal, fs_hz)
    start_s = w.first // fs_hz
    held = (start_s >= 15) & (start_s <= 35)
    assert held.sum() == 21
    assert not np.any(w.usable[held]), np.round(w.index[held], 3)
    clean = ((start_s >= 2) & (start_s <= 10)) | (start_s >= 40)
    assert np.all(w.usable[clean]), np.round(w.index[clean], 3)


@pytest.mark.requirement("SRS-028")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_held_stretch_boundary_five_seconds(make_synthetic_ecg: MakeEcg, fs_hz: int) -> None:
    """A held stretch of exactly 5 s (samples 20 s to 25 s - 1) makes not usable the windows
    that contain all of it (start 16 s to 20 s); the window starting at 15 s ends at 25 s - 1
    and contains it too."""
    signal = _ecg(make_synthetic_ecg, fs_hz, 75)
    signal[20 * fs_hz : 25 * fs_hz] = 2.0
    w = _windows(signal, fs_hz)
    start_s = w.first // fs_hz
    sel = (start_s >= 15) & (start_s <= 20)
    assert not np.any(w.usable[sel]), np.round(w.index[sel], 3)


@pytest.mark.requirement("SRS-028")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_saturated_at_limit_not_usable(make_synthetic_ecg: MakeEcg, fs_hz: int) -> None:
    """Input held at the limit of the range (1000 mV, then -1000 mV) from 20 s to 40 s: the
    windows with at least 5 s of it are not usable."""
    for level in (1000.0, -1000.0):
        signal = _ecg(make_synthetic_ecg, fs_hz, 75)
        signal[20 * fs_hz : 40 * fs_hz] = level
        w = _windows(signal, fs_hz)
        start_s = w.first // fs_hz
        sel = (start_s >= 15) & (start_s <= 35)
        assert not np.any(w.usable[sel])
