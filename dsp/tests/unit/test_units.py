"""Unit tests of the time-to-samples conversions."""

import pytest

from sinus_dsp._units import (
    ceil_samples_ms,
    floor_samples_ms,
    round_samples,
    round_samples_ms,
)


@pytest.mark.parametrize(
    ("t_ms", "at_360", "at_250"),
    [
        (36, 13, 9),  # band-pass delay: 12.96 and 9.0
        (150, 54, 38),  # integration window: 54.0 and 37.5 (half rounds up)
        (95, 34, 24),  # peak timeout: 34.2 and 23.75
        (360, 130, 90),  # T-wave window: 129.6 and 90.0
    ],
)
def test_round_samples_ms_detector_values(t_ms: int, at_360: int, at_250: int) -> None:
    assert round_samples_ms(t_ms, 360.0) == at_360
    assert round_samples_ms(t_ms, 250.0) == at_250


def test_ceil_samples_ms_refractory() -> None:
    assert ceil_samples_ms(200, 360.0) == 72
    assert ceil_samples_ms(200, 250.0) == 50


@pytest.mark.parametrize(("t_s", "at_360", "at_250"), [(2, 720, 500), (8, 2880, 2000)])
def test_round_samples_whole_seconds(t_s: int, at_360: int, at_250: int) -> None:
    assert round_samples(t_s, 360.0) == at_360
    assert round_samples(t_s, 250.0) == at_250


def test_round_samples_is_half_up() -> None:
    assert round_samples(0.5, 1.0) == 1
    assert round_samples(1.5, 1.0) == 2
    assert round_samples(2.5, 1.0) == 3  # not the round-half-even of round()
    assert round_samples(60, 360.0) == 21600


def test_round_samples_ms_is_half_up() -> None:
    assert round_samples_ms(150, 250.0) == 38  # 37.5
    assert round_samples_ms(150, 130.0) == 20  # 19.5
    assert round_samples_ms(10, 250.0) == 3  # 2.5
    assert round_samples_ms(149, 250.0) == 37  # 37.25


def test_floor_keeps_an_at_most_bound() -> None:
    # 150 ms: 54 samples at 360 Hz, 37.5 -> 37 at 250 Hz (38 samples would last 152 ms).
    assert floor_samples_ms(150, 360.0) == 54
    assert floor_samples_ms(150, 250.0) == 37
    assert floor_samples_ms(150, 125.0) == 18  # 18.75


def test_ceil_keeps_an_at_least_bound() -> None:
    assert ceil_samples_ms(200, 125.0) == 25
    assert ceil_samples_ms(200, 128.0) == 26  # 25.6
    assert ceil_samples_ms(300_000, 360.0) == 108000  # 5 minutes


def test_integer_sampling_frequencies_give_exact_products() -> None:
    # t_ms * fs_hz is an exact integer, so a whole number of samples is never rounded away.
    for fs in range(125, 1001):
        assert floor_samples_ms(1000, float(fs)) == fs
        assert ceil_samples_ms(1000, float(fs)) == fs
        assert round_samples_ms(1000, float(fs)) == fs
        assert floor_samples_ms(200, float(fs)) == fs // 5
        assert ceil_samples_ms(200, float(fs)) == -(-fs // 5)


def test_results_are_python_ints() -> None:
    for value in (
        round_samples(2, 360.0),
        round_samples_ms(36, 360.0),
        floor_samples_ms(150, 250.0),
        ceil_samples_ms(200, 250.0),
    ):
        assert type(value) is int
