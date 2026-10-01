"""Requirement tests of SRS-014: detection performance versus signal-to-noise ratio (RC-004).

The report is generated from the fixture databases of `conftest.py`, without network. The
fixture Noise Stress Test database has the 12 ECG records of the real one, with its names
(118e24 ... 118e_6, 119e24 ... 119e_6), their SNR levels, and the annotation structure of
the noise stress records: each carries the reference beats of the record it is made from
(fixture record 118 or 119 of the MIT-BIH fixture). It also holds the three noise records
bw, em and ma (signals only, no annotation file), listed in its RECORDS file as in the real
database. The detector is a double that returns the spike samples of channel 0, so the
counts of every record are known:

| Record | SNR (dB) | TP | FN | FP | | Record | SNR (dB) | TP | FN | FP |
|---|---|---|---|---|---|---|---|---|---|---|
| 118e24 | 24 | 118 | 2 | 2 | | 119e24 | 24 | 134 | 0 | 4 |
| 118e18 | 18 | 117 | 3 | 2 | | 119e18 | 18 | 133 | 1 | 5 |
| 118e12 | 12 | 115 | 5 | 4 | | 119e12 | 12 | 130 | 4 | 6 |
| 118e06 | 6 | 110 | 10 | 12 | | 119e06 | 6 | 126 | 8 | 15 |
| 118e00 | 0 | 100 | 20 | 30 | | 119e00 | 0 | 109 | 25 | 35 |
| 118e_6 | -6 | 80 | 40 | 60 | | 119e_6 | -6 | 0 | 134 | 0 |

The MIT-BIH fixture records 118 (TP 118, FN 2, FP 1) and 119 (TP 134, FN 0, FP 4) are the
records without added noise.

Pass criteria (SRS-014): the command of SRS-009 runs detection on the 12 records with the
channel and mains setting of SRS-007, and the report has a noise stress section with, for
each record, its SNR and statistics; for each SNR, the gross Se and +P from the summed
counts of its two records; the gross Se and +P of records 118 and 119 without added noise;
the database name and version and the outcome of its SRS-013 verification; ordered by record
and by decreasing SNR. No report is written when the SRS-013 verification fails.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sinus_dsp.data.physionet import Database
from sinus_dsp.errors import DataVerificationError
from sinus_dsp.evaluation.noise_stress import (
    CLEAN_RECORDS,
    NOISE_STRESS_RECORDS,
    snr_db,
)
from sinus_dsp.evaluation.run import EvaluationSettings, run_validation, write_validation_report

pytestmark = pytest.mark.usefixtures("forbid_network")

MITDB_TITLE = "MIT-BIH Arrhythmia Database"
NSTDB_TITLE = "MIT-BIH Noise Stress Test Database"
NO_THRESHOLD_SENTENCE = "No pass threshold is set for these results (OP-031)."

# record, SNR (dB), TP, FN, FP: the fixture records, by record and by decreasing SNR.
PER_RECORD: list[tuple[str, int, int, int, int]] = [
    ("118e24", 24, 118, 2, 2),
    ("118e18", 18, 117, 3, 2),
    ("118e12", 12, 115, 5, 4),
    ("118e06", 6, 110, 10, 12),
    ("118e00", 0, 100, 20, 30),
    ("118e_6", -6, 80, 40, 60),
    ("119e24", 24, 134, 0, 4),
    ("119e18", 18, 133, 1, 5),
    ("119e12", 12, 130, 4, 6),
    ("119e06", 6, 126, 8, 15),
    ("119e00", 0, 109, 25, 35),
    ("119e_6", -6, 0, 134, 0),
]
# SNR (dB), summed TP, FN, FP of its two records, gross Se (%), gross +P (%).
PER_SNR: list[tuple[int, int, int, int, str, str]] = [
    (24, 252, 2, 6, "99.21", "97.67"),
    (18, 250, 4, 7, "98.43", "97.28"),
    (12, 245, 9, 10, "96.46", "96.08"),
    (6, 236, 18, 27, "92.91", "89.73"),
    (0, 209, 45, 65, "82.28", "76.28"),
    (-6, 80, 174, 60, "31.50", "57.14"),
]
# Records 118 and 119 of the MIT-BIH fixture, without added noise: TP, FN, FP, Se, +P.
CLEAN = (252, 2, 5, "99.21", "98.05")


def _databases(fixture: Any) -> tuple[Database, Database]:
    """The two `Database` values of a fixture, pinned to the digests of its checksum lists."""
    mitdb = Database(
        slug="mitdb",
        version="1.0.0",
        title=MITDB_TITLE,
        checksum_list_sha256=fixture.mitdb.checksum_list_sha256,
    )
    nstdb = Database(
        slug="nstdb",
        version="1.0.0",
        title=NSTDB_TITLE,
        checksum_list_sha256=fixture.nstdb.checksum_list_sha256,
    )
    return mitdb, nstdb


@dataclass(frozen=True)
class Run:
    """A report generated from a fixture: the evaluation results and the text written."""

    results: Any
    text: str
    calls: tuple[tuple[int, float, int], ...]


@pytest.fixture(scope="module")
def standard_run(
    evaluation_fixture: Any,
    make_spike_detector: Callable[[], Any],
    network_forbidden: Callable[[], Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> Run:
    """The report of the standard fixture with the default settings, and its results."""
    output = tmp_path_factory.mktemp("srs014-standard") / "qrs-ec57-report.md"
    mitdb, nstdb = _databases(evaluation_fixture)
    detector = make_spike_detector()
    with network_forbidden():
        write_validation_report(
            output,
            evaluation_fixture.data_root,
            mitdb=mitdb,
            nstdb=nstdb,
            detector=detector,
            fetch=None,
        )
        results = run_validation(
            evaluation_fixture.data_root,
            mitdb=mitdb,
            nstdb=nstdb,
            detector=make_spike_detector(),
            fetch=None,
        )
    return Run(
        results=results, text=output.read_bytes().decode("utf-8"), calls=tuple(detector.calls)
    )


def _snr(cell: str) -> int | None:
    """The SNR written in a cell ("24", "-6", "24 dB"), or None."""
    match = re.fullmatch(r"([+-]?\d+)(?:\s*dB)?", cell)
    return int(match.group(1)) if match else None


def _per_snr_table(section: Any) -> Any:
    """The table of the noise stress section whose first row is the 24 dB row."""
    tables = [t for t in section.tables() if t.rows and _snr(t.rows[0][0]) == 24]
    assert len(tables) == 1, f"{len(tables)} tables start with a 24 dB row"
    return tables[0]


def _snr_row(row: tuple[str, ...]) -> tuple[Any, ...]:
    """A row of the per-SNR table, with its SNR (first cell) read as an integer."""
    return (_snr(row[0]), *row[1:])


def _record_row(row: tuple[str, ...]) -> tuple[Any, ...]:
    """A row of the per-record table, with its SNR (second cell) read as an integer."""
    return (row[0], _snr(row[1]), *row[2:])


# --------------------------------------------------------------------------------------------
# The noise stress record set and the settings
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-014")
def test_noise_stress_records_are_the_12_ecg_records_of_the_database() -> None:
    """The records on which detection runs, and the records without added noise.

    Input: the noise stress record set and the clean records of the software.
    Expected: the 12 ECG records 118e24, 118e18, 118e12, 118e06, 118e00, 118e_6, 119e24,
    119e18, 119e12, 119e06, 119e00, 119e_6, in this order (by record, then by decreasing
    SNR), and the records 118 and 119 of the MIT-BIH Arrhythmia Database.
    """
    assert tuple(NOISE_STRESS_RECORDS) == tuple(name for name, *_ in PER_RECORD)
    assert tuple(CLEAN_RECORDS) == ("118", "119")


@pytest.mark.requirement("SRS-014")
@pytest.mark.parametrize(("record", "snr"), [(name, snr) for name, snr, *_ in PER_RECORD])
def test_snr_of_each_noise_stress_record(record: str, snr: int) -> None:
    """The SNR of each noise stress record, from its name.

    Input: the name of a noise stress record.
    Expected: 24, 18, 12, 6, 0 and -6 dB for the suffixes e24, e18, e12, e06, e00 and e_6.
    """
    assert snr_db(record) == snr


@pytest.mark.requirement("SRS-014")
def test_noise_stress_detection_uses_the_channel_and_mains_setting_of_srs_007(
    standard_run: Run, evaluation_fixture: Any
) -> None:
    """Detection on the noise stress records with the settings of SRS-007.

    Input: the report of the standard fixture with the default settings.
    Expected: the default settings are channel 0 (first stored signal) and 60 Hz; every call
    of the detector received the 60 Hz setting at 360 Hz; it ran on the 14 MIT-BIH records
    and the 12 noise stress records (7-min signals) and never on the noise records bw, em and
    ma (1-min signals). The channel used is channel 0: the counts in the report are those of
    the spikes of channel 0 (channel 1 is flat), checked by the per-record test.
    """
    records = len(evaluation_fixture.mitdb.records) + len(PER_RECORD)

    assert EvaluationSettings() == EvaluationSettings(channel=0, mains_hz=60)
    assert {(fs, mains) for _, fs, mains in standard_run.calls} == {(360.0, 60)}
    assert sum(1 for n, _, _ in standard_run.calls if n == 151200) >= records
    assert all(n != 21600 for n, _, _ in standard_run.calls)


# --------------------------------------------------------------------------------------------
# The noise stress section of the report
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-014")
def test_noise_stress_section_states_the_database_and_its_verification(
    standard_run: Run, evaluation_fixture: Any, parse_report: Callable[[str], Any]
) -> None:
    """The database name and version, and the outcome of its SRS-013 verification.

    Input: the report of the standard fixture, whose noise stress checksum list names 44
    files.
    Expected, in the section "Noise stress test": "MIT-BIH Noise Stress Test Database",
    "1.0.0" and "verified: 44 files match the published SHA-256 checksum list
    (SHA256SUMS.txt, SHA-256 <digest of the fixture list>)".
    """
    section = parse_report(standard_run.text).section("noise stress")
    nstdb = evaluation_fixture.nstdb
    verified = (
        f"verified: {nstdb.n_listed_files} files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {nstdb.checksum_list_sha256})"
    )

    assert NSTDB_TITLE in section.text
    assert "1.0.0" in section.text
    assert verified in section.text


@pytest.mark.requirement("SRS-014")
def test_noise_stress_section_gives_each_record_its_snr_and_statistics(
    standard_run: Run,
    evaluation_fixture: Any,
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
) -> None:
    """For each record, its SNR and the statistics of SRS-011, by record and decreasing SNR.

    Input: the report of the standard fixture (counts in the module docstring).
    Expected, in the section "Noise stress test": a table with one row per noise stress
    record, in the order 118e24 ... 118e_6, 119e24 ... 119e_6; each row gives record, SNR
    (dB), TP, FN, FP, Se (%), +P (%), e.g. 118e06: 6, 110, 10, 12, 91.67, 90.16; 119e_6: -6,
    0, 134, 0, 0.00, not defined.
    """
    table = parse_report(standard_run.text).section("noise stress").table_with_row("118e24")

    assert table.first_cells() == [name for name, *_ in PER_RECORD]
    for name, snr, tp, fn, fp in PER_RECORD:
        fixture_record = evaluation_fixture.nstdb.records[name]
        assert (fixture_record.tp, fixture_record.fn, fixture_record.fp) == (tp, fn, fp)
        expected = (snr, str(tp), str(fn), str(fp))
        expected += (percent_text(tp, tp + fn), percent_text(tp, tp + fp))
        assert _record_row(table.row(name))[1:] == expected, name
    assert _record_row(table.row("118e06"))[1:] == (6, "110", "10", "12", "91.67", "90.16")
    assert _record_row(table.row("119e_6"))[1:] == (-6, "0", "134", "0", "0.00", "not defined")


@pytest.mark.requirement("SRS-014")
def test_noise_stress_section_gives_the_gross_statistics_of_each_snr(
    standard_run: Run,
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
) -> None:
    """For each SNR, the gross Se and +P from the summed counts of its two records.

    Input: the report of the standard fixture.
    Expected, in the section "Noise stress test": a table whose first six rows are the SNR
    levels in decreasing order, 24, 18, 12, 6, 0 and -6 dB, each with the summed TP, FN, FP
    of the two records at that SNR and the gross Se and +P: 24 dB: 252, 2, 6, 99.21, 97.67;
    18: 250, 4, 7, 98.43, 97.28; 12: 245, 9, 10, 96.46, 96.08; 6: 236, 18, 27, 92.91, 89.73;
    0: 209, 45, 65, 82.28, 76.28; -6: 80, 174, 60, 31.50, 57.14.
    """
    table = _per_snr_table(parse_report(standard_run.text).section("noise stress"))

    for snr, tp, fn, fp, se, ppv in PER_SNR:
        records = [r for r in PER_RECORD if r[1] == snr]
        assert (sum(r[2] for r in records), sum(r[3] for r in records)) == (tp, fn)
        assert sum(r[4] for r in records) == fp
        assert (percent_text(tp, tp + fn), percent_text(tp, tp + fp)) == (se, ppv)
    rows = [_snr_row(row) for row in table.rows[:6]]
    assert rows == [
        (snr, str(tp), str(fn), str(fp), se, ppv) for snr, tp, fn, fp, se, ppv in PER_SNR
    ]


@pytest.mark.requirement("SRS-014")
@pytest.mark.parametrize(
    ("snr", "gross", "means"),
    [
        pytest.param(6, ("92.91", "89.73"), ("92.85", "89.76"), id="6-dB"),
        pytest.param(-6, ("31.50", "57.14"), ("33.33", "57.14"), id="minus-6-dB"),
    ],
)
def test_gross_value_per_snr_is_not_the_mean_of_the_two_records(
    snr: int,
    gross: tuple[str, str],
    means: tuple[str, str],
    standard_run: Run,
    parse_report: Callable[[str], Any],
    mean_percent_text: Callable[[list[tuple[int, int]]], str],
) -> None:
    """The per-SNR values come from the summed counts, not from the per-record values.

    Input: the report of the standard fixture. At 6 dB, 118e06 has Se 91.67 and +P 90.16,
    119e06 Se 94.03 and +P 89.36: the means would be 92.85 and 89.76, the gross values are
    92.91 and 89.73. At -6 dB, the Se of 118e_6 and 119e_6 are 66.67 and 0.00 (mean 33.33,
    gross 31.50); the +P of 119e_6 is not defined, and the gross +P is 57.14.
    Expected: the row of that SNR gives the gross values, not the means.
    """
    records = [r for r in PER_RECORD if r[1] == snr]
    se_pairs = [(tp, tp + fn) for _, _, tp, fn, _ in records]
    ppv_pairs = [(tp, tp + fp) for _, _, tp, _, fp in records]
    assert (mean_percent_text(se_pairs), mean_percent_text(ppv_pairs)) == means
    table = _per_snr_table(parse_report(standard_run.text).section("noise stress"))

    row = next(_snr_row(r) for r in table.rows if _snr(r[0]) == snr)

    assert row[-2:] == gross
    assert row[-2:] != means


@pytest.mark.requirement("SRS-014")
def test_noise_stress_section_gives_records_118_and_119_without_added_noise(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """The gross Se and +P of records 118 and 119 without added noise, for comparison.

    Input: the report of the standard fixture: MIT-BIH fixture records 118 (TP 118, FN 2,
    FP 1) and 119 (TP 134, FN 0, FP 4); the 24 dB records differ (+P 97.67), and so do the
    14 MIT-BIH records together (98.50).
    Expected: after the six SNR rows, a last row naming records 118 and 119, with gross Se
    99.21 and gross +P 98.05 (252 of 254, 252 of 257).
    """
    table = _per_snr_table(parse_report(standard_run.text).section("noise stress"))
    row = table.rows[-1]

    assert len(table.rows) == 7
    assert "118" in row[0] and "119" in row[0], row
    assert row[-2:] == CLEAN[-2:]


@pytest.mark.requirement("SRS-014")
def test_noise_stress_section_sets_no_pass_threshold(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """No pass threshold for the noise stress results (OP-031).

    Input: the report of the standard fixture.
    Expected: the section "Noise stress test" says "No pass threshold is set for these
    results (OP-031)." and gives no pass or fail.
    """
    section = parse_report(standard_run.text).section("noise stress")

    assert NO_THRESHOLD_SENTENCE in section.text
    assert not re.search(r"\b(pass|fail)\b", section.text.replace(NO_THRESHOLD_SENTENCE, ""))


@pytest.mark.requirement("SRS-014")
def test_noise_records_of_the_database_are_not_evaluated(
    standard_run: Run, parse_report: Callable[[str], Any]
) -> None:
    """Only the 12 ECG records are evaluated, not the noise records.

    Input: the report of the standard fixture, whose noise stress database also holds the
    noise records bw, em and ma (no annotation file), listed in its RECORDS file.
    Expected: none of them has a row in any table of the section "Noise stress test", and the
    report was written (they were not loaded as ECG records).
    """
    section = parse_report(standard_run.text).section("noise stress")

    for table in section.tables():
        for name in ("bw", "em", "ma"):
            assert name not in table.first_cells()


@pytest.mark.requirement("SRS-014")
def test_evaluation_results_carry_the_noise_stress_statistics(
    standard_run: Run, evaluation_fixture: Any
) -> None:
    """The noise stress results that the section is rendered from.

    Input: the evaluation results of the standard fixture.
    Expected: the 12 record results in the order of the record set, each with the counts of
    the fixture; one statistics entry per SNR in decreasing order with the summed counts of
    its two records and the gross values; the values of 118 and 119 without added noise;
    the whole noise stress database verified (every listed file, no record selection).
    """
    noise = standard_run.results.noise_stress

    assert [r.record for r in noise.records] == [name for name, *_ in PER_RECORD]
    for result, (_, _, tp, fn, fp) in zip(noise.records, PER_RECORD, strict=True):
        assert (result.counts.tp, result.counts.fn, result.counts.fp) == (tp, fn, fp)
    assert [s.snr_db for s in noise.by_snr] == [24, 18, 12, 6, 0, -6]
    for entry, (_, tp, fn, fp, _, _) in zip(noise.by_snr, PER_SNR, strict=True):
        stats = entry.statistics
        assert (stats.n_records, stats.tp, stats.fn, stats.fp) == (2, tp, fn, fp)
        assert stats.gross_se_percent == pytest.approx(100 * tp / (tp + fn), abs=1e-9)
        assert stats.gross_ppv_percent == pytest.approx(100 * tp / (tp + fp), abs=1e-9)
    clean = noise.clean
    assert (clean.n_records, clean.tp, clean.fn, clean.fp) == (2, *CLEAN[:3])
    assert noise.nstdb.records is None
    assert len(noise.nstdb.files) == evaluation_fixture.nstdb.n_listed_files


# --------------------------------------------------------------------------------------------
# No report when the verification of the noise stress database fails
# --------------------------------------------------------------------------------------------


def _flip_one_bit(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))


@pytest.mark.requirement("SRS-014")
@pytest.mark.parametrize(
    ("damage", "missing", "mismatched"),
    [
        pytest.param(
            "file-altered-and-file-missing",
            ("119e_6.atr",),
            ("118e06.dat",),
            id="one-file-altered-one-missing",
        ),
        pytest.param("checksum-list-missing", ("SHA256SUMS.txt",), (), id="checksum-list-missing"),
        pytest.param("checksum-list-altered", (), ("SHA256SUMS.txt",), id="checksum-list-altered"),
        pytest.param("database-absent", ("SHA256SUMS.txt",), (), id="database-absent"),
    ],
)
def test_no_report_is_written_when_the_noise_stress_database_is_not_verified(
    damage: str,
    missing: tuple[str, ...],
    mismatched: tuple[str, ...],
    tmp_path: Path,
    evaluation_fixture: Any,
    copy_evaluation_fixture: Callable[[Any, Path], Any],
    make_spike_detector: Callable[[], Any],
) -> None:
    """A fixture noise stress database that fails its SRS-013 verification.

    Input: a copy of the standard fixture with, in the noise stress database, 118e06.dat
    altered by one bit and 119e_6.atr deleted; or its checksum list deleted; or its checksum
    list altered; or the whole database folder absent. The report is requested at a path
    that holds a previous report, and at a path where no file exists.
    Expected: each request raises `DataVerificationError` for "nstdb 1.0.0", naming the
    missing and the altered files; the previous report is unchanged, no report is written at
    the other path, nothing else is written in the output folder; the detector is never
    called (both databases are verified before any evaluation).
    """
    fixture = copy_evaluation_fixture(evaluation_fixture, tmp_path / "data")
    folder = fixture.nstdb.folder.folder
    if damage == "file-altered-and-file-missing":
        _flip_one_bit(folder / "118e06.dat")
        (folder / "119e_6.atr").unlink()
    elif damage == "checksum-list-missing":
        (folder / "SHA256SUMS.txt").unlink()
    elif damage == "checksum-list-altered":
        checksum_list = folder / "SHA256SUMS.txt"
        checksum_list.write_bytes(checksum_list.read_bytes() + b"0" * 64 + b" extra.dat\n")
    else:
        shutil.rmtree(folder)
    mitdb, nstdb = _databases(fixture)
    output = tmp_path / "out"
    output.mkdir()
    (output / "previous.md").write_bytes(b"previous report\n")
    detector = make_spike_detector()

    for name in ("previous.md", "new.md"):
        with pytest.raises(DataVerificationError) as excinfo:
            write_validation_report(
                output / name,
                fixture.data_root,
                mitdb=mitdb,
                nstdb=nstdb,
                detector=detector,
                fetch=None,
            )
        assert excinfo.value.database == "nstdb 1.0.0"
        assert (excinfo.value.missing, excinfo.value.mismatched) == (missing, mismatched)

    assert sorted(p.name for p in output.iterdir()) == ["previous.md"]
    assert (output / "previous.md").read_bytes() == b"previous report\n"
    assert detector.calls == []
