"""Unit tests of ``sinus_dsp.synthetic`` (architecture §7.2, §8.12)."""

import math
from fractions import Fraction
from typing import Any

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError
from sinus_dsp.synthetic import (
    SYNTHETIC_DURATION_S,
    SYNTHETIC_FS_HZ,
    SYNTHETIC_HEART_RATES_BPM,
    SYNTHETIC_VARIANTS,
    SyntheticEcg,
    synthetic_ecg,
    synthetic_set,
)

# (offset in ms, amplitude in mV, width in ms, scaled with sqrt(RR / 1 s)): §7.2.
WAVES = (
    (-200, 0.15, 25, True),
    (-30, -0.10, 10, False),
    (0, 1.00, 10, False),
    (30, -0.20, 10, False),
    (280, 0.30, 45, True),
)

EXPECTED_IDS = [
    f"syn-fs{fs}-hr{hr}-{variant}"
    for fs in ("250", "360")
    for hr in ("040", "075", "180")
    for variant in ("clean", "bw-mains50", "bw-mains60")
]


@pytest.fixture(scope="module")
def the_set() -> tuple[SyntheticEcg, ...]:
    return synthetic_set()


def test_constants() -> None:
    assert SYNTHETIC_DURATION_S == 30
    assert isinstance(SYNTHETIC_DURATION_S, int)
    assert SYNTHETIC_FS_HZ == (250.0, 360.0)
    assert all(isinstance(fs, float) for fs in SYNTHETIC_FS_HZ)
    assert SYNTHETIC_HEART_RATES_BPM == (40, 75, 180)
    assert SYNTHETIC_VARIANTS == ("clean", "bw-mains50", "bw-mains60")


def test_the_set_has_18_inputs_in_order(the_set: tuple[SyntheticEcg, ...]) -> None:
    assert [ecg.input_id for ecg in the_set] == EXPECTED_IDS
    assert [(ecg.fs_hz, ecg.heart_rate_bpm, ecg.variant) for ecg in the_set] == [
        (fs, hr, variant)
        for fs in (250.0, 360.0)
        for hr in (40, 75, 180)
        for variant in ("clean", "bw-mains50", "bw-mains60")
    ]


def test_each_input_of_the_set_equals_a_direct_call(the_set: tuple[SyntheticEcg, ...]) -> None:
    for ecg in the_set:
        direct = synthetic_ecg(ecg.fs_hz, ecg.heart_rate_bpm, ecg.variant)
        assert direct.signal_mv.tobytes() == ecg.signal_mv.tobytes()
        assert direct.r_peaks.tobytes() == ecg.r_peaks.tobytes()
        assert direct.parameters == ecg.parameters


def test_types_and_lengths(the_set: tuple[SyntheticEcg, ...]) -> None:
    for ecg in the_set:
        assert type(ecg.fs_hz) is float
        assert type(ecg.heart_rate_bpm) is int
        assert type(ecg.mains_hz) is int
        assert ecg.signal_mv.dtype == np.float64
        assert ecg.signal_mv.ndim == 1
        assert ecg.signal_mv.flags.c_contiguous
        assert ecg.signal_mv.shape[0] == 30 * int(ecg.fs_hz)
        assert ecg.r_peaks.dtype == np.int64
        assert bool(np.all(np.diff(ecg.r_peaks) > 0))


def test_mains_setting_of_each_variant(the_set: tuple[SyntheticEcg, ...]) -> None:
    expected = {"clean": 50, "bw-mains50": 50, "bw-mains60": 60}
    for ecg in the_set:
        assert ecg.mains_hz == expected[ecg.variant]


