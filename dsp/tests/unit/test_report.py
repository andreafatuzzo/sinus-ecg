"""Unit tests of the rendering of the validation reports, on results built by hand."""

import ast
import dataclasses
import random
import re
from pathlib import Path

import pytest

from sinus_dsp.data.physionet import (
    MITDB,
    NSTDB,
    ODC_BY_1_0,
    Database,
    DatabaseLicence,
    VerificationResult,
)
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation import report
from sinus_dsp.evaluation.metrics import RecordCounts, aggregate_statistics
from sinus_dsp.evaluation.noise_stress import (
    NOISE_STRESS_RECORDS,
    NoiseStressResults,
    SnrStatistics,
    snr_db,
)
from sinus_dsp.evaluation.report import (
    render_full_report,
    render_subset_report,
    software_rows,
    stale_software_rows,
)
from sinus_dsp.evaluation.run import (
    DEFAULT_SETTINGS,
    EvaluationSettings,
    RecordEvaluation,
    ValidationResults,
)
from sinus_dsp.evaluation.signal_quality import (
    QualityResults,
    RecordQuality,
    WindowSummary,
    build_quality_results,
)
from sinus_dsp.evaluation.start_of_stream import StartOfStreamRecord, StartOfStreamResults
from sinus_dsp.version import SoftwareIdentity

# Fixture licences: one per database, neither that of the real databases, so that each row
# "Database licence" is seen to come from the database of its table.
MITDB_LICENCE = DatabaseLicence("Fixture Arrhythmia Licence 1.0", "https://licences.example/a/")
NSTDB_LICENCE = DatabaseLicence("Fixture Noise Licence 2.0", "https://licences.example/n/")
MITDB_VERIFICATION = VerificationResult(
    Database("mitdb", "1.0.0", "Fixture Arrhythmia Database", "a" * 64, MITDB_LICENCE),
    None,
    ("100.dat", "100.hea", "RECORDS"),
)
NSTDB_VERIFICATION = VerificationResult(
    Database("nstdb", "1.0.0", "Fixture Noise Database", "b" * 64, NSTDB_LICENCE),
    None,
    ("118e24.dat",),
)
MITDB_LICENCE_LINE = (
    "| Database licence | Fixture Arrhythmia Licence 1.0, https://licences.example/a/ |"
)
NSTDB_LICENCE_LINE = "| Database licence | Fixture Noise Licence 2.0, https://licences.example/n/ |"
# The row of the real databases (architecture §8.15).
REAL_LICENCE_LINE = (
    "| Database licence | Open Data Commons Attribution License v1.0, "
    "https://opendatacommons.org/licenses/by/1-0/ |"
)
SOFTWARE = SoftwareIdentity(
    version="0.1.0.dev0",
    source_sha256="0123456789abcdef" * 4,
    python="3.11",
    runtime=(("numpy", "2.4.6"), ("scipy", "1.17.1"), ("wfdb", "4.3.1")),
)
SOFTWARE_LINE = (
    "| Software | sinus-dsp 0.1.0.dev0, source SHA-256 "
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef |"
)
RUNTIME_LINE = "| Runtime | Python 3.11, numpy 2.4.6, scipy 1.17.1, wfdb 4.3.1 |"


def evaluation(
    name: str,
    tp: int,
    fn: int,
    fp: int,
    *,
    signal: str = "MLII",
    fs_hz: float = 360.0,
    vf: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
    flutter: int = 0,
) -> RecordEvaluation:
    """A record evaluation; ``vf`` is (episodes, from 5:00, samples, reference, detections)."""
    return RecordEvaluation(
        record=name,
        signal_name=signal,
        fs_hz=fs_hz,
        counts=RecordCounts(name, tp, fn, fp),
        vf_episodes=vf[0],
        vf_episodes_scored=vf[1],
        vf_samples_scored=vf[2],
        reference_excluded=vf[3],
        detections_excluded=vf[4],
        flutter_waves_outside_vf=flutter,
    )


RECORDS = (
    evaluation("100", 793, 7, 0),  # Se 99.125 exactly: two decimals give 99.12
    evaluation("102", 3, 0, 0, signal="V5", flutter=2),
    evaluation("105", 0, 0, 4),  # Se not defined
    evaluation("118", 2000, 5, 10),
    evaluation("119", 1500, 1, 2),
    evaluation("207", 1000, 30, 20, vf=(6, 1, 35245, 0, 3)),
)


def noise_stress(
    records: tuple[RecordEvaluation, ...] = RECORDS, *, snr_order: tuple[int, ...] | None = None
) -> NoiseStressResults:
    noisy = tuple(
        evaluation(name, 100 - i, i, 2 * i) for i, name in enumerate(NOISE_STRESS_RECORDS)
    )
    snrs = snr_order if snr_order is not None else (24, 18, 12, 6, 0, -6)
    by_snr = tuple(
        SnrStatistics(
            snr,
            aggregate_statistics([entry.counts for entry in noisy if snr_db(entry.record) == snr]),
        )
        for snr in snrs
    )
    clean = aggregate_statistics(
        [entry.counts for entry in records if entry.record in ("118", "119")]
    )
    return NoiseStressResults(NSTDB_VERIFICATION, noisy, by_snr, clean)


def summary(n_windows: int, n_usable: int, median: float | None) -> WindowSummary:
    return WindowSummary(n_windows=n_windows, n_usable=n_usable, median_index=median)


def quality_results() -> QualityResults:
    """Signal quality results by hand: 6 dB just fails (21 %), em fails, ma has no window."""
    return build_quality_results(
        [
            RecordQuality("118", summary(120, 100, 0.8), 1, 0),
            RecordQuality("100", summary(80, 70, 0.7), 3, 4),
        ],
        [
            (24, summary(100, 100, 0.9)),
            (18, summary(100, 95, 0.8125)),
            (12, summary(100, 50, 0.7)),
            (6, summary(100, 21, 0.5)),
            (0, summary(100, 10, 0.3)),
            (-6, summary(100, 5, 0.25)),
        ],
        summary(200, 198, 0.91234),
        [("bw", summary(50, 5, 0.2)), ("em", summary(50, 6, 0.21)), ("ma", summary(0, 0, None))],
    )


