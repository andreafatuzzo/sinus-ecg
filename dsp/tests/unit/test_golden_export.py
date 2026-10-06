"""Unit tests of ``sinus_dsp.golden.export_golden_vectors`` (architecture §8.12).

The record segments come from a fixture database whose files are pinned by a fixture checksum
list. Most tests use a fake loader that returns records built from the synthetic ECG; one test
reads WFDB records written with ``wfdb``.
"""

import hashlib
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import wfdb

from sinus_dsp import golden
from sinus_dsp.data.physionet import CHECKSUM_LIST_NAME, MITDB, Database, DatabaseLicence
from sinus_dsp.data.records import Record, load_record
from sinus_dsp.errors import InvalidInputError, MalformedFileError, NonFiniteOutputError
from sinus_dsp.evaluation.subset import SUBSET_RECORDS
from sinus_dsp.golden import (
    ExportSummary,
    export_golden_vectors,
    golden_vector,
    read_golden_vector,
    render_golden_vector,
)
from sinus_dsp.pipeline import run_pipeline
from sinus_dsp.synthetic import synthetic_ecg, synthetic_set
from sinus_dsp.version import SoftwareIdentity, software_identity

DSP_DIR = Path(__file__).resolve().parents[2]
SYNTHETIC_FILES = [f"{ecg.input_id}.golden.txt" for ecg in synthetic_set()]
FIXTURE_FS_HZ = 250.0
SEGMENT = 15000  # 60 s at 250 Hz
RECORD_SAMPLES = 15500  # 62 s at 250 Hz
IDENTITY = SoftwareIdentity(
    version="9.9.9.dev0", source_sha256="f" * 64, python="3.11", runtime=(("numpy", "x"),)
)

PinDatabase = Callable[..., Database]


def fixture_signal(gain: float, n_samples: int = RECORD_SAMPLES) -> np.ndarray[Any, Any]:
    """The synthetic ECG at 250 Hz, 75 bpm, with interference, repeated, times ``gain``."""
    ecg = synthetic_ecg(FIXTURE_FS_HZ, 75, "bw-mains60")
    return np.asarray(np.tile(ecg.signal_mv, 3)[:n_samples] * gain, dtype=np.float64)


def fixture_beats(n_samples: int = RECORD_SAMPLES) -> np.ndarray[Any, Any]:
    """The R-wave centres of the repeated ECG, the first one twice (equal samples)."""
    r_peaks = synthetic_ecg(FIXTURE_FS_HZ, 75, "clean").r_peaks
    beats = np.concatenate([r_peaks + 7500 * k for k in range(3)])
    beats = beats[beats < n_samples]
    return np.concatenate([beats[:1], beats]).astype(np.int64)


class FakeLoader:
    """Returns a record built from the synthetic ECG; records the calls."""

    def __init__(
        self,
        samples: dict[str, int] | None = None,
        constant: dict[str, float] | None = None,
        fs_hz: float = FIXTURE_FS_HZ,
        beats: dict[str, list[int]] | None = None,
    ) -> None:
        self.calls: list[tuple[Path, int]] = []
        self.samples = samples or {}
        self.constant = constant or {}
        self.fs_hz = fs_hz
        self.beats = beats or {}

    def __call__(self, path: Path, channel: int) -> Record:
        self.calls.append((path, channel))
        name = path.name
        n_samples = self.samples.get(name, RECORD_SAMPLES)
        if name in self.constant:
            signal = np.full(n_samples, self.constant[name])
        else:
            signal = fixture_signal(1.0 + int(name) / 1000.0, n_samples)
        if name in self.beats:
            beats = np.array(self.beats[name], dtype=np.int64)
        else:
            beats = fixture_beats(n_samples)
        return Record(
            name=name,
            channel=channel,
            signal_name="MLII",
            fs_hz=self.fs_hz,
            signal_mv=signal,
            beat_samples=beats,
            beat_symbols=tuple("N" for _ in beats.tolist()),
            other_annotations=(),
        )


def write_database(root: Path, pin_database: PinDatabase, names: Sequence[str]) -> Database:
    """Files ``<name>.hea/.dat/.atr`` with fixture content, and a checksum list pinning them."""
    folder = root / "mitdb"
    folder.mkdir(parents=True)
    for name in names:
        for extension in ("hea", "dat", "atr"):
            (folder / f"{name}.{extension}").write_bytes(f"{name}.{extension}\n".encode())
    return pin_database(folder, "Fixture Arrhythmia Database", records_file=list(names))


@pytest.fixture
def database(tmp_path: Path, pin_database: PinDatabase) -> tuple[Path, Database]:
    root = tmp_path / "data"
    return root, write_database(root, pin_database, SUBSET_RECORDS)


