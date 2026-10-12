"""Write the WFDB fixture records of the desktop tests (architecture-m3.md 17.8).

Run from ``dsp/``::

    uv run python ../desktop/tests/fixtures/make_wfdb_fixtures.py

The records go to ``desktop/tests/fixtures/wfdb/`` (committed). Records that ``wfdb`` can write
are written with ``wfdb.wrsamp``; the others (rejections, ``no_units``, ``gain_zero``, the
recorded sessions) are written as text. Every header is written with LF line ends, whatever the
operating system. For each readable record the script also writes ``<record>.expected`` (the
values of the offline loader, computed here as ``(d - baseline) / gain`` in binary64), and
``rejections.txt`` lists the status of the reader for each rejection record.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import wfdb

from sinus_dsp.synthetic import synthetic_ecg

FIXTURE_DIR: Final = Path(__file__).resolve().parent / "wfdb"

#: The values of a format: format 16 and 212 without their invalid-sample codes.
_RANGE: Final = {"16": (-32767, 32767), "212": (-2047, 2047)}
#: Rows of small records are listed in full in their ``.expected`` file; long ones are not.
_REPLAY_SECONDS: Final = 61
_SESSION_SECONDS: Final = 20

#: Metadata of the recorded sessions (architecture-m3.md 17.6).
_SESSION_METADATA: Final = (
    "sinus_recording=1",
    "start_utc=2026-10-11T10:20:30.123Z",
    "source=test",
    "source_name=127.0.0.1:45000",
    "mains_hz={mains}",
    "desktop_version=0.3.0.dev0",
    "desktop_source_sha256=" + "0123456789abcdef" * 4,
    "library_version=0.3.0.dev0",
    "library_source_sha256=" + "fedcba9876543210" * 4,
)
_SESSION_EVENTS: Final = (
    "event=gap at_sample=3600 missing_samples=1080",
    "event=interruption at_sample=5400 missing_samples=0 duration_ms=1500",
)

#: Values of the small rejection records.
_SMALL: Final = (0, 10, -10, 20, -20, 30, -30, 40, -40, 50)


@dataclass(frozen=True)
class Expected:
    """The content of a ``.expected`` file of a readable record."""

    record: str
    fs_millihertz: int
    signal0_adu: np.ndarray
    gain: float
    baseline: int
    listed: bool


def checksum(values: np.ndarray | tuple[int, ...]) -> int:
    """The WFDB checksum: the sum modulo 2**16 as a signed 16-bit number."""
    total = int(np.sum(np.asarray(values, dtype=np.int64))) % 65536
    return total - 65536 if total >= 32768 else total


def format16_bytes(values: np.ndarray | tuple[int, ...]) -> bytes:
    """Little-endian two's-complement 16-bit values."""
    return np.asarray(values, dtype="<i2").tobytes()


def format212_bytes(values: np.ndarray | tuple[int, ...]) -> bytes:
    """Pairs of 12-bit values in 3 bytes; an odd last value takes 2 bytes."""
    words = [int(value) & 0xFFF for value in values]
    out = bytearray()
    for j in range(0, len(words), 2):
        even = words[j]
        out.append(even & 0xFF)
        if j + 1 == len(words):
            out.append(even >> 8)
            break
        odd = words[j + 1]
        out.append((even >> 8) | ((odd >> 8) << 4))
        out.append(odd & 0xFF)
    return bytes(out)


def _normalise_header(path: Path, signal_count: int) -> None:
    """Rewrite a header written by ``wfdb`` in the form of the reference databases.

    ``wfdb`` writes CRLF line ends on Windows, and the checksum as an unsigned number (0 to
    65535); the reference databases and the recording writer state it as a signed 16-bit
    number, the form the reader of the desktop application accepts. Nothing else changes.
    """
    lines = path.read_bytes().decode("ascii").replace("\r\n", "\n").split("\n")
    for index in range(1, 1 + signal_count):
        fields = lines[index].split(" ")
        fields[6] = str(checksum((int(fields[6]),)))
        lines[index] = " ".join(fields)
    path.write_bytes("\n".join(lines).encode("ascii"))


def _wrsamp(
    folder: Path,
    name: str,
    fs: float,
    fmt: str,
    columns: list[np.ndarray],
    gains: list[float],
    baselines: list[int],
) -> list[Path]:
    """Write a record with ``wfdb.wrsamp`` from its digital values, one column per signal."""
    d_signal = np.column_stack([np.asarray(column, dtype=np.int64) for column in columns])
    names = ["ECG"] + [f"S{index}" for index in range(1, len(columns))]
    wfdb.wrsamp(
        name,
        fs=fs,
        units=["mV"] * len(columns),
        sig_name=names,
        d_signal=d_signal,
        fmt=[fmt] * len(columns),
        adc_gain=gains,
        baseline=baselines,
        write_dir=str(folder),
    )
    header = folder / f"{name}.hea"
    _normalise_header(header, len(columns))
    return [header, folder / f"{name}.dat"]