def start_of_stream_results() -> StartOfStreamResults:
    records = (
        StartOfStreamRecord("100", "MLII", 3, RecordCounts("100", 90, 10, 0)),
        StartOfStreamRecord("118", "MLII", 3, RecordCounts("118", 200, 1, 0)),
    )
    return StartOfStreamResults(
        segment_s=60,
        starts_s=(0, 60, 120),
        records=records,
        statistics=aggregate_statistics([entry.counts for entry in records]),
    )


def full_results(
    records: tuple[RecordEvaluation, ...] = RECORDS,
    settings: EvaluationSettings = DEFAULT_SETTINGS,
) -> ValidationResults:
    return ValidationResults(
        software=SOFTWARE,
        settings=settings,
        mitdb=MITDB_VERIFICATION,
        records=records,
        noise_stress=noise_stress(records),
        subset=False,
        quality=quality_results(),
        start_of_stream=start_of_stream_results(),
    )


def subset_results(records: tuple[RecordEvaluation, ...] = RECORDS) -> ValidationResults:
    return dataclasses.replace(
        full_results(records), noise_stress=None, quality=None, start_of_stream=None, subset=True
    )


# The full report of RECORDS, checked by hand: Se of 100 = 79300 / 800 = 99.125 is written
# 99.12 (correctly rounded from the float64 value, which is exact); gross 5296, 43, 36 gives
# Se 529600 / 5339 = 99.195 and +P 529600 / 5332 = 99.325; the Se average is over the 5
# defined values; the +P tie at 100.00 between 100 and 102 is ordered by record name; record
# 207 has 35245 samples from 5:00 at 360 Hz, 97.9 s.
EXPECTED_FULL_REPORT = (
    (
        "\n".join(
            [
                "# QRS detection: EC57 beat-by-beat evaluation",
                "",
                "Technical evaluation only. Sinus is not a medical device; these results are not "
                "a clinical validation.",
                "",
                "Generated by dsp/scripts/validate.py; do not edit by hand.",
                "",
                "## Software, data and settings",
                "",
                "| Item | Value |",
                "|---|---|",
                "| Software | sinus-dsp 0.1.0.dev0, source SHA-256 "
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef |",
                "| Runtime | Python 3.11, numpy 2.4.6, scipy 1.17.1, wfdb 4.3.1 |",
                "| Database | Fixture Arrhythmia Database, version 1.0.0 |",
                "| Database licence | Fixture Arrhythmia Licence 1.0, "
                "https://licences.example/a/ |",
                "| Verification | verified: 3 files match the published SHA-256 checksum list "
                "(SHA256SUMS.txt, SHA-256 {A}) |",
                "| Records | 6 |",
                "| Signal | first stored signal of each record (channel 0) |",
                "| Mains interference filter | 60 Hz |",
                "| Matching | EC57 beat by beat, pairing rules of the WFDB comparator bxb; match "
                "window 150 ms; first 5 min of each record not scored; ventricular flutter and "
                "fibrillation episodes not scored |",
                "",
                "## Performance targets",
                "",
                "| Statistic | Value (%) | Target (%) | Result |",
                "|---|---:|---|---|",
                "| Gross Se | 99.19 | ≥ 99.50 | fail |",
                "| Gross +P | 99.32 | ≥ 99.50 | fail |",
                "",
                "## Results per record",
                "",
                "| Record | Signal | TP | FN | FP | Se (%) | +P (%) |",
                "|---|---|---:|---:|---:|---:|---:|",
                "| 100 | MLII | 793 | 7 | 0 | 99.12 | 100.00 |",
                "| 102 | V5 | 3 | 0 | 0 | 100.00 | 100.00 |",
                "| 105 | MLII | 0 | 0 | 4 | not defined | 0.00 |",
                "| 118 | MLII | 2000 | 5 | 10 | 99.75 | 99.50 |",
                "| 119 | MLII | 1500 | 1 | 2 | 99.93 | 99.87 |",
                "| 207 | MLII | 1000 | 30 | 20 | 97.09 | 98.04 |",
                "| Gross |  | 5296 | 43 | 36 | 99.19 | 99.32 |",
                "| Average |  |  |  |  | 99.18 | 82.90 |",
                "",
                "The averages are the means of the defined per-record values: Se is defined for 5"
                " of 6 records, +P for 6 of 6 records.",
                "",
                "## Lowest sensitivity",
                "",
                "The records with the lowest defined Se, at most 5, lowest first; ties are "
                "ordered by record name.",
                "",
                "| Rank | Record | Se (%) |",
                "|---:|---|---:|",
                "| 1 | 207 | 97.09 |",
                "| 2 | 100 | 99.12 |",
                "| 3 | 118 | 99.75 |",
                "| 4 | 119 | 99.93 |",
                "| 5 | 102 | 100.00 |",
                "",
                "## Lowest positive predictivity",
                "",
                "The records with the lowest defined +P, at most 5, lowest first; ties are "
                "ordered by record name.",
                "",
                "| Rank | Record | +P (%) |",
                "|---:|---|---:|",
                "| 1 | 105 | 0.00 |",
                "| 2 | 207 | 98.04 |",
                "| 3 | 118 | 99.50 |",
                "| 4 | 119 | 99.87 |",
                "| 5 | 100 | 100.00 |",
                "",
                "## Segments not scored",
                "",
                "The first 5 min of each record are not scored. Ventricular flutter and "
                "fibrillation episodes are not scored either. The durations and counts below "
                "cover the part of each record from 5:00 to its end, except the episodes in the "
                "record, which are counted over the whole record.",
                "",
                "| Record | Episodes in the record | Episodes from 5:00 | Duration from 5:00 (s) "
                "| Reference beats not scored | Detections not scored |",
                "|---|---:|---:|---:|---:|---:|",
                "| 207 | 6 | 1 | 97.9 | 0 | 3 |",
                "",
                "Flutter-wave annotations outside ventricular flutter and fibrillation episodes, "
                "in all records: 2.",
                "",
                "## Noise stress test",
                "",
                "| Item | Value |",
                "|---|---|",
                "| Database | Fixture Noise Database, version 1.0.0 |",
                "| Database licence | Fixture Noise Licence 2.0, https://licences.example/n/ |",
                "| Verification | verified: 1 files match the published SHA-256 checksum list "
                "(SHA256SUMS.txt, SHA-256 {B}) |",
                "",
                "### Results per record",
                "",
                "| Record | SNR (dB) | TP | FN | FP | Se (%) | +P (%) |",
                "|---|---:|---:|---:|---:|---:|---:|",
                "| 118e24 | 24 | 100 | 0 | 0 | 100.00 | 100.00 |",
                "| 118e18 | 18 | 99 | 1 | 2 | 99.00 | 98.02 |",
                "| 118e12 | 12 | 98 | 2 | 4 | 98.00 | 96.08 |",
                "| 118e06 | 6 | 97 | 3 | 6 | 97.00 | 94.17 |",
                "| 118e00 | 0 | 96 | 4 | 8 | 96.00 | 92.31 |",
                "| 118e_6 | -6 | 95 | 5 | 10 | 95.00 | 90.48 |",
                "| 119e24 | 24 | 94 | 6 | 12 | 94.00 | 88.68 |",
                "| 119e18 | 18 | 93 | 7 | 14 | 93.00 | 86.92 |",
                "| 119e12 | 12 | 92 | 8 | 16 | 92.00 | 85.19 |",
                "| 119e06 | 6 | 91 | 9 | 18 | 91.00 | 83.49 |",
                "| 119e00 | 0 | 90 | 10 | 20 | 90.00 | 81.82 |",
                "| 119e_6 | -6 | 89 | 11 | 22 | 89.00 | 80.18 |",
                "",
                "### Results per SNR",
                "",
                "| SNR (dB) | TP | FN | FP | Gross Se (%) | Gross +P (%) |",
                "|---|---:|---:|---:|---:|---:|",
                "| 24 | 194 | 6 | 12 | 97.00 | 94.17 |",
                "| 18 | 192 | 8 | 16 | 96.00 | 92.31 |",
                "| 12 | 190 | 10 | 20 | 95.00 | 90.48 |",
                "| 6 | 188 | 12 | 24 | 94.00 | 88.68 |",
                "| 0 | 186 | 14 | 28 | 93.00 | 86.92 |",
                "| -6 | 184 | 16 | 32 | 92.00 | 85.19 |",
                "| no added noise (Fixture Arrhythmia Database, records 118 and 119) | 3500 | 6 |"
                " 12 | 99.83 | 99.66 |",
                "",
                "No pass threshold is set for these results (OP-031).",
            ]
        )
        + "\n"
    )
    .replace("{A}", "a" * 64)
    .replace("{B}", "b" * 64)
)

