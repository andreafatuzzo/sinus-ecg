"""Unit tests of the record loader, on small synthetic WFDB records written by the tests."""

import dataclasses
import struct
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
import wfdb

from sinus_dsp.data.records import BEAT_SYMBOLS, Annotation, Record, load_record
from sinus_dsp.errors import InvalidInputError, MalformedFileError, SinusError

FS_HZ = 360
N_SAMPLES = 1800
ADC_GAIN = 200.0

BEAT_CODES: tuple[str, ...] = tuple("NLRBAaJSVrFejnE/fQ?")
NON_BEAT_CODES: tuple[str, ...] = tuple('+~[!]"|x()ptu^=@')


def two_signals(n_samples: int = N_SAMPLES) -> npt.NDArray[np.float64]:
    """Two channels in mV, on the quantization grid of the record (multiples of 1 / 200 mV)."""
    n = np.arange(n_samples)
    first = np.round(ADC_GAIN * 1.2 * np.sin(2.0 * np.pi * n / 90.0)) / ADC_GAIN
    second = np.round(ADC_GAIN * 0.4 * np.cos(2.0 * np.pi * n / 45.0)) / ADC_GAIN
    return np.column_stack([first, second])


def write_record(
    folder: Path,
    name: str = "rec",
    *,
    units: Sequence[str] = ("mV", "mV"),
    fmt: str = "16",
    fs: float = FS_HZ,
) -> npt.NDArray[np.float64]:
    """Write a two-channel record and return the signals written, in mV."""
    signals = two_signals()
    wfdb.wrsamp(
        name,
        fs=fs,
        units=list(units),
        sig_name=["MLII", "V5"],
        p_signal=signals,
        fmt=[fmt, fmt],
        adc_gain=[ADC_GAIN, ADC_GAIN],
        baseline=[0, 0],
        write_dir=str(folder),
    )
    return signals


def write_annotations(
    folder: Path,
    samples: Sequence[int],
    symbols: Sequence[str],
    *,
    name: str = "rec",
    annotator: str = "atr",
    subtypes: Sequence[int] | None = None,
    aux_notes: Sequence[str] | None = None,
) -> None:
    wfdb.wrann(
        name,
        annotator,
        np.array(samples, dtype=np.int64),
        symbol=list(symbols),
        subtype=None if subtypes is None else np.array(subtypes, dtype=np.int64),
        aux_note=None if aux_notes is None else list(aux_notes),
        write_dir=str(folder),
    )


def annotation_word(code: int, interval: int) -> bytes:
    """One 16-bit word of the MIT annotation format: 6 bits of code, 10 bits of interval."""
    return struct.pack("<H", (code << 10) | interval)


def write_decreasing_annotations(path: Path) -> None:
    """An annotation file with beats at samples 100, 50 and 250: a SKIP goes back 150."""
    skip = -150 & 0xFFFFFFFF
    content = annotation_word(1, 100)  # N at 100
    content += annotation_word(1, 100)  # N at 200
    content += annotation_word(59, 0) + struct.pack("<HH", skip >> 16, skip & 0xFFFF)  # SKIP
    content += annotation_word(5, 0)  # V at 50
    content += annotation_word(1, 200)  # N at 250
    content += annotation_word(0, 0)  # end of file
    path.write_bytes(content)


# BEAT_SYMBOLS


def test_beat_symbols_are_the_19_codes() -> None:
    assert BEAT_SYMBOLS == frozenset(BEAT_CODES)
    assert len(BEAT_SYMBOLS) == 19
    assert isinstance(BEAT_SYMBOLS, frozenset)


@pytest.mark.parametrize("symbol", ["!", "[", "]", "+", "~", "|", "x", "", "NN", "v", "q"])
def test_beat_symbols_leave_out_other_codes(symbol: str) -> None:
    assert symbol not in BEAT_SYMBOLS


# Signal


@pytest.mark.parametrize("fmt", ["16", "212"])
@pytest.mark.parametrize(("channel", "signal_name"), [(0, "MLII"), (1, "V5")])
def test_signal_of_the_channel_in_mv(
    tmp_path: Path, fmt: str, channel: int, signal_name: str
) -> None:
    written = write_record(tmp_path, fmt=fmt)
    write_annotations(tmp_path, [100], ["N"])
    record = load_record(tmp_path / "rec", channel)
    assert record.name == "rec"
    assert record.channel == channel
    assert record.signal_name == signal_name
    assert record.n_samples == N_SAMPLES
    assert record.signal_mv.shape == (N_SAMPLES,)
    assert record.signal_mv.dtype == np.float64
    assert record.signal_mv.flags.c_contiguous
    assert record.signal_mv.flags.owndata
    # Within one quantization step of the record.
    assert float(np.max(np.abs(record.signal_mv - written[:, channel]))) <= 1.0 / ADC_GAIN


def test_channel_0_is_the_default(tmp_path: Path) -> None:
    written = write_record(tmp_path)
    write_annotations(tmp_path, [100], ["N"])
    record = load_record(tmp_path / "rec")
    assert (record.channel, record.signal_name) == (0, "MLII")
    np.testing.assert_allclose(record.signal_mv, written[:, 0], atol=1.0 / ADC_GAIN)


