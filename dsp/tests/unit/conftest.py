"""Helpers of the unit tests.

- A small synthetic ECG with known R-wave centres.
- Fixture WFDB records and databases for the evaluation: a record whose signal is 1 mV at
  the samples that the fake detector must report and 0 elsewhere, its annotation file, and a
  ``SHA256SUMS.txt`` with a ``Database`` pinned to it. A fixture database has a fixture
  licence of its own (name ``Fixture Licence of <slug> 1.0``, address
  ``https://licences.example/<slug>/``), so that a report shows where the licence comes from.
"""

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
import wfdb

from sinus_dsp.data.physionet import CHECKSUM_LIST_NAME, Database, DatabaseLicence

EcgFactory = Callable[..., tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]]

#: Sampling frequency of the fixture records: 5:00 is sample 6000, the match window 3 samples.
FIXTURE_FS_HZ = 20
FIXTURE_ADC_GAIN = 200.0

# (offset from the R centre in s, amplitude in mV, width in s, scales with sqrt(RR / 1 s))
_WAVES = (
    (-0.200, 0.15, 0.025, True),  # P
    (-0.030, -0.10, 0.010, False),  # Q
    (0.000, 1.00, 0.010, False),  # R
    (0.030, -0.20, 0.010, False),  # S
    (0.280, 0.30, 0.045, True),  # T
)


def _synthetic_ecg(
    fs_hz: float,
    heart_rate_bpm: float,
    variant: str = "clean",
    duration_s: float = 30.0,
    beat_gains: Mapping[int, float] | None = None,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]:
    """Sum of five Gaussian waves per beat; returns the signal in mV and the R-wave centres.

    Beat ``k`` is centred on the sample ``floor((0.5 + k * RR) * fs_hz + 0.5)``, for every
    ``k`` with ``0.5 + k * RR <= duration_s - 0.5``. ``variant`` is ``clean``, ``bw-mains50``
    or ``bw-mains60``: the last two add 1 mV of 0.3 Hz baseline wander and 0.2 mV of mains
    interference. ``beat_gains`` scales the whole waveform of single beats.
    """
    n_samples = int(round(duration_s * fs_hz))
    t = np.arange(n_samples) / fs_hz
    rr_s = 60.0 / heart_rate_bpm
    scale = math.sqrt(rr_s)
    signal = np.zeros(n_samples)
    r_peaks: list[int] = []
    k = 0
    while 0.5 + k * rr_s <= duration_s - 0.5:
        r_k = math.floor((0.5 + k * rr_s) * fs_hz + 0.5)
        r_peaks.append(r_k)
        gain = 1.0 if beat_gains is None else beat_gains.get(k, 1.0)
        for offset_s, amplitude_mv, width_s, scaled in _WAVES:
            centre_s = r_k / fs_hz + (offset_s * scale if scaled else offset_s)
            sigma_s = width_s * scale if scaled else width_s
            signal += gain * amplitude_mv * np.exp(-((t - centre_s) ** 2) / (2.0 * sigma_s**2))
        k += 1
    if variant != "clean":
        mains_hz = {"bw-mains50": 50.0, "bw-mains60": 60.0}[variant]
        signal += 1.0 * np.sin(2.0 * np.pi * 0.3 * t) + 0.2 * np.sin(2.0 * np.pi * mains_hz * t)
    return signal, np.array(r_peaks, dtype=np.int64)


@pytest.fixture(scope="session")
def synthetic_ecg() -> EcgFactory:
    """The synthetic ECG generator of the unit tests."""
    return _synthetic_ecg


def _write_fixture_record(
    folder: Path,
    name: str,
    *,
    n_samples: int,
    beats: Sequence[int] = (),
    beat_symbol: str = "N",
    others: Sequence[tuple[int, str]] = (),
    detections: Sequence[int] = (),
    fs_hz: float = FIXTURE_FS_HZ,
    units: str = "mV",
    signal_name: str = "MLII",
) -> None:
    """Write a two-channel record and its ``atr`` annotations into ``folder``.

    Channel 0 is 1 mV at the samples of ``detections`` and 0 elsewhere; channel 1 is 0.5 mV
    everywhere. The annotations are the beats (all with ``beat_symbol``) and the non-beat
    annotations ``others`` given as ``(sample, symbol)``, written in the order of their
    samples (beats first at equal samples). A record without any annotation gets a ``+`` at
    sample 0, because wfdb does not write an empty annotation file.
    """
    folder.mkdir(parents=True, exist_ok=True)
    first = np.zeros(n_samples)
    first[list(detections)] = 1.0
    second = np.full(n_samples, 0.5)
    wfdb.wrsamp(
        name,
        fs=fs_hz,
        units=[units, units],
        sig_name=[signal_name, "V1"],
        p_signal=np.column_stack([first, second]),
        fmt=["16", "16"],
        adc_gain=[FIXTURE_ADC_GAIN, FIXTURE_ADC_GAIN],
        baseline=[0, 0],
        write_dir=str(folder),
    )
    entries = [(sample, 0, beat_symbol) for sample in beats]
    entries += [(sample, 1, symbol) for sample, symbol in others]
    entries.sort()
    if not entries:
        entries = [(0, 1, "+")]
    wfdb.wrann(
        name,
        "atr",
        np.array([sample for sample, _, _ in entries], dtype=np.int64),
        symbol=[symbol for _, _, symbol in entries],
        write_dir=str(folder),
    )