# Sections 8 and 9 of the full report of ``full_results``, checked by hand (architecture
# §13.7.5): 21 of 100 windows is 21.00 % (above the 20 % limit); records 100 and 118 give
# 70 + 100 = 170 usable windows of 200 (85.00 %), sorted by name whatever the order given; the
# median 0.91234 is written with four decimals; start of stream: gross Se 290 / 301 = 96.35,
# +P 290 / 290 = 100.00, average Se (90.00 + 99.50) / 2 = 94.75 (99.5025 rounds to 99.50).
EXPECTED_QUALITY_AND_START = "\n".join(
    [
        "## Signal quality index",
        "",
        "| Item | Value |",
        "|---|---|",
        "| Window length | 10 s |",
        "| Window spacing | 1 s |",
        "| Usable threshold | 0.50 |",
        "| Noisy stretches | from 5:00 to the end of each noise stress record, 2 min with added "
        "noise alternating with 2 min without, starting with noise |",
        "",
        "Noise stress records: the windows that lie entirely in a stretch with added noise. "
        "Records of the Fixture Arrhythmia Database: the windows that start at or after 5:00. "
        "Noise records: every window.",
        "",
        "### Noise stress records",
        "",
        "| Windows of | Windows | Median index | Usable (%) |",
        "|---|---:|---:|---:|",
        "| 24 dB | 100 | 0.9000 | 100.00 |",
        "| 18 dB | 100 | 0.8125 | 95.00 |",
        "| 12 dB | 100 | 0.7000 | 50.00 |",
        "| 6 dB | 100 | 0.5000 | 21.00 |",
        "| 0 dB | 100 | 0.3000 | 10.00 |",
        "| -6 dB | 100 | 0.2500 | 5.00 |",
        "| records 118 and 119, no added noise, from 5:00 | 200 | 0.9123 | 99.00 |",
        "| noise record bw | 50 | 0.2000 | 10.00 |",
        "| noise record em | 50 | 0.2100 | 12.00 |",
        "| noise record ma | 0 | not defined | not defined |",
        "",
        "### Records of the Fixture Arrhythmia Database",
        "",
        "| Record | Windows from 5:00 | Usable (%) | FN in not usable windows "
        "| FP in not usable windows |",
        "|---|---:|---:|---:|---:|",
        "| 100 | 80 | 87.50 | 3 | 4 |",
        "| 118 | 120 | 83.33 | 1 | 0 |",
        "| Total | 200 | 85.00 | 4 | 4 |",
        "",
        "FN and FP are those of the results per record. Each one that lies in at least one "
        "window marked not usable is counted once. No threshold applies to these figures.",
        "",
        "### Criteria",
        "",
        "| Criterion | Value | Required | Result |",
        "|---|---|---|---|",
        "| Median index from 24 dB to -6 dB | 0.9000, 0.8125, 0.7000, 0.5000, 0.3000, 0.2500 "
        "| non-increasing | pass |",
        "| Median index at -6 dB and at 24 dB | 0.2500, 0.9000 | lower at -6 dB | pass |",
        "| Usable windows, records 118 and 119 from 5:00 (%) | 99.00 | ≥ 95.00 | pass |",
        "| Usable windows at 24 dB (%) | 100.00 | ≥ 90.00 | pass |",
        "| Usable windows at 18 dB (%) | 95.00 | ≥ 90.00 | pass |",
        "| Usable windows at 6 dB (%) | 21.00 | ≤ 20.00 | fail |",
        "| Usable windows at 0 dB (%) | 10.00 | ≤ 20.00 | pass |",
        "| Usable windows at -6 dB (%) | 5.00 | ≤ 20.00 | pass |",
        "| Usable windows, noise record bw (%) | 10.00 | ≤ 10.00 | pass |",
        "| Usable windows, noise record em (%) | 12.00 | ≤ 10.00 | fail |",
        "| Usable windows, noise record ma (%) | not defined | ≤ 10.00 | fail |",
        "",
        "## Start of stream",
        "",
        "| Item | Value |",
        "|---|---|",
        "| Segments | 60 s each, processed on their own, starting at 0:00, 1:00, 2:00 |",
        "| Segments per record | 3 |",
        "| Start-up period | first 2 s of each segment, not scored |",
        "| Detections scored | marked reliable |",
        "| Matching | EC57 beat by beat, pairing rules of the WFDB comparator bxb; match window "
        "150 ms; start-up period not scored; ventricular flutter and fibrillation episodes "
        "not scored |",
        "",
        "### Results per record",
        "",
        "| Record | Signal | Segments | TP | FN | FP | Se (%) | +P (%) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
        "| 100 | MLII | 3 | 90 | 10 | 0 | 90.00 | 100.00 |",
        "| 118 | MLII | 3 | 200 | 1 | 0 | 99.50 | 100.00 |",
        "| Gross |  | 6 | 290 | 11 | 0 | 96.35 | 100.00 |",
        "| Average |  |  |  |  |  | 94.75 | 100.00 |",
        "",
        "The averages are the means of the defined per-record values: Se is defined for 2 of 2 "
        "records, +P for 2 of 2 records.",
        "",
        "### Targets",
        "",
        "| Statistic | Value (%) | Target (%) | Result |",
        "|---|---:|---|---|",
        "| Gross Se | 96.35 | ≥ 99.50 | fail |",
        "| Gross +P | 100.00 | ≥ 99.50 | pass |",
    ]
)