def test_sampling_frequency_is_a_float(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100], ["N"])
    record = load_record(tmp_path / "rec")
    assert type(record.fs_hz) is float
    assert record.fs_hz == 360.0


def test_sampling_frequency_that_is_not_an_integer(tmp_path: Path) -> None:
    write_record(tmp_path, fs=128.5)
    write_annotations(tmp_path, [100], ["N"])
    assert load_record(tmp_path / "rec").fs_hz == 128.5


def test_record_path_may_be_a_string_and_the_name_is_its_last_component(tmp_path: Path) -> None:
    folder = tmp_path / "db"
    folder.mkdir()
    write_record(folder, name="x_108")
    write_annotations(folder, [100], ["N"], name="x_108")
    record = load_record(str(folder / "x_108"))  # type: ignore[arg-type]
    assert record.name == "x_108"


def test_record_is_frozen(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100], ["N"])
    record = load_record(tmp_path / "rec")
    assert isinstance(record, Record)
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.channel = 1  # type: ignore[misc]


# Channel and units


@pytest.mark.parametrize("channel", [2, 3, 100, -1, -2])
def test_channel_that_the_record_does_not_have(tmp_path: Path, channel: int) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100], ["N"])
    with pytest.raises(InvalidInputError) as caught:
        load_record(tmp_path / "rec", channel)
    message = str(caught.value)
    assert f"has no channel {channel}" in message
    assert "it has 2 signals, channels 0 to 1" in message


@pytest.mark.parametrize("channel", [True, False, 0.0, 1.5, "0", None])
def test_channel_that_is_not_an_integer(tmp_path: Path, channel: object) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100], ["N"])
    with pytest.raises(InvalidInputError, match="channel is not an integer"):
        load_record(tmp_path / "rec", channel)  # type: ignore[arg-type]


def test_channel_given_as_a_numpy_integer(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100], ["N"])
    record = load_record(tmp_path / "rec", np.int64(1))  # type: ignore[arg-type]
    assert record.channel == 1
    assert type(record.channel) is int


@pytest.mark.parametrize("units", ["uV", "V", "MV", "mv", "mmHg", "NU"])
def test_units_other_than_mv_are_rejected_and_named(tmp_path: Path, units: str) -> None:
    write_record(tmp_path, units=("mV", units))
    write_annotations(tmp_path, [100], ["N"])
    with pytest.raises(InvalidInputError) as caught:
        load_record(tmp_path / "rec", 1)
    assert "is not in mV" in str(caught.value)
    assert repr(units) in str(caught.value)
    # The other channel of the same record is in mV and loads.
    assert load_record(tmp_path / "rec", 0).signal_name == "MLII"


def test_channel_is_checked_before_the_units(tmp_path: Path) -> None:
    write_record(tmp_path, units=("uV", "uV"))
    write_annotations(tmp_path, [100], ["N"])
    with pytest.raises(InvalidInputError, match="has no channel 2"):
        load_record(tmp_path / "rec", 2)


# Annotations


def test_every_beat_code_is_a_beat(tmp_path: Path) -> None:
    write_record(tmp_path)
    samples = [50 + 60 * index for index in range(len(BEAT_CODES))]
    write_annotations(tmp_path, samples, BEAT_CODES)
    record = load_record(tmp_path / "rec")
    assert record.beat_samples.dtype == np.int64
    assert record.beat_samples.tolist() == samples
    assert record.beat_symbols == BEAT_CODES
    assert record.other_annotations == ()


def test_every_other_code_is_kept_apart_in_file_order(tmp_path: Path) -> None:
    write_record(tmp_path)
    samples = [40 + 70 * index for index in range(len(NON_BEAT_CODES))]
    write_annotations(tmp_path, samples, NON_BEAT_CODES)
    record = load_record(tmp_path / "rec")
    assert record.beat_samples.tolist() == []
    assert record.beat_symbols == ()
    assert [(a.sample, a.symbol) for a in record.other_annotations] == list(
        zip(samples, NON_BEAT_CODES, strict=True)
    )


def test_beats_and_other_annotations_together_hold_every_annotation_once(tmp_path: Path) -> None:
    write_record(tmp_path)
    samples = [10, 100, 200, 300, 300, 400, 450, 500, 600, 700, 800, 900]
    symbols = ["+", "N", "V", "~", "[", "!", "!", "]", "A", "/", "+", "?"]
    subtypes = [0, 0, 1, 0x31, 0, 0, 0, 0, 0, 0, 0, 3]
    aux_notes = ["(N", "", "", "", "(VFL", "", "", "", "", "", "(AFIB", ""]
    write_annotations(tmp_path, samples, symbols, subtypes=subtypes, aux_notes=aux_notes)
    record = load_record(tmp_path / "rec")
    assert record.beat_samples.tolist() == [100, 200, 600, 700, 900]
    assert record.beat_symbols == ("N", "V", "A", "/", "?")
    assert record.other_annotations == (
        Annotation(sample=10, symbol="+", subtype=0, aux_note="(N"),
        Annotation(sample=300, symbol="~", subtype=0x31, aux_note=""),
        Annotation(sample=300, symbol="[", subtype=0, aux_note="(VFL"),
        Annotation(sample=400, symbol="!", subtype=0, aux_note=""),
        Annotation(sample=450, symbol="!", subtype=0, aux_note=""),
        Annotation(sample=500, symbol="]", subtype=0, aux_note=""),
        Annotation(sample=800, symbol="+", subtype=0, aux_note="(AFIB"),
    )
    assert len(record.beat_symbols) + len(record.other_annotations) == len(samples)