def _fixture_licence(slug: str) -> DatabaseLicence:
    """The licence of a fixture database: one per slug, never that of the real databases."""
    return DatabaseLicence(f"Fixture Licence of {slug} 1.0", f"https://licences.example/{slug}/")


def _pin_database(
    folder: Path,
    title: str,
    *,
    records_file: Sequence[str] | None = None,
    licence: DatabaseLicence | None = None,
) -> Database:
    """Write ``SHA256SUMS.txt`` for every file of ``folder`` and return a Database pinned to it.

    With ``records_file`` given, a ``RECORDS`` file listing those names is written first. The
    slug of the database is the name of ``folder``; its version is ``1.0.0``; its licence is
    ``licence``, by default ``_fixture_licence(<slug>)``.
    """
    if records_file is not None:
        (folder / "RECORDS").write_bytes("".join(f"{name}\n" for name in records_file).encode())
    paths = sorted(
        path.relative_to(folder).as_posix()
        for path in folder.rglob("*")
        if path.is_file() and path.name != CHECKSUM_LIST_NAME
    )
    lines = [
        f"{hashlib.sha256((folder / path).read_bytes()).hexdigest()}  {path}\n" for path in paths
    ]
    content = "".join(lines).encode()
    (folder / CHECKSUM_LIST_NAME).write_bytes(content)
    return Database(
        slug=folder.name,
        version="1.0.0",
        title=title,
        checksum_list_sha256=hashlib.sha256(content).hexdigest(),
        licence=_fixture_licence(folder.name) if licence is None else licence,
    )


def _fake_detector(
    signal_mv: npt.NDArray[np.float64], fs_hz: float, mains_hz: int
) -> npt.NDArray[np.int64]:
    """The detections of a fixture record: the samples where its signal is above 0.5 mV."""
    return np.flatnonzero(np.asarray(signal_mv) > 0.5).astype(np.int64)


@pytest.fixture(scope="session")
def write_fixture_record() -> Callable[..., None]:
    """Writer of a fixture WFDB record (see ``_write_fixture_record``)."""
    return _write_fixture_record


@pytest.fixture(scope="session")
def pin_database() -> Callable[..., Database]:
    """Writer of the checksum list of a fixture database folder (see ``_pin_database``)."""
    return _pin_database


@pytest.fixture(scope="session")
def fake_detector() -> Callable[[npt.NDArray[np.float64], float, int], npt.NDArray[np.int64]]:
    """A detector that reports the samples where the fixture signal is 1 mV."""
    return _fake_detector


#: Noise stress record names, by record and by decreasing SNR (24, 18, 12, 6, 0, -6 dB).
_NOISE_STRESS_NAMES = tuple(
    f"{record}e{snr}" for record in ("118", "119") for snr in ("24", "18", "12", "06", "00", "_6")
)