STATEMENT = (
    "Technical evaluation only. Sinus is not a medical device; "
    "these results are not a clinical validation."
)


def headings(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith("#")]


def line_after(text: str, start: str) -> list[str]:
    """The lines of the table or paragraph that follows the line starting with ``start``."""
    lines = text.split("\n")
    index = next(i for i, line in enumerate(lines) if line.startswith(start))
    block: list[str] = []
    for line in lines[index + 2 :]:
        if not line:
            break
        block.append(line)
    return block


# --- full report ----------------------------------------------------------------------------


def test_full_report_as_checked_by_hand() -> None:
    assert render_full_report(full_results()) == (
        EXPECTED_FULL_REPORT + "\n" + EXPECTED_QUALITY_AND_START + "\n"
    )


def test_sections_8_and_9_follow_the_noise_stress_test_and_are_deterministic() -> None:
    first = render_full_report(full_results())
    assert first == render_full_report(full_results())
    assert first.index("## Noise stress test") < first.index("## Signal quality index")
    assert first.index("## Signal quality index") < first.index("## Start of stream")
    assert first.endswith("| Gross +P | 100.00 | ≥ 99.50 | pass |\n")
    assert "SRS-" not in first


def test_the_other_sections_do_not_change_with_sections_8_and_9() -> None:
    text = render_full_report(full_results())
    assert text.startswith(EXPECTED_FULL_REPORT + "\n## Signal quality index")


def test_subset_report_is_the_same_with_or_without_the_new_fields_set_to_none() -> None:
    assert "Signal quality" not in render_subset_report(subset_results())
    assert "Start of stream" not in render_subset_report(subset_results())


def test_share_without_windows_and_median_without_windows_are_not_defined() -> None:
    text = render_full_report(full_results())
    assert "| noise record ma | 0 | not defined | not defined |" in text


def test_start_of_stream_starts_are_written_m_ss() -> None:
    stream = dataclasses.replace(start_of_stream_results(), starts_s=(0, 60, 600, 1740))
    results = dataclasses.replace(full_results(), start_of_stream=stream)
    text = render_full_report(results)
    assert "starting at 0:00, 1:00, 10:00, 29:00 |" in text
    assert "| Segments per record | 4 |" in text


def test_full_report_sections_in_order() -> None:
    assert headings(render_full_report(full_results())) == [
        "# QRS detection: EC57 beat-by-beat evaluation",
        "## Software, data and settings",
        "## Performance targets",
        "## Results per record",
        "## Lowest sensitivity",
        "## Lowest positive predictivity",
        "## Segments not scored",
        "## Noise stress test",
        "### Results per record",
        "### Results per SNR",
        "## Signal quality index",
        "### Noise stress records",
        "### Records of the Fixture Arrhythmia Database",
        "### Criteria",
        "## Start of stream",
        "### Results per record",
        "### Targets",
    ]