def test_flutter_wave_is_not_a_beat(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100, 200, 300], ["N", "!", "N"])
    record = load_record(tmp_path / "rec")
    assert record.beat_samples.tolist() == [100, 300]
    assert record.other_annotations == (Annotation(sample=200, symbol="!", subtype=0, aux_note=""),)


def test_no_beat_annotation_gives_empty_int64_arrays(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [10, 500], ["+", "~"], aux_notes=["(N", ""])
    record = load_record(tmp_path / "rec")
    assert record.beat_samples.shape == (0,)
    assert record.beat_samples.dtype == np.int64
    assert record.beat_symbols == ()
    assert len(record.other_annotations) == 2


def test_only_beat_annotations_give_no_other_annotation(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100, 400], ["N", "V"])
    assert load_record(tmp_path / "rec").other_annotations == ()


def test_trailing_nul_characters_of_the_aux_note_are_removed(tmp_path: Path) -> None:
    write_record(tmp_path)
    aux_notes = ["(N\x00", "", "two\x00\x00", "in\x00side"]
    write_annotations(tmp_path, [10, 100, 200, 300], ["+", "N", '"', '"'], aux_notes=aux_notes)
    # The file really holds the NUL characters.
    assert wfdb.rdann(str(tmp_path / "rec"), "atr").aux_note[0] == "(N\x00"
    record = load_record(tmp_path / "rec")
    assert [a.aux_note for a in record.other_annotations] == ["(N", "two", "in\x00side"]


def test_subtype_is_a_python_int(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [10, 20], ["~", "~"], subtypes=[0x30, 2])
    record = load_record(tmp_path / "rec")
    assert [a.subtype for a in record.other_annotations] == [0x30, 2]
    assert all(type(a.subtype) is int for a in record.other_annotations)
    assert all(type(a.sample) is int for a in record.other_annotations)


def test_annotations_at_the_same_sample_are_kept_in_file_order(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100, 100, 100, 200, 200], ["N", "+", "V", "[", "N"])
    record = load_record(tmp_path / "rec")
    assert record.beat_samples.tolist() == [100, 100, 200]
    assert record.beat_symbols == ("N", "V", "N")
    assert [(a.sample, a.symbol) for a in record.other_annotations] == [(100, "+"), (200, "[")]


def test_annotation_beyond_the_end_of_the_signal_is_kept(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100, N_SAMPLES - 1, N_SAMPLES, 50_000, 60_000], list("NNNN+"))
    record = load_record(tmp_path / "rec")
    assert record.beat_samples.tolist() == [100, N_SAMPLES - 1, N_SAMPLES, 50_000]
    assert record.other_annotations[0].sample == 60_000
    assert record.n_samples == N_SAMPLES


def test_other_annotator(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100], ["N"])
    write_annotations(tmp_path, [300, 700], ["V", "V"], annotator="qrs")
    assert load_record(tmp_path / "rec", 0, "qrs").beat_samples.tolist() == [300, 700]
    assert load_record(tmp_path / "rec", annotator="atr").beat_samples.tolist() == [100]


def test_decreasing_sample_indices_are_a_malformed_file(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_decreasing_annotations(tmp_path / "rec.atr")
    # wfdb reads the file as it is.
    assert wfdb.rdann(str(tmp_path / "rec"), "atr").sample.tolist() == [100, 200, 50, 250]
    with pytest.raises(MalformedFileError) as caught:
        load_record(tmp_path / "rec")
    assert caught.value.path == f"{tmp_path / 'rec'}.atr"
    assert caught.value.line is None
    assert caught.value.reason == (
        "annotation sample indices decrease: annotation 3 is at sample 50, after sample 200"
    )
    assert isinstance(caught.value, ValueError)


def test_decreasing_sample_indices_of_another_annotator_name_its_file(tmp_path: Path) -> None:
    write_record(tmp_path)
    write_annotations(tmp_path, [100], ["N"])
    write_decreasing_annotations(tmp_path / "rec.qrs")
    assert load_record(tmp_path / "rec").beat_samples.tolist() == [100]
    with pytest.raises(MalformedFileError) as caught:
        load_record(tmp_path / "rec", 0, "qrs")
    assert caught.value.path.endswith("rec.qrs")


# Errors of wfdb and of the standard library propagate unchanged


def test_absent_record_raises_the_error_of_the_file_system(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as caught:
        load_record(tmp_path / "absent")
    assert not isinstance(caught.value, SinusError)


def test_absent_annotation_file_raises_the_error_of_the_file_system(tmp_path: Path) -> None:
    write_record(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_record(tmp_path / "rec")
