"""Requirement tests of SRS-022, reference part (software item `dsp`): start-up mark (RC-017).

SRS-022: the reference reports each detection with a mark, start-up if its index lies in a
stretch of 2 s from which detection learns its signal levels (the first 2 s of the stream, or
the 2 s from which it learns them again after a stretch without detected QRS complexes),
reliable otherwise; the mark does not change which detections are reported or their indices.

The documented interface is architecture section 13.3: `pipeline.detect_marked` and
`qrs.trace_qrs` return `Detections` (`indices`, `startup`, `reported_at`, `initialisations`,
...). The `artefact` input of section 13.9 (one beat 20 times larger than the others) is built
here from its table, with the waveform of section 7.2. The C++ part of the requirement is
verified by the requirement tests of `libs/sinus-dsp`, not here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.pipeline import detect_beats, detect_marked, run_pipeline
from sinus_dsp.qrs import detect_qrs, trace_qrs

SAMPLING_FREQUENCIES_HZ = [360, 250]
HEART_RATES_BPM = [40, 75, 180]

# Section 7.2 waveform: (offset ms, amplitude mV, sigma ms, scaled with sqrt(RR / 1 s)).
_WAVES = (
    (-200.0, 0.15, 25.0, True),
    (-30.0, -0.10, 10.0, False),
    (0.0, 1.00, 10.0, False),
    (30.0, -0.20, 10.0, False),
    (280.0, 0.30, 45.0, True),
)


def learning_samples(fs_hz: int) -> int:
    """L = round(2 s * fs): the samples of the 2 s (720 at 360 Hz, 500 at 250 Hz)."""
    return round(2 * fs_hz)


def artefact_input(fs_hz: int) -> np.ndarray:
    """The `artefact` input of section 13.9: 40 s, beats every 800 ms from 500 ms (k = 0..48),
    the beat k = 12 (10100 ms) 20 times larger; R centres at (t_ms * fs + 500) // 1000."""
    n = 40 * fs_hz
    t_s = np.arange(n, dtype=np.float64) / fs_hz
    rr_s = 0.8
    s = rr_s**0.5
    signal = np.zeros(n, dtype=np.float64)
    for k in range(49):
        t_ms = 500 + 800 * k
        r = (t_ms * fs_hz + 500) // 1000
        scale = 20.0 if k == 12 else 1.0
        assert t_ms != 10100 or k == 12
        for offset_ms, amplitude_mv, sigma_ms, scaled in _WAVES:
            factor = s if scaled else 1.0
            centre_s = r / fs_hz + offset_ms * factor / 1000.0
            sigma_s = sigma_ms * factor / 1000.0
            signal += scale * amplitude_mv * np.exp(-((t_s - centre_s) ** 2) / (2.0 * sigma_s**2))
    return signal


def expected_startup(indices: np.ndarray, initialisations: np.ndarray, fs_hz: int) -> np.ndarray:
    """Statement: start-up iff the index lies in the 2 s of an initialisation (learning stretch
    [i - L + 1, i], clipped at 0)."""
    length = learning_samples(fs_hz)
    mask = np.zeros(indices.size, dtype=bool)
    for i in initialisations.tolist():
        mask |= (indices >= max(0, i - length + 1)) & (indices <= i)
    return mask