@pytest.mark.parametrize("render", [render_full_report, render_subset_report])
def test_text_format(render: object) -> None:
    results = full_results() if render is render_full_report else subset_results()
    assert callable(render)
    text = render(results)
    assert isinstance(text, str)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\r" not in text
    assert "\t" not in text
    assert all(line == line.rstrip() for line in text.split("\n"))
    assert "\n\n\n" not in text
    # The statement is its own paragraph.
    assert f"\n\n{STATEMENT}\n\n" in text
    # No requirement ID, no date or time, no path of this machine.
    assert re.search(r"SRS-\d", text) is None
    assert re.search(r"\d{4}-\d{2}-\d{2}", text) is None
    assert re.search(r"\d{1,2}:\d{2}:\d{2}", text) is None
    assert "\\" not in text
    text.encode("utf-8")


def test_report_does_not_depend_on_the_order_of_the_records() -> None:
    shuffled = list(RECORDS)
    random.Random(3).shuffle(shuffled)
    assert render_full_report(full_results(tuple(shuffled))) == (
        EXPECTED_FULL_REPORT + "\n" + EXPECTED_QUALITY_AND_START + "\n"
    )
    assert render_full_report(full_results()) == render_full_report(full_results())


def test_snr_rows_in_decreasing_order_whatever_the_order_given() -> None:
    results = dataclasses.replace(
        full_results(), noise_stress=noise_stress(snr_order=(-6, 0, 24, 6, 18, 12))
    )
    assert render_full_report(results) == (
        EXPECTED_FULL_REPORT + "\n" + EXPECTED_QUALITY_AND_START + "\n"
    )


def test_targets_pass_at_99_50_percent() -> None:
    records = (evaluation("100", 199, 1, 1), evaluation("118", 0, 0, 0), evaluation("119", 0, 0, 0))
    text = render_full_report(full_results(records))
    assert line_after(text, "## Performance targets")[2:] == [
        "| Gross Se | 99.50 | ≥ 99.50 | pass |",
        "| Gross +P | 99.50 | ≥ 99.50 | pass |",
    ]


def test_targets_just_below_99_50_percent_fail() -> None:
    # 1990 / 2000 = 99.50 %; 1989 / 1999 = 99.4997 % is written 99.50 but fails.
    records = (evaluation("118", 1989, 10, 10), evaluation("119", 0, 0, 0))
    text = render_full_report(full_results(records))
    assert line_after(text, "## Performance targets")[2:] == [
        "| Gross Se | 99.50 | ≥ 99.50 | fail |",
        "| Gross +P | 99.50 | ≥ 99.50 | fail |",
    ]


def test_targets_not_defined_fail() -> None:
    records = (evaluation("118", 0, 0, 0), evaluation("119", 0, 0, 0))
    text = render_full_report(full_results(records))
    assert line_after(text, "## Performance targets")[2:] == [
        "| Gross Se | not defined | ≥ 99.50 | fail |",
        "| Gross +P | not defined | ≥ 99.50 | fail |",
    ]
    table = line_after(text, "## Results per record")
    assert table[-2:] == [
        "| Gross |  | 0 | 0 | 0 | not defined | not defined |",
        "| Average |  |  |  |  | not defined | not defined |",
    ]
    assert "Se is defined for 0 of 2 records, +P for 0 of 2 records." in text
    assert "## Lowest sensitivity\n\nNo record has a defined Se.\n\n" in text
    assert "## Lowest positive predictivity\n\nNo record has a defined +P.\n\n" in text


def test_lowest_values_ties_by_record_name_and_at_most_five() -> None:
    records = (
        evaluation("201", 99, 1, 0),
        evaluation("118", 99, 1, 0),
        evaluation("119", 98, 2, 0),
        evaluation("200", 99, 1, 0),
        evaluation("101", 99, 1, 0),
        evaluation("102", 99, 1, 0),
        evaluation("103", 50, 0, 50),
    )
    text = render_full_report(full_results(records))
    assert line_after(text, "The records with the lowest defined Se") == [
        "| Rank | Record | Se (%) |",
        "|---:|---|---:|",
        "| 1 | 119 | 98.00 |",
        "| 2 | 101 | 99.00 |",
        "| 3 | 102 | 99.00 |",
        "| 4 | 118 | 99.00 |",
        "| 5 | 200 | 99.00 |",
    ]
    assert line_after(text, "The records with the lowest defined +P") == [
        "| Rank | Record | +P (%) |",
        "|---:|---|---:|",
        "| 1 | 103 | 50.00 |",
        "| 2 | 101 | 100.00 |",
        "| 3 | 102 | 100.00 |",
        "| 4 | 118 | 100.00 |",
        "| 5 | 119 | 100.00 |",
    ]


def test_lowest_values_are_ranked_on_the_values_not_on_the_rounded_text() -> None:
    # 99.124 % and 99.121 % are both written 99.12; the lower value comes first.
    records = (
        evaluation("100", 99124, 876, 0),
        evaluation("118", 99121, 879, 0),
        evaluation("119", 1, 0, 0),
    )
    text = render_full_report(full_results(records))
    assert line_after(text, "The records with the lowest defined Se")[2:4] == [
        "| 1 | 118 | 99.12 |",
        "| 2 | 100 | 99.12 |",
    ]


def test_fewer_than_five_defined_values() -> None:
    records = (evaluation("118", 1, 1, 0), evaluation("119", 0, 0, 3))
    text = render_full_report(full_results(records))
    assert line_after(text, "The records with the lowest defined Se")[2:] == ["| 1 | 118 | 50.00 |"]
    assert line_after(text, "The records with the lowest defined +P")[2:] == [
        "| 1 | 119 | 0.00 |",
        "| 2 | 118 | 100.00 |",
    ]


def test_percentages_are_correctly_rounded() -> None:
    # 2 / 3 = 66.666...; 1 / 8 = 12.5 exactly; 99.995 is not exact in binary.
    records = (
        evaluation("118", 2, 1, 7),  # Se 66.67, +P 22.22
        evaluation("119", 1, 7, 0),  # Se 12.50
    )
    table = line_after(render_full_report(full_results(records)), "## Results per record")
    assert table[2:4] == [
        "| 118 | MLII | 2 | 1 | 7 | 66.67 | 22.22 |",
        "| 119 | MLII | 1 | 7 | 0 | 12.50 | 100.00 |",
    ]
    assert f"{100 * 19999 / 20000:.2f}" == "100.00"


