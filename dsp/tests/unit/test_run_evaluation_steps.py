"""Unit tests of the start-of-stream and signal-quality steps of ``run_validation``.

The records are built in memory at 125 Hz (31 min long, the shortest length that holds the
30 segments of the start of stream and seven noisy stretches), and loaded by a fake loader;
the detection, the marked detection and the signal quality are fakes with known output, so
that every figure of the run is known by hand. The fixture databases of the conftest only
serve the verification of the data (``fetch=None``).
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from sinus_dsp.data.physionet import Database
from sinus_dsp.data.records import Record
from sinus_dsp.evaluation.noise_stress import NOISE_STRESS_RECORDS, snr_db
from sinus_dsp.evaluation.report import render_full_report
from sinus_dsp.evaluation.run import ValidationResults, run_validation
from sinus_dsp.evaluation.start_of_stream import SEGMENT_STARTS_S
from sinus_dsp.qrs import Detections
from sinus_dsp.quality import QualityWindows

FS_HZ = 125
N_SAMPLES = 31 * 60 * FS_HZ  # 232500
SEGMENT_SAMPLES = 60 * FS_HZ
MITDB_NAMES = ("100", "118", "119", "207")
NOISE_NAMES = ("bw", "em", "ma")
# Noise stress records at 12 dB and above are "usable" for the fake quality function; so are
# the records of the arrhythmia database except 207. The others have the signal value 0.
USABLE_VALUE = 1.0


def signal_value(name: str) -> float:
    if name == "207" or name in NOISE_NAMES:
        return 0.0
    if name in NOISE_STRESS_RECORDS:
        return USABLE_VALUE if snr_db(name) >= 12 else 0.0
    return USABLE_VALUE


class MemoryLoader:
    """Builds the record named by the last component of the path; remembers the calls."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, path: Path, channel: int) -> Record:
        self.calls.append(path)
        name = path.name
        beats = [40000, 50000] if name == "207" else [40000]
        return Record(
            name=name,
            channel=channel,
            signal_name="MLII",
            fs_hz=float(FS_HZ),
            signal_mv=np.full(N_SAMPLES, signal_value(name)),
            beat_samples=np.array(beats, dtype=np.int64),
            beat_symbols=tuple("N" for _ in beats),
            other_annotations=(),
        )


def detector(
    signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int
) -> npt.NDArray[np.int64]:
    """Detects the beat at 40000; a record with the signal value 0 adds a detection at 60000."""
    extra = [60000] if signal_mv[0] == 0.0 else []
    return np.array([40000, *extra], dtype=np.int64)


class MarkedDetector:
    def __init__(self) -> None:
        self.calls: list[tuple[int, float, int]] = []

    def __call__(
        self, signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int
    ) -> Detections:
        self.calls.append((signal_mv.shape[0], fs_hz, mains_hz))
        empty = np.zeros(0, dtype=np.int64)
        return Detections(
            indices=np.array([100, 2500], dtype=np.int64),
            startup=np.array([True, False]),
            reported_at=np.array([100, 2500], dtype=np.int64),
            peaks=np.array([100, 2500], dtype=np.int64),
            paths=("peak", "peak"),
            initialisations=empty,
        )


