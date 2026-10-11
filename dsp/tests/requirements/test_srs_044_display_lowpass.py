"""Requirement tests of SRS-044 (item `dsp`): the display low-pass of the reference (RC-019).

SRS-044: the reference provides a display stage applied to the conditioned signal (SRS-019), as
a separate output that does not feed detection, heart rate or signal quality. At 360 Hz and at
250 Hz: gain within +-1 dB of that of the unfiltered signal from 1 Hz to 30 Hz; attenuation of
at least 20 dB at every frequency from 80 Hz to the Nyquist frequency; group delay varying by no
more than 20 ms from 1 Hz to 30 Hz, constant and documented in `architecture.md`; the peak
R-wave amplitude of the synthetic ECG of SRS-006 kept to at least 90%; on that ECG with white
noise in the band from 40 Hz to the Nyquist frequency, the noise RMS in the output at least
6 dB below that of the input. Detections, heart rates and signal quality windows are identical
with the stage on and off. The export of the display output in the golden vectors is verified in
`test_srs_015_golden_vector_format.py` and `test_srs_015_golden_vector_files.py`.

The test cases follow architecture section 16.8 (the seven properties) at 360 Hz and 250 Hz,
through `run_pipeline` (`display_mv` is the display output, `mains_mv` the conditioned signal),
mains setting 50 Hz unless stated; the public interfaces of section 16.3 (errors, exactness)
are checked at the end. The tests derive from the statement and the documented interface, not
from the implementation: the documented delay is M = 11 samples at 360 Hz and 8 at 250 Hz
(section 16.2), the values of the taps are worked out here from the formula of section 16.2.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from functools import cache
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp.display import (
    apply_display_lowpass,
    display_delay_samples,
    display_lowpass,
    display_lowpass_taps,
)
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.pipeline import run_pipeline
from sinus_dsp.synthetic import synthetic_event_set, synthetic_set

RATES = (360, 250)
DOCUMENTED_DELAY = {360: 11, 250: 8}  # samples, architecture section 16.2
GAIN_FREQUENCIES_HZ = (1.0, 5.0, 10.0, 20.0, 30.0)
ATTENUATION_FREQUENCIES_HZ = (80.0, 100.0, 120.0)

FloatArray = npt.NDArray[np.float64]


def _same_float64(a: Any, b: Any) -> bool:
    """Bitwise equality of two float64 arrays."""
    x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return x.shape == y.shape and x.tobytes() == y.tobytes()


def _rms(x: npt.ArrayLike) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def _db(ratio: float) -> float:
    return 20.0 * math.log10(ratio)


def _sine(frequency_hz: float, fs: int, seconds: float = 10.0) -> FloatArray:
    n = np.arange(round(seconds * fs), dtype=np.float64)
    out: FloatArray = np.sin(2.0 * np.pi * frequency_hz * n / fs)
    return out


def _nyquist_signal(fs: int, seconds: float = 10.0) -> FloatArray:
    """cos(pi n) = (-1)^n mV: the signal at the Nyquist frequency (a sine there samples to 0)."""
    n = np.arange(round(seconds * fs), dtype=np.float64)
    out: FloatArray = np.cos(np.pi * n)
    return out


def _gain_db(signal: FloatArray, fs: int) -> float:
    """G = 20 log10(RMS(display second half) / RMS(conditioned second half)), mains 50 Hz."""
    result = run_pipeline(signal, float(fs), 50)
    assert result.display_mv is not None
    half = signal.size // 2
    return _db(_rms(result.display_mv[half:]) / _rms(result.mains_mv[half:]))


# --------------------------------------------------------------------------------------------
# 1, 2: gain from 1 Hz to 30 Hz, attenuation from 80 Hz to the Nyquist frequency
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
@pytest.mark.parametrize("frequency_hz", GAIN_FREQUENCIES_HZ)
def test_gain_from_1_to_30_hz_is_within_1_db(frequency_hz: float, fs: int) -> None:
    """Gain of the display output against the conditioned signal, 1 Hz to 30 Hz.

    Input: x[n] = sin(2 pi f n / fs) mV for f = 1, 5, 10, 20 and 30 Hz, 10 s, through
    `run_pipeline` at 360 Hz and at 250 Hz, mains 50 Hz.
    Expected: G = 20 log10(RMS(display) / RMS(conditioned)) over the second half is within
    +-1 dB.
    """
    gain = _gain_db(_sine(frequency_hz, fs), fs)

    assert abs(gain) <= 1.0, f"{frequency_hz} Hz at {fs} Hz: {gain:.3f} dB"


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
@pytest.mark.parametrize("frequency_hz", ATTENUATION_FREQUENCIES_HZ)
def test_attenuation_from_80_hz_is_at_least_20_db(frequency_hz: float, fs: int) -> None:
    """Attenuation of the display output at 80, 100 and 120 Hz.

    Input: x[n] = sin(2 pi f n / fs) mV for f = 80, 100 and 120 Hz, 10 s, at 360 Hz and at
    250 Hz (all below the Nyquist frequency of 125 Hz), mains 50 Hz.
    Expected: G over the second half is at most -20 dB.
    """
    gain = _gain_db(_sine(frequency_hz, fs), fs)

    assert gain <= -20.0, f"{frequency_hz} Hz at {fs} Hz: {gain:.3f} dB"


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
def test_attenuation_at_the_nyquist_frequency_is_at_least_20_db(fs: int) -> None:
    """Attenuation at the Nyquist frequency (180 Hz at 360 Hz, 125 Hz at 250 Hz).

    Input: x[n] = cos(pi n) = (-1)^n mV, 10 s (a sine at the Nyquist frequency samples to 0).
    Expected: G over the second half is at most -20 dB.
    """
    gain = _gain_db(_nyquist_signal(fs), fs)

    assert gain <= -20.0, f"Nyquist at {fs} Hz: {gain:.3f} dB"


# --------------------------------------------------------------------------------------------
# 3: gain and attenuation at every frequency, from the taps
# --------------------------------------------------------------------------------------------


def _response_db(taps: FloatArray, frequencies_hz: FloatArray, fs: int) -> FloatArray:
    k = np.arange(taps.size, dtype=np.float64)
    phase = -2j * np.pi * np.outer(frequencies_hz, k) / fs
    magnitude = np.abs(np.exp(phase) @ taps)
    out: FloatArray = 20.0 * np.log10(magnitude)
    return out


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
def test_frequency_response_of_the_taps_on_the_full_grids(fs: int) -> None:
    """Gain in the pass band and attenuation in the stop band at every frequency of a grid.

    Input: the taps of `run_pipeline` (`display_taps`) at 360 Hz and at 250 Hz;
    |H(f)| = |sum_k h[k] exp(-2 pi i f k / fs)| on a 0.25 Hz grid from 1 to 30 Hz and from
    80 Hz to the Nyquist frequency (included).
    Expected: |H| within +-1 dB from 1 to 30 Hz; at most -20 dB from 80 Hz to the Nyquist
    frequency; the taps are 2 M + 1 with M the documented delay (11 at 360 Hz, 8 at 250 Hz).
    """
    taps = run_pipeline(_sine(5.0, fs), float(fs), 50).display_taps
    passband = np.arange(1.0, 30.0 + 1e-9, 0.25)
    stopband = np.arange(80.0, fs / 2 + 1e-9, 0.25)

    assert taps.size == 2 * DOCUMENTED_DELAY[fs] + 1
    assert stopband[-1] == fs / 2
    pass_db = _response_db(taps, passband, fs)
    stop_db = _response_db(taps, stopband, fs)
    assert np.max(np.abs(pass_db)) <= 1.0, f"worst pass-band gain {np.max(np.abs(pass_db)):.3f} dB"
    assert np.max(stop_db) <= -20.0, f"worst stop-band gain {np.max(stop_db):.3f} dB"


# --------------------------------------------------------------------------------------------
# 4: group delay
# --------------------------------------------------------------------------------------------


def _phase(signal: FloatArray, frequency_hz: float, fs: int) -> float:
    """Phase phi of the second half in a sin(wn) + b cos(wn) = R sin(wn + phi) (least squares)."""
    n = np.arange(signal.size, dtype=np.float64)
    half = signal.size // 2
    w = 2.0 * np.pi * frequency_hz * n[half:] / fs
    design = np.column_stack([np.sin(w), np.cos(w)])
    a, b = np.linalg.lstsq(design, signal[half:], rcond=None)[0]
    return float(math.atan2(b, a))


def _display_phase_shift(frequency_hz: float, fs: int) -> float:
    """phi_display - phi_conditioned for a sinusoid of 10 s."""
    x = _sine(frequency_hz, fs)
    result = run_pipeline(x, float(fs), 50)
    assert result.display_mv is not None
    return _phase(result.display_mv, frequency_hz, fs) - _phase(result.mains_mv, frequency_hz, fs)


@cache
def _group_delay_ms(frequency_hz: float, fs: int) -> float:
    """tau(f) = -Delta / (2 pi 1 Hz), Delta the difference of the phase shifts at f +- 0.5 Hz,
    wrapped into (-pi, pi]."""
    delta = _display_phase_shift(frequency_hz + 0.5, fs) - _display_phase_shift(
        frequency_hz - 0.5, fs
    )
    delta = math.pi - ((math.pi - delta) % (2.0 * math.pi))  # wrap into (-pi, pi]
    return -delta / (2.0 * math.pi * 1.0) * 1000.0


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
@pytest.mark.parametrize("frequency_hz", [1.0, 10.0, 20.0, 30.0])
def test_group_delay_is_the_documented_constant(frequency_hz: float, fs: int) -> None:
    """The group delay at 1, 10, 20 and 30 Hz is the constant delay documented (M / fs).

    Input: sinusoids of 10 s at f - 0.5 Hz and f + 0.5 Hz through `run_pipeline`; the phase of
    display and conditioned signal by a least-squares fit over the second half;
    tau = -(difference over 1 Hz of the phase shifts) / 2 pi.
    Expected: tau within 0.01 ms of M / fs (30.556 ms at 360 Hz, 32.000 ms at 250 Hz).
    """
    expected_ms = DOCUMENTED_DELAY[fs] / fs * 1000.0

    assert _group_delay_ms(frequency_hz, fs) == pytest.approx(expected_ms, abs=0.01)


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
def test_group_delay_varies_by_at_most_20_ms(fs: int) -> None:
    """The group delay varies by no more than 20 ms from 1 Hz to 30 Hz.

    Input: the delays at 1, 10, 20 and 30 Hz as in the test above.
    Expected: max tau - min tau <= 20 ms.
    """
    delays = [_group_delay_ms(f, fs) for f in (1.0, 10.0, 20.0, 30.0)]

    assert max(delays) - min(delays) <= 20.0, delays


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
def test_delay_is_documented_in_whole_samples(fs: int) -> None:
    """The delay is a whole number of samples, the same in the result and in the function.

    Input: `display_delay_samples(fs)` and `run_pipeline(...).display_delay_samples`.
    Expected: 11 samples (30.556 ms) at 360 Hz, 8 samples (32.0 ms) at 250 Hz, as in
    architecture section 16.2; the two values are equal and are `int`.
    """
    result = run_pipeline(_sine(5.0, fs), float(fs), 50)

    assert display_delay_samples(float(fs)) == DOCUMENTED_DELAY[fs]
    assert result.display_delay_samples == DOCUMENTED_DELAY[fs]
    assert type(display_delay_samples(float(fs))) is int


# --------------------------------------------------------------------------------------------
# 5: R-wave peak
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
@pytest.mark.parametrize("heart_rate_bpm", [30, 75, 200])
def test_r_wave_peak_is_kept_to_90_percent(
    heart_rate_bpm: int, fs: int, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """The peak R-wave amplitude of the display output is at least 90% of the conditioned one.

    Input: the synthetic ECG of SRS-006 (no interference), 30 s, at 30, 75 and 200 bpm, at 360
    and 250 Hz, mains 50 Hz; for each true R centre r with 2 fs <= r and r + M + w < n, with
    M the delay and w = floor(50 fs / 1000): max(display[r+M-w .. r+M+w]) divided by
    max(conditioned[r-w .. r+w]) (the display value given with sample k belongs to index
    k - M; the peak of the conditioned signal is used, not the detector's fiducial).
    Expected: at least one R wave measured, every ratio >= 0.90.
    """
    ecg = make_synthetic_ecg(fs, heart_rate_bpm)
    result = run_pipeline(ecg.signal_mv, float(fs), 50)
    display = result.display_mv
    assert display is not None
    m = DOCUMENTED_DELAY[fs]
    w = math.floor(50 * fs / 1000)
    n = ecg.signal_mv.size
    ratios = [
        float(np.max(display[r + m - w : r + m + w + 1]))
        / float(np.max(result.mains_mv[r - w : r + w + 1]))
        for r in ecg.qrs_samples.tolist()
        if 2 * fs <= r and r + m + w < n
    ]

    assert ratios, "no R wave measured"
    assert min(ratios) >= 0.90, f"lowest ratio {min(ratios):.4f} over {len(ratios)} R waves"


# --------------------------------------------------------------------------------------------
# 6: noise
# --------------------------------------------------------------------------------------------


def _band_noise(n: int, fs: int, seed: int, rms_mv: float = 0.1) -> FloatArray:
    """White Gaussian noise with every DFT component below 40 Hz removed, scaled to ``rms_mv``."""
    white = np.random.default_rng(seed).standard_normal(n)
    spectrum = np.fft.rfft(white)
    spectrum[np.fft.rfftfreq(n, 1.0 / fs) < 40.0] = 0.0
    band = np.fft.irfft(spectrum, n)
    out: FloatArray = band * (rms_mv / _rms(band))
    return out


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_noise_above_40_hz_is_reduced_by_6_db(
    seed: int, fs: int, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """The noise RMS in the output is at least 6 dB below that of the input.

    Input: the synthetic ECG at 75 bpm, 60 s, and the same plus white Gaussian noise of
    0.1 mV RMS band-limited to 40 Hz to the Nyquist frequency (fixed seeds 1, 2, 3); e_in =
    conditioned(ECG + noise) - conditioned(ECG), e_out = display(ECG + noise) - display(ECG),
    from sample 2 fs to the end.
    Expected: 20 log10(RMS(e_out) / RMS(e_in)) <= -6 dB.
    """
    n = 60 * fs
    ecg = make_synthetic_ecg(fs, 75, n_samples=n).signal_mv
    noisy = ecg + _band_noise(n, fs, seed)
    clean = run_pipeline(ecg, float(fs), 50)
    dirty = run_pipeline(noisy, float(fs), 50)
    assert clean.display_mv is not None and dirty.display_mv is not None
    start = 2 * fs
    e_in = (dirty.mains_mv - clean.mains_mv)[start:]
    e_out = (dirty.display_mv - clean.display_mv)[start:]

    reduction = _db(_rms(e_out) / _rms(e_in))
    assert reduction <= -6.0, f"{reduction:.2f} dB"


# --------------------------------------------------------------------------------------------
# 7: detection, heart rate and signal quality unchanged
# --------------------------------------------------------------------------------------------


def _snapshot(value: Any) -> Any:
    """A comparable, bit-exact image of a result: arrays by bytes, floats by their hex form."""
    if isinstance(value, np.ndarray):
        return ("array", str(value.dtype), value.shape, value.tobytes())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return tuple((f.name, _snapshot(getattr(value, f.name))) for f in dataclasses.fields(value))
    if isinstance(value, (list, tuple)):
        return tuple(_snapshot(v) for v in value)
    if isinstance(value, float):
        return ("float", value.hex())
    return value


def _differences_with_the_stage_off(signal: FloatArray, fs: float, mains: int) -> list[str]:
    on = run_pipeline(signal, fs, mains)
    off = run_pipeline(signal, fs, mains, display=False)
    problems = []
    if on.display_mv is None or on.display_mv.shape != signal.shape:
        problems.append("display=True gives no display output of the length of the input")
    if off.display_mv is not None:
        problems.append("display=False gives a display output")
    for field in dataclasses.fields(on):
        if field.name == "display_mv":
            continue
        if _snapshot(getattr(on, field.name)) != _snapshot(getattr(off, field.name)):
            problems.append(f"field {field.name} differs")
    return problems


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("mains", [50, 60])
@pytest.mark.parametrize("heart_rate_bpm", [30, 40, 75, 180, 200])
@pytest.mark.parametrize("fs", RATES)
def test_detection_heart_rate_and_quality_are_identical_with_the_stage_off(
    fs: int, heart_rate_bpm: int, mains: int, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """The display stage changes no detection, heart rate or quality window.

    Input: the synthetic ECG at 30, 40, 75, 180 and 200 bpm, 30 s, at 360 and 250 Hz, with the
    baseline wander and the interference at 50 Hz (mains setting 50) or at 60 Hz (setting 60);
    `run_pipeline(x, fs, mains)` against `run_pipeline(x, fs, mains, display=False)`.
    Expected: every field of the two results other than `display_mv` is identical (floats bit
    for bit, arrays by their bytes: coefficients, input, `baseline_mv`, `mains_mv`, `beats`,
    `detections`, `heart_rate`, `quality`, the display delay and taps); with the stage on,
    `display_mv` is as long as the input; with it off it is None.
    """
    ecg = make_synthetic_ecg(fs, heart_rate_bpm, mains_hz=mains)

    assert _differences_with_the_stage_off(ecg.signal_mv, float(fs), mains) == []


GOLDEN_INPUTS = [(e.input_id, e) for e in (*synthetic_set(), *synthetic_event_set())]


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize(("input_id", "ecg"), GOLDEN_INPUTS, ids=[i for i, _ in GOLDEN_INPUTS])
def test_golden_vector_inputs_are_identical_with_the_stage_off(input_id: str, ecg: Any) -> None:
    """The same, on the synthetic inputs of the golden vectors (SRS-015, SRS-033).

    Input: each of the 18 synthetic ECGs and 8 event inputs of the golden-vector set, at its
    own sampling frequency and mains setting, with the stage on and off.
    Expected: as in the test above.
    """
    assert _differences_with_the_stage_off(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz) == [], input_id


# --------------------------------------------------------------------------------------------
# Public interfaces of architecture section 16.3: results and error behaviour
# --------------------------------------------------------------------------------------------

INVALID_FS: list[Any] = [
    float("nan"),
    float("inf"),
    float("-inf"),
    0.0,
    -360.0,
    124.9,
    124.999999,
    1000.001,
    1000.5,
    1e9,
    True,
    None,
    "360",
    [360.0],
]
VALID_FS_M = [
    (125.0, 4),
    (137.5, 4),
    (250.0, 8),
    (333.3, 10),
    (349.99, 10),
    (350.0, 11),
    (360.0, 11),
    (500.0, 15),
    (999.0, 30),
    (1000.0, 30),
]


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize(("fs", "m"), VALID_FS_M)
def test_delay_is_the_half_length_of_30_ms_rounded(fs: float, m: int) -> None:
    """M = floor(30 fs / 1000 + 0.5) and 2 M + 1 taps, over the whole range of rates.

    Input: fs = 125 and 1000 Hz (the limits), 250, 333.3, 349.99, 350 (the rounding point),
    360, 500 and 999 Hz and others.
    Expected: `display_delay_samples(fs)` is M; `display_lowpass_taps(fs)` is a float64 array of
    2 M + 1 taps that is symmetric and sums to 1.
    """
    taps = display_lowpass_taps(fs)

    assert display_delay_samples(fs) == m
    assert taps.dtype == np.float64 and taps.ndim == 1 and taps.size == 2 * m + 1
    assert np.allclose(taps, taps[::-1], rtol=0.0, atol=1e-15)
    assert abs(float(np.sum(taps)) - 1.0) < 1e-12


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", [np.float64(360.0), np.int64(360), 360])
def test_delay_accepts_any_real_number_type(fs: Any) -> None:
    """A real number of any numeric type is a valid sampling frequency.

    Input: 360 as numpy float64, numpy int64 and Python int.
    Expected: M = 11 and 23 taps.
    """
    assert display_delay_samples(fs) == 11
    assert display_lowpass_taps(fs).size == 23


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", INVALID_FS, ids=repr)
def test_invalid_sampling_frequency_is_rejected(fs: Any) -> None:
    """A sampling frequency that is not a real number, not finite or outside 125 to 1000 Hz is
    rejected by every function that takes one.

    Input: NaN, +-inf, 0, -360, 124.9, 124.999999, 1000.001, 1000.5, 1e9, True, None, "360" and a
    list, given to `display_delay_samples`, `display_lowpass_taps` and `display_lowpass`.
    Expected: `InvalidInputError`.
    """
    with pytest.raises(InvalidInputError):
        display_delay_samples(fs)
    with pytest.raises(InvalidInputError):
        display_lowpass_taps(fs)
    with pytest.raises(InvalidInputError):
        display_lowpass(np.zeros(100), fs)


def _own_taps(fs: float) -> FloatArray:
    """The taps by the expressions of architecture section 16.2, in the order written."""
    m = math.floor(30.0 * fs / 1000.0 + 0.5)
    n_taps = 2 * m + 1
    raw = []
    for k in range(n_taps):
        j = k - m
        ideal = (
            2.0 * 50.0 / fs if j == 0 else math.sin(2.0 * math.pi * 50.0 * j / fs) / (math.pi * j)
        )
        window = 0.54 - 0.46 * math.cos(2.0 * math.pi * k / (n_taps - 1))
        raw.append(window * ideal)
    total = raw[0]
    for value in raw[1:]:
        total = total + value
    return np.array([value / total for value in raw], dtype=np.float64)


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", [125.0, 250.0, 333.3, 360.0, 1000.0])
def test_taps_are_the_windowed_sinc_of_the_design(fs: float) -> None:
    """The taps are the Hamming-windowed sinc of cut-off 50 Hz, normalised to a sum of 1.

    Input: `display_lowpass_taps(fs)` against the formula of architecture section 16.2 written
    out in the test (math.sin, math.cos, the sum added in index order, a division by the sum).
    Expected: bit-for-bit equal.
    """
    assert _same_float64(display_lowpass_taps(fs), _own_taps(fs))


@pytest.mark.requirement("SRS-044")
def test_taps_are_a_new_array_at_every_call() -> None:
    """The taps are a new array: changing one does not change what the next call returns.

    Input: `display_lowpass_taps(360.0)` modified in place, then called again.
    Expected: the second result equals the first as returned, and is another object.
    """
    first = display_lowpass_taps(360.0)
    original = first.copy()
    first[:] = 7.0
    second = display_lowpass_taps(360.0)

    assert second is not first
    assert _same_float64(second, original)


def _reference_filter(taps: FloatArray, x: FloatArray) -> FloatArray:
    """y[n] = (...((h[0] x[n] + h[1] x[n-1]) + h[2] x[n-2]) + ...) + h[N-1] x[n-N+1], with
    x[i] = x[0] for i < 0, in Python floats (one binary64 operation at a time)."""
    h = [float(v) for v in taps]
    xs = [float(v) for v in x]
    out = []
    for n in range(len(xs)):
        acc = h[0] * xs[n]
        for k in range(1, len(h)):
            acc = acc + h[k] * xs[max(n - k, 0)]
        out.append(acc)
    return np.array(out, dtype=np.float64)


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", [250.0, 360.0])
def test_filtering_follows_the_written_order_of_operations(fs: float) -> None:
    """`apply_display_lowpass` is the sum of section 16.2 in the written order, bit for bit.

    Input: 400 deterministic values (seeded Gaussian, 0.5 mV scale) with a nonzero first
    sample, filtered with the taps of `display_lowpass_taps(fs)` and, in the test, by a loop in
    Python floats over the taps in index order, the history before the first sample holding
    the first sample.
    Expected: bit-for-bit equal; `display_lowpass(x, fs)` equals both.
    """
    x = 0.5 * np.random.default_rng(7).standard_normal(400) + 0.3
    taps = display_lowpass_taps(fs)

    expected = _reference_filter(taps, x)

    assert _same_float64(apply_display_lowpass(taps, x), expected)
    assert _same_float64(display_lowpass(x, fs), expected)


@pytest.mark.requirement("SRS-044")
def test_impulse_response_is_the_taps() -> None:
    """The filter is causal and its impulse response is the taps.

    Input: 60 samples that are 0 except a 1 at sample 5, filtered with the taps at 360 Hz (23
    taps).
    Expected: output samples 0 to 4 are 0; samples 5 + k hold h[k] exactly, k = 0 .. 22; the
    rest are 0.
    """
    taps = display_lowpass_taps(360.0)
    x = np.zeros(60)
    x[5] = 1.0

    y = apply_display_lowpass(taps, x)

    assert np.all(y[:5] == 0.0)
    assert _same_float64(y[5 : 5 + taps.size], taps)
    assert np.all(y[5 + taps.size :] == 0.0)


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("level", [0.0, 1.0, -2.5, 29.75, -1000.0])
def test_constant_input_gives_the_same_constant(level: float) -> None:
    """A constant input is steady-state from the first sample (the history holds x[0]).

    Input: 100 samples at a constant level, 0 to -1000 mV.
    Expected: every output sample equals the level to within 1e-12 mV.
    """
    y = display_lowpass(np.full(100, level), 360.0)

    assert np.max(np.abs(y - level)) <= 1e-12


@pytest.mark.requirement("SRS-044")
def test_display_lowpass_takes_short_and_large_signals_and_lists() -> None:
    """`display_lowpass` has no 10 s minimum and no 1000 mV bound, and takes any array-like.

    Input: a list of 5 values; one value of 1e6 mV among 50; a single sample.
    Expected: no error; the output is a float64 array as long as the input; for a list, equal
    to the result for the same values as an array.
    """
    values = [0.5, -0.25, 1.0, 0.0, 2.0]

    assert _same_float64(display_lowpass(values, 360.0), display_lowpass(np.array(values), 360.0))
    large = np.zeros(50)
    large[10] = 1e6
    out = display_lowpass(large, 360.0)
    assert out.dtype == np.float64 and out.shape == large.shape
    one = display_lowpass([3.0], 250.0)
    assert one.shape == (1,) and abs(float(one[0]) - 3.0) <= 1e-12


BAD_SIGNALS: list[tuple[str, Any]] = [
    ("empty", np.array([])),
    ("two-dimensional", np.zeros((10, 2))),
    ("nan", np.array([0.0, np.nan, 1.0])),
    ("inf", np.array([0.0, 1.0, np.inf])),
    ("minus-inf", np.array([-np.inf, 1.0, 1.0])),
    ("scalar", np.float64(1.0)),
]


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize(("name", "signal"), BAD_SIGNALS, ids=[n for n, _ in BAD_SIGNALS])
def test_invalid_signal_is_rejected(name: str, signal: Any) -> None:
    """A signal that is empty, not one-dimensional or not finite is rejected.

    Input: an empty array, a 10 x 2 array, a scalar, NaN, +inf and -inf among valid samples,
    given to `display_lowpass` and, with valid taps, to `apply_display_lowpass`.
    Expected: `InvalidInputError`.
    """
    with pytest.raises(InvalidInputError):
        display_lowpass(signal, 360.0)
    with pytest.raises(InvalidInputError):
        apply_display_lowpass(display_lowpass_taps(360.0), signal)


BAD_TAPS: list[tuple[str, Any]] = [
    ("empty", np.array([])),
    ("even", np.array([0.25, 0.25, 0.25, 0.25])),
    ("two-dimensional", np.full((3, 3), 0.1)),
    ("nan", np.array([0.25, np.nan, 0.25])),
    ("inf", np.array([0.25, 0.5, np.inf])),
]


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize(("name", "taps"), BAD_TAPS, ids=[n for n, _ in BAD_TAPS])
def test_invalid_taps_are_rejected(name: str, taps: Any) -> None:
    """Taps that are not one-dimensional, not of odd length or not finite are rejected.

    Input: empty taps, 4 taps, a 3 x 3 array, NaN and +inf among 3 taps, with a valid signal.
    Expected: `InvalidInputError`.
    """
    with pytest.raises(InvalidInputError):
        apply_display_lowpass(taps, np.zeros(20))


@pytest.mark.requirement("SRS-044")
def test_arguments_are_not_modified_and_the_output_is_new() -> None:
    """`apply_display_lowpass` and `display_lowpass` leave their arguments alone.

    Input: taps and a signal of 100 values, filtered by both functions.
    Expected: the taps and the signal are unchanged afterwards (bytes); each output is a new
    array as long as the input and shares no memory with either argument.
    """
    taps = display_lowpass_taps(250.0)
    x = np.random.default_rng(3).standard_normal(100)
    taps_before, x_before = taps.tobytes(), x.tobytes()

    for y in (apply_display_lowpass(taps, x), display_lowpass(x, 250.0)):
        assert y.shape == x.shape and y.dtype == np.float64
        assert not np.shares_memory(y, x) and not np.shares_memory(y, taps)
    assert taps.tobytes() == taps_before and x.tobytes() == x_before


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("fs", RATES)
def test_pipeline_display_output_is_the_stage_applied_to_the_conditioned_signal(
    fs: int, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """`run_pipeline` gives the display output of the mains-stage output, with its taps.

    Input: the synthetic ECG at 75 bpm, 30 s, mains interference at 50 Hz, at 360 and 250 Hz.
    Expected: `display_delay_samples` and `display_taps` equal those of the functions of the
    module; `display_mv` equals bit for bit `display_lowpass(mains_mv, fs)` and is as long as
    the input; its first sample is 0.0 (the mains stage starts at 0.0, section 16.2); the
    display output is not the input (it differs from `mains_mv`).
    """
    ecg = make_synthetic_ecg(fs, 75, mains_hz=50)

    result = run_pipeline(ecg.signal_mv, float(fs), 50)

    assert result.display_mv is not None
    assert result.display_delay_samples == display_delay_samples(float(fs))
    assert _same_float64(result.display_taps, display_lowpass_taps(float(fs)))
    assert result.display_mv.shape == ecg.signal_mv.shape
    assert _same_float64(result.display_mv, display_lowpass(result.mains_mv, float(fs)))
    assert result.display_mv[0] == 0.0
    assert not np.array_equal(result.display_mv, result.mains_mv)


@pytest.mark.requirement("SRS-044")
def test_display_off_gives_no_output_but_keeps_the_configuration(
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """With `display=False` there is no display output; the delay and taps are still given.

    Input: `run_pipeline(x, 360.0, 50, display=False)` on 30 s of synthetic ECG.
    Expected: `display_mv` is None; `display_delay_samples` is 11 and `display_taps` the 23
    taps of `display_lowpass_taps(360.0)`; the default (no argument) is the stage on.
    """
    x = make_synthetic_ecg(360, 75).signal_mv

    off = run_pipeline(x, 360.0, 50, display=False)
    default = run_pipeline(x, 360.0, 50)

    assert off.display_mv is None
    assert off.display_delay_samples == 11
    assert _same_float64(off.display_taps, display_lowpass_taps(360.0))
    assert default.display_mv is not None


@pytest.mark.requirement("SRS-044")
@pytest.mark.parametrize("display", [1, 0, None, "True", 1.0, [True]], ids=repr)
def test_display_argument_must_be_a_bool(
    display: Any, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """The `display` argument of `run_pipeline` must be a `bool`.

    Input: 1, 0, None, "True", 1.0 and a list, with a valid signal.
    Expected: `InvalidInputError`.
    """
    x = make_synthetic_ecg(360, 75).signal_mv

    with pytest.raises(InvalidInputError):
        run_pipeline(x, 360.0, 50, display=display)


@pytest.mark.requirement("SRS-044")
def test_display_argument_is_keyword_only(make_synthetic_ecg: Callable[..., Any]) -> None:
    """`display` can only be given by keyword.

    Input: a fifth positional argument to `run_pipeline`.
    Expected: `TypeError`.
    """
    x = make_synthetic_ecg(360, 75).signal_mv

    with pytest.raises(TypeError):
        run_pipeline(x, 360.0, 50, False)  # type: ignore[misc]


@pytest.mark.requirement("SRS-044")
def test_pipeline_input_checks_are_unchanged_with_the_stage(
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """The checks of the pipeline input still apply with the stage on or off (SRS-003).

    Input: 9.99 s of ECG, and 30 s with one value of 1000.5 mV, with `display` True and False.
    Expected: `InvalidInputError`.
    """
    short = make_synthetic_ecg(360, 75, n_samples=3596).signal_mv
    loud = make_synthetic_ecg(360, 75).signal_mv.copy()
    loud[100] = 1000.5

    for display in (True, False):
        with pytest.raises(InvalidInputError):
            run_pipeline(short, 360.0, 50, display=display)
        with pytest.raises(InvalidInputError):
            run_pipeline(loud, 360.0, 50, display=display)
