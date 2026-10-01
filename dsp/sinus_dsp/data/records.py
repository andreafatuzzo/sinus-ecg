"""Loading of a reference record: one channel and its annotations (architecture §8.4).

SRS-002: for a record and a channel, the software provides the signal of the channel in mV,
its sampling frequency in Hz, the reference beat annotations restricted to the PhysioNet beat
annotation codes, and every other annotation separately from the beat annotations.

Records are read with wfdb. Its errors for conditions that are not checked here (a file that
is absent or a corrupted header, for example) propagate unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import wfdb

from sinus_dsp._types import FloatArray, IndexArray
from sinus_dsp.errors import InvalidInputError, MalformedFileError

#: SRS-002: the 19 beat annotation codes. They are the codes for which the WFDB library
#: function ``isqrs()`` is true, except ``!`` (ventricular flutter wave), which stays a
#: non-beat annotation.
BEAT_SYMBOLS: Final[frozenset[str]] = frozenset(
    {"N", "L", "R", "B", "A", "a", "J", "S", "V", "r", "F", "e", "j", "n", "E", "/", "f", "Q", "?"}
)

_UNITS_MV: Final = "mV"


@dataclass(frozen=True)
class Annotation:
    """An annotation that is not a beat (SRS-002).

    Attributes:
        sample: Index in the time base of the record.
        symbol: WFDB annotation mnemonic, e.g. ``+``, ``~``, ``[``, ``]``, ``!``.
        subtype: WFDB ``subtyp`` field (e.g. the signal-quality bits of ``~``).
        aux_note: Auxiliary text (e.g. ``(AFIB``), trailing NUL characters removed.
    """

    sample: int
    symbol: str
    subtype: int
    aux_note: str


@dataclass(frozen=True)
class Record:
    """One channel of a record, with its annotations (SRS-002).

    Attributes:
        name: Name of the record: the last component of the path it was loaded from.
        channel: Number of the channel; the first stored signal is channel 0.
        signal_name: Name of the signal in the header, e.g. ``MLII``, ``V5``.
        fs_hz: Sampling frequency, in Hz.
        signal_mv: The channel in physical units, mV, one dimension, contiguous float64.
        beat_samples: Sample indices of the beat annotations, non-decreasing, int64.
        beat_symbols: Codes of the beat annotations, one per element of ``beat_samples``.
        other_annotations: Every annotation that is not a beat, in file order.
    """

    name: str
    channel: int
    signal_name: str
    fs_hz: float
    signal_mv: FloatArray
    beat_samples: IndexArray
    beat_symbols: tuple[str, ...]
    other_annotations: tuple[Annotation, ...]

    @property
    def n_samples(self) -> int:
        """Number of samples of the signal."""
        return int(self.signal_mv.shape[0])


def load_record(record_path: Path, channel: int = 0, annotator: str = "atr") -> Record:
    """Load one channel of a record and its annotations.

    SRS-002: returns the signal of the channel in mV, its sampling frequency in Hz, the beat
    annotations (sample index and code, for the codes of :data:`BEAT_SYMBOLS` only) and,
    separately, every other annotation. The two lists together hold every annotation of the
    file exactly once.

    An annotation file without any beat annotation gives empty beat arrays. An annotation
    beyond the end of the signal is kept as it is. The channel number is not the signal name:
    the first stored signal is channel 0.

    Args:
        record_path: Path of the record without extension, e.g. ``data/mitdb/100``.
        channel: Number of the channel, from 0 to the number of signals minus 1.
        annotator: Extension of the annotation file.

    Returns:
        The record.

    Raises:
        InvalidInputError: If the record does not have the channel, or if the units of the
            channel are not mV.
        MalformedFileError: If the sample indices of the annotation file decrease.
    """
    path = str(record_path)
    header = wfdb.rdheader(path)
    n_sig = int(header.n_sig)
    if isinstance(channel, bool) or not isinstance(channel, (int, np.integer)):
        raise InvalidInputError(f"channel is not an integer: {channel!r}")
    if not 0 <= channel < n_sig:
        raise InvalidInputError(
            f"record {path} has no channel {int(channel)}: it has {n_sig} signals, "
            f"channels 0 to {n_sig - 1}"
        )
    channel = int(channel)

    signals = wfdb.rdrecord(path, channels=[channel], physical=True, return_res=64)
    units = str(signals.units[0])
    if units != _UNITS_MV:
        raise InvalidInputError(
            f"channel {channel} of record {path} is not in mV: its units are {units!r}"
        )
    signal_mv: FloatArray = np.array(signals.p_signal[:, 0], dtype=np.float64, order="C", copy=True)

    annotations = wfdb.rdann(path, annotator)
    samples = [int(sample) for sample in annotations.sample]
    for index in range(1, len(samples)):
        if samples[index] < samples[index - 1]:
            raise MalformedFileError(
                f"{path}.{annotator}",
                None,
                f"annotation sample indices decrease: annotation {index + 1} is at sample "
                f"{samples[index]}, after sample {samples[index - 1]}",
            )

    beat_samples: list[int] = []
    beat_symbols: list[str] = []
    other_annotations: list[Annotation] = []
    for sample, symbol, subtype, aux_note in zip(
        samples, annotations.symbol, annotations.subtype, annotations.aux_note, strict=True
    ):
        if symbol in BEAT_SYMBOLS:
            beat_samples.append(sample)
            beat_symbols.append(str(symbol))
        else:
            other_annotations.append(
                Annotation(
                    sample=sample,
                    symbol=str(symbol),
                    subtype=int(subtype),
                    aux_note=str(aux_note).rstrip("\x00"),
                )
            )

    return Record(
        name=Path(record_path).name,
        channel=channel,
        signal_name=str(signals.sig_name[0]),
        fs_hz=float(signals.fs),
        signal_mv=signal_mv,
        beat_samples=np.array(beat_samples, dtype=np.int64),
        beat_symbols=tuple(beat_symbols),
        other_annotations=tuple(other_annotations),
    )
