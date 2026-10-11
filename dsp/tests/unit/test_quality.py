"""Unit tests of the signal quality index (architecture §13.6)."""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np
import pytest

from sinus_dsp import pipeline, quality
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.qrs import Detections, QrsTrace, _trace
from sinus_dsp.quality import assess_quality, quality_samples, quality_windows

FS_VALUES = [250.0, 360.0]


def _noisy(x: np.ndarray, seed: int = 1) -> np.ndarray:
    """Add 1 uV of noise so that no two consecutive samples are equal by accident."""
    return x + 1e-3 * np.random.default_rng(seed).standard_normal(x.size)


def _trace_of(x: np.ndarray, fs_hz: float) -> QrsTrace:
    result = pipeline.run_pipeline(x, fs_hz, 50)
    return _trace(result.mains_mv, fs_hz)


def _fake(trace: QrsTrace, indices: list[int], reported: list[int] | None = None) -> QrsTrace:
    """The trace with detections placed by hand (peak = index, reported at the index)."""
    idx = np.array(indices, dtype=np.int64)
    rep = idx if reported is None else np.array(reported, dtype=np.int64)
    detections = Detections(
        indices=idx,
        startup=np.zeros(idx.size, dtype=np.bool_),
        reported_at=rep,
        peaks=idx.copy(),
        paths=("normal",) * idx.size,
        initialisations=np.zeros(0, dtype=np.int64),
    )
    return dataclasses.replace(trace, detections=detections)


def test_constants() -> None:
    assert (quality.BLOCK_MS, quality.WINDOW_BLOCKS, quality.HELD_BLOCKS) == (1000, 10, 5)
    assert quality.REPORT_DELAY_MS == 500
    assert (quality.MIN_DETECTIONS, quality.MAX_DETECTIONS) == (4, 34)
    assert quality.BACKGROUND_WEIGHT == 16.0
    assert quality.USABLE_THRESHOLD == 0.5


@pytest.mark.parametrize(
    ("fs", "expected"),
    [
        (250.0, (250, 2500, 1250, 125, 38)),
        (360.0, (360, 3600, 1800, 180, 54)),
        (300.4, (300, 3000, 1500, 150, 45)),
        (255.5, (256, 2560, 1280, 127, 38)),
    ],
)
def test_quality_samples(fs: float, expected: tuple[int, int, int, int, int]) -> None:
    p = quality_samples(fs)
    assert (p.block, p.window, p.held, p.report_delay, p.zone) == expected
    assert p.zone < p.block


@pytest.mark.parametrize("fs", [124.9, 1000.1, float("nan"), float("inf")])
def test_quality_samples_checks_fs(fs: float) -> None:
    with pytest.raises(InvalidInputError):
        quality_samples(fs)


def test_run_lengths() -> None:
    x = np.array([1.0, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0, -0.0, 0.0])
    assert quality._run_lengths(x).tolist() == [1, 2, 3, 1, 2, 1, 2, 1, 2]
    assert quality._run_lengths(np.array([5.0])).tolist() == [1]


@pytest.mark.parametrize("fs", FS_VALUES)
@pytest.mark.parametrize("bpm", [30, 75, 200])
def test_clean_windows_are_usable(synthetic_ecg: Any, fs: float, bpm: int) -> None:
    x, _ = synthetic_ecg(fs, bpm, "clean", duration_s=60.0)
    w = quality_windows(x, fs, 50)
    late = w.first >= int(2 * fs)
    assert late.sum() > 40
    assert w.usable[late].all()
    assert (w.index[late] >= 0.5).all()
    assert (w.index <= 1.0).all()
    assert not w.held.any()


@pytest.mark.parametrize("fs", FS_VALUES)
def test_clean_with_interference_is_usable(synthetic_ecg: Any, fs: float) -> None:
    x, _ = synthetic_ecg(fs, 75, "bw-mains50", duration_s=60.0)
    w = quality_windows(x, fs, 50)
    assert w.usable[w.first >= int(2 * fs)].all()