def names_in(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


# --- interface ---------------------------------------------------------------------------------


def test_defaults() -> None:
    assert export_golden_vectors.__kwdefaults__ == {
        "database": MITDB,
        "records": SUBSET_RECORDS,
        "loader": load_record,
    }


def test_golden_module_can_be_imported_first() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import sinus_dsp.golden"],
        check=True,
        capture_output=True,
        text=True,
        cwd=DSP_DIR,
    )
    assert completed.stderr == ""


# --- without the database ----------------------------------------------------------------------


def test_without_the_database_only_the_synthetic_files_are_written(tmp_path: Path) -> None:
    data_root = tmp_path / "no-data"
    output = tmp_path / "out" / "golden"
    loader = FakeLoader()
    summary = export_golden_vectors(output, data_root=data_root, loader=loader)
    assert summary == ExportSummary(
        written=tuple(SYNTHETIC_FILES),
        skipped=tuple(f"mitdb-{name}-first60s" for name in SUBSET_RECORDS),
        skip_reason="mitdb 1.0.0 not verified: missing: SHA256SUMS.txt",
    )
    assert names_in(output) == sorted(SYNTHETIC_FILES)
    assert not data_root.exists()
    assert loader.calls == []


def test_each_synthetic_file_holds_the_vector_of_its_input(tmp_path: Path) -> None:
    output = tmp_path / "golden"
    export_golden_vectors(output, data_root=tmp_path / "no-data")
    software = software_identity()
    for ecg in synthetic_set():
        vector = golden_vector(
            ecg.input_id,
            "synthetic",
            ecg.parameters,
            ecg.signal_mv,
            ecg.fs_hz,
            ecg.mains_hz,
            ecg.r_peaks,
            software=software,
        )
        path = output / f"{ecg.input_id}.golden.txt"
        assert path.read_bytes() == render_golden_vector(vector).encode("utf-8")


def test_skipped_segments_are_named_once_in_code_point_order(
    tmp_path: Path, pin_database: PinDatabase
) -> None:
    root = tmp_path / "data"
    database = write_database(root, pin_database, ["100", "99"])
    (root / "mitdb" / "99.dat").write_bytes(b"altered")
    summary = export_golden_vectors(
        tmp_path / "out",
        data_root=root,
        database=database,
        records=["99", "100", "99"],
        loader=FakeLoader(),
    )
    assert summary.skipped == ("mitdb-100-first60s", "mitdb-99-first60s")
    assert summary.skip_reason == "mitdb 1.0.0 not verified: checksum mismatch: 99.dat"
    assert summary.written == tuple(SYNTHETIC_FILES)


