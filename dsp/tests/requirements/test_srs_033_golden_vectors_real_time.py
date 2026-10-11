"""Requirement tests of SRS-033: golden vectors of the real-time functions (RC-012).

SRS-033 (v0.8.1): each golden-vector file of SRS-015 also contains the mark of each detection
(SRS-022); the heart rate reported at each detection marked reliable and at each change of its
validity or of the reason for which it is withheld, with its sample index, its validity and,
when withheld, its reason (SRS-024, SRS-026); and each signal quality window with the sample
indices of its first and last samples, its index and its mark (SRS-027). The set of inputs of
SRS-015 also includes synthetic inputs, documented in `architecture.md`, on which a detection
is marked start-up after detection has learned its signal levels again, the heart rate is
withheld for each reason of SRS-026, and at least one window is marked not usable.
Verification: "each file contains each listed item, and the values read back equal the outputs
of the reference functions called directly on the same input. The set of files contains a
detection marked start-up after detection has learned its signal levels again, a heart rate
withheld for each reason, and a window marked not usable."

The format is architecture section 13.8, read by the test's own reader (`read_golden_file`);
the event inputs are those of section 13.9, built here from its table (`make_event_ecg`).
The export is run on the synthetic ECG subset fixture, so that the 18 + 8 synthetic files and
the 6 record segments are all checked.

The cases and their tests:
- the event inputs are in the set, at both rates, with the documented parameters and samples:
  `test_event_inputs_are_in_the_set`, `test_event_input_is_the_documented_one`;
- every file contains each listed item:
  `test_file_contains_the_marks_the_heart_rates_and_the_windows`;
- the values read back equal the reference functions called directly:
  `test_values_read_back_equal_the_reference_functions`;
- the documented behaviour of each event, at both rates: `test_artefact_event`,
  `test_small_beat_event`, `test_held_event`, `test_rate_change_event`,
  `test_every_input_starts_with_start_up_detections_and_a_withheld_rate`;
- the set contains each mark, reason and a window not usable:
  `test_set_contains_each_mark_each_reason_and_a_window_not_usable`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sinus_dsp.data.physionet import Database, DatabaseLicence
from sinus_dsp.golden import export_golden_vectors
from sinus_dsp.heart_rate import track_heart_rate
from sinus_dsp.pipeline import detect_marked, run_pipeline
from sinus_dsp.quality import quality_windows

pytestmark = pytest.mark.usefixtures("forbid_network")

SUFFIX = ".golden.txt"
SUBSET = ("100", "105", "108", "119", "203", "207")
SYNTHETIC_IDS = tuple(
    f"syn-fs{fs}-hr{hr:03d}-{variant}"
    for fs in (250, 360)
    for hr in (40, 75, 180)
    for variant in ("clean", "bw-mains50", "bw-mains60")
)
EVENTS = ("artefact", "small-beat", "held", "rate-change")
EVENT_IDS = tuple(f"syn-fs{fs}-event-{event}" for fs in (250, 360) for event in EVENTS)
SEGMENT_IDS = tuple(f"mitdb-{name}-first60s" for name in SUBSET)
ALL_IDS = SYNTHETIC_IDS + EVENT_IDS + SEGMENT_IDS
STATUSES = ("valid", "not_enough_beats", "no_recent_beat", "out_of_range")
DURATION_S = {"artefact": 40, "small-beat": 40, "held": 40, "rate-change": 44}
PARAMETERS = {
    "artefact": (
        "duration_s=40;event=artefact;heart_rate_bpm=75;scaled_beat_ms=10100;scale=20.0;mains_hz=50"
    ),
    "small-beat": (
        "duration_s=40;event=small-beat;heart_rate_bpm=75;scaled_beat_ms=10100;scale=0.4;mains_hz=50"
    ),
    "held": (
        "duration_s=40;event=held;heart_rate_bpm=75;held_from_ms=15000;held_ms=6000;mains_hz=50"
    ),
    "rate-change": (
        "duration_s=44;event=rate-change;heart_rates_bpm=75/25/75;changes_ms=11700/30900;mains_hz=50"
    ),
}
# The times of the table of architecture section 13.9 are given to 0.1 s.
TABLE_TOLERANCE_S = 0.06

# A licence of the fixture database: the `Database` has no default for it.
FIXTURE_LICENCE = DatabaseLicence(
    name="Fixture Data Licence 1.0", url="https://licences.example.org/fixture/1-0/"
)


def _event_of(input_id: str) -> tuple[int, str]:
    fs_part, event = input_id.removeprefix("syn-fs").split("-event-")
    return int(fs_part), event


def _fs_of(golden: Any) -> int:
    return round(float(golden.header["sampling_frequency_hz"]))


@pytest.fixture(scope="module")
def vectors(
    subset_ecg_fixture: Any,
    network_forbidden: Callable[[], Any],
    tmp_path_factory: pytest.TempPathFactory,
    read_golden_file: Callable[[bytes], Any],
) -> dict[str, Any]:
    """The export of the synthetic ECG subset fixture, read by the test (input id -> file)."""
    folder = tmp_path_factory.mktemp("srs033-export") / "golden"
    database = Database(
        slug="mitdb",
        version="1.0.0",
        title="MIT-BIH Arrhythmia Database",
        checksum_list_sha256=subset_ecg_fixture.checksum_list_sha256,
        licence=FIXTURE_LICENCE,
    )
    with network_forbidden():
        export_golden_vectors(folder, data_root=subset_ecg_fixture.data_root, database=database)
    return {
        path.name.removesuffix(SUFFIX): read_golden_file(path.read_bytes())
        for path in sorted(folder.iterdir())
        if path.name.endswith(SUFFIX)
    }


def _statuses(golden: Any) -> list[str]:
    """The statuses of the heart-rate rows with the repeated ones collapsed."""
    runs: list[str] = []
    for _sample, _beat, status, _bpm in golden.heart_rates:
        if not runs or runs[-1] != status:
            runs.append(status)
    return runs


def _first_row_of(golden: Any, status: str, after: str | None = None) -> float:
    """The time in s of the first row with ``status`` (after the first row of ``after``)."""
    fs = _fs_of(golden)
    start = 0
    if after is not None:
        start = next(i for i, row in enumerate(golden.heart_rates) if row[2] == after)
    row = next(r for r in golden.heart_rates[start:] if r[2] == status)
    return row[0] / fs


def _not_usable_starts_s(golden: Any) -> list[float]:
    fs = _fs_of(golden)
    return [
        float(first) / fs
        for first, usable in zip(golden.window_first, golden.window_usable, strict=True)
        if not usable
    ]


# --------------------------------------------------------------------------------------------
# The event inputs are in the set
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-033")
def test_event_inputs_are_in_the_set(vectors: dict[str, Any]) -> None:
    """The set of files holds the 8 event inputs, 4 events at each of the two rates.

    Input: the export on the synthetic ECG subset fixture.
    Expected: the files `syn-fs<fs>-event-<event>` exist for fs in 250 and 360 and the events
    `artefact`, `small-beat`, `held` and `rate-change`; the set is the 18 synthetic files of
    SRS-015, these 8 and the 6 record segments, and nothing else.
    """
    assert sorted(vectors) == sorted(ALL_IDS)


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("input_id", EVENT_IDS)
def test_event_input_is_the_documented_one(
    input_id: str,
    vectors: dict[str, Any],
    make_event_ecg: Callable[[int, str], tuple[np.ndarray, np.ndarray]],
) -> None:
    """The file of an event input holds the input that architecture section 13.9 documents.

    Input: the file of the input; the test's own construction of the event from the table of
    section 13.9 (beat times in whole milliseconds, R centres at `(t_ms * fs + 500) // 1000`,
    the waveform of section 7.2 with `s = sqrt(rr_s)`, the scale of the beat, the held
    stretch).
    Expected: `input_source` `synthetic`; `input_parameters` as in the `input_parameters`
    column of the table; sampling frequency 250.0 or 360.0; mains setting 50; `n_samples`
    equal to the duration times the rate (40 s, 44 s for `rate-change`); `input_mv` within
    1e-9 mV of the test's construction; `[reference_beats]` the R centres of all the beats,
    the scaled one included.
    """
    fs, event = _event_of(input_id)
    golden = vectors[input_id]
    signal, reference = make_event_ecg(fs, event)
    header = golden.header

    assert header["input_source"] == "synthetic"
    assert header["input_parameters"] == PARAMETERS[event]
    assert header["sampling_frequency_hz"] == f"{fs}.0"
    assert header["mains_frequency_hz"] == "50"
    assert header["n_samples"] == str(DURATION_S[event] * fs)
    assert golden.input_mv.shape == signal.shape
    assert float(np.max(np.abs(golden.input_mv - signal))) <= 1e-9
    assert golden.reference_beats.tolist() == reference.tolist()


# --------------------------------------------------------------------------------------------
# Each file contains each listed item
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("input_id", ALL_IDS)
def test_file_contains_the_marks_the_heart_rates_and_the_windows(
    input_id: str, vectors: dict[str, Any]
) -> None:
    """Each file holds a mark for each detection, the heart-rate events and the windows.

    Input: the file of each of the 32 inputs, read by the test.
    Expected, from the statement:
    - marks: one mark (`startup` or `reliable`) and one report sample for each detection; a
      detection whose index lies in the first 2 s (`round(2 fs)` samples) is `startup`;
    - heart rates: a row at each detection marked `reliable`, in order, at the sample at which
      the detection is reported (rows with a `beat_index` name the reliable detections once
      each); every other row is a change of status (its status differs from that of the row
      before); the status is one of the four; a rate is present exactly for `valid` and
      `out_of_range`, and `valid` rates lie in 30..200 bpm, `out_of_range` rates outside it;
      the first row of every file is `not_enough_beats`;
    - windows: one for each start at a whole second (`round(fs)` samples) from the first sample
      of the stream, of 10 s (`10 round(fs)` samples; first, last = first + W - 1), reported
      0.5 s (`floor(500 fs / 1000)` samples) after its last sample, as long as that sample is
      inside the stream; an index in [0, 1] and a mark `usable` exactly when the index is at
      least 0.5.
    """
    golden = vectors[input_id]
    fs = _fs_of(golden)
    n = int(golden.header["n_samples"])
    learning = round(2 * fs)

    assert golden.beat_startup.dtype == np.bool_ and golden.beats.size > 0
    assert golden.beat_startup.size == golden.beat_reported_at.size == golden.beats.size
    assert bool(np.all(golden.beat_startup[golden.beats < learning]))
    assert bool(np.all(golden.beat_reported_at >= golden.beats))
    assert bool(np.all(golden.beat_reported_at < n))

    reliable = golden.beats[~golden.beat_startup]
    reported = golden.beat_reported_at[~golden.beat_startup]
    rows = golden.heart_rates
    assert rows[0][2] == "not_enough_beats"
    with_beat = [row for row in rows if row[1] is not None]
    assert [row[1] for row in with_beat] == reliable.tolist()
    assert [row[0] for row in with_beat] == reported.tolist()
    previous = None
    for sample, beat, status, bpm in rows:
        assert status in STATUSES
        assert 0 <= sample < n
        if beat is None:
            assert status != previous
        if status in ("valid", "out_of_range"):
            assert bpm is not None
            assert (30.0 <= bpm <= 200.0) == (status == "valid")
        else:
            assert bpm is None
        previous = status
    assert [row[0] for row in rows] == sorted(row[0] for row in rows)

    window = 10 * fs
    delay = 500 * fs // 1000
    starts = [k * fs for k in range(n) if k * fs + window - 1 + delay < n]
    assert golden.window_first.tolist() == starts
    assert golden.window_last.tolist() == [first + window - 1 for first in starts]
    assert golden.window_reported_at.tolist() == [first + window - 1 + delay for first in starts]
    assert bool(np.all((golden.window_index >= 0.0) & (golden.window_index <= 1.0)))
    assert golden.window_usable.tolist() == (golden.window_index >= 0.5).tolist()


def _same_float64(a: Any, b: Any) -> bool:
    x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return x.shape == y.shape and x.tobytes() == y.tobytes()


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("input_id", ALL_IDS)
def test_values_read_back_equal_the_reference_functions(
    input_id: str, vectors: dict[str, Any]
) -> None:
    """The marks, heart rates and windows of each file equal the reference functions' outputs.

    Input: the input read back from each of the 32 files, at the rate and mains setting of the
    file; `detect_marked`, `run_pipeline`, `track_heart_rate` (on the detections read back,
    with their marks and report samples) and `quality_windows` called directly on it.
    Expected, exactly (bitwise for floats): the marks and report samples equal those of
    `detect_marked` and of `run_pipeline(...).detections`; the heart-rate rows (sample, beat
    index, status, rate) equal the events of `track_heart_rate` and of
    `run_pipeline(...).heart_rate`; the windows (first, last, report sample, index, mark) equal
    those of `quality_windows` and of `run_pipeline(...).quality`.
    """
    golden = vectors[input_id]
    fs = float(golden.header["sampling_frequency_hz"])
    mains = int(golden.header["mains_frequency_hz"])
    signal = golden.input_mv.copy()
    pipeline = run_pipeline(signal, fs, mains)
    marked = detect_marked(signal, fs, mains)
    quality = quality_windows(signal, fs, mains)
    tracked = track_heart_rate(
        golden.beats,
        golden.beat_startup,
        fs,
        signal.size,
        reported_at=golden.beat_reported_at,
    )
    rows = list(golden.heart_rates)

    for detections in (marked, pipeline.detections):
        assert golden.beats.tolist() == np.asarray(detections.indices).tolist()
        assert golden.beat_startup.tolist() == np.asarray(detections.startup).tolist()
        assert golden.beat_reported_at.tolist() == np.asarray(detections.reported_at).tolist()
    for events in (tracked, pipeline.heart_rate):
        assert rows == [(e.sample, e.beat_index, e.status, e.bpm) for e in events]
    for windows in (quality, pipeline.quality):
        assert golden.window_first.tolist() == np.asarray(windows.first).tolist()
        assert golden.window_last.tolist() == np.asarray(windows.last).tolist()
        assert golden.window_reported_at.tolist() == np.asarray(windows.reported_at).tolist()
        assert _same_float64(golden.window_index, windows.index)
        assert golden.window_usable.tolist() == np.asarray(windows.usable).tolist()


# --------------------------------------------------------------------------------------------
# The documented behaviour of each event input (architecture section 13.9)
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("input_id", EVENT_IDS)
def test_every_input_starts_with_start_up_detections_and_a_withheld_rate(
    input_id: str, vectors: dict[str, Any]
) -> None:
    """On every event input, the first 2 s give start-up detections reported at their end.

    Input: the file of each event input.
    Expected: at least one detection lies in the first 2 s; each is marked `startup` and
    reported at the end of the learning period (sample `round(2 fs) - 1` or later, the sample
    at which detection has learned its levels), and the first heart-rate row is
    `not_enough_beats`.
    """
    golden = vectors[input_id]
    fs = _fs_of(golden)
    learning = round(2 * fs)
    early = golden.beats < learning

    assert early.any()
    assert bool(np.all(golden.beat_startup[early]))
    assert bool(np.all(golden.beat_reported_at[early] >= learning - 1))
    assert golden.heart_rates[0][2] == "not_enough_beats"


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("fs", [250, 360])
def test_artefact_event(
    fs: int,
    vectors: dict[str, Any],
    make_event_ecg: Callable[[int, str], tuple[np.ndarray, np.ndarray]],
    match_window_samples: Callable[[float], int],
) -> None:
    """`artefact`: a beat 20 times larger makes detection learn its levels again.

    Input: the file `syn-fs<fs>-event-artefact` (40 s, 75 bpm, the beat at 10.1 s with scale
    20), at 250 Hz and at 360 Hz.
    Expected (architecture section 13.9): the large beat is detected; some later beats are
    missed (fewer detections than reference beats); three detections are marked `startup`
    after the first 2 s, all in one stretch of 2 s that ends by 19 s and lies after the large
    beat (the levels learned again, at about 18.2 s); the other detections after the first
    2 s are `reliable`; the heart-rate statuses in order are `not_enough_beats`, `valid`,
    `no_recent_beat`, `valid`, the second `valid` run beginning at 22.3 s and the
    `no_recent_beat` at 13.1 s (within 0.06 s), ending when a valid rate is reported again;
    the windows that start at 0 s and at 11, 12 and 13 s are the ones marked not usable. At 250
    Hz, one detection by search-back is reported 5.8 s (within 0.06 s) after its index.
    """
    golden = vectors[f"syn-fs{fs}-event-artefact"]
    _, reference = make_event_ecg(fs, "artefact")
    window = match_window_samples(float(fs))
    large = int(reference[12])
    late_startup = golden.beats[golden.beat_startup & (golden.beats >= 2 * fs)]

    assert bool(np.any(np.abs(golden.beats - large) <= window))
    assert golden.beats.size < reference.size
    assert late_startup.size == 3
    assert bool(np.all(late_startup > large)) and (late_startup[-1] - late_startup[0]) < 2 * fs
    assert late_startup[-1] < 19 * fs
    assert _statuses(golden) == ["not_enough_beats", "valid", "no_recent_beat", "valid"]
    assert abs(_first_row_of(golden, "no_recent_beat") - 13.1) <= TABLE_TOLERANCE_S
    assert abs(_first_row_of(golden, "valid", after="no_recent_beat") - 22.3) <= TABLE_TOLERANCE_S
    assert _not_usable_starts_s(golden) == [0.0, 11.0, 12.0, 13.0]
    delays = (golden.beat_reported_at - golden.beats) / fs
    if fs == 250:
        search_back = delays[(golden.beats >= 2 * fs) & (delays > 3.0)]
        assert search_back.size == 1 and abs(float(search_back[0]) - 5.8) <= TABLE_TOLERANCE_S


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("fs", [250, 360])
def test_small_beat_event(
    fs: int,
    vectors: dict[str, Any],
    make_event_ecg: Callable[[int, str], tuple[np.ndarray, np.ndarray]],
    match_window_samples: Callable[[float], int],
) -> None:
    """`small-beat`: a beat 0.4 times the size of the others is found late, by search-back.

    Input: the file `syn-fs<fs>-event-small-beat` (40 s, 75 bpm, the beat at 10.1 s with scale
    0.4), at 250 Hz and at 360 Hz.
    Expected (section 13.9): every beat is detected (one detection within 150 ms of each
    reference beat, no other); the small beat is reported 0.62 s (within 0.06 s) after its
    index, while no other detection after the first 2 s is reported more than 0.5 s after its
    index; the heart-rate statuses in order are `not_enough_beats`, then `valid`, with no
    change of status at no detection; all windows are usable.
    """
    golden = vectors[f"syn-fs{fs}-event-small-beat"]
    _, reference = make_event_ecg(fs, "small-beat")
    window = match_window_samples(float(fs))
    delays = (golden.beat_reported_at - golden.beats) / fs
    small = int(reference[12])
    is_small = np.abs(golden.beats - small) <= window

    assert golden.beats.size == reference.size
    assert all(int(np.sum(np.abs(golden.beats - r) <= window)) == 1 for r in reference.tolist())
    assert int(is_small.sum()) == 1
    assert abs(float(delays[is_small][0]) - 0.62) <= TABLE_TOLERANCE_S
    assert bool(np.all(delays[~is_small & (golden.beats >= 2 * fs)] <= 0.5))
    assert _statuses(golden) == ["not_enough_beats", "valid"]
    assert all(row[1] is not None for row in golden.heart_rates)
    assert _not_usable_starts_s(golden) == []


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("fs", [250, 360])
def test_held_event(
    fs: int,
    vectors: dict[str, Any],
    make_event_ecg: Callable[[int, str], tuple[np.ndarray, np.ndarray]],
) -> None:
    """`held`: the input stays at one value from 15 s to 21 s.

    Input: the file `syn-fs<fs>-event-held` (40 s, 75 bpm), at 250 Hz and at 360 Hz.
    Expected (section 13.9): no detection in the held stretch (samples `15000 fs / 1000`
    to `21000 fs / 1000`, exclusive); detections before and after it; the heart-rate statuses
    in order are `not_enough_beats`, `valid`, `no_recent_beat`, `valid`, the `no_recent_beat`
    reported at 17.9 s and the next `valid` at 24.7 s (within 0.06 s); the windows marked not
    usable are those that start at 10 to 16 s, which hold at least 5 s of the held stretch.
    """
    golden = vectors[f"syn-fs{fs}-event-held"]
    held_from, held_to = (15000 * fs + 500) // 1000, (21000 * fs + 500) // 1000
    _, reference = make_event_ecg(fs, "held")

    assert not bool(np.any((golden.beats >= held_from) & (golden.beats < held_to)))
    assert bool(np.any(golden.beats < held_from)) and bool(np.any(golden.beats >= held_to))
    assert _statuses(golden) == ["not_enough_beats", "valid", "no_recent_beat", "valid"]
    assert abs(_first_row_of(golden, "no_recent_beat") - 17.9) <= TABLE_TOLERANCE_S
    assert abs(_first_row_of(golden, "valid", after="no_recent_beat") - 24.7) <= TABLE_TOLERANCE_S
    # Windows of 10 s with at least 5 s of the held stretch [15 s, 21 s): start from 10 s to 16 s.
    expected = [float(start) for start in range(31) if min(start + 10, 21) - max(start, 15) >= 5]
    assert expected == [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    assert _not_usable_starts_s(golden) == expected
    assert reference.size > golden.beats.size


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("fs", [250, 360])
def test_rate_change_event(
    fs: int,
    vectors: dict[str, Any],
    make_event_ecg: Callable[[int, str], tuple[np.ndarray, np.ndarray]],
    match_window_samples: Callable[[float], int],
) -> None:
    """`rate-change`: 75 bpm, then 25 bpm for 8 beats, then 75 bpm again (44 s).

    Input: the file `syn-fs<fs>-event-rate-change`, at 250 Hz and at 360 Hz.
    Expected (section 13.9): every beat is detected (one detection within 150 ms of each
    reference beat, none else); the heart-rate statuses in order are `not_enough_beats`,
    `valid`, `out_of_range`, `valid`; the `out_of_range` is first reported at 19.1 s and the
    next `valid` at 33.5 s (within 0.06 s); an `out_of_range` row holds a rate of about 25 bpm
    (24 to 26) that lies outside 30..200; every other rate is about 75 bpm (74 to 76); all
    windows are usable.
    """
    golden = vectors[f"syn-fs{fs}-event-rate-change"]
    _, reference = make_event_ecg(fs, "rate-change")
    window = match_window_samples(float(fs))

    assert golden.beats.size == reference.size
    assert all(int(np.sum(np.abs(golden.beats - r) <= window)) == 1 for r in reference.tolist())
    assert _statuses(golden) == ["not_enough_beats", "valid", "out_of_range", "valid"]
    assert abs(_first_row_of(golden, "out_of_range") - 19.1) <= TABLE_TOLERANCE_S
    assert abs(_first_row_of(golden, "valid", after="out_of_range") - 33.5) <= TABLE_TOLERANCE_S
    for _sample, _beat, status, bpm in golden.heart_rates:
        if status == "out_of_range":
            assert bpm is not None and 24.0 <= bpm <= 26.0
        if status == "valid":
            assert bpm is not None and 74.0 <= bpm <= 76.0
    assert _not_usable_starts_s(golden) == []


# --------------------------------------------------------------------------------------------
# The set as a whole
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-033")
@pytest.mark.parametrize("fs", [250, 360])
def test_set_contains_each_mark_each_reason_and_a_window_not_usable(
    fs: int, vectors: dict[str, Any]
) -> None:
    """At each sampling frequency, the set holds every mark, reason and window mark.

    Input: the files of the set written for `fs` (the 9 synthetic ECGs at that rate and the 4
    event inputs).
    Expected:
    - a detection marked `startup` that lies after the first 2 s, at or after the sample
      `round(2 fs)` (detection has learned its levels again), in `artefact`;
    - a detection marked `reliable` in every file;
    - a heart-rate row for each of the four statuses of SRS-026 and SRS-024 (`valid`,
      `not_enough_beats` in every file, `no_recent_beat` in `artefact` and `held`,
      `out_of_range` in `rate-change`), and a `no_recent_beat` row at no detection;
    - a window marked `not_usable` (in `artefact` and `held`) and windows marked `usable`.
    """
    files = {i: v for i, v in vectors.items() if i.startswith(f"syn-fs{fs}-")}
    assert len(files) == 13

    relearned = [
        i for i, v in files.items() if bool(np.any(v.beat_startup & (v.beats >= round(2 * fs))))
    ]
    assert relearned == [f"syn-fs{fs}-event-artefact"]
    assert all(bool(np.any(~v.beat_startup)) for v in files.values())
    for status in STATUSES:
        assert any(row[2] == status for v in files.values() for row in v.heart_rates), status
    assert all(v.heart_rates[0][2] == "not_enough_beats" for v in files.values())
    withheld = {
        i
        for i, v in files.items()
        if any(row[2] == "no_recent_beat" and row[1] is None for row in v.heart_rates)
    }
    assert withheld == {f"syn-fs{fs}-event-artefact", f"syn-fs{fs}-event-held"}
    with_out_of_range = {
        i for i, v in files.items() if any(row[2] == "out_of_range" for row in v.heart_rates)
    }
    assert with_out_of_range == {f"syn-fs{fs}-event-rate-change"}
    not_usable = {i for i, v in files.items() if not bool(np.all(v.window_usable))}
    assert not_usable == {f"syn-fs{fs}-event-artefact", f"syn-fs{fs}-event-held"}
    assert all(bool(np.any(v.window_usable)) for v in files.values())