@pytest.mark.parametrize("fs", FS_VALUES)
@pytest.mark.parametrize("level", [0.0, 1.0])
def test_flat_input_gives_index_zero(fs: float, level: float) -> None:
    w = quality_windows(np.full(int(60 * fs), level), fs, 50)
    assert w.index.size > 40
    assert (w.index == 0.0).all()
    assert not w.usable.any()
    assert (w.n_detections == 0).all()
    assert np.isnan(w.signal_power).all()
    assert np.isnan(w.background_power).all()
    assert w.held.all()


@pytest.mark.parametrize("fs", FS_VALUES)
@pytest.mark.parametrize("rms", [0.01, 0.1, 1.0])
def test_white_noise_is_not_usable(fs: float, rms: float) -> None:
    x = rms * np.random.default_rng(7).standard_normal(int(60 * fs))
    w = quality_windows(x, fs, 50)
    assert not w.usable.any()
    assert (w.index < 0.3).all()


@pytest.mark.parametrize("fs", FS_VALUES)
def test_held_ecg_is_not_usable_while_five_seconds_lie_in_the_window(
    synthetic_ecg: Any, fs: float
) -> None:
    x, _ = synthetic_ecg(fs, 75, "clean", duration_s=60.0)
    x = x.copy()
    x[int(20 * fs) : int(40 * fs)] = 2.0
    w = quality_windows(x, fs, 50)
    starts = w.first / fs
    expected_held = (starts >= 15.0) & (starts <= 35.0)
    assert np.array_equal(w.held, expected_held)
    assert not w.usable[expected_held].any()
    assert (w.index[expected_held] == 0.0).all()
    assert w.usable[(starts >= 2.0) & (starts < 15.0)].all()


@pytest.mark.parametrize("fs", FS_VALUES)
@pytest.mark.parametrize("length_delta", [0, -1])
@pytest.mark.parametrize("start_offset", [0, 1, 777, 1801])
def test_held_gate_at_exactly_five_blocks(
    synthetic_ecg: Any, fs: float, length_delta: int, start_offset: int
) -> None:
    base, _ = synthetic_ecg(fs, 75, "clean", duration_s=40.0)
    x = _noisy(base)
    h = int(fs)
    run = 5 * h + length_delta
    a = 12 * h + start_offset
    x[a : a + run] = 0.5
    w = assess_quality(x, _trace_of(base, fs))
    overlap = np.minimum(a + run - 1, w.last) - np.maximum(a, w.first) + 1
    assert np.array_equal(w.held, overlap >= 5 * h)
    assert w.held.any() == (length_delta == 0)


@pytest.mark.parametrize("fs", FS_VALUES)
def test_held_gate_ignores_runs_of_five_blocks_minus_one_in_pieces(
    synthetic_ecg: Any, fs: float
) -> None:
    base, _ = synthetic_ecg(fs, 75, "clean", duration_s=30.0)
    x = _noisy(base)
    h = int(fs)
    x[5 * h : 5 * h + 3 * h] = 1.0
    x[5 * h + 3 * h] = 3.0
    x[5 * h + 3 * h + 1 : 5 * h + 3 * h + 1 + 3 * h] = 1.0
    assert not assess_quality(x, _trace_of(base, fs)).held.any()


@pytest.mark.parametrize("fs", FS_VALUES)
@pytest.mark.parametrize("count", [3, 4, 34, 35])
def test_detection_count_limits(synthetic_ecg: Any, fs: float, count: int) -> None:
    base, _ = synthetic_ecg(fs, 75, "clean", duration_s=20.0)
    trace = _trace_of(base, fs)
    spacing = quality_samples(fs).window // 40
    fake = _fake(trace, [100 + spacing * i for i in range(count)])
    w = assess_quality(_noisy(base), fake)
    assert w.n_detections[0] == count
    assert (w.index[0] > 0.0) == (4 <= count <= 34)
    assert np.isfinite(w.signal_power[0])