def test_settings_other_than_the_defaults_are_stated() -> None:
    text = render_full_report(full_results(settings=EvaluationSettings(channel=1, mains_hz=50)))
    assert "| Signal | channel 1 of each record |" in text
    assert "| Mains interference filter | 50 Hz |" in text


def test_software_database_and_verification_of_a_subset_selection() -> None:
    licence = DatabaseLicence("Other | Licence", "https://licences.example/x|y/")
    verification = VerificationResult(
        Database("mitdb", "2.0.0", "Other | Database", "c" * 64, licence),
        ("100", "118"),
        ("100.dat",),
    )
    software = SoftwareIdentity("9.8.7", "f" * 64, "3.12", (("numpy", "1.26.0"),))
    results = dataclasses.replace(full_results(), mitdb=verification, software=software)
    text = render_full_report(results)
    assert f"| Software | sinus-dsp 9.8.7, source SHA-256 {'f' * 64} |" in text
    assert "| Runtime | Python 3.12, numpy 1.26.0 |" in text
    assert SOFTWARE_LINE not in text
    assert "| Database | Other \\| Database, version 2.0.0 |" in text
    assert "| Database licence | Other \\| Licence, https://licences.example/x\\|y/ |" in text
    assert (
        "| Verification | verified: 1 files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {'c' * 64}); records 100, 118 |"
    ) in text


# --- licence rows ---------------------------------------------------------------------------


def section_2(text: str) -> list[str]:
    return line_after(text, "## Software, data and settings")


def noise_stress_items(text: str) -> list[str]:
    return line_after(text, "## Noise stress test")


@pytest.mark.parametrize("render", [render_full_report, render_subset_report])
def test_licence_row_follows_the_database_row_in_section_2(render: object) -> None:
    results = full_results() if render is render_full_report else subset_results()
    assert callable(render)
    table = section_2(render(results))
    assert table[4:7] == [
        "| Database | Fixture Arrhythmia Database, version 1.0.0 |",
        MITDB_LICENCE_LINE,
        "| Verification | verified: 3 files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {'a' * 64}) |",
    ]
    assert [line.split(" | ")[0] for line in table[2:]] == [
        "| Software",
        "| Runtime",
        "| Database",
        "| Database licence",
        "| Verification",
        "| Records",
        "| Signal",
        "| Mains interference filter",
        "| Matching",
    ]


def test_licence_row_of_the_noise_stress_database() -> None:
    assert noise_stress_items(render_full_report(full_results())) == [
        "| Item | Value |",
        "|---|---|",
        "| Database | Fixture Noise Database, version 1.0.0 |",
        NSTDB_LICENCE_LINE,
        "| Verification | verified: 1 files match the published SHA-256 checksum list "
        f"(SHA256SUMS.txt, SHA-256 {'b' * 64}) |",
    ]


@pytest.mark.parametrize("render", [render_full_report, render_subset_report])
def test_each_licence_row_comes_from_the_database_of_its_table(render: object) -> None:
    results = full_results() if render is render_full_report else subset_results()
    assert callable(render)
    text = render(results)
    lines = text.split("\n")
    assert lines.count(MITDB_LICENCE_LINE) == 1
    expected_nstdb = 1 if render is render_full_report else 0
    assert lines.count(NSTDB_LICENCE_LINE) == expected_nstdb
    assert sum(line.startswith("| Database licence |") for line in lines) == 1 + expected_nstdb
    # Another licence on the arrhythmia database changes only its row.
    other = DatabaseLicence("Another Licence", "https://licences.example/other/")
    mitdb = dataclasses.replace(
        results.mitdb, database=dataclasses.replace(results.mitdb.database, licence=other)
    )
    changed = render(dataclasses.replace(results, mitdb=mitdb))
    assert changed == text.replace(
        MITDB_LICENCE_LINE,
        "| Database licence | Another Licence, https://licences.example/other/ |",
    )


def test_licence_rows_of_the_real_databases() -> None:
    mitdb = VerificationResult(MITDB, None, ("100.dat",))
    nstdb = VerificationResult(NSTDB, None, ("118e24.dat",))
    results = dataclasses.replace(
        full_results(),
        mitdb=mitdb,
        noise_stress=dataclasses.replace(noise_stress(), nstdb=nstdb),
    )
    full = render_full_report(results)
    assert section_2(full)[4:6] == [
        "| Database | MIT-BIH Arrhythmia Database, version 1.0.0 |",
        REAL_LICENCE_LINE,
    ]
    assert noise_stress_items(full)[2:4] == [
        "| Database | MIT-BIH Noise Stress Test Database, version 1.0.0 |",
        REAL_LICENCE_LINE,
    ]
    subset = render_subset_report(
        dataclasses.replace(
            results, noise_stress=None, quality=None, start_of_stream=None, subset=True
        )
    )
    assert section_2(subset)[4:6] == [
        "| Database | MIT-BIH Arrhythmia Database, version 1.0.0 |",
        REAL_LICENCE_LINE,
    ]


def test_the_report_module_holds_no_licence_text() -> None:
    """The licence rows take their text from the ``Database`` (architecture §8.10, §8.15)."""
    source = Path(report.__file__).read_text(encoding="utf-8")
    strings = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    for text in (ODC_BY_1_0.name, ODC_BY_1_0.url, "Open Data Commons", "opendatacommons"):
        assert not any(text in string for string in strings), text


# --- software rows --------------------------------------------------------------------------


def test_software_rows_literally() -> None:
    assert software_rows(SOFTWARE) == (SOFTWARE_LINE, RUNTIME_LINE)