@pytest.mark.parametrize(
    ("fs", "hr", "variant", "parameters"),
    [
        (
            360,
            75,
            "bw-mains60",
            "duration_s=30;heart_rate_bpm=75;baseline_wander_hz=0.3;baseline_wander_mv=1.0;"
            "mains_hz=60;mains_mv=0.2",
        ),
        (
            250,
            40,
            "clean",
            "duration_s=30;heart_rate_bpm=40;baseline_wander_hz=0.3;baseline_wander_mv=0.0;"
            "mains_hz=50;mains_mv=0.0",
        ),
        (
            250,
            180,
            "bw-mains50",
            "duration_s=30;heart_rate_bpm=180;baseline_wander_hz=0.3;baseline_wander_mv=1.0;"
            "mains_hz=50;mains_mv=0.2",
        ),
    ],
)
def test_parameters_and_identifier(fs: int, hr: int, variant: str, parameters: str) -> None:
    ecg = synthetic_ecg(fs, hr, variant)
    assert ecg.parameters == parameters
    assert ecg.input_id == f"syn-fs{fs}-hr{hr:03d}-{variant}"


# --- beats: the integer rule of §7.2 against the real-number expressions ---------------------


def _real_number_beats(fs: int, hr: int) -> list[int]:
    """Beats of §7.2 with exact rational arithmetic: 0.5 + k RR <= 29.5, floor((...) fs + 0.5)."""
    rr = Fraction(60, hr)
    half = Fraction(1, 2)
    beats: list[int] = []
    k = 0
    while half + k * rr <= Fraction(59, 2):
        beats.append(math.floor((half + k * rr) * fs + half))
        k += 1
    return beats


@pytest.mark.parametrize("fs", [250, 360])
@pytest.mark.parametrize("hr", [40, 75, 180])
@pytest.mark.parametrize("variant", ["clean", "bw-mains50", "bw-mains60"])
def test_integer_beat_rule_equals_the_real_number_expressions(
    fs: int, hr: int, variant: str
) -> None:
    ecg = synthetic_ecg(fs, hr, variant)
    assert ecg.r_peaks.tolist() == _real_number_beats(fs, hr)


@pytest.mark.parametrize(("hr", "count"), [(40, 20), (75, 37), (180, 88)])
@pytest.mark.parametrize("fs", [250, 360])
def test_beat_counts(fs: int, hr: int, count: int) -> None:
    r_peaks = synthetic_ecg(fs, hr, "clean").r_peaks
    assert r_peaks.shape[0] == count
    assert int(r_peaks[0]) == fs // 2
    # The last beat lies at 29.5 s at most; at 180 bpm it is exactly there.
    assert int(r_peaks[-1]) <= math.floor(29.5 * fs + 0.5)


def test_last_beat_at_180_bpm_is_exactly_at_29_5_s() -> None:
    assert synthetic_ecg(360, 180, "clean").r_peaks[-1] == 10620
    assert synthetic_ecg(250, 180, "clean").r_peaks[-1] == 7375


def test_beats_are_the_same_in_every_variant(the_set: tuple[SyntheticEcg, ...]) -> None:
    for ecg in the_set:
        clean = synthetic_ecg(ecg.fs_hz, ecg.heart_rate_bpm, "clean")
        assert ecg.r_peaks.tolist() == clean.r_peaks.tolist()


# --- waveform -----------------------------------------------------------------------------


def _waveform(fs: int, hr: int, samples: range) -> list[float]:
    """The beats of §7.2 at the given samples, evaluated with ``math``, one sample at a time."""
    rr_s = 60.0 / hr
    scale = math.sqrt(rr_s)
    r_peaks = _real_number_beats(fs, hr)
    values: list[float] = []
    for n in samples:
        t = n / fs
        total = 0.0
        for r_k in r_peaks:
            for offset_ms, amplitude, width_ms, scaled in WAVES:
                factor = scale if scaled else 1.0
                centre = r_k / fs + offset_ms * factor / 1000.0
                sigma = width_ms * factor / 1000.0
                total += amplitude * math.exp(-0.5 * ((t - centre) / sigma) ** 2)
        values.append(total)
    return values


@pytest.mark.parametrize("fs", [250, 360])
@pytest.mark.parametrize("hr", [40, 75, 180])
def test_waveform_within_1e_9_mv_of_the_formulas(fs: int, hr: int) -> None:
    samples = range(0, 30 * fs, 7)
    expected = np.array(_waveform(fs, hr, samples))
    signal = synthetic_ecg(fs, hr, "clean").signal_mv[samples.start : samples.stop : samples.step]
    assert float(np.max(np.abs(signal - expected))) <= 1e-9


