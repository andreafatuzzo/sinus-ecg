"""Unit tests of the synthetic event inputs (architecture §13.9)."""

from functools import cache
from typing import Any

import numpy as np
import pytest

from sinus_dsp.errors import InvalidInputError
from sinus_dsp.pipeline import PipelineResult, run_pipeline
from sinus_dsp.synthetic import (
    SYNTHETIC_EVENTS,
    SyntheticEcg,
    synthetic_ecg,
    synthetic_event_ecg,
    synthetic_event_set,
)

FS_VALUES = (250.0, 360.0)


@cache
def result_of(fs_hz: float, event: str) -> PipelineResult:
    ecg = synthetic_event_ecg(fs_hz, event)
    return run_pipeline(ecg.signal_mv, ecg.fs_hz, ecg.mains_hz)


def status_changes(result: PipelineResult) -> list[tuple[float, str]]:
    """(second, status) at every change of status of the heart-rate events."""
    changes: list[tuple[float, str]] = []
    previous = None
    for event in result.heart_rate:
        if event.status != previous:
            changes.append((event.sample / result.fs_hz, event.status))
            previous = event.status
    return changes


def test_the_set_has_eight_inputs_in_order() -> None:
    ids = [ecg.input_id for ecg in synthetic_event_set()]
    assert ids == [f"syn-fs{fs}-event-{event}" for fs in (250, 360) for event in SYNTHETIC_EVENTS]
    assert SYNTHETIC_EVENTS == ("artefact", "small-beat", "held", "rate-change")


@pytest.mark.parametrize("fs_hz", FS_VALUES)
@pytest.mark.parametrize("event", SYNTHETIC_EVENTS)
def test_fields_of_an_event_input(fs_hz: float, event: str) -> None:
    ecg = synthetic_event_ecg(fs_hz, event)
    assert ecg.input_id == f"syn-fs{int(fs_hz)}-event-{event}"
    assert (ecg.fs_hz, ecg.heart_rate_bpm, ecg.variant, ecg.mains_hz) == (fs_hz, 75, event, 50)
    duration = 44 if event == "rate-change" else 40
    assert ecg.signal_mv.shape == (int(duration * fs_hz),)
    assert ecg.signal_mv.dtype == np.float64
    assert ecg.r_peaks.dtype == np.int64
    assert np.isfinite(ecg.signal_mv).all()
    assert ecg.parameters.startswith(f"duration_s={duration};event={event};")


