"""Requirement tests of SRS-002: loading a reference record.

Each test writes a synthetic WFDB record in a temporary folder with the wfdb package (signal
file, header and annotation file) and loads it through the public loader. The written record
has two signals with different content, ADC gain and baseline, so that the channel and the
conversion to millivolts are both checked, and an annotation file with the 19 beat codes of
SRS-002 and non-beat annotations: rhythm changes with a note, signal-quality marks with a
subtype, a ventricular flutter onset (`[`) and offset (`]`) with flutter waves between them,
and others.

Pass criteria (SRS-002): the signal equals the written one within one quantization step of
the record (1 / ADC gain, read from the written header); the sampling frequency is equal; the
beat annotations are equal and hold no non-beat annotation; every non-beat annotation is in
the separate list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
import wfdb

from sinus_dsp.data.records import BEAT_SYMBOLS, Record, load_record

AnnotationTuple = tuple[int, str, int, str]  # sample, symbol, subtype, auxiliary note

# The beat annotation codes of the SRS-002 statement.
BEAT_CODES = tuple("NLRBAaJSVrFejnE/fQ?")

# Every other annotation code that the WFDB annotation format defines.
NON_BEAT_CODES = tuple('~|sT*D"=p^t+u![]@x()')

# The 39 codes in the order in which the record of ``all_codes_record`` holds them: other
# codes and beat codes alternate. The annotation of ``ALL_CODES[i]`` is at sample 50 + 100 i.
ALL_CODES = tuple(
    code
    for k in range(len(NON_BEAT_CODES))
    for code in (NON_BEAT_CODES[k : k + 1] + BEAT_CODES[k : k + 1])
)

# Non-beat annotations of the reference record, as written. Two rhythm notes end with a NUL
# character, as they are stored in the MIT-BIH Arrhythmia Database.
NON_BEAT_WRITTEN: tuple[AnnotationTuple, ...] = (
    (10, "+", 0, "(N\x00"),
    (1000, "~", 1, ""),
    (2000, "+", 0, "(VFL"),
    (2100, "[", 0, ""),
    (2300, "!", 0, ""),
    (2600, "!", 0, ""),
    (3000, "]", 0, ""),
    (3050, "+", 0, "(AFIB\x00"),
    (5000, "|", 0, ""),
    (6000, "x", 0, ""),
    (7000, '"', 0, "lead moved"),
    (9000, "~", 2, ""),
)

FS_HZ = 360
SIGNAL_NAMES = ("MLII", "V5")
ADC_GAIN = (200.0, 100.0)
BASELINE = (1024, 0)


@dataclass(frozen=True)
class WrittenRecord:
    """What a test wrote, to compare with what the loader returns."""

    path: Path
    signals_mv: npt.NDArray[np.float64]
    beats: tuple[tuple[int, str], ...]
    others: tuple[AnnotationTuple, ...]


def _write_reference(
    folder: Path,
    make_synthetic_ecg: Callable[..., Any],
    write_wfdb_record: Callable[..., Path],
    *,
    fmt: str = "212",
) -> WrittenRecord:
    """Write the reference record of these tests: 30 s at 360 Hz, two signals, annotations.

    - Signal 0 is the synthetic ECG at 75 bpm (37 beats); signal 1 is a different signal
      (the ECG inverted and halved, plus a 0.4 Hz sinusoid of 0.3 mV and an offset of
      0.25 mV).
    - Each QRS has a beat annotation; the codes cycle through the 19 beat codes of SRS-002.
    - The non-beat annotations of ``NON_BEAT_WRITTEN`` lie between the beats.
    """
    ecg = make_synthetic_ecg(FS_HZ, 75)
    t_s = np.arange(ecg.signal_mv.size, dtype=np.float64) / FS_HZ
    second = -0.5 * ecg.signal_mv + 0.3 * np.sin(2.0 * np.pi * 0.4 * t_s) + 0.25
    signals = np.column_stack([ecg.signal_mv, second])

    beats = tuple(
        (int(sample), BEAT_CODES[k % len(BEAT_CODES)])
        for k, sample in enumerate(ecg.qrs_samples.tolist())
    )
    annotations = sorted(
        [(sample, code, 0, "") for sample, code in beats] + list(NON_BEAT_WRITTEN),
        key=lambda a: a[0],
    )
    path = write_wfdb_record(
        folder,
        "rec1",
        fs_hz=FS_HZ,
        signals_mv=signals,
        signal_names=SIGNAL_NAMES,
        fmt=fmt,
        adc_gain=ADC_GAIN,
        baseline=BASELINE,
        annotations=annotations,
    )
    others = tuple(
        (sample, symbol, subtype, note.rstrip("\x00"))
        for sample, symbol, subtype, note in NON_BEAT_WRITTEN
    )
    return WrittenRecord(path=path, signals_mv=signals, beats=beats, others=others)


def _other_tuples(record: Record) -> list[AnnotationTuple]:
    """The non-beat annotations of a loaded record as plain tuples."""
    return [(int(a.sample), a.symbol, int(a.subtype), a.aux_note) for a in record.other_annotations]


@pytest.fixture
def reference(
    tmp_path: Path,
    make_synthetic_ecg: Callable[..., Any],
    write_wfdb_record: Callable[..., Path],
) -> WrittenRecord:
    """The reference record, written in storage format 212."""
    return _write_reference(tmp_path, make_synthetic_ecg, write_wfdb_record)


@pytest.fixture(scope="module")
def all_codes_record(
    tmp_path_factory: pytest.TempPathFactory, write_wfdb_record: Callable[..., Path]
) -> Path:
    """A record whose annotation file holds one annotation of every WFDB annotation code.

    The 39 codes (19 beat codes, 20 others) are written in alternating order, 100 samples
    apart from sample 50.
    """
    annotations = [(50 + 100 * i, code, 0, "") for i, code in enumerate(ALL_CODES)]
    signal = 0.5 * np.sin(2.0 * np.pi * np.arange(4000, dtype=np.float64) / FS_HZ)
    return write_wfdb_record(
        tmp_path_factory.mktemp("all_codes"),
        "codes",
        fs_hz=FS_HZ,
        signals_mv=signal.reshape(-1, 1),
        signal_names=["MLII"],
        annotations=annotations,
    )


def _all_codes_sample(code: str) -> int:
    """Sample of the annotation with ``code`` in the record of ``all_codes_record``."""
    return 50 + 100 * ALL_CODES.index(code)


# --------------------------------------------------------------------------------------------
# Signal and sampling frequency
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-002")
@pytest.mark.parametrize("fmt", ["212", "16"])
@pytest.mark.parametrize("channel", [0, 1])
def test_signal_equals_the_written_one_within_one_quantization_step(
    tmp_path: Path,
    make_synthetic_ecg: Callable[..., Any],
    write_wfdb_record: Callable[..., Path],
    fmt: str,
    channel: int,
) -> None:
    """The ECG signal of the given channel, in millivolts.

    Input: the reference record (30 s at 360 Hz), written in storage format 212 or 16 with
    units mV; signal 0 has an ADC gain of 200 per mV and a baseline of 1024, signal 1 a gain
    of 100 per mV and a baseline of 0. The record is loaded for channel 0 or channel 1.
    Expected: a one-dimensional float64 signal with the 10800 written samples, equal to the
    written signal of that channel within one quantization step (1 / ADC gain of the written
    header: 0.005 mV for channel 0, 0.01 mV for channel 1). The other signal of the record
    differs from it by much more than that step.
    """
    written = _write_reference(tmp_path, make_synthetic_ecg, write_wfdb_record, fmt=fmt)
    header = wfdb.rdheader(str(written.path))
    step_mv = 1.0 / header.adc_gain[channel]
    expected = written.signals_mv[:, channel]
    other = written.signals_mv[:, 1 - channel]

    record = load_record(written.path, channel)

    assert header.units[channel] == "mV"
    assert step_mv == 1.0 / ADC_GAIN[channel]
    assert isinstance(record.signal_mv, np.ndarray)
    assert record.signal_mv.dtype == np.float64
    assert record.signal_mv.shape == (10800,)
    assert record.n_samples == 10800
    assert float(np.max(np.abs(record.signal_mv - expected))) <= step_mv
    assert float(np.max(np.abs(other - expected))) > 50 * step_mv


@pytest.mark.requirement("SRS-002")
def test_channel_defaults_to_the_first_stored_signal(reference: WrittenRecord) -> None:
    """Loading a record without naming a channel.

    Input: the reference record, loaded without a channel argument.
    Expected: the first stored signal (channel 0, named MLII), within one quantization step
    (0.005 mV).
    """
    record = load_record(reference.path)

    assert record.channel == 0
    assert record.signal_name == "MLII"
    assert float(np.max(np.abs(record.signal_mv - reference.signals_mv[:, 0]))) <= 0.005


@pytest.mark.requirement("SRS-002")
@pytest.mark.parametrize("channel", [0, 1])
def test_record_identifies_the_record_and_the_channel(
    reference: WrittenRecord, channel: int
) -> None:
    """The loaded record says which record and channel it holds.

    Input: the reference record `rec1` with the signals MLII and V5, loaded for channel 0 or
    channel 1.
    Expected: the record name `rec1`, the requested channel number and the name of that
    signal.
    """
    record = load_record(reference.path, channel)

    assert record.name == "rec1"
    assert record.channel == channel
    assert record.signal_name == SIGNAL_NAMES[channel]


@pytest.mark.requirement("SRS-002")
@pytest.mark.parametrize("fs_hz", [125, 250, 360, 1000])
def test_sampling_frequency_equals_the_written_one(
    tmp_path: Path, write_wfdb_record: Callable[..., Path], fs_hz: int
) -> None:
    """The sampling frequency of the record, in Hz.

    Input: a record of 10 s with one signal (a 1 Hz sinusoid of 0.5 mV) and two annotations,
    written with a sampling frequency of 125, 250, 360 or 1000 Hz.
    Expected: the loaded sampling frequency equals the written one, and the signal has
    10 s times that many samples, equal to the written one within one quantization step
    (0.005 mV).
    """
    n = 10 * fs_hz
    signal = 0.5 * np.sin(2.0 * np.pi * np.arange(n, dtype=np.float64) / fs_hz)
    path = write_wfdb_record(
        tmp_path,
        "rate",
        fs_hz=fs_hz,
        signals_mv=signal.reshape(-1, 1),
        signal_names=["MLII"],
        annotations=[(fs_hz, "N", 0, ""), (2 * fs_hz, "+", 0, "(N")],
    )

    record = load_record(path, 0)

    assert record.fs_hz == fs_hz
    assert record.n_samples == n
    assert float(np.max(np.abs(record.signal_mv - signal))) <= 0.005
    assert record.beat_samples.tolist() == [fs_hz]
    assert _other_tuples(record) == [(2 * fs_hz, "+", 0, "(N")]


# --------------------------------------------------------------------------------------------
# Beat annotations
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-002")
def test_beat_codes_are_the_19_codes_of_the_requirement() -> None:
    """The set of beat annotation codes.

    Input: none.
    Expected: the beat codes of the software are exactly N, L, R, B, A, a, J, S, V, r, F, e,
    j, n, E, /, f, Q and ? (19 codes).
    """
    assert len(BEAT_CODES) == 19
    assert set(BEAT_SYMBOLS) == set(BEAT_CODES)


@pytest.mark.requirement("SRS-002")
def test_beat_annotations_equal_the_written_ones(reference: WrittenRecord) -> None:
    """Reference beat annotations, as sample index and label.

    Input: the reference record: 37 beat annotations at the QRS positions, whose codes cycle
    through the 19 beat codes of SRS-002, among 12 non-beat annotations.
    Expected: the beat samples (integers, in the time base of the record) and the beat
    labels equal the written ones, in the same order; all 19 codes are present; no non-beat
    annotation is among them.
    """
    record = load_record(reference.path)

    assert record.beat_samples.dtype == np.int64
    assert record.beat_samples.tolist() == [sample for sample, _ in reference.beats]
    assert list(record.beat_symbols) == [code for _, code in reference.beats]
    assert len(record.beat_symbols) == 37
    assert set(record.beat_symbols) == set(BEAT_CODES)
    assert not set(record.beat_symbols) & set(NON_BEAT_CODES)
    assert not set(record.beat_samples.tolist()) & {a[0] for a in NON_BEAT_WRITTEN}


@pytest.mark.requirement("SRS-002")
@pytest.mark.parametrize("code", BEAT_CODES)
def test_each_beat_code_is_returned_as_a_beat(all_codes_record: Path, code: str) -> None:
    """Every beat code of SRS-002, one by one.

    Input: a record with one annotation of each of the 39 WFDB annotation codes.
    Expected: the annotation with the given beat code is among the beat annotations, with
    its sample, and is not among the other annotations.
    """
    record = load_record(all_codes_record)
    beats = list(zip(record.beat_samples.tolist(), record.beat_symbols, strict=True))

    assert (_all_codes_sample(code), code) in beats
    assert code not in [a.symbol for a in record.other_annotations]


@pytest.mark.requirement("SRS-002")
@pytest.mark.parametrize("code", NON_BEAT_CODES)
def test_each_other_code_is_returned_separately(all_codes_record: Path, code: str) -> None:
    """Every annotation code that is not a beat code of SRS-002, one by one.

    Input: a record with one annotation of each of the 39 WFDB annotation codes.
    Expected: the annotation with the given non-beat code (among them the ventricular
    flutter wave `!`, the onset `[` and the offset `]`) is in the list of other annotations,
    with its sample, and is not among the beat annotations.
    """
    record = load_record(all_codes_record)
    others = [(int(a.sample), a.symbol) for a in record.other_annotations]

    assert (_all_codes_sample(code), code) in others
    assert code not in record.beat_symbols


@pytest.mark.requirement("SRS-002")
def test_record_with_every_code_is_split_without_loss(all_codes_record: Path) -> None:
    """Beat and other annotations together hold every annotation once.

    Input: a record with one annotation of each of the 39 WFDB annotation codes, beat codes
    and other codes alternating.
    Expected: 19 beat annotations and 20 other annotations, each list in the order of the
    file, and their union is the 39 written annotations.
    """
    record = load_record(all_codes_record)
    beats = list(zip(record.beat_samples.tolist(), record.beat_symbols, strict=True))
    others = [(int(a.sample), a.symbol) for a in record.other_annotations]

    assert beats == sorted((_all_codes_sample(code), code) for code in BEAT_CODES)
    assert others == sorted((_all_codes_sample(code), code) for code in NON_BEAT_CODES)
    assert len(beats) + len(others) == 39


# --------------------------------------------------------------------------------------------
# Other annotations
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-002")
def test_every_non_beat_annotation_is_returned_in_the_separate_list(
    reference: WrittenRecord,
) -> None:
    """All other annotations, separately from the beat annotations.

    Input: the reference record: 12 non-beat annotations (three rhythm changes with a note,
    two signal-quality marks with subtypes 1 and 2, a ventricular flutter onset and offset
    with two flutter waves between them, an isolated artefact, a non-conducted P wave and a
    comment) among 37 beat annotations.
    Expected: the list of other annotations holds exactly these 12 annotations, in the order
    of the file, each with its sample, code, subtype and note (a NUL character that ends a
    stored note is not part of the note); none of them carries a beat code; beat and other
    annotations together are the 49 written annotations.
    """
    record = load_record(reference.path)

    assert _other_tuples(record) == list(reference.others)
    assert not {a.symbol for a in record.other_annotations} & set(BEAT_CODES)
    assert len(record.beat_symbols) + len(record.other_annotations) == 49


@pytest.mark.requirement("SRS-002")
def test_ventricular_flutter_onset_and_offset_are_returned(reference: WrittenRecord) -> None:
    """The `[` and `]` annotations that SRS-008 needs.

    Input: the reference record, with `[` at sample 2100, `]` at sample 3000 and flutter
    waves (`!`) at 2300 and 2600.
    Expected: the other annotations hold the onset and the offset at these samples, in this
    order, and the two flutter waves; none of the three codes is among the beat labels.
    """
    record = load_record(reference.path)
    flutter = [(int(a.sample), a.symbol) for a in record.other_annotations if a.symbol in "[]!"]

    assert flutter == [(2100, "["), (2300, "!"), (2600, "!"), (3000, "]")]
    assert not {"[", "]", "!"} & set(record.beat_symbols)


@pytest.mark.requirement("SRS-002")
def test_rhythm_change_keeps_its_note_and_quality_mark_its_subtype(
    reference: WrittenRecord,
) -> None:
    """The content of a rhythm change and of a signal-quality mark.

    Input: the reference record, with rhythm changes `+` noted `(N`, `(VFL` and `(AFIB` at
    samples 10, 2000 and 3050, and signal-quality marks `~` of subtype 1 and 2 at samples
    1000 and 9000.
    Expected: the other annotations give the three rhythm changes with their notes and the
    two signal-quality marks with their subtypes.
    """
    record = load_record(reference.path)
    rhythm = [(int(a.sample), a.aux_note) for a in record.other_annotations if a.symbol == "+"]
    quality = [(int(a.sample), int(a.subtype)) for a in record.other_annotations if a.symbol == "~"]

    assert rhythm == [(10, "(N"), (2000, "(VFL"), (3050, "(AFIB")]
    assert quality == [(1000, 1), (9000, 2)]


@pytest.mark.requirement("SRS-002")
def test_annotations_do_not_depend_on_the_channel(reference: WrittenRecord) -> None:
    """The annotations of a record are the same for every channel.

    Input: the reference record, loaded for channel 0 and for channel 1.
    Expected: the same beat samples, beat labels and other annotations for both channels.
    """
    first = load_record(reference.path, 0)
    second = load_record(reference.path, 1)

    assert second.beat_samples.tolist() == first.beat_samples.tolist()
    assert second.beat_symbols == first.beat_symbols
    assert _other_tuples(second) == _other_tuples(first)
    assert second.fs_hz == first.fs_hz == FS_HZ


@pytest.mark.requirement("SRS-002")
def test_record_with_beat_annotations_only(
    tmp_path: Path, write_wfdb_record: Callable[..., Path]
) -> None:
    """A record without any non-beat annotation.

    Input: a record of 10 s at 360 Hz with four beat annotations (N, V, /, ?) and nothing
    else.
    Expected: the four beats with their samples and labels; an empty list of other
    annotations.
    """
    signal = 0.5 * np.sin(2.0 * np.pi * np.arange(3600, dtype=np.float64) / FS_HZ)
    beats = [(300, "N", 0, ""), (900, "V", 0, ""), (1500, "/", 0, ""), (2100, "?", 0, "")]
    path = write_wfdb_record(
        tmp_path,
        "beats",
        fs_hz=FS_HZ,
        signals_mv=signal.reshape(-1, 1),
        signal_names=["MLII"],
        annotations=beats,
    )

    record = load_record(path)

    assert record.beat_samples.tolist() == [300, 900, 1500, 2100]
    assert list(record.beat_symbols) == ["N", "V", "/", "?"]
    assert len(record.other_annotations) == 0


@pytest.mark.requirement("SRS-002")
def test_record_without_beat_annotation(
    tmp_path: Path, write_wfdb_record: Callable[..., Path]
) -> None:
    """A record whose annotation file holds no beat.

    Input: a record of 10 s at 360 Hz with a rhythm change, a ventricular flutter onset, a
    flutter wave and a signal-quality mark, and no beat annotation.
    Expected: no beat sample and no beat label; the four annotations in the list of other
    annotations.
    """
    signal = 0.5 * np.sin(2.0 * np.pi * np.arange(3600, dtype=np.float64) / FS_HZ)
    others = [(20, "+", 0, "(VFL"), (25, "[", 0, ""), (400, "!", 0, ""), (3000, "~", 3, "")]
    path = write_wfdb_record(
        tmp_path,
        "nobeat",
        fs_hz=FS_HZ,
        signals_mv=signal.reshape(-1, 1),
        signal_names=["MLII"],
        annotations=others,
    )

    record = load_record(path)

    assert record.beat_samples.tolist() == []
    assert len(record.beat_symbols) == 0
    assert _other_tuples(record) == others