def test_software_rows_follow_the_identity() -> None:
    software = SoftwareIdentity(
        "1.2.3", "a" * 64, "3.13", (("wfdb", "4.3.1"), ("numpy", "2.0.0"), ("scipy", "1.0"))
    )
    assert software_rows(software) == (
        f"| Software | sinus-dsp 1.2.3, source SHA-256 {'a' * 64} |",
        # The runtime packages in the order of the identity.
        "| Runtime | Python 3.13, wfdb 4.3.1, numpy 2.0.0, scipy 1.0 |",
    )


def test_software_rows_without_runtime_packages_and_with_a_bar() -> None:
    software = SoftwareIdentity("1|2", "a" * 64, "3.11", ())
    assert software_rows(software) == (
        f"| Software | sinus-dsp 1\\|2, source SHA-256 {'a' * 64} |",
        "| Runtime | Python 3.11 |",
    )


@pytest.mark.parametrize("render", [render_full_report, render_subset_report])
def test_both_reports_write_the_software_rows_first_in_section_2(render: object) -> None:
    results = full_results() if render is render_full_report else subset_results()
    assert callable(render)
    text = render(results)
    assert line_after(text, "## Software, data and settings")[:4] == [
        "| Item | Value |",
        "|---|---|",
        SOFTWARE_LINE,
        RUNTIME_LINE,
    ]
    lines = text.split("\n")
    assert lines.count(SOFTWARE_LINE) == 1
    assert lines.count(RUNTIME_LINE) == 1


@pytest.mark.parametrize("render", [render_full_report, render_subset_report])
def test_a_rendered_report_states_its_software(render: object) -> None:
    results = full_results() if render is render_full_report else subset_results()
    assert callable(render)
    assert stale_software_rows(render(results), SOFTWARE) == ()
    other = SoftwareIdentity("0.1.0.dev0", "f" * 64, "3.11", SOFTWARE.runtime)
    assert len(stale_software_rows(render(results), other)) == 1


def stale_entry(number: int, found: str, current: str) -> str:
    return f"line {number}: {found}; current: {current}"


def test_stale_software_row() -> None:
    text = render_full_report(full_results())
    other = dataclasses.replace(SOFTWARE, source_sha256="f" * 64)
    # Lines 9 and 10 are the table header and alignment of section 2.
    assert text.split("\n")[10] == SOFTWARE_LINE
    assert stale_software_rows(text, other) == (
        stale_entry(11, SOFTWARE_LINE, software_rows(other)[0]),
    )
    newer = dataclasses.replace(SOFTWARE, version="0.1.0")
    assert stale_software_rows(text, newer) == (
        stale_entry(11, SOFTWARE_LINE, software_rows(newer)[0]),
    )


def test_stale_runtime_row() -> None:
    text = render_subset_report(subset_results())
    for other in (
        dataclasses.replace(SOFTWARE, python="3.12"),
        dataclasses.replace(SOFTWARE, runtime=(("numpy", "2.4.7"), *SOFTWARE.runtime[1:])),
        dataclasses.replace(SOFTWARE, runtime=SOFTWARE.runtime[:2]),
    ):
        # The subset report has one more paragraph before section 2.
        assert stale_software_rows(text, other) == (
            stale_entry(14, RUNTIME_LINE, software_rows(other)[1]),
        )


def test_both_rows_stale_in_the_order_of_the_lines() -> None:
    text = "\n".join(["| Runtime | old |", "", "| Software | old |", ""])
    assert stale_software_rows(text, SOFTWARE) == (
        stale_entry(1, "| Runtime | old |", RUNTIME_LINE),
        stale_entry(3, "| Software | old |", SOFTWARE_LINE),
    )


def test_one_row_missing() -> None:
    text = render_full_report(full_results())
    without_runtime = text.replace(RUNTIME_LINE + "\n", "")
    without_software = text.replace(SOFTWARE_LINE + "\n", "")
    assert stale_software_rows(without_runtime, SOFTWARE) == ("no Runtime row",)
    assert stale_software_rows(without_software, SOFTWARE) == ("no Software row",)
    stale_without_runtime = without_runtime.replace(SOFTWARE_LINE, "| Software | sinus-dsp 0 |")
    assert stale_software_rows(stale_without_runtime, SOFTWARE) == (
        stale_entry(11, "| Software | sinus-dsp 0 |", SOFTWARE_LINE),
        "no Runtime row",
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "# Validation reports\n\n| Report | Requirements |\n|---|---|\n| a.md | none |\n",
        "| Software |\n| Runtime |\n",  # no cell after the label
        "| Softwares | x |\n| Runtimes | y |\n",
        "Software | x |\n  | Runtime | y |\n",
    ],
)
def test_text_with_neither_row(text: str) -> None:
    assert stale_software_rows(text, SOFTWARE) == ()


def test_every_software_row_is_compared() -> None:
    text = "\n".join([SOFTWARE_LINE, RUNTIME_LINE, "", SOFTWARE_LINE, "| Software |  |", ""])
    assert stale_software_rows(text, SOFTWARE) == (
        stale_entry(5, "| Software |  |", SOFTWARE_LINE),
    )


def test_carriage_returns_at_line_ends_are_not_part_of_the_rows() -> None:
    text = render_full_report(full_results()).replace("\n", "\r\n")
    assert stale_software_rows(text, SOFTWARE) == ()
    other = dataclasses.replace(SOFTWARE, python="3.12")
    assert stale_software_rows(text, other) == (
        stale_entry(12, RUNTIME_LINE, software_rows(other)[1]),
    )


# --- segments not scored --------------------------------------------------------------------