@pytest.mark.parametrize("fs", [250, 360])
@pytest.mark.parametrize("hr", [40, 75, 180])
def test_r_wave_is_the_largest_value_near_each_centre(fs: int, hr: int) -> None:
    ecg = synthetic_ecg(fs, hr, "clean")
    for r_k in ecg.r_peaks.tolist():
        window = ecg.signal_mv[max(r_k - 5, 0) : r_k + 6]
        assert float(ecg.signal_mv[r_k]) == float(np.max(window))
        assert 0.9 < float(ecg.signal_mv[r_k]) < 1.1


@pytest.mark.parametrize("fs", [250, 360])
@pytest.mark.parametrize("hr", [40, 75, 180])
@pytest.mark.parametrize(("variant", "mains_hz"), [("bw-mains50", 50), ("bw-mains60", 60)])
def test_interference_is_added_to_the_clean_signal(
    fs: int, hr: int, variant: str, mains_hz: int
) -> None:
    clean = synthetic_ecg(fs, hr, "clean").signal_mv
    noisy = synthetic_ecg(fs, hr, variant).signal_mv
    t = np.arange(30 * fs) / fs
    # The beats first, then the wander, then the mains: exactly the same operations.
    expected = clean + 1.0 * np.sin(2.0 * np.pi * 0.3 * t)
    expected = expected + 0.2 * np.sin(2.0 * np.pi * mains_hz * t)
    assert noisy.tobytes() == expected.tobytes()


def test_clean_signal_has_no_interference() -> None:
    signal = synthetic_ecg(360, 40, "clean").signal_mv
    # Between beats only the Gaussian tails remain: far below the 0.2 mV of mains interference.
    assert float(np.max(np.abs(signal[:20]))) < 1e-6
    assert float(np.min(signal)) > -0.25


def test_generation_is_deterministic() -> None:
    first = synthetic_ecg(250, 75, "bw-mains60")
    second = synthetic_ecg(250, 75, "bw-mains60")
    assert first.signal_mv.tobytes() == second.signal_mv.tobytes()
    assert first.r_peaks.tobytes() == second.r_peaks.tobytes()


# --- arguments ----------------------------------------------------------------------------


@pytest.mark.parametrize("fs", [360, 360.0, np.float64(360.0)])
def test_sampling_frequency_as_int_or_float(fs: Any) -> None:
    ecg = synthetic_ecg(fs, 75, "clean")
    assert type(ecg.fs_hz) is float
    assert ecg.fs_hz == 360.0
    assert ecg.input_id == "syn-fs360-hr075-clean"
    assert ecg.signal_mv.tobytes() == synthetic_ecg(360.0, 75, "clean").signal_mv.tobytes()


@pytest.mark.parametrize("fs", [300, 250.5, 0, -360, "360", None, True, float("nan"), 1000.0])
def test_sampling_frequency_outside_the_set_is_rejected(fs: Any) -> None:
    with pytest.raises(InvalidInputError, match="fs_hz") as caught:
        synthetic_ecg(fs, 75, "clean")
    assert repr(fs) in str(caught.value)


@pytest.mark.parametrize("hr", [60, 75.0, "75", None, True, 0, -75, 300])
def test_heart_rate_outside_the_set_is_rejected(hr: Any) -> None:
    with pytest.raises(InvalidInputError, match="heart_rate_bpm") as caught:
        synthetic_ecg(360, hr, "clean")
    assert repr(hr) in str(caught.value)


@pytest.mark.parametrize("variant", ["CLEAN", "bw-mains", "bw-mains55", "", None, 50, ("clean",)])
def test_variant_outside_the_set_is_rejected(variant: Any) -> None:
    with pytest.raises(InvalidInputError, match="variant") as caught:
        synthetic_ecg(360, 75, variant)
    assert repr(variant) in str(caught.value)


def test_arguments_are_checked_in_order() -> None:
    with pytest.raises(InvalidInputError, match="fs_hz"):
        synthetic_ecg(300, 60, "x")
    with pytest.raises(InvalidInputError, match="heart_rate_bpm"):
        synthetic_ecg(360, 60, "x")