@pytest.mark.parametrize("fs", FS_VALUES)
def test_index_of_hand_built_powers(synthetic_ecg: Any, fs: float) -> None:
    base, _ = synthetic_ecg(fs, 75, "clean", duration_s=20.0)
    trace = _trace_of(base, fs)
    p = quality_samples(fs)
    indices = [200 + 300 * i for i in range(5)]
    for background, usable in [(0.25, True), (0.2501, False), (0.0, True)]:
        derivative = np.full(trace.signals.derivative_mv_per_s.size, math.sqrt(background))
        for m in indices:
            derivative[m - p.zone + 1 : m + 1] = 2.0
        fake = dataclasses.replace(
            _fake(trace, indices),
            signals=dataclasses.replace(trace.signals, derivative_mv_per_s=derivative),
        )
        w = assess_quality(_noisy(base), fake)
        assert w.signal_power[0] == pytest.approx(4.0, rel=1e-12)
        assert w.background_power[0] == pytest.approx(background, rel=1e-9, abs=1e-30)
        expected = 4.0 / (4.0 + 16.0 * w.background_power[0])
        assert w.index[0] == pytest.approx(expected, rel=1e-12)
        assert bool(w.usable[0]) is usable


def test_index_is_zero_when_all_power_is_zero(synthetic_ecg: Any) -> None:
    base, _ = synthetic_ecg(360.0, 75, "clean", duration_s=20.0)
    trace = _trace_of(base, 360.0)
    fake = dataclasses.replace(
        _fake(trace, [200 + 300 * i for i in range(5)]),
        signals=dataclasses.replace(trace.signals, derivative_mv_per_s=np.zeros(base.size)),
    )
    w = assess_quality(_noisy(base), fake)
    assert w.index[0] == 0.0
    assert w.signal_power[0] == 0.0


def test_signal_power_is_the_mean_of_the_zones(synthetic_ecg: Any) -> None:
    fs = 360.0
    base, _ = synthetic_ecg(fs, 75, "clean", duration_s=20.0)
    trace = _trace_of(base, fs)
    p = quality_samples(fs)
    indices = [300, 900, 1500, 2100, 2700]
    w = assess_quality(_noisy(base), _fake(trace, indices))
    s = trace.signals.derivative_mv_per_s**2
    mask = np.zeros(s.size, dtype=bool)
    for m in indices:
        mask[m - p.zone + 1 : m + 1] = True
    assert w.signal_power[0] == pytest.approx(s[:3600][mask[:3600]].mean(), rel=1e-12)
    assert w.background_power[0] == pytest.approx(s[:3600][~mask[:3600]].mean(), rel=1e-12)


def test_zone_across_a_block_boundary_counts_in_each_window_for_its_part() -> None:
    fs = 360.0
    x = _noisy(np.zeros(8000))
    base_trace = _trace_of(x, fs)
    p = quality_samples(fs)
    derivative = np.zeros(8000)
    derivative[p.block - 43 : p.block + 11] = 3.0  # the zone of a peak at block + 10
    fake = dataclasses.replace(
        _fake(base_trace, [p.block + 10]),
        signals=dataclasses.replace(base_trace.signals, derivative_mv_per_s=derivative),
    )
    w = assess_quality(x, fake)
    # window 0 holds the whole zone (54 samples), window 1 only the 11 samples from block 1
    assert w.signal_power[0] == pytest.approx(9.0)
    assert w.signal_power[1] == pytest.approx(9.0)
    # window 1 has 11 zone samples at 9 and nothing else: the background is zero
    assert w.background_power[1] == 0.0
    assert w.background_power[0] == 0.0
    # window 2 starts after the detection: no zone
    assert np.isnan(w.signal_power[2])


def test_late_detection_is_left_out(synthetic_ecg: Any) -> None:
    fs = 360.0
    base, _ = synthetic_ecg(fs, 75, "clean", duration_s=20.0)
    trace = _trace_of(base, fs)
    p = quality_samples(fs)
    on_time = [300, 900, 1500, 2100]
    late = 2700
    window_report = p.window - 1 + p.report_delay
    w_late = assess_quality(
        _noisy(base),
        _fake(trace, [*on_time, late], [*on_time, window_report + 1]),
    )
    w_in = assess_quality(
        _noisy(base),
        _fake(trace, [*on_time, late], [*on_time, window_report]),
    )
    w_four = assess_quality(_noisy(base), _fake(trace, on_time))
    assert w_late.n_detections[0] == 4
    assert w_in.n_detections[0] == 5
    assert w_late.signal_power[0] == w_four.signal_power[0]
    assert w_late.background_power[0] == w_four.background_power[0]
    assert w_in.signal_power[0] != w_late.signal_power[0]
    only_three = _fake(trace, on_time[:3] + [late], [*on_time[:3], window_report + 1])
    assert assess_quality(_noisy(base), only_three).index[0] == 0.0


