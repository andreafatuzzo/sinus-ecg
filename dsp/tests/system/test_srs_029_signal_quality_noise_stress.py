"""System verification of SRS-029: signal quality index on the noise stress records.

The windows, the noisy stretches and the selections are rebuilt here from the requirement text
and the database files. Each of the 12 noise stress records, records 118 and 119 of the
MIT-BIH Arrhythmia Database and the three noise records is read with wfdb (first stored
signal), given to ``quality_windows`` of the reference with the mains setting of SRS-007 (60
Hz), and the windows are selected by sample indices: a noise stress window is one that lies
entirely in a stretch with added noise (stretch ``i`` from ``300 + 240 i`` s to ``420 + 240 i``
s, the last one to the end of the record), a window from 5:00 is one that starts at or after
5:00. Each criterion is asserted as written, each SNR and each noise record on its own.
The figures are also compared with section "Signal quality index" of the generated report.

Needs the verified local MIT-BIH Arrhythmia and Noise Stress Test Databases; skipped in CI.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import wfdb

from sinus_dsp.quality import USABLE_THRESHOLD, QualityWindows, quality_windows

ROOT = Path(__file__).resolve().parents[3]
MITDB_DIR = ROOT / "data" / "mitdb"
NSTDB_DIR = ROOT / "data" / "nstdb"
REPORT = ROOT / "docs" / "validation" / "qrs-ec57-report.md"

MAINS_HZ = 60
FS = 360
BLOCK = FS  # 1 s
WINDOW = 10 * FS
FROM_5_00 = 300 * FS
SNRS = (24, 18, 12, 6, 0, -6)
NOISE_RECORDS = ("bw", "em", "ma")


def _name(base: str, snr: int) -> str:
    return f"{base}e{'_' + str(-snr) if snr < 0 else format(snr, '02d')}"


@dataclass(frozen=True)
class Summary:
    n: int
    usable: int
    median: float

    @property
    def percent(self) -> float:
        return 100 * self.usable / self.n


def _windows(directory: Path, name: str) -> tuple[QualityWindows, int]:
    path = str(directory / name)
    record = wfdb.rdrecord(path, channels=[0], physical=True)
    assert record.fs == FS
    signal = np.ascontiguousarray(record.p_signal[:, 0], dtype=np.float64)
    windows = quality_windows(signal, float(FS), MAINS_HZ)
    # SRS-027: windows of 10 s, one every 1 s from the first sample, all inside the stream.
    n_windows = (len(signal) - WINDOW) // BLOCK + 1
    assert len(windows.first) == n_windows
    assert np.array_equal(windows.first, np.arange(n_windows) * BLOCK)
    assert np.array_equal(windows.last, windows.first + WINDOW - 1)
    assert np.array_equal(windows.usable, windows.index >= USABLE_THRESHOLD)
    return windows, len(signal)


def _summary(parts: list[tuple[QualityWindows, np.ndarray]]) -> Summary:
    indices = np.concatenate([w.index[sel] for w, sel in parts])
    usable = np.concatenate([w.usable[sel] for w, sel in parts])
    assert len(indices) > 0
    return Summary(len(indices), int(usable.sum()), float(statistics.median(indices.tolist())))


def _stretches(n_samples: int) -> list[tuple[int, int]]:
    out = []
    i = 0
    while (300 + 240 * i) * FS < n_samples:
        out.append(((300 + 240 * i) * FS, min((420 + 240 * i) * FS - 1, n_samples - 1)))
        i += 1
    return out


def _in_noise(w: QualityWindows, n_samples: int) -> np.ndarray:
    sel = np.zeros(len(w.first), dtype=bool)
    for a, b in _stretches(n_samples):
        sel |= (w.first >= a) & (w.last <= b)
    return sel


@dataclass(frozen=True)
class Results:
    by_snr: dict[int, Summary]
    per_record_snr: dict[str, Summary]
    clean: Summary
    noise: dict[str, Summary]
    n_stretches: int


@pytest.fixture(scope="module")
def results() -> Results:
    by_snr: dict[int, Summary] = {}
    per_record: dict[str, Summary] = {}
    n_stretches = 0
    for snr in SNRS:
        parts = []
        for base in ("118", "119"):
            name = _name(base, snr)
            w, n = _windows(NSTDB_DIR, name)
            n_stretches = len(_stretches(n))
            sel = _in_noise(w, n)
            parts.append((w, sel))
            per_record[name] = _summary([(w, sel)])
        by_snr[snr] = _summary(parts)
    clean_parts = []
    for base in ("118", "119"):
        w, _ = _windows(MITDB_DIR, base)
        clean_parts.append((w, w.first >= FROM_5_00))
    noise: dict[str, Summary] = {}
    for name in NOISE_RECORDS:
        w, _ = _windows(NSTDB_DIR, name)
        noise[name] = _summary([(w, np.ones(len(w.first), dtype=bool))])
    return Results(by_snr, per_record, _summary(clean_parts), noise, n_stretches)


@pytest.mark.requirement("SRS-029")
@pytest.mark.needs_data
@pytest.mark.needs_nstdb
def test_window_counts_follow_from_the_requirement(results: Results) -> None:
    assert results.n_stretches == 7
    for name, s in results.per_record_snr.items():
        assert s.n == 722, name  # 6 x 111 + 56
    assert all(s.n == 1444 for s in results.by_snr.values())
    assert results.clean.n == 2992  # 2 x 1496 windows from 5:00
    assert [results.noise[n].n for n in NOISE_RECORDS] == [1796] * 3


@pytest.mark.requirement("SRS-029")
@pytest.mark.needs_data
@pytest.mark.needs_nstdb
def test_median_does_not_increase_from_one_snr_to_the_next_lower(results: Results) -> None:
    medians = [results.by_snr[s].median for s in SNRS]
    pairs = [(SNRS[i], SNRS[i + 1], medians[i], medians[i + 1]) for i in range(5)]
    bad = [p for p in pairs if p[3] > p[2]]
    assert not bad, (
        f"median increases at (higher dB, lower dB, median, median): {bad}; all {medians}"
    )


@pytest.mark.requirement("SRS-029")
@pytest.mark.needs_data
@pytest.mark.needs_nstdb
def test_median_lower_at_minus_6_db_than_at_24_db(results: Results) -> None:
    assert results.by_snr[-6].median < results.by_snr[24].median


@pytest.mark.requirement("SRS-029")
@pytest.mark.needs_data
@pytest.mark.needs_nstdb
def test_clean_records_118_and_119_usable_from_5_00(results: Results) -> None:
    c = results.clean
    assert 100 * c.usable >= 95 * c.n, f"{c.percent:.2f} % of {c.n}"


@pytest.mark.requirement("SRS-029")
@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.parametrize("snr", [24, 18])
def test_high_snr_at_least_90_percent_usable(results: Results, snr: int) -> None:
    s = results.by_snr[snr]
    assert 100 * s.usable >= 90 * s.n, f"{snr} dB: {s.percent:.2f} % of {s.n}"


@pytest.mark.requirement("SRS-029")
@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.parametrize("snr", [6, 0, -6])
def test_low_snr_at_most_20_percent_usable(results: Results, snr: int) -> None:
    s = results.by_snr[snr]
    assert 100 * s.usable <= 20 * s.n, f"{snr} dB: {s.percent:.2f} % of {s.n}"


@pytest.mark.requirement("SRS-029")
@pytest.mark.needs_data
@pytest.mark.needs_nstdb
@pytest.mark.parametrize("name", NOISE_RECORDS)
def test_noise_record_at_most_10_percent_usable(results: Results, name: str) -> None:
    s = results.noise[name]
    assert 100 * s.usable <= 10 * s.n, f"{name}: {s.percent:.2f} % of {s.n}"


@pytest.mark.requirement("SRS-029")
@pytest.mark.needs_data
@pytest.mark.needs_nstdb
def test_report_states_the_same_figures(results: Results) -> None:
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("\n## Signal quality index\n", 1)[1]
    section = section.split("### Noise stress records\n", 1)[1].split("\n### ", 1)[0]
    rows: dict[str, tuple[int, float, float]] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[1].isdigit():
            rows[cells[0]] = (int(cells[1]), float(cells[2]), float(cells[3]))
    expected = {f"{snr} dB": results.by_snr[snr] for snr in SNRS}
    expected["records 118 and 119, no added noise, from 5:00"] = results.clean
    expected.update({f"noise record {n}": results.noise[n] for n in NOISE_RECORDS})
    assert set(rows) == set(expected)
    for key, s in expected.items():
        n, median, percent = rows[key]
        assert n == s.n, key
        assert f"{median:.4f}" == f"{s.median:.4f}", key
        assert f"{percent:.2f}" == f"{s.percent:.2f}", key
