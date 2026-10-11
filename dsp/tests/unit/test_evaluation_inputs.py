"""Unit tests: records without annotations and the noisy stretches (architecture §13.7.1)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import wfdb

from sinus_dsp.data.records import load_record, load_signal
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.noise_stress import NOISE_RECORDS, noisy_stretches


def test_record_without_annotation_file(
    tmp_path: Path, write_fixture_record: Callable[..., None]
) -> None:
    write_fixture_record(tmp_path, "r", n_samples=50, beats=[5, 9], detections=[3])
    (tmp_path / "r.atr").unlink()
    record = load_record(tmp_path / "r", 0, None)
    assert record.beat_samples.dtype == np.int64
    assert record.beat_samples.size == 0
    assert record.beat_symbols == ()
    assert record.other_annotations == ()
    assert record.name == "r"
    assert record.signal_name == "MLII"
    assert record.n_samples == 50
    assert record.signal_mv[3] == pytest.approx(1.0, abs=0.01)


def test_none_ignores_an_existing_annotation_file(
    tmp_path: Path, write_fixture_record: Callable[..., None]
) -> None:
    write_fixture_record(tmp_path, "r", n_samples=50, beats=[5, 9])
    assert load_record(tmp_path / "r", 0, "atr").beat_samples.size == 2
    assert load_record(tmp_path / "r", 0, None).beat_samples.size == 0


def test_load_signal_is_load_record_without_annotator(
    tmp_path: Path, write_fixture_record: Callable[..., None]
) -> None:
    write_fixture_record(tmp_path, "r", n_samples=40, beats=[5], detections=[7])
    (tmp_path / "r.atr").unlink()
    signal = load_signal(tmp_path / "r")
    other = load_record(tmp_path / "r", 0, None)
    assert np.array_equal(signal.signal_mv, other.signal_mv)
    assert signal.beat_samples.size == 0
    assert load_signal(tmp_path / "r", 1).signal_name == "V1"


@pytest.mark.parametrize("channel", [-1, 2])
def test_channel_is_still_checked_without_annotations(
    tmp_path: Path, write_fixture_record: Callable[..., None], channel: int
) -> None:
    write_fixture_record(tmp_path, "r", n_samples=20)
    with pytest.raises(InvalidInputError, match="channel"):
        load_signal(tmp_path / "r", channel)


def test_units_are_still_checked_without_annotations(
    tmp_path: Path, write_fixture_record: Callable[..., None]
) -> None:
    write_fixture_record(tmp_path, "r", n_samples=20, units="uV")
    with pytest.raises(InvalidInputError, match="mV"):
        load_signal(tmp_path / "r")


def test_header_with_gain_zero_loads_in_mv(tmp_path: Path) -> None:
    """The noise records state an ADC gain of 0 and no units: 200 adu/mV and mV are used."""
    adu = np.arange(-5, 5, dtype=np.float64) * 20 / 200  # mV, whole adu at gain 200
    wfdb.wrsamp(
        "n",
        fs=360,
        units=["mV"],
        sig_name=["noise1"],
        p_signal=adu.reshape(-1, 1),
        fmt=["16"],
        adc_gain=[200.0],
        baseline=[0],
        write_dir=str(tmp_path),
    )
    header = (tmp_path / "n.hea").read_text().splitlines()
    first_adu = int(round(adu[0] * 200))
    checksum = int(header[1].split()[6])
    header[1] = f"n.dat 16 0 16 0 {first_adu} {checksum} 0 noise1"
    (tmp_path / "n.hea").write_text("\n".join(header) + "\n")
    record = load_signal(tmp_path / "n")
    assert record.signal_name == "noise1"
    assert record.fs_hz == 360.0
    assert np.allclose(record.signal_mv, adu)


STRETCHES_650000: Any = (
    (108000, 151199),
    (194400, 237599),
    (280800, 323999),
    (367200, 410399),
    (453600, 496799),
    (540000, 583199),
    (626400, 649999),
)


def test_stretches_of_the_database_records() -> None:
    assert noisy_stretches(650000, 360.0) == STRETCHES_650000


def test_noise_record_names() -> None:
    assert NOISE_RECORDS == ("bw", "em", "ma")


def test_stretch_that_ends_at_the_record_end_is_cut() -> None:
    assert noisy_stretches(120000, 360.0) == ((108000, 119999),)


def test_start_at_the_last_sample_gives_a_stretch_of_one_sample() -> None:
    assert noisy_stretches(108001, 360.0) == ((108000, 108000),)


def test_start_at_the_record_end_gives_no_stretch() -> None:
    assert noisy_stretches(108000, 360.0) == ()
    assert noisy_stretches(0, 360.0) == ()


def test_stretch_ending_exactly_at_the_end() -> None:
    assert noisy_stretches(151200, 360.0) == ((108000, 151199),)


def test_other_sampling_frequency() -> None:
    assert noisy_stretches(100000, 250.0) == ((75000, 99999),)
    assert noisy_stretches(200000, 250.0)[1] == (135000, 164999)


def test_rounding_of_a_fractional_sampling_frequency() -> None:
    first = noisy_stretches(10**6, 360.5)[0]
    assert first == (108150, 151409)


@pytest.mark.parametrize("n_samples", [-1, 1.5, True, "10"])
def test_invalid_length_is_rejected(n_samples: Any) -> None:
    with pytest.raises(InvalidInputError):
        noisy_stretches(n_samples, 360.0)


@pytest.mark.parametrize("fs", [0.0, float("nan"), 50.0, True])
def test_invalid_sampling_frequency_is_rejected(fs: Any) -> None:
    with pytest.raises(InvalidInputError):
        noisy_stretches(1000, fs)