def quality(signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int) -> QualityWindows:
    """Windows of 10 s every second; index 0.9 (usable) where the signal is 1, else 0.1."""
    hop = int(fs_hz)
    width = 10 * hop
    first = np.arange(0, (signal_mv.shape[0] - width) // hop + 1, dtype=np.int64) * hop
    value = 0.9 if signal_mv[0] == USABLE_VALUE else 0.1
    index = np.full(first.shape, value)
    nothing = np.zeros(first.shape, dtype=np.int64)
    return QualityWindows(
        first=first,
        last=first + width - 1,
        reported_at=first + width - 1,
        index=index,
        usable=index >= 0.5,
        held=np.zeros(first.shape, dtype=np.bool_),
        n_detections=nothing,
        signal_power=np.full(first.shape, np.nan),
        background_power=np.full(first.shape, np.nan),
    )


class Run:
    """One run on the fixture databases, with the fakes it used."""

    def __init__(self, root: Path, mitdb: Database, nstdb: Database) -> None:
        self.root = root
        self.mitdb = mitdb
        self.nstdb = nstdb
        self.loader = MemoryLoader()
        self.noise_loader = MemoryLoader()
        self.marked = MarkedDetector()
        self.results = self.execute()

    def execute(self) -> ValidationResults:
        return run_validation(
            self.root,
            mitdb=self.mitdb,
            nstdb=self.nstdb,
            detector=detector,
            loader=self.loader,
            marked_detector=self.marked,
            quality=quality,
            noise_loader=self.noise_loader,
            fetch=None,
        )


@pytest.fixture
def run(
    tmp_path: Path, write_fixture_databases: Callable[[Path], tuple[Database, Database]]
) -> Run:
    root = tmp_path / "data"
    mitdb, nstdb = write_fixture_databases(root)
    return Run(root, mitdb, nstdb)


def test_false_negatives_and_false_positives_are_kept_per_record(run: Run) -> None:
    by_name = {record.record: record for record in run.results.records}
    assert by_name["100"].false_negatives == () and by_name["100"].false_positives == ()
    assert by_name["207"].false_negatives == (50000,)
    assert by_name["207"].false_positives == (60000,)
    assert (by_name["207"].counts.fn, by_name["207"].counts.fp) == (1, 1)


def test_the_records_are_loaded_in_the_order_of_the_steps(run: Run) -> None:
    mitdb = [run.root / "mitdb" / name for name in MITDB_NAMES]
    nstdb = [run.root / "nstdb" / name for name in NOISE_STRESS_RECORDS]
    # Detection, noise stress, start of stream, signal quality (records, then noise stress).
    assert run.loader.calls == mitdb + nstdb + mitdb + mitdb + nstdb
    assert run.noise_loader.calls == [run.root / "nstdb" / name for name in NOISE_NAMES]


def test_start_of_stream_step(run: Run) -> None:
    stream = run.results.start_of_stream
    assert stream is not None
    assert stream.segment_s == 60 and stream.starts_s == SEGMENT_STARTS_S
    assert [entry.record for entry in stream.records] == list(MITDB_NAMES)
    assert all(entry.n_segments == 30 for entry in stream.records)
    # The beat at 40000 lies in the segment from 37500, 2500 samples in: matched by the reliable
    # detection at 2500 (the start-up detection at 100 is not scored); the other 29 segments
    # have that detection without a reference beat. Record 207 has a second beat at 50000.
    counts = {
        entry.record: (entry.counts.tp, entry.counts.fn, entry.counts.fp)
        for entry in stream.records
    }
    assert counts == {
        "100": (1, 0, 29),
        "118": (1, 0, 29),
        "119": (1, 0, 29),
        "207": (1, 1, 29),
    }
    assert (stream.statistics.tp, stream.statistics.fn, stream.statistics.fp) == (4, 1, 116)
    assert (
        run.marked.calls == [(SEGMENT_SAMPLES + 1000, float(FS_HZ), 60)] * 120
    )  # segment + continuation


def test_quality_step_per_snr_and_clean_and_noise_records(run: Run) -> None:
    result = run.results.quality
    assert result is not None
    # Seven noisy stretches of 120 s: 111 windows of 10 s each, two records per SNR.
    summaries = dict(result.by_snr)
    assert list(summaries) == [24, 18, 12, 6, 0, -6]
    for snr in (24, 18, 12):
        assert (summaries[snr].n_windows, summaries[snr].n_usable) == (1554, 1554)
        assert summaries[snr].median_index == 0.9
    for snr in (6, 0, -6):
        assert (summaries[snr].n_windows, summaries[snr].n_usable) == (1554, 0)
        assert summaries[snr].median_index == 0.1
    # Records 118 and 119 from 5:00: windows 300 to 1850, 1551 each.
    assert (result.clean.n_windows, result.clean.n_usable) == (3102, 3102)
    # Every window of a noise record: 0 to 1850.
    assert [(name, s.n_windows, s.n_usable) for name, s in result.noise_records] == [
        (name, 1851, 0) for name in NOISE_NAMES
    ]
    assert all(passed for _, passed in result.criteria)


def test_quality_step_per_record_with_the_errors_in_not_usable_windows(run: Run) -> None:
    result = run.results.quality
    assert result is not None
    by_name = {entry.record: entry for entry in result.records}
    assert list(by_name) == list(MITDB_NAMES)
    for name in MITDB_NAMES:
        assert by_name[name].from_start.n_windows == 1551
    assert by_name["100"].from_start.n_usable == 1551
    assert by_name["207"].from_start.n_usable == 0
    assert (by_name["100"].fn_in_not_usable, by_name["100"].fp_in_not_usable) == (0, 0)
    assert (by_name["207"].fn_in_not_usable, by_name["207"].fp_in_not_usable) == (1, 1)


def test_full_report_of_the_run_has_sections_8_and_9_and_is_repeatable(run: Run) -> None:
    text = render_full_report(run.results)
    assert "## Signal quality index" in text and "## Start of stream" in text
    # Four records of 1551 windows each, three usable: 4653 of 6204 is 75.00 %.
    assert "| Total | 6204 | 75.00 | 1 | 1 |" in text
    # Start of stream: TP 4, FN 1, FP 116 gives Se 80.00 and +P 3.33.
    assert "| Gross |  | 120 | 4 | 1 | 116 | 80.00 | 3.33 |" in text
    assert render_full_report(run.execute()) == text