def test_a_record_that_is_not_verified_skips_every_segment(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    (root / "mitdb" / "203.atr").unlink()
    (root / "mitdb" / "105.dat").write_bytes(b"altered")
    loader = FakeLoader()
    summary = export_golden_vectors(
        tmp_path / "out", data_root=root, database=fixture, loader=loader
    )
    assert summary.skipped == tuple(f"mitdb-{name}-first60s" for name in SUBSET_RECORDS)
    assert summary.skip_reason == (
        "mitdb 1.0.0 not verified: missing: 203.atr; checksum mismatch: 105.dat"
    )
    assert loader.calls == []
    assert names_in(tmp_path / "out") == sorted(SYNTHETIC_FILES)


# --- with the database -------------------------------------------------------------------------


def test_segments_follow_the_synthetic_files_in_code_point_order(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    loader = FakeLoader()
    summary = export_golden_vectors(
        tmp_path / "out",
        data_root=root,
        database=fixture,
        records=["207", "100", "119", "100"],
        loader=loader,
    )
    segments = ["mitdb-100-first60s.golden.txt", "mitdb-119-first60s.golden.txt"]
    segments.append("mitdb-207-first60s.golden.txt")
    assert summary == ExportSummary(
        written=(*SYNTHETIC_FILES, *segments), skipped=(), skip_reason=None
    )
    assert loader.calls == [(root / "mitdb" / name, 0) for name in ("100", "119", "207")]
    assert names_in(tmp_path / "out") == sorted([*SYNTHETIC_FILES, *segments])


def test_a_segment_is_the_first_60_s_processed_on_its_own(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    export_golden_vectors(
        tmp_path / "out", data_root=root, database=fixture, records=["105"], loader=FakeLoader()
    )
    vector = read_golden_vector(tmp_path / "out" / "mitdb-105-first60s.golden.txt")
    signal = fixture_signal(1.105)
    beats = fixture_beats()
    assert vector.input_id == "mitdb-105-first60s"
    assert vector.input_source == "mitdb"
    assert vector.input_parameters == (
        "database=mitdb;database_version=1.0.0;record=105;signal=0;start_sample=0;duration_s=60"
    )
    assert vector.fs_hz == 250.0
    assert vector.mains_hz == 60
    assert vector.input_mv.tobytes() == signal[:SEGMENT].tobytes()
    reference = beats[beats < SEGMENT]
    assert vector.reference_beats.tolist() == reference.tolist()
    assert reference[0] == reference[1]  # equal annotated samples are kept
    assert int(beats.max()) >= SEGMENT  # beats after the segment exist and are left out
    result = run_pipeline(signal[:SEGMENT], 250.0, 60)
    assert vector.beats.tobytes() == result.beats.tobytes()
    assert vector.stage_outputs_mv[1].tobytes() == result.mains_mv.tobytes()


def test_the_software_identity_is_taken_once(
    database: tuple[Path, Database], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, fixture = database
    calls: list[None] = []

    def fixed_identity() -> SoftwareIdentity:
        calls.append(None)
        return IDENTITY

    monkeypatch.setattr(golden, "software_identity", fixed_identity)
    summary = export_golden_vectors(
        tmp_path / "out", data_root=root, database=fixture, loader=FakeLoader()
    )
    assert len(calls) == 1
    assert len(summary.written) == 24
    for name in summary.written:
        vector = read_golden_vector(tmp_path / "out" / name)
        assert (vector.software_version, vector.source_sha256) == ("9.9.9.dev0", "f" * 64)


def test_two_exports_write_byte_identical_files(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    first = export_golden_vectors(
        tmp_path / "a", data_root=root, database=fixture, loader=FakeLoader()
    )
    second = export_golden_vectors(
        tmp_path / "b", data_root=root, database=fixture, loader=FakeLoader()
    )
    assert first == second
    for name in first.written:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_files_with_the_names_written_are_replaced_and_others_kept(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    output = tmp_path / "out"
    output.mkdir()
    (output / "mitdb-100-first60s.golden.txt").write_bytes(b"old\n")
    (output / "mitdb-100-first60s.golden.txt.part~").write_bytes(b"interrupted\n")
    (output / "other.golden.txt").write_bytes(b"other\n")
    (output / "notes.md").write_bytes(b"notes\n")
    export_golden_vectors(
        output, data_root=root, database=fixture, records=["100"], loader=FakeLoader()
    )
    assert read_golden_vector(output / "mitdb-100-first60s.golden.txt").input_id == (
        "mitdb-100-first60s"
    )
    assert (output / "other.golden.txt").read_bytes() == b"other\n"
    assert (output / "notes.md").read_bytes() == b"notes\n"
    assert names_in(output) == sorted(
        [*SYNTHETIC_FILES, "mitdb-100-first60s.golden.txt", "other.golden.txt", "notes.md"]
    )


def test_a_record_of_exactly_60_s_is_exported(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    loader = FakeLoader(samples={"100": 21600}, fs_hz=360.0)
    export_golden_vectors(
        tmp_path / "out", data_root=root, database=fixture, records=["100"], loader=loader
    )
    vector = read_golden_vector(tmp_path / "out" / "mitdb-100-first60s.golden.txt")
    assert vector.input_mv.shape == (21600,)
    assert vector.fs_hz == 360.0


def test_reference_beats_are_those_below_the_segment_end(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    beats = {"100": [0, 7, 7, SEGMENT - 1, SEGMENT, SEGMENT + 1, RECORD_SAMPLES - 1]}
    loader = FakeLoader(beats=beats)
    export_golden_vectors(
        tmp_path / "out", data_root=root, database=fixture, records=["100"], loader=loader
    )
    vector = read_golden_vector(tmp_path / "out" / "mitdb-100-first60s.golden.txt")
    assert vector.reference_beats.tolist() == [0, 7, 7, SEGMENT - 1]


# --- errors ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ((), "the record selection is empty"),
        ([], "the record selection is empty"),
        ("100", "records is a string"),
        (["10 0"], "invalid record name"),
        (["100", 105], "invalid record name"),
        (None, "records is None"),
    ],
)
def test_an_invalid_record_selection_is_rejected_before_anything_is_written(
    database: tuple[Path, Database],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    records: Any,
    message: str,
) -> None:
    root, fixture = database

    def never() -> SoftwareIdentity:
        raise AssertionError("the identity is taken after the verification")

    monkeypatch.setattr(golden, "software_identity", never)
    loader = FakeLoader()
    with pytest.raises(InvalidInputError, match=message):
        export_golden_vectors(
            tmp_path / "out", data_root=root, database=fixture, records=records, loader=loader
        )
    assert not (tmp_path / "out").exists()
    assert loader.calls == []


def test_a_malformed_checksum_list_is_raised_before_anything_is_written(tmp_path: Path) -> None:
    root = tmp_path / "data"
    folder = root / "mitdb"
    folder.mkdir(parents=True)
    content = b"not a checksum entry\n"
    (folder / CHECKSUM_LIST_NAME).write_bytes(content)
    licence = DatabaseLicence("Fixture Licence 1.0", "https://licences.example/mitdb/")
    database = Database("mitdb", "1.0.0", "Fixture", hashlib.sha256(content).hexdigest(), licence)
    with pytest.raises(MalformedFileError, match="not a checksum entry"):
        export_golden_vectors(tmp_path / "out", data_root=root, database=database)
    assert not (tmp_path / "out").exists()


def test_a_short_record_stops_the_export_and_keeps_the_files_written(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    loader = FakeLoader(samples={"105": SEGMENT - 1})
    with pytest.raises(InvalidInputError) as caught:
        export_golden_vectors(tmp_path / "out", data_root=root, database=fixture, loader=loader)
    assert str(caught.value) == (
        "record 105 is shorter than its 60 s segment: 14999 samples at 250.0 Hz, 15000 needed"
    )
    written = sorted([*SYNTHETIC_FILES, "mitdb-100-first60s.golden.txt"])
    assert names_in(tmp_path / "out") == written
    for name in written:
        read_golden_vector(tmp_path / "out" / name)
    assert [path.name for path, _ in loader.calls] == ["100", "105"]


@pytest.mark.parametrize(
    "error",
    [
        InvalidInputError("record has no channel 0"),
        MalformedFileError("x.atr", None, "annotation sample indices decrease"),
    ],
)
def test_errors_of_the_loader_propagate(
    database: tuple[Path, Database], tmp_path: Path, error: Exception
) -> None:
    root, fixture = database

    def failing(path: Path, channel: int) -> Record:
        raise error

    with pytest.raises(type(error)) as caught:
        export_golden_vectors(tmp_path / "out", data_root=root, database=fixture, loader=failing)
    assert caught.value is error
    assert names_in(tmp_path / "out") == sorted(SYNTHETIC_FILES)


def test_a_non_finite_output_stops_the_export(
    database: tuple[Path, Database], tmp_path: Path
) -> None:
    root, fixture = database
    loader = FakeLoader(constant={"108": 1e308})
    with pytest.raises(NonFiniteOutputError) as caught:
        export_golden_vectors(tmp_path / "out", data_root=root, database=fixture, loader=loader)
    assert caught.value.input_id == "mitdb-108-first60s"
    assert names_in(tmp_path / "out") == sorted(
        [*SYNTHETIC_FILES, "mitdb-100-first60s.golden.txt", "mitdb-105-first60s.golden.txt"]
    )


def test_an_unwritable_output_folder_raises_os_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_bytes(b"not a folder\n")
    with pytest.raises(OSError):
        export_golden_vectors(blocker / "golden", data_root=tmp_path / "no-data")


# --- the default loader on WFDB records --------------------------------------------------------


def _write_wfdb_record(folder: Path, name: str, gain: float) -> np.ndarray[Any, Any]:
    signal = fixture_signal(gain)
    wfdb.wrsamp(
        name,
        fs=FIXTURE_FS_HZ,
        units=["mV", "mV"],
        sig_name=["MLII", "V1"],
        p_signal=np.column_stack([signal, np.zeros_like(signal)]),
        fmt=["16", "16"],
        adc_gain=[1000.0, 1000.0],
        baseline=[0, 0],
        write_dir=str(folder),
    )
    beats = fixture_beats()
    wfdb.wrann(name, "atr", beats, symbol=["N"] * len(beats), write_dir=str(folder))
    return beats


def test_records_read_with_the_default_loader(tmp_path: Path, pin_database: PinDatabase) -> None:
    root = tmp_path / "data"
    folder = root / "mitdb"
    folder.mkdir(parents=True)
    beats = {
        name: _write_wfdb_record(folder, name, gain) for name, gain in (("100", 1.0), ("119", 0.8))
    }
    database = pin_database(folder, "Fixture Arrhythmia Database")
    output = tmp_path / "out"
    summary = export_golden_vectors(
        output, data_root=root, database=database, records=["119", "100"]
    )
    assert summary.written[-2:] == (
        "mitdb-100-first60s.golden.txt",
        "mitdb-119-first60s.golden.txt",
    )
    for name in ("100", "119"):
        record = load_record(folder / name, 0)
        vector = read_golden_vector(output / f"mitdb-{name}-first60s.golden.txt")
        assert vector.input_mv.tobytes() == record.signal_mv[:SEGMENT].tobytes()
        assert vector.reference_beats.tolist() == [b for b in beats[name].tolist() if b < SEGMENT]
        result = run_pipeline(record.signal_mv[:SEGMENT], record.fs_hz, 60)
        assert vector.beats.tobytes() == result.beats.tobytes()
        assert vector.beats.shape[0] > 50