def test_detections_outside_the_window_are_not_counted(synthetic_ecg: Any) -> None:
    fs = 360.0
    base, _ = synthetic_ecg(fs, 75, "clean", duration_s=20.0)
    trace = _trace_of(base, fs)
    w = assess_quality(_noisy(base), _fake(trace, [3599, 3600, 3601, 5000]))
    assert w.n_detections[0] == 1
    assert w.n_detections[1] == 3  # window 1 is 360 to 3959


@pytest.mark.parametrize("fs", [250.0, 360.0, 300.4, 255.5, 125.0, 1000.0])
def test_window_timing(synthetic_ecg: Any, fs: float) -> None:
    x = _noisy(np.zeros(int(round(40 * fs))))
    n = x.size
    p = quality_samples(fs)
    w = quality_windows(x, fs, 50)
    k = np.arange(w.first.size)
    assert np.array_equal(w.first, k * p.block)
    assert np.array_equal(w.last, w.first + p.window - 1)
    assert np.array_equal(w.reported_at, w.last + p.report_delay)
    assert w.reported_at[-1] <= n - 1 < w.reported_at[-1] + p.block
    assert p.report_delay / fs <= 0.5 < (p.report_delay + 1) / fs
    assert w.first.dtype == np.int64
    if float(fs).is_integer():
        assert p.window == 10 * int(fs)
        assert ((w.last - w.first + 1) / fs == 10.0).all()


@pytest.mark.parametrize("fs", [250.0, 360.0])
def test_short_streams(fs: float) -> None:
    p = quality_samples(fs)
    n = p.window + p.report_delay
    empty = quality_windows(_noisy(np.zeros(n - 1)), fs, 50)
    assert empty.first.size == 0
    assert empty.index.size == 0
    one = quality_windows(_noisy(np.zeros(n)), fs, 50)
    assert one.first.tolist() == [0]
    assert one.reported_at.tolist() == [n - 1]
    two = quality_windows(_noisy(np.zeros(n + p.block)), fs, 50)
    assert two.first.tolist() == [0, p.block]


def test_pipeline_result_holds_the_same_windows(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75, "bw-mains50", duration_s=30.0)
    result = pipeline.run_pipeline(x, 360.0, 50)
    direct = quality_windows(x, 360.0, 50)
    again = assess_quality(result.input_mv, _trace(result.mains_mv, 360.0))
    for name in (f.name for f in dataclasses.fields(direct)):
        a, b = getattr(result.quality, name), getattr(direct, name)
        assert np.array_equal(a, b, equal_nan=True)
        assert np.array_equal(a, getattr(again, name), equal_nan=True)


def test_assess_quality_checks_its_arguments(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75, "clean", duration_s=20.0)
    trace = _trace_of(x, 360.0)
    with pytest.raises(InvalidInputError, match="detector trace"):
        assess_quality(x[:-1], trace)
    with pytest.raises(InvalidInputError):
        assess_quality(np.full(x.size, np.nan), trace)
    with pytest.raises(InvalidInputError):
        quality_windows(x, 360.0, 55)


def test_input_is_not_modified(synthetic_ecg: Any) -> None:
    x, _ = synthetic_ecg(360.0, 75, "clean", duration_s=20.0)
    before = x.copy()
    quality_windows(x, 360.0, 50)
    assert np.array_equal(x, before)


def test_result_is_frozen() -> None:
    w = quality_windows(_noisy(np.zeros(5000)), 360.0, 50)
    with pytest.raises(dataclasses.FrozenInstanceError):
        w.first = w.last  # type: ignore[misc]