def _write_fixture_databases(data_root: Path) -> tuple[Database, Database]:
    """Write a small arrhythmia database and a noise stress database under ``data_root``.

    With the fake detector (20 Hz, 5:00 = sample 6000, match window 3 samples):

    - ``mitdb``: ``RECORDS`` lists 207, 100, 119, 118 (not sorted), plus ``mitdbdir/notes.txt``.
      Counts (TP, FN, FP): 100 (2, 1, 1); 118 (2, 0, 0); 119 (3, 1, 0); 207 (2, 0, 0). Record
      207 has two episodes, one before 5:00 and one from 6200 to 6300 (101 samples), one
      reference beat and two unpaired detections inside the second, and two ``!`` outside
      the episodes: one before 5:00 (not counted) and one after it (counted).
    - ``nstdb``: the 12 noise stress records, plus ``RECORDS`` and ``old/readme.txt``. At the
      SNR index ``j`` (0 for 24 dB … 5 for -6 dB): TP 2, FN 0 for ``j < 3``, else TP 1, FN 1;
      FP 1 for ``j >= 4``, else 0.
    """
    mitdb_dir = data_root / "mitdb"
    write = _write_fixture_record
    write(mitdb_dir, "100", n_samples=6600, beats=[6100, 6200, 6300], detections=[6100, 6201, 6400])
    write(mitdb_dir, "118", n_samples=6600, beats=[6100, 6200], detections=[6100, 6200])
    write(
        mitdb_dir,
        "119",
        n_samples=6600,
        beats=[6100, 6200, 6300, 6400],
        detections=[6101, 6199, 6300],
    )
    write(
        mitdb_dir,
        "207",
        n_samples=6600,
        beats=[100, 6100, 6250, 6400],
        others=[(50, "["), (150, "]"), (300, "!"), (6200, "["), (6300, "]"), (6500, "!")],
        detections=[120, 6100, 6260, 6280, 6401],
    )
    (mitdb_dir / "mitdbdir").mkdir()
    (mitdb_dir / "mitdbdir" / "notes.txt").write_bytes(b"documentation\n")
    mitdb = _pin_database(
        mitdb_dir, "Fixture Arrhythmia Database", records_file=["207", "100", "119", "118"]
    )

    nstdb_dir = data_root / "nstdb"
    for index, name in enumerate(_NOISE_STRESS_NAMES):
        j = index % 6
        detections = [6100, *([6200] if j < 3 else []), *([6400] if j >= 4 else [])]
        write(nstdb_dir, name, n_samples=6600, beats=[6100, 6200], detections=detections)
    (nstdb_dir / "old").mkdir()
    (nstdb_dir / "old" / "readme.txt").write_bytes(b"older files\n")
    nstdb = _pin_database(
        nstdb_dir, "Fixture Noise Stress Database", records_file=_NOISE_STRESS_NAMES
    )
    return mitdb, nstdb


@pytest.fixture(scope="session")
def write_fixture_databases() -> Callable[[Path], tuple[Database, Database]]:
    """Writer of the two fixture databases (see ``_write_fixture_databases``)."""
    return _write_fixture_databases


#: Files of the fixture subset database that are not records: name -> content.
SUBSET_EXTRA_FILES = {
    "100.xws": b"waveform settings\n",
    "108.at_": b"further annotations of 108\n",
    "119.at_": b"further annotations of 119\n",
    "203.at-": b"older annotations of 203\n",
    "203.at_": b"further annotations of 203\n",
    "1001.dat": b"not a file of record 100\n",
    "mitdbdir/notes.txt": b"documentation\n",
    "x_mitdb/x_108.hea": b"not a top-level file\n",
}


def _write_subset_database(data_root: Path) -> Database:
    """Write a fixture arrhythmia database with the records of the subset under ``data_root``.

    With the fake detector (20 Hz, 5:00 = sample 6000, match window 3 samples), the counts
    (TP, FN, FP) are: 100 (2, 1, 1); 105 (2, 0, 2); 108 (1, 2, 0); 119 (3, 1, 0); 203
    (2, 0, 0); 207 (2, 0, 0), with the episodes and ``!`` annotations of record 207 of
    ``_write_fixture_databases``. Record 118, the ``RECORDS`` file and the files of
    ``SUBSET_EXTRA_FILES`` are there too; the selection of the six records holds 23 files.
    """
    folder = data_root / "mitdb"
    write = _write_fixture_record
    write(folder, "100", n_samples=6600, beats=[6100, 6200, 6300], detections=[6100, 6201, 6400])
    write(folder, "105", n_samples=6600, beats=[6100, 6200], detections=[6100, 6200, 6300, 6350])
    write(folder, "108", n_samples=6600, beats=[6100, 6200, 6300], detections=[6100])
    write(folder, "118", n_samples=6600, beats=[6100, 6200], detections=[6100, 6200])
    write(
        folder,
        "119",
        n_samples=6600,
        beats=[6100, 6200, 6300, 6400],
        detections=[6101, 6199, 6300],
    )
    write(folder, "203", n_samples=6600, beats=[6100, 6200], detections=[6100, 6200])
    write(
        folder,
        "207",
        n_samples=6600,
        beats=[100, 6100, 6250, 6400],
        others=[(50, "["), (150, "]"), (300, "!"), (6200, "["), (6300, "]"), (6500, "!")],
        detections=[120, 6100, 6260, 6280, 6401],
    )
    for name, content in SUBSET_EXTRA_FILES.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return _pin_database(
        folder,
        "Fixture Arrhythmia Database",
        records_file=["100", "105", "108", "118", "119", "203", "207"],
    )


@pytest.fixture(scope="session")
def write_subset_database() -> Callable[[Path], Database]:
    """Writer of the fixture database of the subset check (see ``_write_subset_database``)."""
    return _write_subset_database
