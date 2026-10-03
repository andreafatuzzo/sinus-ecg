"""Shared fixtures of the requirement tests.

The helpers here are independent of the software under test: they build the test inputs
(synthetic ECGs with known QRS positions, sinusoids, WFDB records, database folders with
their checksum list, a fetch function that serves bytes from a dictionary, random beat and
detection lists around 5:00, fixture databases for the evaluation with a detector double
whose output is known, copies of the package under test run in a separate process) and apply
the pass criteria of the requirements to its outputs (including reading the tables of a
Markdown report, and the software identity a report must state, computed by the test from
the source files with the documented method). Each helper is exposed as a fixture that
returns a function, a class or the fixture data.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib
import importlib.metadata
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tomllib
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

FloatArray = npt.NDArray[np.float64]
IndexArray = npt.NDArray[np.int64]

# Synthetic ECG of docs/regulatory/architecture.md, section 7.2: each beat is the sum of five
# Gaussian waves. Columns: offset from the R centre (ms), amplitude (mV), width sigma (ms),
# and whether the offset and the width scale with sqrt(RR / 1 s).
_WAVES: tuple[tuple[str, float, float, float, bool], ...] = (
    ("P", -200.0, 0.15, 25.0, True),
    ("Q", -30.0, -0.10, 10.0, False),
    ("R", 0.0, 1.00, 10.0, False),
    ("S", 30.0, -0.20, 10.0, False),
    ("T", 280.0, 0.30, 45.0, True),
)

BASELINE_WANDER_HZ = 0.3
BASELINE_WANDER_MV = 1.0
MAINS_INTERFERENCE_MV = 0.2


@dataclass(frozen=True)
class SyntheticEcg:
    """A synthetic ECG and the true positions of its QRS complexes."""

    fs_hz: float
    signal_mv: FloatArray
    qrs_samples: IndexArray


def _synthetic_ecg(
    fs_hz: int,
    heart_rate_bpm: int,
    *,
    n_samples: int | None = None,
    mains_hz: int | None = None,
) -> SyntheticEcg:
    """Deterministic synthetic ECG with known QRS positions.

    - Sample instants t_n = n / fs_hz, for n = 0 .. n_samples - 1 (30 s by default).
    - RR = 60 / heart rate. The R wave of beat k is centred on the sample
      r_k = floor((0.5 + k * RR) * fs_hz + 0.5), for every k >= 0 with
      0.5 + k * RR <= duration - 0.5 s. The r_k are computed in exact rational arithmetic.
    - Each beat is the sum of the five Gaussian waves of ``_WAVES``, centred at
      r_k / fs_hz + offset; the R wave has an amplitude of 1 mV.
    - With ``mains_hz``, a 0.3 Hz sinusoidal baseline wander of 1 mV and a sinusoid of 0.2 mV
      at ``mains_hz`` are added (the interference of SRS-010).
    """
    if n_samples is None:
        n_samples = 30 * fs_hz
    t_s = np.arange(n_samples, dtype=np.float64) / fs_hz

    rr = Fraction(60, heart_rate_bpm)
    last_centre_s = Fraction(n_samples, fs_hz) - Fraction(1, 2)
    n_beats = max(0, math.floor((last_centre_s - Fraction(1, 2)) / rr) + 1)
    qrs = [math.floor((Fraction(1, 2) + k * rr) * fs_hz + Fraction(1, 2)) for k in range(n_beats)]

    scale = math.sqrt(60.0 / heart_rate_bpm)
    signal = np.zeros(n_samples, dtype=np.float64)
    for r in qrs:
        for _name, offset_ms, amplitude_mv, sigma_ms, scaled in _WAVES:
            factor = scale if scaled else 1.0
            centre_s = r / fs_hz + offset_ms * factor / 1000.0
            sigma_s = sigma_ms * factor / 1000.0
            signal += amplitude_mv * np.exp(-((t_s - centre_s) ** 2) / (2.0 * sigma_s**2))

    if mains_hz is not None:
        signal += BASELINE_WANDER_MV * np.sin(2.0 * np.pi * BASELINE_WANDER_HZ * t_s)
        signal += MAINS_INTERFERENCE_MV * np.sin(2.0 * np.pi * mains_hz * t_s)

    return SyntheticEcg(
        fs_hz=float(fs_hz), signal_mv=signal, qrs_samples=np.asarray(qrs, dtype=np.int64)
    )


def _sinusoid(
    frequency_hz: float,
    fs_hz: float,
    duration_s: float,
    *,
    phase_rad: float = 0.0,
    amplitude_mv: float = 1.0,
) -> FloatArray:
    """``amplitude_mv * sin(2 pi f n / fs + phase)`` for n = 0 .. round(duration * fs) - 1."""
    n = np.arange(round(duration_s * fs_hz), dtype=np.float64)
    out: FloatArray = amplitude_mv * np.sin(2.0 * np.pi * frequency_hz * n / fs_hz + phase_rad)
    return out


def _second_half_rms(signal_mv: npt.ArrayLike) -> float:
    """RMS of the second half of a signal (samples n // 2 to the end)."""
    x = np.asarray(signal_mv, dtype=np.float64)
    half = x[x.size // 2 :]
    return float(np.sqrt(np.mean(half**2)))


def _match_window_samples(fs_hz: float) -> int:
    """'Within 150 ms' in samples: the bound is kept exact, floor(0.150 * fs_hz)."""
    return math.floor(150 * fs_hz / 1000)


def _min_spacing_samples(fs_hz: float) -> int:
    """'No closer than 200 ms' in samples: the bound is kept exact, ceil(0.200 * fs_hz)."""
    return math.ceil(200 * fs_hz / 1000)


def _detection_errors(
    detections: npt.ArrayLike, qrs_samples: npt.ArrayLike, fs_hz: float
) -> list[str]:
    """Violations of 'exactly one detection within 150 ms of every QRS, and no other detection'.

    Returns one message per QRS that does not have exactly one detection within
    floor(0.150 * fs_hz) samples, and one per detection that lies within that distance of no
    QRS. An empty list means that the criterion holds.
    """
    window = _match_window_samples(fs_hz)
    det = np.asarray(detections, dtype=np.int64).reshape(-1)
    qrs = np.asarray(qrs_samples, dtype=np.int64).reshape(-1)
    errors: list[str] = []
    for r in qrs.tolist():
        near = det[np.abs(det - r) <= window]
        if near.size != 1:
            errors.append(
                f"QRS at sample {r}: {near.size} detections within {window} samples "
                f"{near.tolist()}, expected exactly 1"
            )
    for d in det.tolist():
        if not np.any(np.abs(qrs - d) <= window):
            errors.append(f"detection at sample {d}: no QRS within {window} samples")
    return errors


def _ordering_errors(detections: npt.ArrayLike, fs_hz: float) -> list[str]:
    """Violations of 'strictly increasing, and no two indices closer than 200 ms'.

    Returns one message per pair of consecutive indices that is not increasing or whose
    distance is below ceil(0.200 * fs_hz) samples. An empty list means that the criterion holds.
    """
    spacing = _min_spacing_samples(fs_hz)
    det = np.asarray(detections, dtype=np.int64).reshape(-1).tolist()
    errors: list[str] = []
    for previous, current in zip(det[:-1], det[1:], strict=True):
        if current <= previous:
            errors.append(f"indices {previous}, {current}: not strictly increasing")
        elif current - previous < spacing:
            errors.append(
                f"indices {previous}, {current}: {current - previous} samples apart, "
                f"minimum {spacing}"
            )
    return errors


@pytest.fixture(scope="session")
def make_synthetic_ecg() -> Callable[..., SyntheticEcg]:
    """``make_synthetic_ecg(fs_hz, heart_rate_bpm, *, n_samples=None, mains_hz=None)``."""
    return _synthetic_ecg


@pytest.fixture(scope="session")
def make_sinusoid() -> Callable[..., FloatArray]:
    """``make_sinusoid(frequency_hz, fs_hz, duration_s, *, phase_rad=0.0, amplitude_mv=1.0)``."""
    return _sinusoid


@pytest.fixture(scope="session")
def second_half_rms() -> Callable[[npt.ArrayLike], float]:
    """``second_half_rms(signal_mv)``: RMS of the second half of a signal."""
    return _second_half_rms


@pytest.fixture(scope="session")
def match_window_samples() -> Callable[[float], int]:
    """``match_window_samples(fs_hz)``: 150 ms in samples, rounded down."""
    return _match_window_samples


@pytest.fixture(scope="session")
def min_spacing_samples() -> Callable[[float], int]:
    """``min_spacing_samples(fs_hz)``: 200 ms in samples, rounded up."""
    return _min_spacing_samples


@pytest.fixture(scope="session")
def detection_errors() -> Callable[[npt.ArrayLike, npt.ArrayLike, float], list[str]]:
    """``detection_errors(detections, qrs_samples, fs_hz)``: see ``_detection_errors``."""
    return _detection_errors


@pytest.fixture(scope="session")
def ordering_errors() -> Callable[[npt.ArrayLike, float], list[str]]:
    """``ordering_errors(detections, fs_hz)``: see ``_ordering_errors``."""
    return _ordering_errors


# --------------------------------------------------------------------------------------------
# WFDB records written by the tests
# --------------------------------------------------------------------------------------------

# One annotation: sample index, WFDB symbol, subtype, auxiliary note.
AnnotationTuple = tuple[int, str, int, str]


def _write_wfdb_record(
    folder: Path,
    name: str,
    *,
    fs_hz: float,
    signals_mv: npt.ArrayLike,
    signal_names: Sequence[str],
    units: Sequence[str] | None = None,
    fmt: str = "212",
    adc_gain: Sequence[float] | None = None,
    baseline: Sequence[int] | None = None,
    annotations: Sequence[AnnotationTuple] | None = None,
    annotator: str = "atr",
) -> Path:
    """Write a WFDB record with the wfdb package and return its path without extension.

    - ``signals_mv`` has one row per sample and one column per signal, in physical units.
    - Defaults: units ``mV``, an ADC gain of 200 per mV and a baseline of 1024 for every
      signal (the values of the MIT-BIH Arrhythmia Database), storage format 212.
    - With ``annotations``, an annotation file ``<name>.<annotator>`` is written with the
      given samples, symbols, subtypes and auxiliary notes, in the given order.
    """
    import wfdb

    physical = np.asarray(signals_mv, dtype=np.float64)
    n_signals = physical.shape[1]
    wfdb.wrsamp(
        name,
        fs=fs_hz,
        units=list(units) if units is not None else ["mV"] * n_signals,
        sig_name=list(signal_names),
        p_signal=physical,
        fmt=[fmt] * n_signals,
        adc_gain=list(adc_gain) if adc_gain is not None else [200.0] * n_signals,
        baseline=list(baseline) if baseline is not None else [1024] * n_signals,
        write_dir=str(folder),
    )
    if annotations is not None:
        wfdb.wrann(
            name,
            annotator,
            np.asarray([a[0] for a in annotations], dtype=np.int64),
            [a[1] for a in annotations],
            subtype=np.asarray([a[2] for a in annotations], dtype=np.int64),
            aux_note=[a[3] for a in annotations],
            fs=fs_hz,
            write_dir=str(folder),
        )
    return folder / name


@pytest.fixture(scope="session")
def write_wfdb_record() -> Callable[..., Path]:
    """``write_wfdb_record(folder, name, *, fs_hz, signals_mv, signal_names, ...)``.

    See ``_write_wfdb_record``.
    """
    return _write_wfdb_record


# --------------------------------------------------------------------------------------------
# Database folders with their SHA-256 checksum list, and a fetch function without network
# --------------------------------------------------------------------------------------------

CHECKSUM_LIST_NAME = "SHA256SUMS.txt"


@dataclass(frozen=True)
class DatabaseFolder:
    """A database folder prepared by a test, and the checksum list of its files."""

    data_root: Path
    folder: Path
    files: dict[str, bytes]
    checksum_list: bytes
    checksum_list_sha256: str


def _sha256_hex(data: bytes) -> str:
    """SHA-256 of ``data`` as 64 lowercase hexadecimal digits."""
    return hashlib.sha256(data).hexdigest()


def _checksum_list(files: Mapping[str, bytes]) -> bytes:
    """Checksum list in the format that PhysioNet publishes.

    One line per file, ``<64 hexadecimal digits> <relative path>``, paths with ``/`` and in
    code-point order, each line ended by a line feed.
    """
    lines = [f"{_sha256_hex(files[path])} {path}\n" for path in sorted(files)]
    return "".join(lines).encode("ascii")


def _write_database_folder(
    data_root: Path,
    slug: str,
    files: Mapping[str, bytes],
    *,
    with_files: bool = True,
    with_list: bool = True,
) -> DatabaseFolder:
    """Describe a database of ``files`` (relative path -> content) and write it on request.

    The folder is ``data_root / slug``. With ``with_files`` every file is written, in its
    subfolder if it has one; with ``with_list`` the checksum list ``SHA256SUMS.txt`` is
    written. The returned object gives the list and its SHA-256, to be pinned in the
    ``Database`` under test.
    """
    folder = data_root / slug
    checksum_list = _checksum_list(files)
    if with_files:
        for path, content in files.items():
            target = folder.joinpath(*path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    if with_list:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / CHECKSUM_LIST_NAME).write_bytes(checksum_list)
    return DatabaseFolder(
        data_root=data_root,
        folder=folder,
        files=dict(files),
        checksum_list=checksum_list,
        checksum_list_sha256=_sha256_hex(checksum_list),
    )


class FakeFetch:
    """Fetch function that serves bytes from a dictionary, without network.

    ``FakeFetch(contents)`` maps URLs to contents. A call returns the content of the URL, or
    raises ``OSError`` when the URL is not in the dictionary. ``calls`` lists the URLs asked,
    in order.
    """

    def __init__(self, contents: Mapping[str, bytes]) -> None:
        self.contents = dict(contents)
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url not in self.contents:
            raise OSError(f"nothing is served at {url}")
        return self.contents[url]


@pytest.fixture(scope="session")
def sha256_hex() -> Callable[[bytes], str]:
    """``sha256_hex(data)``: SHA-256 as 64 lowercase hexadecimal digits."""
    return _sha256_hex


@pytest.fixture(scope="session")
def make_checksum_list() -> Callable[[Mapping[str, bytes]], bytes]:
    """``make_checksum_list(files)``: see ``_checksum_list``."""
    return _checksum_list


@pytest.fixture(scope="session")
def write_database_folder() -> Callable[..., DatabaseFolder]:
    """``write_database_folder(data_root, slug, files, *, with_files=True, with_list=True)``.

    See ``_write_database_folder``.
    """
    return _write_database_folder


@pytest.fixture(scope="session")
def make_fake_fetch() -> type[FakeFetch]:
    """``make_fake_fetch(contents)``: see ``FakeFetch``."""
    return FakeFetch


# --------------------------------------------------------------------------------------------
# Beat matching around 5:00 (SRS-008, SRS-012): random configurations and the rule at 5:00
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchingCase:
    """Reference beats, detections and ventricular flutter episodes of one random case.

    Samples are at 360 Hz; both lists are strictly increasing. Each episode is a pair
    (onset sample, offset sample), both included, in increasing order and not overlapping.
    """

    reference: tuple[int, ...]
    detections: tuple[int, ...]
    episodes: tuple[tuple[int, int], ...]


def _matching_cases(
    seed: int, count: int, *, start: int = 108000, window: int = 54
) -> list[MatchingCase]:
    """``count`` random configurations around 5:00 (``start``), with a fixed seed.

    - Reference beats from up to 1500 samples before ``start`` to 3000 samples after it,
      40 to 400 samples apart (so closer than twice the match window at times).
    - A detection near 80% of the beats (up to 80 samples before or after), plus 0 to 5
      detections anywhere; with probability 0.3 each, a detection from 0 to ``window + 1``
      samples after ``start`` and one from 1 to 60 samples before it.
    - 0 to 2 episodes of 0 to 1500 samples, whose onset and offset fall on a beat, on a
      detection or on ``start`` in some cases, so that items lie on their limits.
    """
    rng = np.random.default_rng(seed)
    cases: list[MatchingCase] = []
    for _ in range(count):
        beats: list[int] = []
        position = start - int(rng.integers(0, 1500))
        while position <= start + 3000:
            beats.append(position)
            position += int(rng.integers(40, 401))

        detections = {b + int(rng.integers(-80, 81)) for b in beats if rng.random() < 0.8}
        low, high = start - 1600, start + 3100
        detections.update(int(d) for d in rng.integers(low, high, size=int(rng.integers(0, 6))))
        if rng.random() < 0.3:
            detections.add(start + int(rng.integers(0, window + 2)))
        if rng.random() < 0.3:
            detections.add(start - int(rng.integers(1, 61)))
        items = sorted(set(beats) | detections)

        episodes: list[tuple[int, int]] = []
        for _ in range(int(rng.integers(0, 3))):
            draw = rng.random()
            if draw < 0.3:
                onset = items[int(rng.integers(0, len(items)))]
            elif draw < 0.4:
                onset = start
            else:
                onset = int(rng.integers(start - 1200, start + 2500))
            offset = onset + int(rng.integers(0, 1500))
            if rng.random() < 0.3:
                later = [s for s in items if s >= onset]
                offset = later[int(rng.integers(0, len(later)))] if later else offset
            episodes.append((onset, offset))
        episodes.sort()
        kept: list[tuple[int, int]] = []
        for onset, offset in episodes:
            if not kept or onset > kept[-1][1]:
                kept.append((onset, offset))

        cases.append(
            MatchingCase(
                reference=tuple(beats),
                detections=tuple(sorted(detections)),
                episodes=tuple(kept),
            )
        )
    return cases


def _five_minute_rule(
    scored_reference: Sequence[int], detections: Sequence[int], start: int, window: int
) -> tuple[int | None, int | None]:
    """The two exceptions of SRS-008 at 5:00, from its statement.

    ``scored_reference`` are the scored reference beats in order (at or after ``start`` and
    outside every episode); ``detections`` all detections in order. Returns:

    - the last detection before 5:00, if it is paired with the first scored reference beat
      (they can match, and it is closer to that beat than the next detection is), else None;
    - otherwise, the first detection at or after 5:00 if it is not scored (at most ``window``
      samples after ``start``, and either the next detection is closer to the first scored
      reference beat or no reference beat is scored), else None.
    """
    first_scored = scored_reference[0] if scored_reference else None
    before = [d for d in detections if d < start]
    after = [d for d in detections if d >= start]
    last_before = before[-1] if before else None
    first_after = after[0] if after else None
    second_after = after[1] if len(after) > 1 else None

    if first_scored is not None and last_before is not None:
        distance = first_scored - last_before
        if distance <= window and (
            first_after is None or distance < abs(first_scored - first_after)
        ):
            return last_before, None
    if first_after is not None and first_after - start <= window:
        if first_scored is None:
            return None, first_after
        if second_after is not None and abs(first_scored - second_after) < abs(
            first_scored - first_after
        ):
            return None, first_after
    return None, None


@pytest.fixture(scope="session")
def make_matching_cases() -> Callable[..., list[MatchingCase]]:
    """``make_matching_cases(seed, count, *, start=108000, window=54)``.

    See ``_matching_cases``.
    """
    return _matching_cases


@pytest.fixture(scope="session")
def five_minute_rule() -> Callable[..., tuple[int | None, int | None]]:
    """``five_minute_rule(scored_reference, detections, start, window)``.

    See ``_five_minute_rule``.
    """
    return _five_minute_rule


@pytest.fixture
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Make any network access fail, and fail the test if one was attempted.

    Name resolution, socket connections and ``urllib.request.urlopen`` raise an error for
    the duration of the test. The fixture value lists the attempts; the test fails at the
    end if the list is not empty, even when the software under test caught the error.
    """
    attempts: list[str] = []

    def refuse(name: str) -> Callable[..., Any]:
        def refused(*args: Any, **kwargs: Any) -> Any:
            attempts.append(name)
            raise RuntimeError(f"network access attempted ({name}) in a test without network")

        return refused

    monkeypatch.setattr(socket.socket, "connect", refuse("socket.connect"))
    monkeypatch.setattr(socket, "create_connection", refuse("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("socket.getaddrinfo"))
    monkeypatch.setattr(urllib.request, "urlopen", refuse("urllib.request.urlopen"))
    yield attempts
    assert attempts == [], f"network access attempted: {attempts}"


@contextlib.contextmanager
def _network_forbidden() -> Iterator[list[str]]:
    """The guard of ``forbid_network`` as a context manager, for fixtures of a wider scope.

    Inside the block, name resolution, socket connections and ``urllib.request.urlopen``
    raise an error. On exit, the block fails if any access was attempted, even when the
    software under test caught the error.
    """
    attempts: list[str] = []

    def refuse(name: str) -> Callable[..., Any]:
        def refused(*args: Any, **kwargs: Any) -> Any:
            attempts.append(name)
            raise RuntimeError(f"network access attempted ({name}) in a test without network")

        return refused

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", refuse("socket.connect"))
        patch.setattr(socket, "create_connection", refuse("socket.create_connection"))
        patch.setattr(socket, "getaddrinfo", refuse("socket.getaddrinfo"))
        patch.setattr(urllib.request, "urlopen", refuse("urllib.request.urlopen"))
        yield attempts
    assert attempts == [], f"network access attempted: {attempts}"


@pytest.fixture(scope="session")
def network_forbidden() -> Callable[[], contextlib.AbstractContextManager[list[str]]]:
    """``with network_forbidden(): ...``: see ``_network_forbidden``."""
    return _network_forbidden


# --------------------------------------------------------------------------------------------
# Fixture databases for the evaluation run and the validation report (SRS-009, SRS-012,
# SRS-014)
# --------------------------------------------------------------------------------------------

EVALUATION_FS_HZ = 360
FIVE_MINUTES = 108000  # 5:00 at 360 Hz: the first scored sample
SIX_MINUTES = 129600  # length of the synthetic ECG records, in samples
SEVEN_MINUTES = 151200  # length of the spike records, in samples
SPIKE_MV = 1.0
SPIKE_THRESHOLD_MV = 0.5

# The 12 ECG records of the MIT-BIH Noise Stress Test Database, by record and by decreasing
# signal-to-noise ratio, with the number of missed beats and of false detections of each
# fixture record (see ``_standard_nstdb_records``).
NOISE_STRESS_DESIGN: tuple[tuple[str, int, int], ...] = (
    ("118e24", 2, 2),
    ("118e18", 3, 2),
    ("118e12", 5, 4),
    ("118e06", 10, 12),
    ("118e00", 20, 30),
    ("118e_6", 40, 60),
    ("119e24", 0, 4),
    ("119e18", 1, 5),
    ("119e12", 4, 6),
    ("119e06", 8, 15),
    ("119e00", 25, 35),
    ("119e_6", 134, 0),
)


@dataclass(frozen=True)
class FixtureRecord:
    """A record of a fixture database, and the figures that its evaluation must give.

    Both channels are 0 mV, except for a 1 mV spike at each sample of ``spikes_0`` (channel 0)
    and of ``spikes_1`` (channel 1): the spike detector returns exactly these samples. For a
    synthetic ECG record, ``ecg_mv`` is channel 0. ``annotations`` are the reference
    annotations (beats and others) in file order; ``None`` writes no annotation file.

    The expected figures (``tp`` to ``flutter_waves_outside_vf``) are those of channel 0 with
    the settings of SRS-007, at 360 Hz: match window 54 samples, 5:00 = sample 108000. They are
    worked out from the statements of SRS-008 and SRS-012 when the record is designed, in the
    docstring of its builder.
    """

    name: str
    n_samples: int
    signal_names: tuple[str, str]
    annotations: tuple[AnnotationTuple, ...] | None
    spikes_0: tuple[int, ...]
    spikes_1: tuple[int, ...]
    tp: int
    fn: int
    fp: int
    vf_episodes: int = 0
    vf_episodes_scored: int = 0
    vf_samples_scored: int = 0
    reference_excluded: int = 0
    detections_excluded: int = 0
    flutter_waves_outside_vf: int = 0
    ecg_mv: FloatArray | None = field(default=None, compare=False, repr=False)

    @property
    def beats(self) -> tuple[int, ...]:
        """The samples of the reference beat annotations."""
        if self.annotations is None:
            return ()
        return tuple(a[0] for a in self.annotations if a[1] in ("N", "V"))


def _file_order(
    beats: Sequence[int], others: Sequence[AnnotationTuple]
) -> tuple[AnnotationTuple, ...]:
    """Reference annotations in file order.

    A rhythm annotation ``+`` with the note ``(N`` at sample 10 (as in the reference database),
    a beat annotation at each of ``beats`` (``N``, and ``V`` for every seventh beat: any beat
    code is a reference beat), and ``others``, merged in sample order.
    """
    merged: list[AnnotationTuple] = [(10, "+", 0, "(N")]
    merged += [(b, "V" if i % 7 == 3 else "N", 0, "") for i, b in enumerate(beats)]
    merged += list(others)
    return tuple(sorted(merged, key=lambda a: a[0]))


def _spread(items: Sequence[int], count: int) -> list[int]:
    """``count`` items of ``items``, spread evenly over it, starting with the first one."""
    return [items[i * len(items) // count] for i in range(count)]


def _every_360() -> list[int]:
    """Beats every 360 samples (60 bpm) from sample 180 to the end of a 7-min record.

    420 beats; the 120 from 108180 to 151020 are at or after 5:00.
    """
    return list(range(180, SEVEN_MINUTES, 360))


def _regular_record(
    name: str, *, period: int, misses: int, extras: int, signal_name: str = "MLII"
) -> FixtureRecord:
    """A 7-min record with a beat every ``period`` samples, from sample 180.

    Channel 0 has a spike 3 samples after every beat, except after ``misses`` of the beats at
    or after 5:00 (spread over them), and ``extras`` more spikes halfway between a beat at or
    after 5:00 and the next beat. A spike 3 samples after a beat is paired with it; a beat
    without a spike is a false negative; a spike halfway lies at least 162 samples from any
    beat and is a false positive. No spike lies within 54 samples of 5:00, so the rule at 5:00
    changes nothing. Channel 1 has no spike.

    Period 360: 120 beats at or after 5:00 (108180 to 151020). Period 324: 134 (108072 to
    151164). Expected: TP = those beats - misses, FN = misses, FP = extras; no episode.
    """
    beats = list(range(180, SEVEN_MINUTES, period))
    scored = [b for b in beats if b >= FIVE_MINUTES]
    missed = set(_spread(scored, misses)) if misses else set()
    halfway = [b + period // 2 for b in _spread(scored, extras)] if extras else []
    spikes = sorted([b + 3 for b in beats if b not in missed] + halfway)
    return FixtureRecord(
        name=name,
        n_samples=SEVEN_MINUTES,
        signal_names=(signal_name, "V1"),
        annotations=_file_order(beats, ()),
        spikes_0=tuple(spikes),
        spikes_1=(),
        tp=len(scored) - misses,
        fn=misses,
        fp=extras,
    )


def _record_105() -> FixtureRecord:
    """Reference beats only in the first 5 minutes, and detections after 5:00.

    Beats every 360 samples from 180 to 107820, each with a spike 3 samples later, and five
    more spikes at 111960, 115560, 119160, 122760 and 126360.
    Expected: no scored reference beat, so TP 0 and FN 0 (Se not defined); the five spikes
    after 5:00 are false positives (the first one is 3960 samples after 5:00, so the rule at
    5:00 does not apply): FP 5, +P 0.00%.
    """
    beats = list(range(180, FIVE_MINUTES, 360))
    late = [111960, 115560, 119160, 122760, 126360]
    return FixtureRecord(
        name="105",
        n_samples=SEVEN_MINUTES,
        signal_names=("MLII", "V1"),
        annotations=_file_order(beats, ()),
        spikes_0=tuple(sorted([b + 3 for b in beats] + late)),
        spikes_1=(),
        tp=0,
        fn=0,
        fp=5,
    )


def _record_207() -> FixtureRecord:
    """Two ventricular flutter episodes, one that ends before 5:00 and one after 5:00.

    The fixture of the verification of SRS-012. Beats every 360 samples from 180.
    - Episode 1, ``[`` at 36000 and ``]`` at 43200 (100 s to 120 s): the 20 beats from 36180
      to 43020 lie inside it, each with a spike 3 samples later, and one more spike at 40000.
    - Episode 2, ``[`` at 115200 and ``]`` at 124350: the 25 beats from 115380 to 124020 lie
      inside it, with no spike near them; two spikes at 117000 and 121000, far from any
      scored beat (not paired); a spike at 124340, inside the episode, 40 samples before the
      scored beat at 124380 (outside it), which has no other spike: they are paired. A flutter
      wave ``!`` at 118000.
    - Every other beat has a spike 3 samples later.
    Expected: TP 95 (the 120 beats after 5:00 minus the 25 of episode 2), FN 0, FP 0; 2
    episodes in the record, 1 that reaches 5:00 or later, lasting 124350 - 115200 + 1 = 9151
    samples (25.4 s) from 5:00; 25 reference beats and 2 detections not scored; no flutter
    wave outside the episodes.
    """
    beats = _every_360()
    spikes = [b + 3 for b in beats if not 115200 <= b <= 124380]
    spikes += [40000, 117000, 121000, 124340]
    others: list[AnnotationTuple] = [
        (36000, "[", 0, ""),
        (43200, "]", 0, ""),
        (115200, "[", 0, ""),
        (118000, "!", 0, ""),
        (124350, "]", 0, ""),
    ]
    return FixtureRecord(
        name="207",
        n_samples=SEVEN_MINUTES,
        signal_names=("MLII", "V1"),
        annotations=_file_order(beats, others),
        spikes_0=tuple(sorted(spikes)),
        spikes_1=(),
        tp=95,
        fn=0,
        fp=0,
        vf_episodes=2,
        vf_episodes_scored=1,
        vf_samples_scored=9151,
        reference_excluded=25,
        detections_excluded=2,
    )


def _record_208() -> FixtureRecord:
    """Twenty short episodes after 5:00: the duration includes the onset and offset samples.

    Beats every 360 samples from 180, each with a spike 3 samples later. For k = 310, 312,
    ..., 348, an episode from 60 to 420 samples after the beat ``180 + 360 k``: 361 samples,
    onset and offset included, with the next beat and its spike inside it.
    Expected: TP 100, FN 0, FP 0; 20 episodes, all from 5:00, lasting 20 x 361 = 7220 samples
    (20.1 s; 20.0 s if the onset or the offset sample were left out); 20 reference beats and
    20 detections not scored.
    """
    beats = _every_360()
    others: list[AnnotationTuple] = []
    for k in range(310, 350, 2):
        beat = 180 + 360 * k
        others += [(beat + 60, "[", 0, ""), (beat + 420, "]", 0, "")]
    return FixtureRecord(
        name="208",
        n_samples=SEVEN_MINUTES,
        signal_names=("MLII", "V1"),
        annotations=_file_order(beats, others),
        spikes_0=tuple(b + 3 for b in beats),
        spikes_1=(),
        tp=100,
        fn=0,
        fp=0,
        vf_episodes=20,
        vf_episodes_scored=20,
        vf_samples_scored=7220,
        reference_excluded=20,
        detections_excluded=20,
    )


def _record_209() -> FixtureRecord:
    """An episode that contains 5:00, and a detection dropped by the rule at 5:00 inside it.

    Beats every 360 samples from 180. An episode from 107000 to 109000 holds the beats 107100,
    107460 and 107820 (before 5:00) and 108180, 108540 and 108900 (after 5:00). Every beat has
    a spike 3 samples later, except 108180; one more spike at 108020, 20 samples after 5:00.
    The first scored reference beat is 109260. The first detection at or after 5:00 (108020)
    lies within 54 samples of 5:00 and the next one (108543) is closer to 109260: the rule at
    5:00 of SRS-008 leaves it unscored. 108543 and 108903 lie inside the episode and are not
    paired.
    Expected: TP 117, FN 0, FP 0; 1 episode, 1 from 5:00, lasting 109000 - 108000 + 1 = 1001
    samples (2.8 s) from 5:00; 3 reference beats not scored (those at or after 5:00) and 2
    detections not scored (the one dropped by the rule at 5:00 is not included).
    """
    beats = _every_360()
    spikes = [b + 3 for b in beats if b != 108180] + [108020]
    others: list[AnnotationTuple] = [(107000, "[", 0, ""), (109000, "]", 0, "")]
    return FixtureRecord(
        name="209",
        n_samples=SEVEN_MINUTES,
        signal_names=("MLII", "V1"),
        annotations=_file_order(beats, others),
        spikes_0=tuple(sorted(spikes)),
        spikes_1=(),
        tp=117,
        fn=0,
        fp=0,
        vf_episodes=1,
        vf_episodes_scored=1,
        vf_samples_scored=1001,
        reference_excluded=3,
        detections_excluded=2,
    )


def _record_210() -> FixtureRecord:
    """An episode that ends before 5:00 only, and two flutter waves outside any episode.

    Beats every 360 samples from 180, each with a spike 3 samples later. An episode from 36000
    to 43200 (20 beats and their spikes inside it). Two flutter waves ``!`` outside it: one at
    60090, before 5:00, and one at 120240, after 5:00, halfway between the beats 120060 and
    120420 (177 samples from the nearest spike). A ``!`` is not a reference beat, so neither
    changes the counts.
    Expected: TP 120, FN 0, FP 0; 1 episode in the record, 0 from 5:00, duration 0 samples,
    no reference beat and no detection not scored; 1 flutter wave outside the episodes: the
    one at 120240. The one at 60090 is not counted, because the flutter waves are counted from
    5:00 to the end of the record (architecture sections 8.8 and 8.10, a design figure of the
    report).
    """
    beats = _every_360()
    others: list[AnnotationTuple] = [
        (36000, "[", 0, ""),
        (43200, "]", 0, ""),
        (60090, "!", 0, ""),
        (120240, "!", 0, ""),
    ]
    return FixtureRecord(
        name="210",
        n_samples=SEVEN_MINUTES,
        signal_names=("MLII", "V1"),
        annotations=_file_order(beats, others),
        spikes_0=tuple(b + 3 for b in beats),
        spikes_1=(),
        tp=120,
        fn=0,
        fp=0,
        vf_episodes=1,
        flutter_waves_outside_vf=1,
    )


def _record_211() -> FixtureRecord:
    """An episode without an offset annotation: it lasts until the end of the record.

    Beats every 360 samples from 180, each with a spike 3 samples later. A ``[`` at 140000 and
    no ``]``: the 31 beats from 140220 to 151020 and their spikes lie inside the episode.
    Expected: TP 89, FN 0, FP 0; 1 episode, 1 from 5:00, lasting 151199 - 140000 + 1 = 11200
    samples (31.1 s); 31 reference beats and 31 detections not scored.
    """
    beats = _every_360()
    return FixtureRecord(
        name="211",
        n_samples=SEVEN_MINUTES,
        signal_names=("MLII", "V1"),
        annotations=_file_order(beats, [(140000, "[", 0, "")]),
        spikes_0=tuple(b + 3 for b in beats),
        spikes_1=(),
        tp=89,
        fn=0,
        fp=0,
        vf_episodes=1,
        vf_episodes_scored=1,
        vf_samples_scored=11200,
        reference_excluded=31,
        detections_excluded=31,
    )


def _standard_mitdb_records() -> list[FixtureRecord]:
    """The 14 records of the fixture MIT-BIH Arrhythmia Database.

    | Record | TP | FN | FP | Se (%) | +P (%) | Episodes |
    |---|---|---|---|---|---|---|
    | 100 | 120 | 0 | 0 | 100.00 | 100.00 | |
    | 101 | 117 | 3 | 1 | 97.50 | 99.15 | |
    | 102 | 134 | 0 | 4 | 100.00 | 97.10 | |
    | 103 | 117 | 3 | 0 | 97.50 | 100.00 | |
    | 104 | 114 | 6 | 6 | 95.00 | 95.00 | (signal V5) |
    | 105 | 0 | 0 | 5 | not defined | 0.00 | |
    | 106 | 0 | 120 | 0 | 0.00 | not defined | |
    | 118 | 118 | 2 | 1 | 98.33 | 99.16 | |
    | 119 | 134 | 0 | 4 | 100.00 | 97.10 | |
    | 207 to 211 | | 0 | 0 | 100.00 | 100.00 | see their builders |

    Gross: TP 1375, FN 134, FP 21.
    """
    return [
        _regular_record("100", period=360, misses=0, extras=0),
        _regular_record("101", period=360, misses=3, extras=1),
        _regular_record("102", period=324, misses=0, extras=4),
        _regular_record("103", period=360, misses=3, extras=0),
        _regular_record("104", period=360, misses=6, extras=6, signal_name="V5"),
        _record_105(),
        _regular_record("106", period=360, misses=120, extras=0),
        _regular_record("118", period=360, misses=2, extras=1),
        _regular_record("119", period=324, misses=0, extras=4),
        _record_207(),
        _record_208(),
        _record_209(),
        _record_210(),
        _record_211(),
    ]


def _noise_record(name: str) -> FixtureRecord:
    """A noise record of the Noise Stress Test Database (``bw``, ``em``, ``ma``).

    One minute, two flat channels, no annotation file: noise only, not an ECG record.
    """
    return FixtureRecord(
        name=name,
        n_samples=21600,
        signal_names=("noise1", "noise2"),
        annotations=None,
        spikes_0=(),
        spikes_1=(),
        tp=0,
        fn=0,
        fp=0,
    )


def _standard_nstdb_records() -> list[FixtureRecord]:
    """The 12 ECG records and the 3 noise records of the fixture Noise Stress Test Database.

    Each ECG record has the reference beats of the fixture record 118 (``118eNN``, period 360)
    or 119 (``119eNN``, period 324), as the noise stress records carry the annotations of the
    record they are made from, and the misses and false detections of ``NOISE_STRESS_DESIGN``.
    """
    records = [
        _regular_record(
            name, period=360 if name.startswith("118") else 324, misses=misses, extras=extras
        )
        for name, misses, extras in NOISE_STRESS_DESIGN
    ]
    return records + [_noise_record(name) for name in ("bw", "em", "ma")]


def _long_synthetic_ecg(fs_hz: int, heart_rate_bpm: int, n_samples: int) -> SyntheticEcg:
    """The synthetic ECG of ``make_synthetic_ecg``, computed fast for long records.

    Same QRS positions and waves, but each wave is evaluated only within 1 s of the R centre
    of its beat. From 30 bpm up, every wave is below 1e-15 mV beyond that distance.
    """
    rr = Fraction(60, heart_rate_bpm)
    last_centre_s = Fraction(n_samples, fs_hz) - Fraction(1, 2)
    n_beats = max(0, math.floor((last_centre_s - Fraction(1, 2)) / rr) + 1)
    qrs = [math.floor((Fraction(1, 2) + k * rr) * fs_hz + Fraction(1, 2)) for k in range(n_beats)]

    scale = math.sqrt(60.0 / heart_rate_bpm)
    signal = np.zeros(n_samples, dtype=np.float64)
    for r in qrs:
        low, high = max(0, r - fs_hz), min(n_samples, r + fs_hz + 1)
        t_s = np.arange(low, high, dtype=np.float64) / fs_hz
        for _name, offset_ms, amplitude_mv, sigma_ms, scaled in _WAVES:
            factor = scale if scaled else 1.0
            centre_s = r / fs_hz + offset_ms * factor / 1000.0
            sigma_s = sigma_ms * factor / 1000.0
            signal[low:high] += amplitude_mv * np.exp(-((t_s - centre_s) ** 2) / (2.0 * sigma_s**2))
    return SyntheticEcg(
        fs_hz=float(fs_hz), signal_mv=signal, qrs_samples=np.asarray(qrs, dtype=np.int64)
    )


def _ecg_record(name: str, ecg: SyntheticEcg) -> FixtureRecord:
    """A 6-min record whose channel 0 is a noise-free synthetic ECG, annotated at its QRS.

    For the real detector: by SRS-006 it detects each QRS once, within 150 ms, so every
    reference beat at or after 5:00 is paired. Expected: TP = those beats, FN 0, FP 0.
    """
    beats = ecg.qrs_samples.tolist()
    return FixtureRecord(
        name=name,
        n_samples=ecg.signal_mv.size,
        signal_names=("MLII", "V1"),
        annotations=_file_order(beats, ()),
        spikes_0=(),
        spikes_1=(),
        tp=sum(1 for b in beats if b >= FIVE_MINUTES),
        fn=0,
        fp=0,
        ecg_mv=ecg.signal_mv,
    )


@dataclass(frozen=True)
class FixtureDatabase:
    """A fixture database written in a data folder, with the records it holds."""

    slug: str
    folder: DatabaseFolder
    records: dict[str, FixtureRecord]  # every record written, by name
    record_list: tuple[str, ...]  # the names of its RECORDS file, in file order

    @property
    def checksum_list_sha256(self) -> str:
        """SHA-256 of its checksum list, to pin in the ``Database`` under test."""
        return self.folder.checksum_list_sha256

    @property
    def n_listed_files(self) -> int:
        """Number of files that its checksum list names."""
        return len(self.folder.files)


@dataclass(frozen=True)
class EvaluationFixture:
    """A data folder holding a fixture ``mitdb`` and a fixture ``nstdb`` database."""

    data_root: Path
    mitdb: FixtureDatabase
    nstdb: FixtureDatabase


def _write_evaluation_database(
    data_root: Path,
    slug: str,
    records: Sequence[FixtureRecord],
    *,
    record_list: Sequence[str],
    extra_files: Mapping[str, bytes],
) -> FixtureDatabase:
    """Write ``records`` as WFDB records (360 Hz, two channels, format 212, gain 200/mV) in
    ``data_root / slug``, with a ``RECORDS`` file listing ``record_list``, the
    ``extra_files``, and the checksum list of every file.
    """
    folder = data_root / slug
    folder.mkdir(parents=True, exist_ok=True)
    for record in records:
        signals = np.zeros((record.n_samples, 2), dtype=np.float64)
        if record.ecg_mv is not None:
            signals[:, 0] = record.ecg_mv
        signals[list(record.spikes_0), 0] = SPIKE_MV
        signals[list(record.spikes_1), 1] = SPIKE_MV
        _write_wfdb_record(
            folder,
            record.name,
            fs_hz=EVALUATION_FS_HZ,
            signals_mv=signals,
            signal_names=record.signal_names,
            annotations=record.annotations,
        )
    files = {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }
    files["RECORDS"] = "".join(f"{name}\n" for name in record_list).encode("ascii")
    files.update(extra_files)
    return FixtureDatabase(
        slug=slug,
        folder=_write_database_folder(data_root, slug, files),
        records={record.name: record for record in records},
        record_list=tuple(record_list),
    )


_ANNOTATORS = {"ANNOTATORS": b"atr\treference beat, rhythm, and signal quality annotations\n"}


def _moved(database: FixtureDatabase, data_root: Path) -> FixtureDatabase:
    """The same fixture database, copied under another data folder."""
    folder = replace(database.folder, data_root=data_root, folder=data_root / database.slug)
    return replace(database, folder=folder)


def _copy_evaluation_fixture(source: EvaluationFixture, data_root: Path) -> EvaluationFixture:
    """Copy both databases of ``source`` to ``data_root`` (which must not exist)."""
    shutil.copytree(source.data_root, data_root)
    return EvaluationFixture(
        data_root=data_root,
        mitdb=_moved(source.mitdb, data_root),
        nstdb=_moved(source.nstdb, data_root),
    )


@pytest.fixture(scope="session")
def evaluation_fixture(tmp_path_factory: pytest.TempPathFactory) -> EvaluationFixture:
    """The standard fixture databases of the report tests. Read only: copy it to alter it.

    - ``mitdb``: the 14 records of ``_standard_mitdb_records``, a ``RECORDS`` file that lists
      them in decreasing order of name, an ``ANNOTATORS`` file and a documentation file.
    - ``nstdb``: the 12 ECG records and 3 noise records of ``_standard_nstdb_records``, a
      ``RECORDS`` file listing all 15 in increasing order of name, an ``ANNOTATORS`` file.
    """
    data_root = tmp_path_factory.mktemp("evaluation") / "data"
    mitdb_records = _standard_mitdb_records()
    mitdb = _write_evaluation_database(
        data_root,
        "mitdb",
        mitdb_records,
        record_list=sorted((r.name for r in mitdb_records), reverse=True),
        extra_files={**_ANNOTATORS, "mitdbdir/intro.htm": b"<html><body>Intro</body></html>\n"},
    )
    nstdb_records = _standard_nstdb_records()
    nstdb = _write_evaluation_database(
        data_root,
        "nstdb",
        nstdb_records,
        record_list=sorted(r.name for r in nstdb_records),
        extra_files=_ANNOTATORS,
    )
    return EvaluationFixture(data_root=data_root, mitdb=mitdb, nstdb=nstdb)


@pytest.fixture(scope="session")
def evaluation_fixture_without_episodes(
    evaluation_fixture: EvaluationFixture, tmp_path_factory: pytest.TempPathFactory
) -> EvaluationFixture:
    """Fixture databases in which no record has a ventricular flutter episode. Read only.

    - ``mitdb``: records 100 and 118 (period 360, no miss, no false detection) and 119
      (period 324, no miss, one false detection): gross TP 374, FN 0, FP 1.
    - ``nstdb``: a copy of the standard fixture ``nstdb``.
    """
    data_root = tmp_path_factory.mktemp("evaluation-without-episodes") / "data"
    records = [
        _regular_record("100", period=360, misses=0, extras=0),
        _regular_record("118", period=360, misses=0, extras=0),
        _regular_record("119", period=324, misses=0, extras=1),
    ]
    mitdb = _write_evaluation_database(
        data_root, "mitdb", records, record_list=[r.name for r in records], extra_files={}
    )
    shutil.copytree(evaluation_fixture.nstdb.folder.folder, data_root / "nstdb")
    nstdb = _moved(evaluation_fixture.nstdb, data_root)
    return EvaluationFixture(data_root=data_root, mitdb=mitdb, nstdb=nstdb)


@pytest.fixture(scope="session")
def ecg_evaluation_fixture(tmp_path_factory: pytest.TempPathFactory) -> EvaluationFixture:
    """Fixture databases of 6-min noise-free synthetic ECGs, for the real detector. Read only.

    - ``mitdb``: records 118 (75 bpm) and 119 (60 bpm).
    - ``nstdb``: the 12 ECG records, ``118eNN`` at 75 bpm and ``119eNN`` at 60 bpm.
    Channel 1 is flat. Every record: TP = the beats at or after 5:00, FN 0, FP 0.
    """
    data_root = tmp_path_factory.mktemp("evaluation-ecg") / "data"
    ecg = {rate: _long_synthetic_ecg(EVALUATION_FS_HZ, rate, SIX_MINUTES) for rate in (60, 75)}
    mitdb = _write_evaluation_database(
        data_root,
        "mitdb",
        [_ecg_record("118", ecg[75]), _ecg_record("119", ecg[60])],
        record_list=["118", "119"],
        extra_files={},
    )
    names = [name for name, _, _ in NOISE_STRESS_DESIGN]
    nstdb = _write_evaluation_database(
        data_root,
        "nstdb",
        [_ecg_record(name, ecg[75 if name.startswith("118") else 60]) for name in names],
        record_list=names,
        extra_files={},
    )
    return EvaluationFixture(data_root=data_root, mitdb=mitdb, nstdb=nstdb)


@pytest.fixture(scope="session")
def copy_evaluation_fixture() -> Callable[[EvaluationFixture, Path], EvaluationFixture]:
    """``copy_evaluation_fixture(source, data_root)``: see ``_copy_evaluation_fixture``."""
    return _copy_evaluation_fixture


class SpikeDetector:
    """Detector double with a known output: the samples where the signal exceeds 0.5 mV.

    It has the interface of the detector of the evaluation: (signal in mV, sampling frequency
    in Hz, mains setting in Hz) -> sample indices. ``calls`` lists, for each call, the number
    of samples of the signal, the sampling frequency and the mains setting.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[int, float, int]] = []

    def __call__(self, signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int) -> IndexArray:
        signal = np.asarray(signal_mv, dtype=np.float64)
        self.calls.append((int(signal.size), float(fs_hz), int(mains_hz)))
        return np.flatnonzero(signal > SPIKE_THRESHOLD_MV).astype(np.int64)


@pytest.fixture(scope="session")
def make_spike_detector() -> type[SpikeDetector]:
    """``make_spike_detector()``: see ``SpikeDetector``."""
    return SpikeDetector


# A script run in a separate Python process by the command tests. It forbids network access,
# may set the pinned SHA-256 of the checksum lists to those of fixture databases (for that
# process only), then runs a command-line script of the software as ``python SCRIPT ...``
# would.
_COMMAND_DRIVER = '''\
"""Run a command-line script of the software without network access.

Usage: python <this file> MITDB_PIN NSTDB_PIN SCRIPT [ARGUMENT ...]

Name resolution, socket connections and urllib.request.urlopen raise an error. A PIN other
than "-" replaces, in this process only, the pinned SHA-256 of the checksum list of that
database, so that a fixture database stands for the real one.
"""

import runpy
import socket
import sys
import urllib.request
from pathlib import Path


def _refuse(*args, **kwargs):
    raise RuntimeError("network access attempted in a test without network")


socket.socket.connect = _refuse
socket.create_connection = _refuse
socket.getaddrinfo = _refuse
urllib.request.urlopen = _refuse

from sinus_dsp.data import physionet  # noqa: E402

for database, pin in ((physionet.MITDB, sys.argv[1]), (physionet.NSTDB, sys.argv[2])):
    if pin != "-":
        object.__setattr__(database, "checksum_list_sha256", pin)

script = Path(sys.argv[3]).resolve()
sys.argv = [str(script), *sys.argv[4:]]
sys.path.insert(0, str(script.parent))
runpy.run_path(str(script), run_name="__main__")
'''


def _write_command_driver(folder: Path) -> Path:
    """Write the command driver in ``folder`` and return its path.

    ``python <driver> MITDB_PIN NSTDB_PIN SCRIPT [ARGUMENT ...]`` runs ``SCRIPT`` with its
    arguments, without network access; a PIN other than ``-`` replaces the pinned SHA-256 of
    the checksum list of that database in that process only.
    """
    path = folder / "run_command_without_network.py"
    path.write_text(_COMMAND_DRIVER, encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def write_command_driver() -> Callable[[Path], Path]:
    """``write_command_driver(folder)``: see ``_write_command_driver``."""
    return _write_command_driver


# --------------------------------------------------------------------------------------------
# Reading the validation report
# --------------------------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")


def _normalize_cell(text: str) -> str:
    """A table cell without emphasis, code marks, escapes or a trailing ``%``, ASCII minus."""
    value = text.strip().replace("**", "").replace("`", "").replace("\\_", "_")
    value = value.replace("−", "-").strip()
    if value.endswith("%"):
        value = value[:-1].rstrip()
    return value


@dataclass(frozen=True)
class ReportTable:
    """A Markdown table: its header cells and its data rows, cells normalized."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def first_cells(self) -> list[str]:
        """The first cell of every data row, in order."""
        return [row[0] for row in self.rows]

    def row(self, first_cell: str) -> tuple[str, ...]:
        """The only data row whose first cell is ``first_cell``."""
        matches = [row for row in self.rows if row[0] == first_cell]
        assert len(matches) == 1, f"{len(matches)} rows start with {first_cell!r}: {self.rows}"
        return matches[0]


def _parse_table(lines: Sequence[str]) -> ReportTable:
    rows: list[tuple[str, ...]] = []
    for line in lines:
        stripped = line.strip()
        inner = stripped[1:-1] if len(stripped) > 1 and stripped.endswith("|") else stripped[1:]
        cells = tuple(_normalize_cell(cell) for cell in inner.split("|"))
        if all(_SEPARATOR_CELL.match(cell) for cell in cells):
            continue
        rows.append(cells)
    assert rows, f"empty table: {lines}"
    return ReportTable(header=rows[0], rows=tuple(rows[1:]))


@dataclass(frozen=True)
class ReportSection:
    """The lines under a heading, up to the next heading of the same or a higher level."""

    title: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def tables(self) -> list[ReportTable]:
        """Every Markdown table of the section, in order."""
        tables: list[ReportTable] = []
        block: list[str] = []
        for line in (*self.lines, ""):
            if line.lstrip().startswith("|"):
                block.append(line)
            elif block:
                tables.append(_parse_table(block))
                block = []
        return tables

    def table_with_row(self, first_cell: str) -> ReportTable:
        """The only table of the section with a data row whose first cell is ``first_cell``."""
        found = [t for t in self.tables() if first_cell in t.first_cells()]
        assert len(found) == 1, f"{len(found)} tables with a row {first_cell!r} in {self.title!r}"
        return found[0]


class ParsedReport:
    """A Markdown report split into headings, sections and tables."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = tuple(text.split("\n"))
        self.headings: list[tuple[int, int, str]] = []  # (line index, level, title)
        for index, line in enumerate(self.lines):
            match = _HEADING.match(line)
            if match:
                self.headings.append((index, len(match.group(1)), match.group(2)))

    def titles(self) -> list[str]:
        return [title for _, _, title in self.headings]

    def section(self, keyword: str) -> ReportSection:
        """The first section whose heading contains ``keyword``, ignoring case."""
        for position, (index, level, title) in enumerate(self.headings):
            if keyword.casefold() in title.casefold():
                end = next(
                    (i for i, lv, _ in self.headings[position + 1 :] if lv <= level),
                    len(self.lines),
                )
                return ReportSection(title=title, lines=self.lines[index + 1 : end])
        raise AssertionError(f"no heading contains {keyword!r}; headings: {self.titles()}")


def _two_decimals(value: Fraction) -> str:
    """``value`` with two decimals, rounded from its exact value.

    Fails if ``value`` lies within 1e-6 hundredths of a rounding tie: there, the rounding of
    its binary64 value could differ, and a fixture must avoid such values.
    """
    scaled = value * 100
    whole = math.floor(scaled)
    remainder = scaled - whole
    assert abs(remainder - Fraction(1, 2)) > Fraction(1, 10**6), (
        f"{float(value)} is too close to a rounding tie for a fixture"
    )
    hundredths = whole + (1 if remainder > Fraction(1, 2) else 0)
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def _percent_text(numerator: int, denominator: int) -> str:
    """``100 * numerator / denominator`` as the reports write it: two decimals, or
    ``not defined`` for a zero denominator (SRS-011)."""
    if denominator == 0:
        return "not defined"
    return _two_decimals(Fraction(100 * numerator, denominator))


def _mean_percent_text(pairs: Sequence[tuple[int, int]]) -> str:
    """Mean of the defined values ``100 * n / d`` of ``pairs``, as the reports write it."""
    values = [Fraction(100 * n, d) for n, d in pairs if d != 0]
    if not values:
        return "not defined"
    return _two_decimals(sum(values, Fraction(0)) / len(values))


@pytest.fixture(scope="session")
def parse_report() -> type[ParsedReport]:
    """``parse_report(text)``: see ``ParsedReport``."""
    return ParsedReport


@pytest.fixture(scope="session")
def percent_text() -> Callable[[int, int], str]:
    """``percent_text(numerator, denominator)``: see ``_percent_text``."""
    return _percent_text


@pytest.fixture(scope="session")
def mean_percent_text() -> Callable[[Sequence[tuple[int, int]]], str]:
    """``mean_percent_text(pairs)``: see ``_mean_percent_text``."""
    return _mean_percent_text


# --------------------------------------------------------------------------------------------
# Software identity: version, source identifier and runtime versions (SRS-009, SRS-012)
# --------------------------------------------------------------------------------------------

DSP_DIR = Path(__file__).resolve().parents[2]
# The runtime third-party packages, in the order of the documented `Runtime` row
# (architecture, sections 8.10 and 8.14).
RUNTIME_DISTRIBUTIONS = ("numpy", "scipy", "wfdb")
_DEPENDENCY_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _source_files(package_dir: Path) -> list[tuple[str, Path]]:
    """Steps 1 and 2 of the source identifier (architecture, section 8.14).

    Walk ``package_dir`` without following symbolic links, skipping folders whose name starts
    with ``.`` or is ``__pycache__``; keep each regular file that is not a symbolic link,
    whose name ends with ``.py`` and does not start with ``.``. Name each one by its path
    relative to the parent of ``package_dir``, with ``/``, and sort the names in code-point
    order. Returns (name, path) pairs.
    """
    found: list[tuple[str, Path]] = []
    for folder, subfolders, files in os.walk(package_dir, followlinks=False):
        subfolders[:] = [s for s in subfolders if not s.startswith(".") and s != "__pycache__"]
        for file_name in files:
            path = Path(folder) / file_name
            if not file_name.endswith(".py") or file_name.startswith("."):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            found.append((path.relative_to(package_dir.parent).as_posix(), path))
    return sorted(found)


def _source_manifest(package_dir: Path) -> bytes:
    """Steps 3 to 5: one line ``<SHA-256 of the file, CR LF read as LF>  <name>\\n`` per
    file, in the order of the names, encoded in UTF-8."""
    lines = []
    for name, path in _source_files(package_dir):
        content = path.read_bytes().replace(b"\r\n", b"\n")
        lines.append(f"{hashlib.sha256(content).hexdigest()}  {name}\n")
    return "".join(lines).encode("utf-8")


def _source_digest(package_dir: Path) -> str:
    """Step 6: the SHA-256 of the manifest, 64 lowercase hexadecimal digits."""
    return hashlib.sha256(_source_manifest(package_dir)).hexdigest()


def _version_literal(package_dir: Path) -> str:
    """The string literal assigned to ``__version__`` in ``<package_dir>/__init__.py``."""
    tree = ast.parse((package_dir / "__init__.py").read_bytes())
    values = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    assert len(values) == 1, f"{len(values)} string literals assigned to __version__"
    return values[0]


def _runtime_dependency_names() -> tuple[str, ...]:
    """The names of the ``[project] dependencies`` of ``dsp/pyproject.toml``."""
    project = tomllib.loads((DSP_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = []
    for requirement in project["dependencies"]:
        match = _DEPENDENCY_NAME.match(requirement)
        assert match, requirement
        names.append(match.group(1).lower())
    return tuple(names)


def _project_version() -> str:
    """The ``[project] version`` of ``dsp/pyproject.toml``."""
    text = (DSP_DIR / "pyproject.toml").read_text(encoding="utf-8")
    return str(tomllib.loads(text)["project"]["version"])


@dataclass(frozen=True)
class ExpectedSoftware:
    """The software identity a report must state, worked out by the test.

    ``version`` is the ``__version__`` literal of the package, ``source_sha256`` the
    identifier computed with the six steps of architecture section 8.14, ``python`` and
    ``runtime`` the versions of the environment that runs the test (``sys.version_info`` and
    ``importlib.metadata``).
    """

    package_dir: Path
    version: str
    source_sha256: str
    python: str
    runtime: tuple[tuple[str, str], ...]

    @property
    def software_row(self) -> str:
        """The documented table line ``| Software | sinus-dsp <version>, source SHA-256 <d> |``."""
        return f"| Software | sinus-dsp {self.version}, source SHA-256 {self.source_sha256} |"

    @property
    def runtime_row(self) -> str:
        """The documented table line ``| Runtime | Python <x.y>, numpy <v>, scipy <v>, ... |``."""
        parts = [f"Python {self.python}", *(f"{name} {version}" for name, version in self.runtime)]
        return f"| Runtime | {', '.join(parts)} |"


def _expected_software(package_dir: Path) -> ExpectedSoftware:
    """The identity of the package in ``package_dir`` run in this environment."""
    return ExpectedSoftware(
        package_dir=package_dir,
        version=_version_literal(package_dir),
        source_sha256=_source_digest(package_dir),
        python=f"{sys.version_info.major}.{sys.version_info.minor}",
        runtime=tuple((name, importlib.metadata.version(name)) for name in RUNTIME_DISTRIBUTIONS),
    )


def _running_package_dir() -> Path:
    """The folder of the package ``sinus_dsp`` that the tests import."""
    module = importlib.import_module("sinus_dsp")
    assert module.__file__ is not None
    return Path(module.__file__).resolve().parent


def _copy_package(destination: Path, *, crlf: bool = False) -> Path:
    """Copy the package under test into ``destination`` (without ``__pycache__``) and return
    the folder of the copy. With ``crlf``, every ``.py`` file of the copy gets CR LF line
    endings."""
    target = destination / "sinus_dsp"
    shutil.copytree(_running_package_dir(), target, ignore=shutil.ignore_patterns("__pycache__"))
    if crlf:
        for path in target.rglob("*.py"):
            content = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(content.replace(b"\n", b"\r\n"))
    return target


@pytest.fixture(scope="session")
def source_digest() -> Callable[[Path], str]:
    """``source_digest(package_dir)``: see ``_source_digest`` (computed by the test)."""
    return _source_digest


@pytest.fixture(scope="session")
def source_manifest() -> Callable[[Path], bytes]:
    """``source_manifest(package_dir)``: see ``_source_manifest`` (computed by the test)."""
    return _source_manifest


@pytest.fixture(scope="session")
def expected_software() -> Callable[[Path], ExpectedSoftware]:
    """``expected_software(package_dir)``: see ``_expected_software``."""
    return _expected_software


@pytest.fixture(scope="session")
def running_software() -> ExpectedSoftware:
    """The identity of the package under test, run in this environment."""
    return _expected_software(_running_package_dir())


@pytest.fixture(scope="session")
def runtime_dependency_names() -> tuple[str, ...]:
    """The names of the runtime dependencies of ``dsp/pyproject.toml``."""
    return _runtime_dependency_names()


@pytest.fixture(scope="session")
def project_version() -> str:
    """The ``[project] version`` of ``dsp/pyproject.toml``."""
    return _project_version()


@pytest.fixture(scope="session")
def copy_package() -> Callable[..., Path]:
    """``copy_package(destination, *, crlf=False)``: see ``_copy_package``."""
    return _copy_package


# A script run in a separate Python process: it writes the validation report of fixture
# databases with a detector double (the samples above 0.5 mV), without network access, and
# prints the folder of the package ``sinus_dsp`` it imported.
_REPORT_DRIVER = '''\
"""Write the validation report of fixture databases with a detector double, without network.

Usage: python <this file> OUTPUT DATA_ROOT MITDB_PIN NSTDB_PIN

Prints "package: <folder of the imported package sinus_dsp>" on standard output.
"""

import socket
import sys
import urllib.request
from pathlib import Path

import numpy as np


def _refuse(*args, **kwargs):
    raise RuntimeError("network access attempted in a test without network")


socket.socket.connect = _refuse
socket.create_connection = _refuse
socket.getaddrinfo = _refuse
urllib.request.urlopen = _refuse

import sinus_dsp  # noqa: E402
from sinus_dsp.data.physionet import Database  # noqa: E402
from sinus_dsp.evaluation.run import write_validation_report  # noqa: E402


def spike_detector(signal_mv, fs_hz, mains_hz):
    return np.flatnonzero(np.asarray(signal_mv, dtype=np.float64) > 0.5).astype(np.int64)


output, data_root, mitdb_pin, nstdb_pin = sys.argv[1:5]
print("package:", Path(sinus_dsp.__file__).resolve().parent)
write_validation_report(
    Path(output),
    Path(data_root),
    mitdb=Database(
        slug="mitdb",
        version="1.0.0",
        title="MIT-BIH Arrhythmia Database",
        checksum_list_sha256=mitdb_pin,
    ),
    nstdb=Database(
        slug="nstdb",
        version="1.0.0",
        title="MIT-BIH Noise Stress Test Database",
        checksum_list_sha256=nstdb_pin,
    ),
    detector=spike_detector,
    fetch=None,
)
'''


@dataclass(frozen=True)
class DriverRun:
    """A report written by the report driver in a separate process."""

    completed: subprocess.CompletedProcess[str]
    package_dir: Path | None
    report: bytes | None


def _run_report_driver(
    fixture: EvaluationFixture,
    output: Path,
    *,
    cwd: Path,
    package_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> DriverRun:
    """Write the report of ``fixture`` to ``output`` in a separate Python process.

    With ``package_root``, that folder comes first on ``PYTHONPATH``, so the process imports
    the package ``sinus_dsp`` found there. ``env`` adds environment variables.
    """
    driver = output.parent / "write_report_driver.py"
    driver.write_text(_REPORT_DRIVER, encoding="utf-8")
    environment = {**os.environ, **(env or {})}
    if package_root is not None:
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(package_root), *([existing] if existing else [])]
        )
    completed = subprocess.run(
        [
            sys.executable,
            str(driver),
            str(output),
            str(fixture.data_root),
            fixture.mitdb.checksum_list_sha256,
            fixture.nstdb.checksum_list_sha256,
        ],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    package = [
        line.removeprefix("package:").strip()
        for line in completed.stdout.splitlines()
        if line.startswith("package:")
    ]
    driver.unlink()
    return DriverRun(
        completed=completed,
        package_dir=Path(package[0]) if package else None,
        report=output.read_bytes() if output.exists() else None,
    )


@pytest.fixture(scope="session")
def run_report_driver() -> Callable[..., DriverRun]:
    """``run_report_driver(fixture, output, *, cwd, package_root=None, env=None)``: see
    ``_run_report_driver``."""
    return _run_report_driver
