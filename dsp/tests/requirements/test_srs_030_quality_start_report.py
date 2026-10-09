"""Requirement tests of SRS-030: signal quality and start-of-stream sections of the report.

The report gains section 8 (signal quality index) and section 9 (start of stream) in the
literal format of the detailed design (architecture-m2, section 13.7.5). The tests render
hand-built results (figures chosen here, expected text worked out here), and run the whole
evaluation on fixture databases with stage doubles of known output: a quality double whose
window indices follow a rule written in this file, and the detections marked reliable of
`conftest.py`. Nothing needs the network or the real databases.

Covered: every item of the two sections, the figures per SNR, per noise record and for
records 118 and 119 together, each criterion of SRS-029 with its value, its limit and its
result (at the boundaries too), the false negatives and false positives in not usable
windows, the start-of-stream counts and the gross Se and +P against the target, the
sections absent from the subset report, and determinism.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sinus_dsp.data.physionet import Database, DatabaseLicence, VerificationResult
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.metrics import RecordCounts, aggregate_statistics
from sinus_dsp.evaluation.noise_stress import NoiseStressResults, SnrStatistics
from sinus_dsp.evaluation.report import render_full_report, render_subset_report
from sinus_dsp.evaluation.run import (
    EvaluationSettings,
    RecordEvaluation,
    ValidationResults,
    run_validation,
    write_validation_report,
)
from sinus_dsp.evaluation.signal_quality import (
    QUALITY_CRITERIA,
    QualityResults,
    RecordQuality,
    WindowSummary,
    count_in_not_usable,
    quality_criteria,
)
from sinus_dsp.evaluation.start_of_stream import (
    SEGMENT_STARTS_S,
    StartOfStreamRecord,
    StartOfStreamResults,
)
from sinus_dsp.quality import QualityWindows
from sinus_dsp.version import SoftwareIdentity

pytestmark = pytest.mark.usefixtures("forbid_network")

MITDB_TITLE = "MIT-BIH Arrhythmia Database"
NSTDB_TITLE = "MIT-BIH Noise Stress Test Database"
RENDER_MITDB = Database(
    slug="mitdb",
    version="1.0.0",
    title=MITDB_TITLE,
    checksum_list_sha256="0" * 64,
    licence=DatabaseLicence(name="Licence A", url="https://licences.example.org/a/"),
)
RENDER_NSTDB = Database(
    slug="nstdb",
    version="1.0.0",
    title=NSTDB_TITLE,
    checksum_list_sha256="1" * 64,
    licence=DatabaseLicence(name="Licence B", url="https://licences.example.org/b/"),
)
RENDER_SOFTWARE = SoftwareIdentity(
    version="0.0.0.dev0",
    source_sha256="e" * 64,
    python="3.11",
    runtime=(("numpy", "2.0.0"), ("scipy", "1.0.0"), ("wfdb", "4.0.0")),
)
SNRS = (24, 18, 12, 6, 0, -6)
NOISE_NAMES = ("bw", "em", "ma")
NOISY_STRETCHES_TEXT = (
    "from 5:00 to the end of each noise stress record, 2 min with added noise alternating "
    "with 2 min without, starting with noise"
)
NOISE_STRESS_PARAGRAPH = (
    "Noise stress records: the windows that lie entirely in a stretch with added noise. "
    f"Records of the {MITDB_TITLE}: the windows that start at or after 5:00. "
    "Noise records: every window."
)
RECORDS_PARAGRAPH = (
    "FN and FP are those of the results per record. Each one that lies in at least one "
    "window marked not usable is counted once. No threshold applies to these figures."
)
MATCHING_TEXT = (
    "EC57 beat by beat, pairing rules of the WFDB comparator bxb; match window 150 ms; "
    "start-up period not scored; ventricular flutter and fibrillation episodes not scored"
)
CRITERION_LABELS = (
    "Median index from 24 dB to -6 dB",
    "Median index at -6 dB and at 24 dB",
    "Usable windows, records 118 and 119 from 5:00 (%)",
    "Usable windows at 24 dB (%)",
    "Usable windows at 18 dB (%)",
    "Usable windows at 6 dB (%)",
    "Usable windows at 0 dB (%)",
    "Usable windows at -6 dB (%)",
    "Usable windows, noise record bw (%)",
    "Usable windows, noise record em (%)",
    "Usable windows, noise record ma (%)",
)
CRITERION_REQUIRED = (
    "non-increasing",
    "lower at -6 dB",
    "≥ 95.00",
    "≥ 90.00",
    "≥ 90.00",
    "≤ 20.00",
    "≤ 20.00",
    "≤ 20.00",
    "≤ 10.00",
    "≤ 10.00",
    "≤ 10.00",
)


# --------------------------------------------------------------------------------------------
# Hand-built results
# --------------------------------------------------------------------------------------------


def _evaluation(name: str, tp: int, fn: int, fp: int) -> RecordEvaluation:
    return RecordEvaluation(
        record=name,
        signal_name="MLII",
        fs_hz=360.0,
        counts=RecordCounts(record=name, tp=tp, fn=fn, fp=fp),
        vf_episodes=0,
        vf_episodes_scored=0,
        vf_samples_scored=0,
        reference_excluded=0,
        detections_excluded=0,
        flutter_waves_outside_vf=0,
    )


def _noise_stress() -> NoiseStressResults:
    names = [f"{r}e{t}" for r in (118, 119) for t in ("24", "18", "12", "06", "00", "_6")]
    records = tuple(_evaluation(n, 50, 1, 1) for n in names)
    by_snr = tuple(
        SnrStatistics(
            snr_db=snr,
            statistics=aggregate_statistics([records[i].counts, records[i + 6].counts]),
        )
        for i, snr in enumerate(SNRS)
    )
    return NoiseStressResults(
        nstdb=VerificationResult(database=RENDER_NSTDB, records=None, files=("RECORDS",)),
        records=records,
        by_snr=by_snr,
        clean=aggregate_statistics([RecordCounts("118", 50, 0, 0), RecordCounts("119", 50, 0, 0)]),
    )


def _results(
    quality: QualityResults | None,
    start: StartOfStreamResults | None,
    names: Sequence[str] = ("100", "118", "119", "207"),
) -> ValidationResults:
    return ValidationResults(
        software=RENDER_SOFTWARE,
        settings=EvaluationSettings(),
        mitdb=VerificationResult(database=RENDER_MITDB, records=None, files=("RECORDS",)),
        records=tuple(_evaluation(n, 100, 1, 1) for n in names),
        noise_stress=_noise_stress(),
        subset=False,
        quality=quality,
        start_of_stream=start,
    )


def _summary(n: int, usable: int, median: float | None) -> WindowSummary:
    return WindowSummary(n_windows=n, n_usable=usable, median_index=median)


def _quality(
    *,
    by_snr: Sequence[WindowSummary],
    clean: WindowSummary,
    noise: Sequence[WindowSummary],
    records: Sequence[RecordQuality],
) -> QualityResults:
    by_snr_pairs = tuple(zip(SNRS, by_snr, strict=True))
    noise_pairs = tuple(zip(NOISE_NAMES, noise, strict=True))
    return QualityResults(
        records=tuple(records),
        by_snr=by_snr_pairs,
        clean=clean,
        noise_records=noise_pairs,
        criteria=quality_criteria(by_snr_pairs, clean, noise_pairs),
    )


def _record_quality(name: str, n: int, usable: int, fn: int, fp: int) -> RecordQuality:
    return RecordQuality(
        record=name,
        from_start=_summary(n, usable, 0.5 if n else None),
        fn_in_not_usable=fn,
        fp_in_not_usable=fp,
    )


RECORD_QUALITY = (
    _record_quality("100", 1200, 1190, 3, 1),
    _record_quality("118", 1000, 1000, 0, 0),
    _record_quality("119", 1000, 953, 7, 2),
    _record_quality("207", 0, 0, 0, 0),
)
SNR_SUMMARIES = (
    _summary(722, 700, 0.9812),
    _summary(722, 650, 0.9051),
    _summary(722, 300, 0.5234),
    _summary(722, 140, 0.3120),
    _summary(722, 40, 0.1507),
    _summary(722, 3, 0.0410),
)
CLEAN_SUMMARY = _summary(2000, 1960, 0.9444)
NOISE_SUMMARIES = (_summary(51, 0, 0.0100), _summary(51, 5, 0.0800), _summary(51, 6, 0.1000))


def _standard_quality() -> QualityResults:
    return _quality(
        by_snr=SNR_SUMMARIES, clean=CLEAN_SUMMARY, noise=NOISE_SUMMARIES, records=RECORD_QUALITY
    )


def _record_counts(name: str, tp: int, fn: int, fp: int) -> RecordCounts:
    return RecordCounts(record=name, tp=tp, fn=fn, fp=fp)


def _start(
    counts: Sequence[RecordCounts],
    *,
    starts: Sequence[int] = SEGMENT_STARTS_S,
    segment_s: int = 60,
    signals: dict[str, str] | None = None,
) -> StartOfStreamResults:
    signals = signals or {}
    return StartOfStreamResults(
        segment_s=segment_s,
        starts_s=tuple(starts),
        records=tuple(
            StartOfStreamRecord(
                record=c.record,
                signal_name=signals.get(c.record, "MLII"),
                n_segments=len(starts),
                counts=c,
            )
            for c in counts
        ),
        statistics=aggregate_statistics(list(counts)),
    )


START_COUNTS_PASS = (
    _record_counts("100", 2000, 5, 20),
    _record_counts("118", 1990, 10, 0),
    _record_counts("207", 0, 0, 0),
)
START_COUNTS_FAIL = (
    _record_counts("100", 2000, 5, 21),
    _record_counts("118", 1990, 10, 0),
    _record_counts("207", 0, 0, 0),
)


def _mss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _text(results: ValidationResults) -> str:
    return render_full_report(results)


def _sections(text: str, parse_report: Callable[[str], Any]) -> tuple[Any, Any]:
    """The parsed sections 8 and 9 of a report (each with its own sub-headings)."""
    report = parse_report(text)
    quality = report.section("Signal quality index")
    start = report.section("Start of stream")
    return (
        parse_report(f"## {quality.title}\n{quality.text}"),
        parse_report(f"## {start.title}\n{start.text}"),
    )


def _flat(text: str) -> str:
    return " ".join(text.split())


# --------------------------------------------------------------------------------------------
# Order, headings, absence of the sections from the subset report
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-030")
def test_sections_follow_the_noise_stress_section_in_order(
    parse_report: Callable[[str], Any],
) -> None:
    """Section 8 and section 9 come after section 7 (noise stress test), in this order.

    Input: hand-built results with both new fields.
    Expected: headings `## Signal quality index` then `## Start of stream` are the last two
    level-2 headings, directly after the noise stress test section; the text names no
    requirement, risk control or hazard identifier.
    """
    text = _text(_results(_standard_quality(), _start(START_COUNTS_PASS)))
    level2 = [t for (_, level, t) in parse_report(text).headings if level == 2]

    assert level2[-2:] == ["Signal quality index", "Start of stream"]
    assert "noise stress" in level2[-3].casefold()
    section_8_9 = text[text.index("## Signal quality index") :]
    assert not re.search(r"\b(SRS|RC|HAZ|OP)-\d", section_8_9)


@pytest.mark.requirement("SRS-030")
def test_full_report_requires_both_sections_of_results(
    parse_report: Callable[[str], Any],
) -> None:
    """The full report is refused when a field of the new sections is missing.

    Input: results without `quality`, results without `start_of_stream`.
    Expected: `render_full_report` raises `InvalidInputError` in both cases.
    """
    with pytest.raises(InvalidInputError):
        render_full_report(_results(None, _start(START_COUNTS_PASS)))
    with pytest.raises(InvalidInputError):
        render_full_report(_results(_standard_quality(), None))
    with pytest.raises(InvalidInputError):
        render_full_report(_results(None, None))


@pytest.mark.requirement("SRS-030")
@pytest.mark.parametrize(
    ("with_quality", "with_start"),
    [(True, False), (False, True), (True, True)],
    ids=["quality", "start-of-stream", "both"],
)
def test_subset_report_refuses_results_with_the_new_sections(
    with_quality: bool, with_start: bool
) -> None:
    """The subset report holds neither section, and refuses results that carry them.

    Input: subset results (`subset=True`, no noise stress) with `quality`,
    `start_of_stream` or both set.
    Expected: `render_subset_report` raises `InvalidInputError`.
    """
    results = replace(
        _results(
            _standard_quality() if with_quality else None,
            _start(START_COUNTS_PASS) if with_start else None,
        ),
        subset=True,
        noise_stress=None,
    )
    with pytest.raises(InvalidInputError):
        render_subset_report(results)


@pytest.mark.requirement("SRS-030")
def test_subset_report_has_neither_section() -> None:
    """The subset report text has neither the section 8 nor the section 9.

    Input: subset results without the two fields; also the stored subset report.
    Expected: no heading `Signal quality index` or `Start of stream` in either.
    """
    results = replace(_results(None, None), subset=True, noise_stress=None)
    text = render_subset_report(results)
    stored = (
        Path(__file__).resolve().parents[3] / "docs" / "validation" / "qrs-ec57-subset-report.md"
    ).read_text(encoding="utf-8")

    for report in (text, stored):
        headings = [line for line in report.splitlines() if line.startswith("#")]
        assert not [h for h in headings if re.search(r"signal quality|start of stream", h, re.I)]


# --------------------------------------------------------------------------------------------
# Section 8
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-030")
def test_quality_section_states_window_length_spacing_threshold_and_stretches(
    parse_report: Callable[[str], Any],
) -> None:
    """The window length, the window spacing, the threshold and the selection of windows.

    Input: hand-built results.
    Expected: a table `Item`/`Value` with `Window length` = `10 s`, `Window spacing` = `1 s`,
    `Usable threshold` = `0.50` and the `Noisy stretches` sentence, then the paragraph on the
    windows of each kind of record.
    """
    quality, _ = _sections(
        _text(_results(_standard_quality(), _start(START_COUNTS_PASS))), parse_report
    )
    section = quality.section("Signal quality index")
    table = section.tables()[0]

    assert table.header == ("Item", "Value")
    assert table.row("Window length") == ("Window length", "10 s")
    assert table.row("Window spacing") == ("Window spacing", "1 s")
    assert table.row("Usable threshold") == ("Usable threshold", "0.50")
    assert table.row("Noisy stretches") == ("Noisy stretches", NOISY_STRETCHES_TEXT)
    assert NOISE_STRESS_PARAGRAPH in _flat(section.text)


@pytest.mark.requirement("SRS-030")
def test_quality_section_gives_the_figures_per_snr_and_per_noise_record(
    parse_report: Callable[[str], Any], percent_text: Callable[[int, int], str]
) -> None:
    """Number of windows, median index and share usable, per SNR, for 118+119 and per record.

    Input: windows (722, 700, 0.9812), (722, 650, 0.9051), (722, 300, 0.5234),
    (722, 140, 0.3120), (722, 40, 0.1507), (722, 3, 0.0410) for 24 to -6 dB; (2000, 1960,
    0.9444) for records 118 and 119; (51, 0, 0.0100), (51, 5, 0.0800), (51, 6, 0.1000) for bw,
    em and ma.
    Expected: table with columns `Windows of`, `Windows`, `Median index`, `Usable (%)`; rows
    `24 dB` ... `-6 dB` in this order, `records 118 and 119, no added noise, from 5:00`, then
    `noise record bw`, `em`, `ma`; medians with four decimals, shares with two (96.95, 90.03,
    41.55, 19.39, 5.54, 0.42; 98.00; 0.00, 9.80, 11.76).
    """
    quality, _ = _sections(
        _text(_results(_standard_quality(), _start(START_COUNTS_PASS))), parse_report
    )
    table = quality.section("Noise stress records").tables()[0]

    assert table.header == ("Windows of", "Windows", "Median index", "Usable (%)")
    expected_rows = [
        *((f"{snr} dB", s) for snr, s in zip(SNRS, SNR_SUMMARIES, strict=True)),
        ("records 118 and 119, no added noise, from 5:00", CLEAN_SUMMARY),
        *((f"noise record {n}", s) for n, s in zip(NOISE_NAMES, NOISE_SUMMARIES, strict=True)),
    ]
    assert table.first_cells() == [label for label, _ in expected_rows]
    for label, summary in expected_rows:
        assert table.row(label) == (
            label,
            str(summary.n_windows),
            f"{summary.median_index:.4f}",
            percent_text(summary.n_usable, summary.n_windows),
        ), label
    assert [table.row(f"{s} dB")[3] for s in SNRS] == [
        "96.95",
        "90.03",
        "41.55",
        "19.39",
        "5.54",
        "0.42",
    ]
    assert table.row("records 118 and 119, no added noise, from 5:00")[3] == "98.00"
    assert [table.row(f"noise record {n}")[3] for n in NOISE_NAMES] == ["0.00", "9.80", "11.76"]


@pytest.mark.requirement("SRS-030")
def test_quality_section_says_not_defined_without_windows(
    parse_report: Callable[[str], Any],
) -> None:
    """A group without windows has no median and no share.

    Input: noise record `em` and record 207 with no window, no median.
    Expected: the row `noise record em` reads 0 windows, `not defined`, `not defined`; the
    row of record 207 reads 0 windows and `not defined` as share; the criterion of the noise
    record `em` fails.
    """
    noise = (NOISE_SUMMARIES[0], _summary(0, 0, None), NOISE_SUMMARIES[2])
    quality_results = _quality(
        by_snr=SNR_SUMMARIES, clean=CLEAN_SUMMARY, noise=noise, records=RECORD_QUALITY
    )
    quality, _ = _sections(
        _text(_results(quality_results, _start(START_COUNTS_PASS))), parse_report
    )

    row = quality.section("Noise stress records").tables()[0].row("noise record em")
    assert row == ("noise record em", "0", "not defined", "not defined")
    assert quality.section("Records of the").tables()[0].row("207")[1:3] == ("0", "not defined")
    criteria = quality.section("Criteria").tables()[0]
    assert criteria.row("Usable windows, noise record em (%)")[1:] == (
        "not defined",
        "≤ 10.00",
        "fail",
    )


@pytest.mark.requirement("SRS-030")
def test_quality_section_gives_the_share_usable_of_each_record_and_the_total(
    parse_report: Callable[[str], Any], percent_text: Callable[[int, int], str]
) -> None:
    """Per record of the reference database: windows from 5:00, share usable, FN and FP.

    Input: records 100 (1200 windows, 1190 usable, 3 FN, 1 FP), 118 (1000, 1000, 0, 0), 119
    (1000, 953, 7, 2) and 207 (no window).
    Expected: heading `Records of the MIT-BIH Arrhythmia Database`; columns `Record`,
    `Windows from 5:00`, `Usable (%)`, `FN in not usable windows`, `FP in not usable windows`;
    one row per record in the order given, then `Total` with 3200 windows, 3143 usable
    (98.22) from the summed counts (not the mean of the shares), 10 FN, 3 FP; then the
    paragraph on FN and FP, which states that no threshold applies.
    """
    quality, _ = _sections(
        _text(_results(_standard_quality(), _start(START_COUNTS_PASS))), parse_report
    )
    section = quality.section(f"Records of the {MITDB_TITLE}")
    table = section.tables()[0]

    assert table.header == (
        "Record",
        "Windows from 5:00",
        "Usable (%)",
        "FN in not usable windows",
        "FP in not usable windows",
    )
    assert table.first_cells() == ["100", "118", "119", "207", "Total"]
    assert table.row("100") == ("100", "1200", "99.17", "3", "1")
    assert table.row("118") == ("118", "1000", "100.00", "0", "0")
    assert table.row("119") == ("119", "1000", "95.30", "7", "2")
    assert table.row("207") == ("207", "0", "not defined", "0", "0")
    assert table.row("Total") == ("Total", "3200", percent_text(3143, 3200), "10", "3")
    assert table.row("Total")[2] == "98.22"
    assert RECORDS_PARAGRAPH in _flat(section.text)


def _boundary_quality(
    snr: dict[int, WindowSummary] | None = None,
    clean: WindowSummary | None = None,
    noise: dict[str, WindowSummary] | None = None,
) -> QualityResults:
    """A quality result in which every criterion is met, with some summaries replaced."""
    base_snr = {
        24: _summary(200, 190, 0.9),
        18: _summary(200, 185, 0.8),
        12: _summary(200, 100, 0.6),
        6: _summary(200, 20, 0.4),
        0: _summary(200, 10, 0.2),
        -6: _summary(200, 0, 0.1),
    }
    base_noise = {
        "bw": _summary(100, 0, 0.0),
        "em": _summary(100, 5, 0.1),
        "ma": _summary(100, 10, 0.1),
    }
    base_snr.update(snr or {})
    base_noise.update(noise or {})
    return _quality(
        by_snr=[base_snr[s] for s in SNRS],
        clean=clean or _summary(400, 390, 0.9),
        noise=[base_noise[n] for n in NOISE_NAMES],
        records=RECORD_QUALITY,
    )


def _criteria_rows(
    results: QualityResults, parse_report: Callable[[str], Any]
) -> dict[str, tuple[str, ...]]:
    text = _text(_results(results, _start(START_COUNTS_PASS)))
    quality, _ = _sections(text, parse_report)
    table = quality.section("Criteria").tables()[0]
    assert table.header == ("Criterion", "Value", "Required", "Result")
    return {row[0]: row for row in table.rows}


@pytest.mark.requirement("SRS-030")
def test_criteria_table_lists_each_criterion_with_value_limit_and_result(
    parse_report: Callable[[str], Any], percent_text: Callable[[int, int], str]
) -> None:
    """Every criterion of SRS-029 with its value, its limit and pass or fail.

    Input: the standard hand-built figures of the SNR, clean and noise windows (all pass but
    the noise record `ma`: 11.76 % usable against at most 10.00).
    Expected: the 11 rows in the order of the criteria, with the labels, the values (six
    medians separated by `, `; the two medians; the shares), the limits (`non-increasing`,
    `lower at -6 dB`, `≥ 95.00`, `≥ 90.00` twice, `≤ 20.00` three times, `≤ 10.00` three
    times) and `pass` for all but the last, which reads `fail`.
    """
    quality_results = _standard_quality()
    rows = _criteria_rows(quality_results, parse_report)
    medians = [s.median_index for s in SNR_SUMMARIES]
    shares = [percent_text(s.n_usable, s.n_windows) for s in SNR_SUMMARIES]
    values = [
        ", ".join(f"{m:.4f}" for m in medians),
        f"{medians[5]:.4f}, {medians[0]:.4f}",
        percent_text(CLEAN_SUMMARY.n_usable, CLEAN_SUMMARY.n_windows),
        shares[0],
        shares[1],
        shares[3],
        shares[4],
        shares[5],
        *(percent_text(s.n_usable, s.n_windows) for s in NOISE_SUMMARIES),
    ]

    assert len(QUALITY_CRITERIA) == len(CRITERION_LABELS) == 11
    assert list(rows) == list(CRITERION_LABELS)
    results = ["pass"] * 10 + ["fail"]
    for label, value, required, result in zip(
        CRITERION_LABELS, values, CRITERION_REQUIRED, results, strict=True
    ):
        assert rows[label] == (label, value, required, result), label


@pytest.mark.requirement("SRS-030")
def test_criteria_table_keeps_the_order_of_the_criteria(
    parse_report: Callable[[str], Any],
) -> None:
    """The criteria are listed in the order of the criteria of SRS-029.

    Input: the standard hand-built figures.
    Expected: the first cells of the criteria table are the 11 labels, in order, once each.
    """
    text = _text(_results(_standard_quality(), _start(START_COUNTS_PASS)))
    quality, _ = _sections(text, parse_report)

    assert quality.section("Criteria").tables()[0].first_cells() == list(CRITERION_LABELS)


@dataclass(frozen=True)
class Boundary:
    label: str
    changes: dict[str, Any]
    result: str


def _boundary_cases() -> list[Any]:
    cases: list[Boundary] = []
    clean = "Usable windows, records 118 and 119 from 5:00 (%)"
    for usable, result in ((190, "pass"), (189, "fail")):
        cases.append(Boundary(clean, {"clean": _summary(200, usable, 0.9)}, result))
    cases.append(Boundary(clean, {"clean": _summary(0, 0, None)}, "fail"))
    for snr in (24, 18):
        for usable, result in ((180, "pass"), (179, "fail")):
            cases.append(
                Boundary(
                    f"Usable windows at {snr} dB (%)",
                    {"snr": {snr: _summary(200, usable, 0.9 if snr == 24 else 0.8)}},
                    result,
                )
            )
    for snr, median in ((6, 0.4), (0, 0.2), (-6, 0.1)):
        for usable, result in ((40, "pass"), (41, "fail")):
            cases.append(
                Boundary(
                    f"Usable windows at {snr} dB (%)",
                    {"snr": {snr: _summary(200, usable, median)}},
                    result,
                )
            )
        cases.append(
            Boundary(
                f"Usable windows at {snr} dB (%)",
                {"snr": {snr: _summary(0, 0, None)}},
                "fail",
            )
        )
    for name in NOISE_NAMES:
        for usable, result in ((20, "pass"), (21, "fail")):
            cases.append(
                Boundary(
                    f"Usable windows, noise record {name} (%)",
                    {"noise": {name: _summary(200, usable, 0.1)}},
                    result,
                )
            )
        cases.append(
            Boundary(
                f"Usable windows, noise record {name} (%)",
                {"noise": {name: _summary(0, 0, None)}},
                "fail",
            )
        )
    return [pytest.param(c, id=f"{c.label}-{c.result}-{i}") for i, c in enumerate(cases)]


@pytest.mark.requirement("SRS-030")
@pytest.mark.parametrize("case", _boundary_cases())
def test_criterion_result_at_its_boundary(
    case: Boundary, parse_report: Callable[[str], Any], percent_text: Callable[[int, int], str]
) -> None:
    """A criterion that is met reads pass, one that is not met reads fail, at the limit.

    Input: all the criteria met, except one group of windows set exactly at the limit (95,
    90, 20, 10 percent of 200 windows: pass) or one window beyond it (fail), or without
    windows (fail).
    Expected: the row of that criterion gives the share of the group and the result; every
    other row reads pass.
    """
    changes = case.changes
    results = _boundary_quality(
        snr=changes.get("snr"), clean=changes.get("clean"), noise=changes.get("noise")
    )
    rows = _criteria_rows(results, parse_report)

    assert rows[case.label][3] == case.result, rows[case.label]
    skipped = {case.label}
    if any(s.n_windows == 0 for s in (changes.get("snr") or {}).values()):
        # The criteria on the medians need a window at every SNR.
        skipped |= set(CRITERION_LABELS[:2])
    others = {k: r[3] for k, r in rows.items() if k not in skipped}
    assert set(others.values()) == {"pass"}, others


@pytest.mark.requirement("SRS-030")
def test_boundary_values_show_the_share_they_have(
    parse_report: Callable[[str], Any],
) -> None:
    """The values at the boundaries are written with two decimals.

    Input: clean 190 of 200 windows, 24 dB 180 of 200, 6 dB 40 of 200, bw 20 of 200.
    Expected: the `Value` cells read 95.00, 90.00, 20.00 and 10.00 and the results pass.
    """
    results = _boundary_quality(
        snr={24: _summary(200, 180, 0.9), 6: _summary(200, 40, 0.4)},
        clean=_summary(200, 190, 0.9),
        noise={"bw": _summary(200, 20, 0.0)},
    )
    rows = _criteria_rows(results, parse_report)

    assert rows["Usable windows, records 118 and 119 from 5:00 (%)"][1] == "95.00"
    assert rows["Usable windows at 24 dB (%)"][1] == "90.00"
    assert rows["Usable windows at 6 dB (%)"][1] == "20.00"
    assert rows["Usable windows, noise record bw (%)"][1] == "10.00"


@pytest.mark.requirement("SRS-030")
@pytest.mark.parametrize(
    ("medians", "non_increasing", "lower"),
    [
        ((0.9, 0.8, 0.6, 0.4, 0.2, 0.1), "pass", "pass"),
        ((0.9, 0.9, 0.6, 0.6, 0.2, 0.2), "pass", "pass"),
        ((0.9, 0.8, 0.6, 0.4, 0.2, 0.9), "fail", "fail"),
        ((0.9, 0.8, 0.6, 0.7, 0.2, 0.1), "fail", "pass"),
        ((0.5, 0.5, 0.5, 0.5, 0.5, 0.5), "pass", "fail"),
        ((0.1, 0.8, 0.6, 0.4, 0.2, 0.1), "fail", "fail"),
    ],
    ids=["strict", "equal-neighbours", "rising-at-end", "bump", "all-equal", "low-at-24"],
)
def test_median_criteria_results(
    medians: tuple[float, ...],
    non_increasing: str,
    lower: str,
    parse_report: Callable[[str], Any],
) -> None:
    """The two criteria on the median index, from the medians of the six SNRs.

    Input: medians for 24 to -6 dB as in the parameters, with all the shares unchanged.
    Expected: `Median index from 24 dB to -6 dB` reads pass when each median is not above
    the one before (equal values pass); `Median index at -6 dB and at 24 dB` reads pass only
    if the median at -6 dB is lower than at 24 dB; the Value cells show the medians.
    """
    base = _boundary_quality()
    snr = {
        s: replace(summary, median_index=m)
        for (s, summary), m in zip(base.by_snr, medians, strict=True)
    }
    rows = _criteria_rows(_boundary_quality(snr=snr), parse_report)

    first = rows["Median index from 24 dB to -6 dB"]
    second = rows["Median index at -6 dB and at 24 dB"]
    assert first[1] == ", ".join(f"{m:.4f}" for m in medians)
    assert first[3] == non_increasing
    assert second[1] == f"{medians[5]:.4f}, {medians[0]:.4f}"
    assert second[3] == lower


@pytest.mark.requirement("SRS-030")
def test_count_in_not_usable_includes_both_ends_of_a_window_and_counts_once() -> None:
    """The false negatives and false positives inside a window marked not usable.

    Input: windows of 10 samples at 0, 5, 10, 15 (first..last = 0-9, 5-14, 10-19, 15-24),
    usable False, True, True, False; samples 0, 4, 9, 10, 20, 24, 25, 12 and 16.
    Expected: a sample counts if it lies in at least one not usable window, whatever its
    start: 0, 4, 9 (window 0), 16 and 24 (window 3), also 15 to 24; 10 and 12 do not (windows
    1 and 2 are usable); 20 is not in window 3? it is (15-24): counted; 25 is outside every
    window. Each sample is counted once even in overlapping windows (9 is in windows 0 and
    1; 16 in 2 and 3).
    """
    first = np.array([0, 5, 10, 15], dtype=np.int64)
    windows = QualityWindows(
        first=first,
        last=first + 9,
        reported_at=first + 9,
        index=np.array([0.1, 0.9, 0.9, 0.1]),
        usable=np.array([False, True, True, False]),
        held=np.zeros(4, dtype=bool),
        n_detections=np.zeros(4, dtype=np.int64),
        signal_power=np.full(4, np.nan),
        background_power=np.full(4, np.nan),
    )

    assert count_in_not_usable([0, 4, 9, 10, 20, 24, 25, 12, 16], windows) == 6
    assert count_in_not_usable([10, 12], windows) == 0
    assert count_in_not_usable([25, 26], windows) == 0
    assert count_in_not_usable([15, 24], windows) == 2
    assert count_in_not_usable([14], windows) == 0
    assert count_in_not_usable([], windows) == 0


# --------------------------------------------------------------------------------------------
# Section 9
# --------------------------------------------------------------------------------------------


@pytest.mark.requirement("SRS-030")
def test_start_section_states_the_segments_and_the_start_up_period(
    parse_report: Callable[[str], Any],
) -> None:
    """The start-up period, the starting points and the rules of the start-of-stream section.

    Input: results with the 30 starts of 60 s (0:00 to 29:00).
    Expected: a table `Item`/`Value` with `Segments` = `60 s each, processed on their own,
    starting at 0:00, 1:00, 2:00, ..., 29:00` (all 30 written out), `Segments per record` =
    30, `Start-up period` = `first 2 s of each segment, not scored`, `Detections scored` =
    `marked reliable` and `Matching` with the literal sentence.
    """
    _, start = _sections(
        _text(_results(_standard_quality(), _start(START_COUNTS_PASS))), parse_report
    )
    table = start.section("Start of stream").tables()[0]
    starts = ", ".join(f"{m}:00" for m in range(30))

    assert table.header == ("Item", "Value")
    assert table.row("Segments") == (
        "Segments",
        f"60 s each, processed on their own, starting at {starts}",
    )
    assert starts.startswith("0:00, 1:00, 2:00, 3:00") and starts.endswith("28:00, 29:00")
    assert table.row("Segments per record") == ("Segments per record", "30")
    assert table.row("Start-up period") == (
        "Start-up period",
        "first 2 s of each segment, not scored",
    )
    assert table.row("Detections scored") == ("Detections scored", "marked reliable")
    assert table.row("Matching") == ("Matching", MATCHING_TEXT)


@pytest.mark.requirement("SRS-030")
def test_start_section_writes_the_starts_of_the_results_as_minutes_and_seconds(
    parse_report: Callable[[str], Any],
) -> None:
    """The starts and the segment length are those of the results, written m:ss.

    Input: results with segments of 45 s starting at 0, 5, 65, 600, 1740 and 3725 s.
    Expected: `45 s each, processed on their own, starting at 0:00, 0:05, 1:05, 10:00, 29:00,
    62:05` and 6 segments per record.
    """
    starts = (0, 5, 65, 600, 1740, 3725)
    _, section = _sections(
        _text(
            _results(_standard_quality(), _start(START_COUNTS_PASS, starts=starts, segment_s=45))
        ),
        parse_report,
    )
    table = section.section("Start of stream").tables()[0]

    assert [_mss(s) for s in starts] == ["0:00", "0:05", "1:05", "10:00", "29:00", "62:05"]
    assert table.row("Segments")[1] == (
        "45 s each, processed on their own, starting at 0:00, 0:05, 1:05, 10:00, 29:00, 62:05"
    )
    assert table.row("Segments per record")[1] == "6"


@pytest.mark.requirement("SRS-030")
def test_start_section_gives_the_statistics_of_each_record_and_all_segments(
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
    mean_percent_text: Callable[[Sequence[tuple[int, int]]], str],
) -> None:
    """Counts and statistics per record, summed over its segments, and over all segments.

    Input: records 100 (MLII, TP 2000, FN 5, FP 20), 118 (V5, 1990, 10, 0) and 207 (MLII, 0,
    0, 0), each over 30 segments.
    Expected: table `Record`, `Signal`, `Segments`, `TP`, `FN`, `FP`, `Se (%)`, `+P (%)`;
    rows 100, 118, 207 (Se and +P `not defined` for 207), `Gross` with 90 segments, 3990, 15,
    20, 99.63, 99.50, and `Average` with the means of the defined values (2 of 3 records
    each) and no counts; then the sentence on the averages.
    """
    start_results = _start(START_COUNTS_PASS, signals={"118": "V5"})
    _, start = _sections(_text(_results(_standard_quality(), start_results)), parse_report)
    section = start.section("Results per record")
    table = section.tables()[0]

    assert table.header == ("Record", "Signal", "Segments", "TP", "FN", "FP", "Se (%)", "+P (%)")
    assert table.first_cells() == ["100", "118", "207", "Gross", "Average"]
    assert table.row("100") == ("100", "MLII", "30", "2000", "5", "20", "99.75", "99.01")
    assert table.row("118") == ("118", "V5", "30", "1990", "10", "0", "99.50", "100.00")
    assert table.row("207") == (
        "207",
        "MLII",
        "30",
        "0",
        "0",
        "0",
        "not defined",
        "not defined",
    )
    se_pairs = [(2000, 2005), (1990, 2000), (0, 0)]
    ppv_pairs = [(2000, 2020), (1990, 1990), (0, 0)]
    gross = table.row("Gross")
    assert gross[0] == "Gross"
    assert gross[1] == ""
    assert gross[2:] == (
        "90",
        "3990",
        "15",
        "20",
        percent_text(3990, 4005),
        percent_text(3990, 4010),
    )
    assert gross[-2:] == ("99.63", "99.50")
    average = table.row("Average")
    assert average[1:6] == ("", "", "", "", "")
    assert average[6:] == (mean_percent_text(se_pairs), mean_percent_text(ppv_pairs))
    assert average[6:] == ("99.63", "99.50")
    sentence = (
        "The averages are the means of the defined per-record values: Se is defined for 2 of "
        "3 records, +P for 2 of 3 records."
    )
    assert sentence in _flat(section.text)


@pytest.mark.requirement("SRS-030")
@pytest.mark.parametrize(
    ("counts", "se", "ppv", "se_result", "ppv_result"),
    [
        (START_COUNTS_PASS, "99.63", "99.50", "pass", "pass"),
        (START_COUNTS_FAIL, "99.63", "99.48", "pass", "fail"),
        (
            (_record_counts("100", 199, 1, 1),),
            "99.50",
            "99.50",
            "pass",
            "pass",
        ),
        (
            (_record_counts("100", 198, 1, 1),),
            "99.50",
            "99.50",
            "fail",
            "fail",
        ),
        (
            (_record_counts("100", 9900, 100, 0),),
            "99.00",
            "100.00",
            "fail",
            "pass",
        ),
        ((_record_counts("100", 0, 0, 0),), "not defined", "not defined", "fail", "fail"),
    ],
    ids=["both-met", "ppv-missed", "exactly-99.50", "99.497-shown-99.50", "se-missed", "nothing"],
)
def test_start_section_compares_the_gross_values_with_the_target(
    counts: Sequence[RecordCounts],
    se: str,
    ppv: str,
    se_result: str,
    ppv_result: str,
    parse_report: Callable[[str], Any],
) -> None:
    """The gross Se and +P of all the segments against the target, pass or fail.

    Input: counts of the parameters (the gross values 99.63/99.50 pass; +P 4011 detections of
    which 21 false fails; 199 of 200 is exactly 99.50 and passes; 198 of 199 shows 99.50 but
    is 99.497 and fails; no counts leave both values undefined and fail).
    Expected: table `Statistic`, `Value (%)`, `Target (%)`, `Result` with the rows `Gross Se`
    and `Gross +P`, target `≥ 99.50`, the result decided on the exact counts.
    """
    _, start = _sections(_text(_results(_standard_quality(), _start(counts))), parse_report)
    table = start.section("Targets").tables()[0]

    assert table.header == ("Statistic", "Value (%)", "Target (%)", "Result")
    assert table.first_cells() == ["Gross Se", "Gross +P"]
    assert table.row("Gross Se") == ("Gross Se", se, "≥ 99.50", se_result)
    assert table.row("Gross +P") == ("Gross +P", ppv, "≥ 99.50", ppv_result)


@pytest.mark.requirement("SRS-030")
def test_start_section_does_not_use_the_counts_of_the_main_evaluation(
    parse_report: Callable[[str], Any],
) -> None:
    """The statistics of section 9 are those of the start-of-stream results.

    Input: main evaluation of 4 records with 100 TP, 1 FN, 1 FP each; start-of-stream counts
    of 100 (2000, 5, 20), 118 (1990, 10, 0), 207 (0, 0, 0).
    Expected: section 9 lists the records 100, 118 and 207 (not 119) with their own counts.
    """
    _, start = _sections(
        _text(_results(_standard_quality(), _start(START_COUNTS_PASS))), parse_report
    )
    table = start.section("Results per record").tables()[0]

    assert "119" not in table.first_cells()
    assert table.row("100")[3:6] == ("2000", "5", "20")


@pytest.mark.requirement("SRS-030")
def test_rendering_is_deterministic() -> None:
    """The same results give the same text, byte for byte.

    Input: the same hand-built results rendered twice, and an equal copy of them.
    Expected: three identical texts.
    """
    results = _results(_standard_quality(), _start(START_COUNTS_PASS))
    copy = _results(_standard_quality(), _start(START_COUNTS_PASS))

    assert _text(results) == _text(results) == _text(copy)


# --------------------------------------------------------------------------------------------
# The whole run on fixture databases, with stage doubles of known output
# --------------------------------------------------------------------------------------------

FS = 360
BLOCK = 360
WINDOW = 3600
PADDED = 648000  # the fixture loader pads every second load of a record to 30:00
FIVE_MINUTES = 108000


def _quality_double(signal_mv: Any, fs_hz: float, mains_hz: int) -> QualityWindows:
    """Windows of 10 s every second; the index of the window that starts at second t of a
    signal with m samples above 0.5 mV is ((t + m) mod 10) / 10, usable from 0.5."""
    signal = np.asarray(signal_mv, dtype=np.float64)
    n_spikes = int(np.count_nonzero(signal > 0.5))
    first = np.arange(0, signal.size - WINDOW + 1, BLOCK, dtype=np.int64)
    k = (first // BLOCK + n_spikes) % 10
    last = first + WINDOW - 1
    return QualityWindows(
        first=first,
        last=last,
        reported_at=np.minimum(last + 180, signal.size - 1),
        index=k / 10.0,
        usable=k >= 5,
        held=np.zeros(first.size, dtype=bool),
        n_detections=np.zeros(first.size, dtype=np.int64),
        signal_power=np.full(first.size, np.nan),
        background_power=np.full(first.size, np.nan),
    )


def _expected_windows(n_samples: int, n_spikes: int) -> list[tuple[int, int, int]]:
    """(first, last, k) of the windows of the double for a signal, written independently."""
    return [
        (f, f + WINDOW - 1, (f // BLOCK + n_spikes) % 10)
        for f in range(0, n_samples - WINDOW + 1, BLOCK)
    ]


def _stretches(n_samples: int) -> list[tuple[int, int]]:
    """Noisy stretches of SRS-029 / design 13.7.1: 5:00 + 4 min * i, 2 min long."""
    out = []
    i = 0
    while round((300 + 240 * i) * FS) < n_samples:
        out.append(
            (round((300 + 240 * i) * FS), min(round((420 + 240 * i) * FS) - 1, n_samples - 1))
        )
        i += 1
    return out


def _summarise(windows: list[tuple[int, int, int]]) -> tuple[int, int, str]:
    """(windows, usable, median index text) of windows (k/10 as the index)."""
    if not windows:
        return 0, 0, "not defined"
    return (
        len(windows),
        sum(1 for _, _, k in windows if k >= 5),
        f"{statistics.median([k / 10.0 for _, _, k in windows]):.4f}",
    )


@dataclass(frozen=True)
class FullRun:
    results: ValidationResults
    text: str
    written: str
    fixture: Any


@pytest.fixture(scope="module")
def full_run(
    evaluation_fixture_without_episodes: Any,
    make_spike_detector: Callable[[], Any],
    network_forbidden: Callable[[], Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> FullRun:
    """`run_validation` and `write_validation_report` on the fixture without episodes.

    Records 100, 118 and 119 (7 min, a beat every 360 samples, 119 every 324 with one false
    detection), the 12 noise stress records (7 min) and the 3 noise records (1 min).
    """
    fixture = evaluation_fixture_without_episodes
    mitdb = Database(
        slug="mitdb",
        version="1.0.0",
        title=MITDB_TITLE,
        checksum_list_sha256=fixture.mitdb.checksum_list_sha256,
        licence=fixture.mitdb.licence,
    )
    nstdb = Database(
        slug="nstdb",
        version="1.0.0",
        title=NSTDB_TITLE,
        checksum_list_sha256=fixture.nstdb.checksum_list_sha256,
        licence=fixture.nstdb.licence,
    )

    def stages(detector: Any) -> dict[str, Any]:
        return {**detector.stages(), "quality": _quality_double}

    output = tmp_path_factory.mktemp("srs030") / "qrs-ec57-report.md"
    with network_forbidden():
        first = make_spike_detector()
        write_validation_report(
            output,
            fixture.data_root,
            mitdb=mitdb,
            nstdb=nstdb,
            detector=first,
            fetch=None,
            **stages(first),
        )
        second = make_spike_detector()
        results = run_validation(
            fixture.data_root,
            mitdb=mitdb,
            nstdb=nstdb,
            detector=second,
            fetch=None,
            **stages(second),
        )
    return FullRun(
        results=results,
        text=render_full_report(results),
        written=output.read_bytes().decode("utf-8"),
        fixture=fixture,
    )


@pytest.mark.requirement("SRS-030")
def test_run_gives_the_same_report_twice(full_run: FullRun) -> None:
    """Two evaluations of the same data give the same file, byte for byte.

    Input: the report file written by one run and the text rendered from the results of a
    second run.
    Expected: identical text, which contains both new sections.
    """
    assert full_run.written == full_run.text
    assert "## Signal quality index" in full_run.text
    assert "## Start of stream" in full_run.text
    assert full_run.results.quality is not None
    assert full_run.results.start_of_stream is not None


@pytest.mark.requirement("SRS-030")
def test_run_quality_figures_per_snr_clean_and_noise_records(
    full_run: FullRun,
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
) -> None:
    """Windows, median and share usable of each group, from the windows of the double.

    Input: quality double with index ((second + spikes in the record) mod 10) / 10; noise
    stress records of 30:00 (loaded padded), records 118 and 119 of 30:00, noise records of
    1:00.
    Expected: per SNR the windows lying entirely in the seven noisy stretches of the two
    records at that SNR; for 118 and 119 together the windows from 5:00; for bw, em and ma
    every window (51 each); counts, medians (four decimals) and shares as worked out here.
    """
    nstdb = full_run.fixture.nstdb.records
    mitdb = full_run.fixture.mitdb.records
    quality, _ = _sections(full_run.text, parse_report)
    table = quality.section("Noise stress records").tables()[0]
    tags = ("24", "18", "12", "06", "00", "_6")

    stretches = _stretches(PADDED)
    assert len(stretches) == 7
    for snr, tag in zip(SNRS, tags, strict=True):
        selected = []
        for record in (f"118e{tag}", f"119e{tag}"):
            windows = _expected_windows(PADDED, len(nstdb[record].spikes_0))
            selected += [w for w in windows if any(w[0] >= a and w[1] <= b for a, b in stretches)]
        n, usable, median = _summarise(selected)
        assert table.row(f"{snr} dB") == (
            f"{snr} dB",
            str(n),
            median,
            percent_text(usable, n),
        ), snr

    clean = []
    for record in ("118", "119"):
        clean += [
            w
            for w in _expected_windows(PADDED, len(mitdb[record].spikes_0))
            if w[0] >= FIVE_MINUTES
        ]
    n, usable, median = _summarise(clean)
    label = "records 118 and 119, no added noise, from 5:00"
    assert table.row(label) == (label, str(n), median, percent_text(usable, n))

    for name in NOISE_NAMES:
        n, usable, median = _summarise(_expected_windows(21600, 0))
        assert n == 51
        assert table.row(f"noise record {name}") == (
            f"noise record {name}",
            "51",
            median,
            percent_text(usable, 51),
        )


@pytest.mark.requirement("SRS-030")
def test_run_quality_per_record_with_false_detections_in_not_usable_windows(
    full_run: FullRun,
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
) -> None:
    """The share usable from 5:00 of each record, with its FN and FP in not usable windows.

    Input: records 100 and 118 (no error) and 119 (one false detection halfway between two
    beats, at 108234); the double marks a window usable when ((second + spikes) mod 10) >=
    5. The false detection lies in 10 or 11 windows, so at least one of them is not usable
    and the false positive counts (once).
    Expected: rows for the three records and `Total`, windows from 5:00 (1491 each), shares
    from the integer counts, 0 FN and FP for 100 and 118, FP 1 for 119, FN 0.
    """
    mitdb = full_run.fixture.mitdb.records
    quality, _ = _sections(full_run.text, parse_report)
    table = quality.section(f"Records of the {MITDB_TITLE}").tables()[0]
    by_name = {r.record: r for r in full_run.results.records}

    assert table.first_cells() == ["100", "118", "119", "Total"]
    total_n = total_u = total_fn = total_fp = 0
    for name in ("100", "118", "119"):
        windows = _expected_windows(PADDED, len(mitdb[name].spikes_0))
        scored = [w for w in windows if w[0] >= FIVE_MINUTES]
        n, usable, _ = _summarise(scored)
        fn_samples = by_name[name].false_negatives
        fp_samples = by_name[name].false_positives
        assert len(fn_samples) == mitdb[name].fn
        assert len(fp_samples) == mitdb[name].fp
        not_usable = [w for w in windows if w[2] < 5]
        fn = sum(1 for s in fn_samples if any(a <= s <= b for a, b, _ in not_usable))
        fp = sum(1 for s in fp_samples if any(a <= s <= b for a, b, _ in not_usable))
        assert table.row(name) == (name, str(n), percent_text(usable, n), str(fn), str(fp))
        total_n, total_u, total_fn, total_fp = (
            total_n + n,
            total_u + usable,
            total_fn + fn,
            total_fp + fp,
        )
    assert table.row("119")[4] == "1"
    assert table.row("Total") == (
        "Total",
        str(total_n),
        percent_text(total_u, total_n),
        str(total_fn),
        str(total_fp),
    )


@pytest.mark.requirement("SRS-030")
def test_run_criteria_are_decided_on_the_figures_of_the_run(
    full_run: FullRun, parse_report: Callable[[str], Any], percent_text: Callable[[int, int], str]
) -> None:
    """Each criterion of SRS-029 with the value of the run and the result worked out here.

    Input: the windows of the double for the fixture records.
    Expected: every row of the criteria table has the label, the share or medians, the limit
    and the result that follow from the counts with the limits 95, 90, 20 and 10 percent and
    the order of the medians, computed with integers.
    """
    nstdb = full_run.fixture.nstdb.records
    mitdb = full_run.fixture.mitdb.records
    tags = ("24", "18", "12", "06", "00", "_6")
    stretches = _stretches(PADDED)
    snr_windows: dict[int, list[tuple[int, int, int]]] = {}
    for snr, tag in zip(SNRS, tags, strict=True):
        selected: list[tuple[int, int, int]] = []
        for record in (f"118e{tag}", f"119e{tag}"):
            selected += [
                w
                for w in _expected_windows(PADDED, len(nstdb[record].spikes_0))
                if any(w[0] >= a and w[1] <= b for a, b in stretches)
            ]
        snr_windows[snr] = selected
    clean = [
        w
        for record in ("118", "119")
        for w in _expected_windows(PADDED, len(mitdb[record].spikes_0))
        if w[0] >= FIVE_MINUTES
    ]
    noise = _expected_windows(21600, 0)
    medians = [statistics.median([k / 10.0 for _, _, k in snr_windows[s]]) for s in SNRS]

    def share(windows: list[tuple[int, int, int]]) -> tuple[int, int]:
        return len(windows), sum(1 for _, _, k in windows if k >= 5)

    expected_value = [
        ", ".join(f"{m:.4f}" for m in medians),
        f"{medians[5]:.4f}, {medians[0]:.4f}",
        percent_text(share(clean)[1], share(clean)[0]),
        *(percent_text(share(snr_windows[s])[1], share(snr_windows[s])[0]) for s in (24, 18)),
        *(percent_text(share(snr_windows[s])[1], share(snr_windows[s])[0]) for s in (6, 0, -6)),
        *(percent_text(share(noise)[1], share(noise)[0]) for _ in NOISE_NAMES),
    ]
    n_clean, u_clean = share(clean)
    n_noise, u_noise = share(noise)
    ok = [
        all(a >= b for a, b in zip(medians, medians[1:], strict=False)),
        medians[5] < medians[0],
        100 * u_clean >= 95 * n_clean,
        *(100 * share(snr_windows[s])[1] >= 90 * share(snr_windows[s])[0] for s in (24, 18)),
        *(100 * share(snr_windows[s])[1] <= 20 * share(snr_windows[s])[0] for s in (6, 0, -6)),
        *(100 * u_noise <= 10 * n_noise for _ in NOISE_NAMES),
    ]
    quality, _ = _sections(full_run.text, parse_report)
    rows = {r[0]: r for r in quality.section("Criteria").tables()[0].rows}

    assert list(rows) == list(CRITERION_LABELS)
    for label, value, required, passed in zip(
        CRITERION_LABELS, expected_value, CRITERION_REQUIRED, ok, strict=True
    ):
        assert rows[label] == (label, value, required, "pass" if passed else "fail"), label


def _expected_start_counts(record: Any) -> tuple[int, int, int]:
    """TP, FN, FP over the 30 segments of 60 s of a fixture record with spikes 3 samples
    after the beats, a start-up period of 2 s (720 samples) and a match window of 54."""
    segment = 21600
    startup = 720
    tp = fn = fp = 0
    beats = [b for b in record.beats]
    spikes = list(record.spikes_0)
    for j in range(30):
        s0 = j * segment
        ref = [b - s0 for b in beats if s0 <= b < s0 + segment and b - s0 >= startup]
        det = [d - s0 for d in spikes if s0 <= d < s0 + segment and d - s0 >= startup]
        matched = 0
        free = list(det)
        for b in ref:
            near = [d for d in free if abs(d - b) <= 54]
            if near:
                free.remove(min(near, key=lambda d: abs(d - b)))
                matched += 1
        tp += matched
        fn += len(ref) - matched
        fp += len(free)
    return tp, fn, fp


@pytest.mark.requirement("SRS-030")
def test_run_start_of_stream_counts_and_targets(
    full_run: FullRun,
    parse_report: Callable[[str], Any],
    percent_text: Callable[[int, int], str],
) -> None:
    """The counts of 30 segments of 60 s per record and the gross values against the target.

    Input: records 100 and 118 (beats every 360 samples, a detection 3 samples after each),
    119 (beats every 324, one false detection at 108234); every segment starts at a multiple
    of 21600 samples, the first 720 samples of each segment are not scored; the records are
    7 min long (loaded padded with zeros to 30:00), so only the first 7 segments hold beats.
    Expected: 30 segments per record; TP/FN/FP worked out here (100 and 118: 7 * 58 = 406 TP,
    no error; 119: from the beats and detections in each segment, the false detection falls in
    the start-up period of its segment); gross values from the summed counts; `Segments per
    record` 30; the starts 0:00 to 29:00.
    """
    mitdb = full_run.fixture.mitdb.records
    _, start = _sections(full_run.text, parse_report)
    table = start.section("Results per record").tables()[0]
    items = start.section("Start of stream").tables()[0]
    expected = {name: _expected_start_counts(mitdb[name]) for name in ("100", "118", "119")}

    assert expected["100"] == (406, 0, 0)
    assert expected["118"] == (406, 0, 0)
    assert items.row("Segments per record")[1] == "30"
    assert items.row("Segments")[1].endswith("28:00, 29:00")
    assert table.first_cells() == ["100", "118", "119", "Gross", "Average"]
    for name, (tp, fn, fp) in expected.items():
        assert table.row(name)[2:6] == ("30", str(tp), str(fn), str(fp)), name
        assert table.row(name)[6:] == (percent_text(tp, tp + fn), percent_text(tp, tp + fp))
    tp, fn, fp = (sum(c[i] for c in expected.values()) for i in range(3))
    assert table.row("Gross")[2:] == (
        "90",
        str(tp),
        str(fn),
        str(fp),
        percent_text(tp, tp + fn),
        percent_text(tp, tp + fp),
    )
    targets = start.section("Targets").tables()[0]
    se_pass = 10000 * tp >= 9950 * (tp + fn)
    ppv_pass = 10000 * tp >= 9950 * (tp + fp)
    assert targets.row("Gross Se")[1:] == (
        percent_text(tp, tp + fn),
        "≥ 99.50",
        "pass" if se_pass else "fail",
    )
    assert targets.row("Gross +P")[1:] == (
        percent_text(tp, tp + fp),
        "≥ 99.50",
        "pass" if ppv_pass else "fail",
    )