@pytest.mark.requirement("SRS-022")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", [50, 60])
def test_first_two_seconds_are_startup_and_others_reliable(
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """Detections with index in the first 2 s are start-up, all others reliable.

    Input: the synthetic ECG of SRS-006 (30 s) at 40, 75 and 180 bpm, 360 Hz and 250 Hz,
    mains setting 50 and 60 Hz, through `detect_marked`.
    Expected: `startup[i]` is True exactly when `indices[i] <= L - 1` with L = round(2 fs)
    (719 at 360 Hz, 499 at 250 Hz); at least one detection of each mark exists; `startup` is a
    boolean array with one entry per index.
    """
    signal = make_synthetic_ecg(fs_hz, heart_rate_bpm).signal_mv

    detections = detect_marked(signal, float(fs_hz), mains_hz)

    length = learning_samples(fs_hz)
    assert detections.startup.dtype == np.bool_
    assert detections.startup.shape == detections.indices.shape
    assert np.array_equal(detections.startup, detections.indices <= length - 1)
    assert detections.startup.any(), "no detection in the first 2 s: the case checks nothing"
    assert not detections.startup.all(), "no reliable detection after the first 2 s"


@pytest.mark.requirement("SRS-022")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
@pytest.mark.parametrize("mains_hz", [50, 60])
def test_marks_do_not_change_the_detections(
    fs_hz: int,
    heart_rate_bpm: int,
    mains_hz: int,
    make_synthetic_ecg: Callable[..., Any],
) -> None:
    """The detections of the reference equal those of SRS-006 on the same input.

    Input: the synthetic ECG of SRS-006 (30 s) at 40, 75 and 180 bpm, 360 Hz and 250 Hz,
    mains setting 50 and 60 Hz.
    Expected: `detect_marked(...).indices`, `trace_qrs(<conditioned signal>).detections.indices`,
    `detect_beats` and `detect_qrs` on the conditioned signal return the same indices (int64).
    """
    signal = make_synthetic_ecg(fs_hz, heart_rate_bpm).signal_mv
    conditioned = run_pipeline(signal, float(fs_hz), mains_hz).mains_mv

    marked = detect_marked(signal, float(fs_hz), mains_hz)
    traced = trace_qrs(conditioned, float(fs_hz)).detections

    expected = detect_beats(signal, float(fs_hz), mains_hz)
    assert marked.indices.dtype == np.int64
    assert np.array_equal(marked.indices, expected)
    assert np.array_equal(traced.indices, expected)
    assert np.array_equal(detect_qrs(conditioned, float(fs_hz)), expected)
    assert np.array_equal(traced.startup, marked.startup)


@pytest.mark.requirement("SRS-022")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
@pytest.mark.parametrize("heart_rate_bpm", HEART_RATES_BPM)
def test_trace_marks_follow_the_first_initialisation(
    fs_hz: int, heart_rate_bpm: int, make_synthetic_ecg: Callable[..., Any]
) -> None:
    """On a regular rhythm detection never learns again; the only learning stretch is the first.

    Input: the synthetic ECG of SRS-006 at 40, 75 and 180 bpm, 360 Hz and 250 Hz, through
    `trace_qrs` on the filtered signal.
    Expected: the first initialisation is at sample L - 1; start-up marks equal "index in
    [0, L - 1]"; the mark is also the rule applied to every listed initialisation.
    """
    signal = make_synthetic_ecg(fs_hz, heart_rate_bpm).signal_mv
    conditioned = run_pipeline(signal, float(fs_hz), 50).mains_mv

    detections = trace_qrs(conditioned, float(fs_hz)).detections

    length = learning_samples(fs_hz)
    assert int(detections.initialisations[0]) == length - 1
    assert np.array_equal(
        detections.startup,
        expected_startup(detections.indices, detections.initialisations, fs_hz),
    )


@pytest.mark.requirement("SRS-022")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_artefact_input_makes_detection_learn_its_levels_again(fs_hz: int) -> None:
    """After a beat 20 times larger, detection misses beats and learns its levels again.

    Input: the `artefact` input of section 13.9 (40 s, beats every 800 ms from 500 ms, the
    beat at 10100 ms 20 times larger), 360 Hz and 250 Hz, mains setting 50 Hz.
    Expected: at least two initialisations (the first at L - 1, another after the large
    beat); at least one beat after the large one at 10.1 s is missed before the second
    initialisation (so the input does what the design says); and at least one detection has
    its index in the 2 s from which detection learns again.
    """
    signal = artefact_input(fs_hz)
    assert float(np.max(np.abs(signal))) < 1000.0

    detections = detect_marked(signal, float(fs_hz), 50)

    length = learning_samples(fs_hz)
    inits = detections.initialisations
    assert int(inits[0]) == length - 1
    assert inits.size >= 2, "detection did not learn its levels again"
    relearn = int(inits[1])
    large_beat = (10100 * fs_hz + 500) // 1000
    assert relearn > large_beat

    beats = [(t * fs_hz + 500) // 1000 for t in range(500 + 800 * 13, 500 + 800 * 49, 800)]
    window = int(0.15 * fs_hz)
    missed = [
        r
        for r in beats
        if r < relearn - length and not np.any(np.abs(detections.indices - r) <= window)
    ]
    assert missed, "no beat was missed between the large beat and the re-learning"

    in_stretch = (detections.indices >= relearn - length + 1) & (detections.indices <= relearn)
    assert in_stretch.any(), "no detection in the 2 s from which detection learns again"


@pytest.mark.requirement("SRS-022")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_artefact_input_marks_the_learning_stretches_only(fs_hz: int) -> None:
    """Detections in the first 2 s or in the 2 s of the re-learning are start-up, others reliable.

    Input: the `artefact` input of section 13.9, 360 Hz and 250 Hz, mains setting 50 Hz.
    Expected: `startup[i]` is True exactly when the index lies in [0, L - 1] or in
    [i2 - L + 1, i2] with i2 the second initialisation; the detections in the second stretch
    are start-up (at least one), and there are reliable detections before and after it.
    """
    signal = artefact_input(fs_hz)

    detections = detect_marked(signal, float(fs_hz), 50)

    length = learning_samples(fs_hz)
    relearn = int(detections.initialisations[1])
    first = detections.indices <= length - 1
    second = (detections.indices >= relearn - length + 1) & (detections.indices <= relearn)
    assert np.array_equal(detections.startup, first | second)
    assert (detections.startup & second).any()
    assert (
        ~detections.startup
        & (detections.indices > length - 1)
        & (detections.indices < relearn - length + 1)
    ).any()
    assert (~detections.startup & (detections.indices > relearn)).any()


@pytest.mark.requirement("SRS-022")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_artefact_marks_do_not_change_the_detections(fs_hz: int) -> None:
    """The mark does not change which detections are reported on the `artefact` input.

    Input: the `artefact` input of section 13.9, 360 Hz and 250 Hz, mains setting 50 Hz.
    Expected: `detect_marked(...).indices` equals `detect_beats` on the same input and is
    strictly increasing.
    """
    signal = artefact_input(fs_hz)

    marked = detect_marked(signal, float(fs_hz), 50)

    assert np.array_equal(marked.indices, detect_beats(signal, float(fs_hz), 50))
    assert np.all(np.diff(marked.indices) > 0)
    assert marked.startup.shape == marked.indices.shape


@pytest.mark.requirement("SRS-022")
@pytest.mark.parametrize("fs_hz", SAMPLING_FREQUENCIES_HZ)
def test_flat_input_has_no_detection_and_no_mark(fs_hz: int) -> None:
    """A flat input gives no detection, so no mark.

    Input: a constant signal of 10 s at 360 Hz and 250 Hz.
    Expected: empty `indices` and empty boolean `startup`.
    """
    detections = detect_marked(np.full(10 * fs_hz, 0.5), float(fs_hz), 50)

    assert detections.indices.size == 0
    assert detections.startup.size == 0
    assert detections.startup.dtype == np.bool_