def _text_record(
    folder: Path, name: str, header: str, signal_files: dict[str, bytes]
) -> list[Path]:
    """Write a header given as text, and its signal files."""
    header_path = folder / f"{name}.hea"
    header_path.write_bytes(header.encode("utf-8"))
    paths = [header_path]
    for file_name, content in signal_files.items():
        path = folder / file_name
        path.write_bytes(content)
        paths.append(path)
    return paths


def _signal_line(name: str, fmt: str, gain: str, values: tuple[int, ...] | np.ndarray) -> str:
    """A signal line of format ``fmt`` with the initial value and checksum of ``values``."""
    first = int(np.asarray(values)[0]) if len(values) else 0
    return f"{name}.dat {fmt} {gain} 16 0 {first} {checksum(values)} 0 ECG\n"


def _replay_values(fs: int, variant: str) -> np.ndarray:
    """``synthetic_ecg`` three times end to end, cut to 61 s, in mV."""
    signal = synthetic_ecg(fs, 75, variant).signal_mv
    return np.concatenate([signal, signal, signal])[: _REPLAY_SECONDS * fs]


def _to_adu(values_mv: np.ndarray, gain: float, baseline: int, fmt: str) -> np.ndarray:
    """Analogue values to adu: ``numpy.round``, then clipped to the range of the format."""
    low, high = _RANGE[fmt]
    adu = np.round(values_mv * gain) + baseline
    return np.clip(adu, low, high).astype(np.int64)


def _session_header(name: str, adu: np.ndarray, mains: int, events: tuple[str, ...]) -> str:
    """The header of a recorded session as the recording writer writes it (17.6)."""
    lines = [
        f"{name} 1 360 {len(adu)}\n",
        f"{name}.dat 16 1000(0)/mV 16 0 {int(adu[0])} {checksum(adu)} 0 ECG\n",
    ]
    lines += [f"# {line.format(mains=mains)}\n" for line in _SESSION_METADATA]
    lines += [f"# {line}\n" for line in events]
    return "".join(lines)


def _session_adu(replay16: np.ndarray, samples: int) -> np.ndarray:
    """The adu at gain 1000 of the binary32 values of ``replay16`` (gain 200), as recorded."""
    values_mv = (replay16[:samples].astype(np.float64) / 200.0).astype(np.float32)
    return _to_adu(values_mv.astype(np.float64), 1000.0, 0, "16")


def _expected_text(expected: Expected) -> str:
    """The ``.expected`` file: record, fs, count, SHA-256 of the binary32 values, rows."""
    adu = expected.signal0_adu
    values = (adu.astype(np.float64) - float(expected.baseline)) / expected.gain
    rounded = values.astype(np.float32)
    digest = hashlib.sha256(rounded.astype("<f4").tobytes()).hexdigest()
    rows = len(adu) if expected.listed else 0
    lines = [
        f"record={expected.record}",
        f"fs_millihertz={expected.fs_millihertz}",
        f"sample_count={len(adu)}",
        f"sha256_binary32={digest}",
        f"rows={rows}",
    ]
    for index in range(rows):
        bits64 = struct.pack(">d", float(values[index])).hex()
        bits32 = struct.pack(">f", float(rounded[index])).hex()
        lines.append(f"{int(adu[index])} {bits64} {bits32}")
    return "\n".join(lines) + "\n"


