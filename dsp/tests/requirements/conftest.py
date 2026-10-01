"""Shared fixtures of the requirement tests.

The helpers here are independent of the software under test: they build the test inputs
(synthetic ECGs with known QRS positions, sinusoids, WFDB records, database folders with
their checksum list, a fetch function that serves bytes from a dictionary, random beat and
detection lists around 5:00) and apply the pass criteria of the requirements to its outputs.
Each helper is exposed as a fixture that returns a function or a class.
"""

from __future__ import annotations

import hashlib
import math
import socket
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
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