def test_segments_not_scored_rows_sorted_with_episodes_only() -> None:
    records = (
        evaluation("207", 1, 0, 0, vf=(6, 1, 35245, 0, 3)),
        evaluation("119", 1, 0, 0),
        evaluation("118", 1, 0, 0, fs_hz=250.0, vf=(1, 1, 1000, 4, 2), flutter=1),
        evaluation("106", 1, 0, 0, vf=(2, 0, 0, 0, 0), flutter=5),
    )
    text = render_full_report(full_results(records))
    assert line_after(text, "The first 5 min of each record are not scored.") == [
        "| Record | Episodes in the record | Episodes from 5:00 | Duration from 5:00 (s) "
        "| Reference beats not scored | Detections not scored |",
        "|---|---:|---:|---:|---:|---:|",
        "| 106 | 2 | 0 | 0.0 | 0 | 0 |",
        "| 118 | 1 | 1 | 4.0 | 4 | 2 |",
        "| 207 | 6 | 1 | 97.9 | 0 | 3 |",
    ]
    assert (
        "Flutter-wave annotations outside ventricular flutter and fibrillation episodes, "
        "in all records: 6."
    ) in text


def test_no_episode_in_any_record() -> None:
    records = (evaluation("118", 1, 0, 0), evaluation("119", 1, 0, 0))
    text = render_full_report(full_results(records))
    section = text.split("## Segments not scored\n\n", 1)[1].split("\n\n## ", 1)[0]
    assert section.split("\n\n") == [
        "The first 5 min of each record are not scored. Ventricular flutter and fibrillation "
        "episodes are not scored either. The durations and counts below cover the part of "
        "each record from 5:00 to its end, except the episodes in the record, which are "
        "counted over the whole record.",
        "No ventricular flutter or fibrillation episode is annotated in these records.",
        "Flutter-wave annotations outside ventricular flutter and fibrillation episodes, in "
        "all records: 0.",
    ]


def test_duration_is_rounded_to_one_decimal() -> None:
    records = (
        evaluation("118", 1, 0, 0, vf=(1, 1, 18, 0, 0)),  # 0.05 s at 360 Hz
        evaluation("119", 1, 0, 0, vf=(1, 1, 125, 0, 0), fs_hz=250.0),  # 0.5 s
    )
    table = line_after(render_full_report(full_results(records)), "The first 5 min")
    assert [row.split(" | ")[3] for row in table[2:]] == [f"{18 / 360:.1f}", "0.5"]


# --- subset report --------------------------------------------------------------------------


def test_subset_report_sections_and_paragraph() -> None:
    text = render_subset_report(subset_results())
    assert headings(text) == [
        "# QRS detection: EC57 subset report for regression checking",
        "## Software, data and settings",
        "## Results per record",
        "## Lowest sensitivity",
        "## Lowest positive predictivity",
        "## Segments not scored",
    ]
    assert text.startswith(
        "# QRS detection: EC57 subset report for regression checking\n\n"
        f"{STATEMENT}\n\n"
        "This report covers records 100, 102, 105, 118, 119 and 207 of the Fixture "
        "Arrhythmia Database. It is a regression check run on every change, not the "
        "performance evaluation against the targets, which uses all 48 records "
        "(qrs-ec57-report.md).\n\n"
        "Generated by dsp/scripts/subset_check.py; do not edit by hand.\n\n"
        "## Software, data and settings\n\n"
    )
    assert "Performance targets" not in text
    assert "Noise stress" not in text
    assert "OP-031" not in text


def test_subset_report_shares_the_sections_of_the_full_report() -> None:
    full = render_full_report(full_results())
    subset = render_subset_report(subset_results())
    shared = full.split("## Software, data and settings", 1)[1]
    shared_sections = (
        shared.split("## Performance targets", 1)[0]
        + ("## Results per record" + shared.split("## Results per record", 1)[1]).split(
            "## Noise stress test", 1
        )[0]
    )
    assert (
        subset.split("## Software, data and settings", 1)[1] == shared_sections.rstrip("\n") + "\n"
    )


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (("100",), "This report covers record 100 of the"),
        (("100", "207"), "This report covers records 100 and 207 of the"),
        (("207", "100", "105"), "This report covers records 100, 105 and 207 of the"),
    ],
)
def test_subset_paragraph_names_the_records(names: tuple[str, ...], expected: str) -> None:
    records = tuple(evaluation(name, 1, 0, 0) for name in names)
    assert expected in render_subset_report(subset_results(records))


# --- misuse ---------------------------------------------------------------------------------


def test_full_report_needs_the_whole_evaluation() -> None:
    with pytest.raises(InvalidInputError, match="needs the results of the whole evaluation"):
        render_full_report(subset_results())
    with pytest.raises(InvalidInputError, match="with the noise stress test"):
        render_full_report(dataclasses.replace(full_results(), noise_stress=None))
    with pytest.raises(InvalidInputError):
        render_full_report(dataclasses.replace(full_results(), subset=True))
    with pytest.raises(InvalidInputError, match="the signal quality and the start of stream"):
        render_full_report(dataclasses.replace(full_results(), quality=None))
    with pytest.raises(InvalidInputError, match="the signal quality and the start of stream"):
        render_full_report(dataclasses.replace(full_results(), start_of_stream=None))


def test_subset_report_needs_a_subset() -> None:
    with pytest.raises(InvalidInputError, match="needs the results of a subset"):
        render_subset_report(full_results())
    with pytest.raises(InvalidInputError, match="needs the results of a subset"):
        render_subset_report(dataclasses.replace(subset_results(), subset=False))


def test_subset_report_refuses_results_with_a_noise_stress_test() -> None:
    results = dataclasses.replace(subset_results(), noise_stress=noise_stress())
    assert results.subset is True
    with pytest.raises(
        InvalidInputError,
        match=(
            "^the subset report needs the results of a subset of the records, without the "
            "noise stress test, the signal quality and the start of stream$"
        ),
    ):
        render_subset_report(results)


def test_subset_report_refuses_results_with_sections_8_or_9() -> None:
    with_quality = dataclasses.replace(subset_results(), quality=quality_results())
    with_stream = dataclasses.replace(subset_results(), start_of_stream=start_of_stream_results())
    for results in (with_quality, with_stream):
        with pytest.raises(InvalidInputError, match="the signal quality and the start of stream"):
            render_subset_report(results)