def _readable_records(folder: Path) -> tuple[list[Path], list[Expected], np.ndarray]:
    """The records that the reader accepts; also returns the values of ``replay16``."""
    paths: list[Path] = []
    expected: list[Expected] = []

    f16_one = np.array(
        [-32767, -1, 0, 1, 32767] + [(k * 7919) % 65535 - 32767 for k in range(32)], dtype=np.int64
    )
    paths += _wrsamp(folder, "f16_one", 360, "16", [f16_one], [200.0], [-12])
    expected.append(Expected("f16_one", 360000, f16_one, 200.0, -12, listed=True))

    f16_two = [
        np.array([(k * 37) % 2001 - 1000 for k in range(25)], dtype=np.int64),
        np.array([k * 3 - 30 for k in range(25)], dtype=np.int64),
    ]
    paths += _wrsamp(folder, "f16_two", 250, "16", f16_two, [1000.0, 100.0], [5, 0])
    expected.append(Expected("f16_two", 250000, f16_two[0], 1000.0, 5, listed=True))

    f212_even = [
        np.array([-2047, -1, 0, 2047] + [(k * 331) % 4095 - 2047 for k in range(36)]),
        np.array([(k * 97) % 4095 - 2047 for k in range(40)]),
    ]
    paths += _wrsamp(folder, "f212_even", 360, "212", f212_even, [200.0, 200.0], [1024, 1024])
    expected.append(Expected("f212_even", 360000, f212_even[0], 200.0, 1024, listed=True))

    f212_odd = np.array([-2047, -5, 0, 5, 100, 2047, -300], dtype=np.int64)
    paths += _wrsamp(folder, "f212_odd", 360, "212", [f212_odd], [200.0], [0])
    expected.append(Expected("f212_odd", 360000, f212_odd, 200.0, 0, listed=True))

    f212_odd3 = [
        np.array([10, -20, 30, -40, 50]),
        np.array([2047, -2047, 1, -1, 0]),
        np.array([-100, 200, -300, 400, -500]),
    ]
    paths += _wrsamp(folder, "f212_odd3", 360, "212", f212_odd3, [200.0] * 3, [0] * 3)
    expected.append(Expected("f212_odd3", 360000, f212_odd3[0], 200.0, 0, listed=True))

    no_units = np.array([5, -5, 15, -15, 25, -25, 35, -35, 45, -45], dtype=np.int64)
    paths += _text_record(
        folder,
        "no_units",
        "no_units 1 360 10\n" + _signal_line("no_units", "16", "200", no_units),
        {"no_units.dat": format16_bytes(no_units)},
    )
    expected.append(Expected("no_units", 360000, no_units, 200.0, 0, listed=True))

    gain_zero = np.array(_SMALL, dtype=np.int64)
    paths += _text_record(
        folder,
        "gain_zero",
        "gain_zero 1 360 10\n" + _signal_line("gain_zero", "16", "0", gain_zero),
        {"gain_zero.dat": format16_bytes(gain_zero)},
    )
    expected.append(Expected("gain_zero", 360000, gain_zero, 200.0, 0, listed=True))

    fs_frac = np.array([k * 11 - 60 for k in range(13)], dtype=np.int64)
    paths += _wrsamp(folder, "fs_frac", 128.5, "16", [fs_frac], [200.0], [0])
    expected.append(Expected("fs_frac", 128500, fs_frac, 200.0, 0, listed=True))

    replay16 = _to_adu(_replay_values(360, "clean"), 200.0, 0, "16")
    paths += _wrsamp(folder, "replay16", 360, "16", [replay16], [200.0], [0])
    expected.append(Expected("replay16", 360000, replay16, 200.0, 0, listed=False))

    replay212_mv = _replay_values(250, "bw-mains50")
    replay212 = [
        _to_adu(replay212_mv, 200.0, 1024, "212"),
        _to_adu(-replay212_mv, 200.0, 1024, "212"),
    ]
    paths += _wrsamp(folder, "replay212", 250, "212", replay212, [200.0, 200.0], [1024, 1024])
    expected.append(Expected("replay212", 250000, replay212[0], 200.0, 1024, listed=False))

    session = _session_adu(replay16, _SESSION_SECONDS * 360)
    paths += _text_record(
        folder,
        "session_gap",
        _session_header("session_gap", session, 60, _SESSION_EVENTS),
        {"session_gap.dat": format16_bytes(session)},
    )
    expected.append(Expected("session_gap", 360000, session, 1000.0, 0, listed=False))

    for item in expected:
        path = folder / f"{item.record}.expected"
        path.write_bytes(_expected_text(item).encode("ascii"))
        paths.append(path)
    return paths, expected, replay16


def _reference_folders(folder: Path) -> list[Path]:
    """``refdb/ref1`` (``f16_one`` under that name) with its checksum list, and ``refdb_bad``."""
    refdb = folder / "refdb"
    refdb_bad = folder / "refdb_bad"
    for path in (refdb, refdb_bad):
        path.mkdir(parents=True, exist_ok=True)
    values = np.array(
        [-32767, -1, 0, 1, 32767] + [(k * 7919) % 65535 - 32767 for k in range(32)], dtype=np.int64
    )
    paths = _wrsamp(refdb, "ref1", 360, "16", [values], [200.0], [-12])
    entries = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in sorted(paths)
    )
    checksum_list = refdb / "SHA256SUMS.txt"
    checksum_list.write_bytes(entries.encode("ascii"))
    paths.append(checksum_list)
    for path in sorted(refdb.iterdir()):
        copy = refdb_bad / path.name
        shutil.copyfile(path, copy)
        paths.append(copy)
    damaged = refdb_bad / "ref1.dat"
    content = bytearray(damaged.read_bytes())
    content[10] ^= 0x01
    damaged.write_bytes(bytes(content))
    return paths