def test_the_parameters_are_those_of_the_design() -> None:
    parameters = {event: synthetic_event_ecg(360.0, event).parameters for event in SYNTHETIC_EVENTS}
    assert parameters == {
        "artefact": "duration_s=40;event=artefact;heart_rate_bpm=75;scaled_beat_ms=10100;"
        "scale=20.0;mains_hz=50",
        "small-beat": "duration_s=40;event=small-beat;heart_rate_bpm=75;scaled_beat_ms=10100;"
        "scale=0.4;mains_hz=50",
        "held": "duration_s=40;event=held;heart_rate_bpm=75;held_from_ms=15000;held_ms=6000;"
        "mains_hz=50",
        "rate-change": "duration_s=44;event=rate-change;heart_rates_bpm=75/25/75;"
        "changes_ms=11700/30900;mains_hz=50",
    }


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_reference_beats_are_computed_on_integers(fs_hz: float) -> None:
    fs = int(fs_hz)
    regular = [(500 + 800 * k) for k in range(49)]
    rate_change = (
        [500 + 800 * k for k in range(15)]
        + [11700 + 2400 * j for j in range(1, 9)]
        + [30900 + 800 * j for j in range(1, 16)]
    )
    for event, times in (
        ("artefact", regular),
        ("small-beat", regular),
        ("held", regular),
        ("rate-change", rate_change),
    ):
        expected = [(t_ms * fs + 500) // 1000 for t_ms in times]
        assert synthetic_event_ecg(fs_hz, event).r_peaks.tolist() == expected
    assert len(rate_change) == 38


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_the_scaled_beat_and_the_held_stretch(fs_hz: float) -> None:
    fs = int(fs_hz)
    big = synthetic_event_ecg(fs_hz, "artefact")
    small = synthetic_event_ecg(fs_hz, "small-beat")
    held = synthetic_event_ecg(fs_hz, "held")
    r = big.r_peaks.tolist()
    # The waves of neighbouring beats overlap little: the R wave scales by the factor.
    assert big.signal_mv[r[12]] / held.signal_mv[r[12]] == pytest.approx(20.0, rel=1e-3)
    assert small.signal_mv[r[12]] / held.signal_mv[r[12]] == pytest.approx(0.4, rel=1e-3)
    other = [i for i in range(49) if i != 12]
    assert np.array_equal(big.signal_mv[r[5]], held.signal_mv[r[5]])
    assert all(big.signal_mv[r[i]] == held.signal_mv[r[i]] for i in other[:5])
    first = (15000 * fs + 500) // 1000
    end = (21000 * fs + 500) // 1000
    assert (held.signal_mv[first:end] == held.signal_mv[first]).all()
    assert held.signal_mv[first - 1] != held.signal_mv[first]
    assert held.signal_mv[end] != held.signal_mv[first]
    # Beats inside the held stretch stay in the reference.
    assert any(first <= peak < end for peak in held.r_peaks.tolist())


def test_the_waveform_is_that_of_the_regular_rhythm() -> None:
    """With the scale 1.0 and RR 0.8 s the beats are those of 75 bpm (s = sqrt(0.8))."""
    event = synthetic_event_ecg(360.0, "held")
    regular = synthetic_ecg(360.0, 75, "clean")
    # Same waves, same widths: the R wave centre value is the same up to overlap and rounding.
    peak = int(event.r_peaks[10])
    assert abs(event.signal_mv[peak] - 1.0) < 0.05
    assert abs(regular.signal_mv[int(regular.r_peaks[10])] - 1.0) < 0.05


@pytest.mark.parametrize("fs_hz", [100.0, 250.5, True, "250", None])
def test_fs_is_checked(fs_hz: Any) -> None:
    with pytest.raises(InvalidInputError, match="fs_hz"):
        synthetic_event_ecg(fs_hz, "held")


@pytest.mark.parametrize("event", ["clean", "", "Held", None, 3])
def test_event_is_checked(event: Any) -> None:
    with pytest.raises(InvalidInputError, match="event"):
        synthetic_event_ecg(250.0, event)


def test_the_inputs_are_deterministic() -> None:
    first = synthetic_event_ecg(360.0, "rate-change")
    second = synthetic_event_ecg(360.0, "rate-change")
    assert first.signal_mv.tobytes() == second.signal_mv.tobytes()
    assert isinstance(first, SyntheticEcg)


# --- the facts of architecture §13.9 (re-checked) -----------------------------------------------


@pytest.mark.parametrize("fs_hz", FS_VALUES)
@pytest.mark.parametrize("event", SYNTHETIC_EVENTS)
def test_every_input_starts_with_two_startup_detections_and_withheld_rates(
    fs_hz: float, event: str
) -> None:
    result = result_of(fs_hz, event)
    detections = result.detections
    first = [i for i in range(len(detections.indices)) if detections.startup[i]][:2]
    assert first == [0, 1]
    assert detections.indices[0] < 2 * fs_hz
    assert detections.reported_at[0] == detections.reported_at[1] == int(2 * fs_hz) - 1
    assert result.heart_rate[0].status == "not_enough_beats"
    assert status_changes(result)[0][0] == pytest.approx(2.28, abs=0.01)


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_artefact(fs_hz: float) -> None:
    result = result_of(fs_hz, "artefact")
    detections = result.detections
    relearning = 6553 if fs_hz == 360.0 else 4623
    assert detections.initialisations.tolist() == [int(2 * fs_hz) - 1, relearning]
    assert relearning / fs_hz == pytest.approx(18.2 if fs_hz == 360.0 else 18.49, abs=0.01)
    startup_after = [
        int(i)
        for i, startup in zip(detections.indices, detections.startup, strict=True)
        if startup and i > 4 * fs_hz
    ]
    assert len(startup_after) == 3
    assert all(
        detections.reported_at[list(detections.indices).index(i)] >= relearning
        for i in startup_after
    )
    if fs_hz == 250.0:
        assert detections.paths.count("search_back") == 1
        position = detections.paths.index("search_back")
        late = (detections.reported_at[position] - detections.indices[position]) / fs_hz
        assert late == pytest.approx(5.8, abs=0.05)
    else:
        assert "search_back" not in detections.paths
    changes = status_changes(result)
    assert [status for _, status in changes] == [
        "not_enough_beats",
        "valid",
        "no_recent_beat",
        "valid",
    ]
    assert changes[2][0] == pytest.approx(13.1, abs=0.05)
    assert changes[3][0] == pytest.approx(22.3, abs=0.05)
    not_usable = [
        int(f) / fs_hz
        for f, u in zip(result.quality.first, result.quality.usable, strict=True)
        if not u
    ]
    assert not_usable == [0.0, 11.0, 12.0, 13.0]


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_small_beat(fs_hz: float) -> None:
    result = result_of(fs_hz, "small-beat")
    detections = result.detections
    assert detections.paths.count("search_back") == 1
    position = detections.paths.index("search_back")
    reference = int(synthetic_event_ecg(fs_hz, "small-beat").r_peaks[12])
    assert abs(int(detections.indices[position]) - reference) < 10
    late = (detections.reported_at[position] - detections.indices[position]) / fs_hz
    assert late == pytest.approx(0.62, abs=0.01)
    assert [status for _, status in status_changes(result)] == ["not_enough_beats", "valid"]
    assert result.quality.usable.all()
    assert len(detections.indices) == 49


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_held(fs_hz: float) -> None:
    result = result_of(fs_hz, "held")
    held_from, held_to = 15.0 * fs_hz, 21.0 * fs_hz
    assert not any(held_from <= i < held_to for i in result.detections.indices)
    changes = status_changes(result)
    assert [status for _, status in changes] == [
        "not_enough_beats",
        "valid",
        "no_recent_beat",
        "valid",
    ]
    assert changes[2][0] == pytest.approx(17.9, abs=0.05)
    assert changes[3][0] == pytest.approx(24.7, abs=0.05)
    not_usable = [
        int(f) / fs_hz
        for f, u in zip(result.quality.first, result.quality.usable, strict=True)
        if not u
    ]
    assert not_usable == [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]


@pytest.mark.parametrize("fs_hz", FS_VALUES)
def test_rate_change(fs_hz: float) -> None:
    result = result_of(fs_hz, "rate-change")
    assert len(result.detections.indices) == 38
    changes = status_changes(result)
    assert [status for _, status in changes] == [
        "not_enough_beats",
        "valid",
        "out_of_range",
        "valid",
    ]
    assert changes[2][0] == pytest.approx(19.1, abs=0.05)
    assert changes[3][0] == pytest.approx(33.5, abs=0.05)
    out = [e.bpm for e in result.heart_rate if e.status == "out_of_range"]
    assert out and all(bpm is not None and bpm == pytest.approx(25.0, abs=0.5) for bpm in out)
    assert result.quality.usable.all()