def _rejection_records(folder: Path, replay16: np.ndarray) -> tuple[list[Path], list[str]]:
    """The rejection records and the lines of ``rejections.txt``."""
    small = _SMALL
    small16 = format16_bytes(small)
    paths: list[Path] = []
    lines: list[str] = []

    def add(name: str, status: str, header: str, files: dict[str, bytes]) -> None:
        paths.extend(_text_record(folder, name, header, files))
        lines.append(f"{name} {status}")

    def line(name: str, fmt: str = "16", gain: str = "200/mV") -> str:
        return _signal_line(name, fmt, gain, small)

    add(
        "bad_format",
        "kUnsupportedFormat",
        "bad_format 1 360 10\n" + line("bad_format", fmt="80"),
        {"bad_format.dat": small16},
    )
    add(
        "bad_units",
        "kUnsupportedUnits",
        "bad_units 1 360 10\n" + line("bad_units", gain="200/µV"),
        {"bad_units.dat": small16},
    )
    add(
        "truncated",
        "kTruncatedSignal",
        "truncated 1 360 10\n" + line("truncated"),
        {"truncated.dat": small16[:-1]},
    )
    add(
        "empty",
        "kEmptyRecord",
        "empty 1 360 0\nempty.dat 16 200/mV 16 0 0 0 0 ECG\n",
        {"empty.dat": b""},
    )
    add("multiseg", "kUnsupportedRecord", "multiseg/2 1 360 20\nseg_a 10\nseg_b 10\n", {})
    add(
        "skew",
        "kUnsupportedRecord",
        "skew 1 360 10\n" + line("skew", fmt="16:1"),
        {"skew.dat": small16},
    )
    add(
        "offset",
        "kUnsupportedRecord",
        "offset 1 360 10\n" + line("offset", fmt="16+512"),
        {"offset.dat": bytes(512) + small16},
    )
    add(
        "two_files",
        "kUnsupportedRecord",
        "two_files 2 360 10\n"
        + _signal_line("two_files_a", "16", "200/mV", small)
        + _signal_line("two_files_b", "16", "200/mV", small),
        {"two_files_a.dat": small16, "two_files_b.dat": small16},
    )
    add(
        "fs_low",
        "kUnsupportedRecord",
        "fs_low 1 100 10\n" + line("fs_low"),
        {"fs_low.dat": small16},
    )
    add("no_fs", "kMalformedHeader", "no_fs 1\n" + line("no_fs"), {"no_fs.dat": small16})
    first = small[0]
    add(
        "bad_checksum",
        "kChecksumMismatch",
        f"bad_checksum 1 360 10\nbad_checksum.dat 16 200/mV 16 0 {first} {checksum(small) + 1}"
        " 0 ECG\n",
        {"bad_checksum.dat": small16},
    )
    add(
        "bad_initval",
        "kChecksumMismatch",
        f"bad_initval 1 360 10\nbad_initval.dat 16 200/mV 16 0 {first + 1} {checksum(small)}"
        " 0 ECG\n",
        {"bad_initval.dat": small16},
    )
    invalid = (0, 10, -32768, 20)
    add(
        "invalid_code",
        "kInvalidSampleValue",
        "invalid_code 1 360 4\n" + _signal_line("invalid_code", "16", "200/mV", invalid),
        {"invalid_code.dat": format16_bytes(invalid)},
    )
    add(
        "name_mismatch",
        "kUnsupportedRecord",
        "other 1 360 10\n" + line("name_mismatch"),
        {"name_mismatch.dat": small16},
    )
    too_big = (0, 100, 20000, -5)
    add(
        "too_big",
        "kSampleOutOfRange",
        "too_big 1 360 4\n" + _signal_line("too_big", "16", "1/mV", too_big),
        {"too_big.dat": format16_bytes(too_big)},
    )
    session = _session_adu(replay16, 360)
    add(
        "session_bad_mains",
        "kMalformedRecording",
        _session_header("session_bad_mains", session, 55, ()),
        {"session_bad_mains.dat": format16_bytes(session)},
    )
    return paths, lines


def write_fixtures(folder: Path) -> list[Path]:
    """Write every fixture into ``folder``; returns the files written, sorted."""
    folder.mkdir(parents=True, exist_ok=True)
    paths, _, replay16 = _readable_records(folder)
    paths += _reference_folders(folder)
    rejection_paths, lines = _rejection_records(folder, replay16)
    paths += rejection_paths
    rejections = folder / "rejections.txt"
    rejections.write_bytes(("\n".join(lines) + "\n").encode("ascii"))
    paths.append(rejections)
    return sorted(set(paths))


def main() -> int:
    for path in write_fixtures(FIXTURE_DIR):
        print(path.relative_to(FIXTURE_DIR).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
