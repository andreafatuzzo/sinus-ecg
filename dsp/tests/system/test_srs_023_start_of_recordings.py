"""System verification of SRS-023: detection at the start of real recordings.

The segments, the reference beats and the episodes are rebuilt here from the requirement text
and the database files, not taken from ``evaluate_start_of_stream``: the first stored signal of
each record is read with wfdb, the 30 segments of 60 s are cut at 0:00, 1:00, ... 29:00, each
is processed on its own by the reference (``detect_marked``, mains 60 Hz, SRS-007) together
with its continuation on the record, the 2876 samples of the maximum delay of a detection at
360 Hz (architecture-m2 13.4, row "Search-back": G + N + D + 1 - R), or to the end of the
record if that comes first. Only the detections marked reliable whose index lies in the
segment are kept (the continuation is not scored), and they are scored with the documented
matching of SRS-008 (``match_beats``) with the start-up period of the first 2 s in place of
5 minutes.
The reference beats and the flutter and fibrillation episodes are counted here from the
annotation file and clipped to each segment. The gross values are compared with the targets
exactly, and with the figures of the generated validation report, section "Start of stream".

Needs the verified local MIT-BIH Arrhythmia Database (``data/mitdb``); skipped in CI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
import wfdb

from sinus_dsp.evaluation.matching import Episode, match_beats
from sinus_dsp.pipeline import detect_marked

ROOT = Path(__file__).resolve().parents[3]
MITDB_DIR = ROOT / "data" / "mitdb"
REPORT = ROOT / "docs" / "validation" / "qrs-ec57-report.md"

MITDB_RECORDS = (
    "100", "101", "102", "103", "104", "105", "106", "107", "108", "109",
    "111", "112", "113", "114", "115", "116", "117", "118", "119",
    "121", "122", "123", "124",
    "200", "201", "202", "203", "205", "207", "208", "209", "210",
    "212", "213", "214", "215", "217", "219",
    "220", "221", "222", "223", "228", "230", "231", "232", "233", "234",
)  # fmt: skip

MAINS_HZ = 60  # SRS-007
FS = 360
SEGMENT = 60 * FS  # SRS-023: segments of 60 s
STARTS_S = tuple(range(0, 30 * 60, 60))  # 0:00 and every whole minute to 29:00
CONTINUATION = 2876  # SRS-023 / SRS-021: maximum delay of a detection at 360 Hz
STARTUP = 2 * FS  # SRS-022: the first 2 s of the segment
MATCH_WINDOW = 54  # SRS-008: 150 ms at 360 Hz
TARGET = Fraction(995, 1000)
BEAT_CODES = frozenset("N L R B A a J S V r F e j n E / f Q ?".split())


@dataclass
class Counts:
    tp: int = 0
    fn: int = 0
    fp: int = 0
    n_segments: int = 0
    short_continuations: int = 0
    detections_startup: int = 0
    detections_reliable: int = 0


@dataclass
class Outcome:
    counts: dict[str, Counts]
    #: (record, segment start s, false negative sample relative to the segment)
    false_negatives: list[tuple[str, int, int]]
    false_positives: list[tuple[str, int, int]]


def _episodes(symbols: list[str], samples: list[int], n_samples: int) -> list[tuple[int, int]]:
    episodes: list[tuple[int, int]] = []
    onset: int | None = None
    for sample, symbol in zip(samples, symbols, strict=True):
        if symbol == "[" and onset is None:
            onset = sample
        elif symbol == "]" and onset is not None:
            episodes.append((onset, sample))
            onset = None
    if onset is not None:
        episodes.append((onset, max(onset, n_samples - 1)))
    return episodes


@pytest.fixture(scope="module")
def outcome() -> Outcome:
    result = Outcome({}, [], [])
    for name in MITDB_RECORDS:
        path = str(MITDB_DIR / name)
        record = wfdb.rdrecord(path, channels=[0], physical=True)
        assert record.fs == FS
        signal = np.ascontiguousarray(record.p_signal[:, 0], dtype=np.float64)
        n_samples = len(signal)
        annotation = wfdb.rdann(path, "atr")
        samples = [int(s) for s in annotation.sample]
        symbols = [str(s) for s in annotation.symbol]
        beats = np.array(
            [s for s, c in zip(samples, symbols, strict=True) if c in BEAT_CODES], dtype=np.int64
        )
        episodes = _episodes(symbols, samples, n_samples)
        counts = Counts()
        for start_s in STARTS_S:
            s0 = start_s * FS
            s1 = s0 + SEGMENT  # exclusive
            assert s1 <= n_samples
            cont = min(CONTINUATION, n_samples - s1)
            detections = detect_marked(signal[s0 : s1 + cont], float(FS), MAINS_HZ)
            in_segment = detections.indices < SEGMENT
            reliable = detections.indices[~detections.startup & in_segment]
            counts.short_continuations += int(cont < CONTINUATION)
            reference = beats[(beats >= s0) & (beats < s1)] - s0
            clipped = tuple(
                Episode(max(a, s0) - s0, min(b, s1 - 1) - s0)
                for a, b in episodes
                if a <= s1 - 1 and b >= s0
            )
            m = match_beats(
                reference,
                reliable,
                window_samples=MATCH_WINDOW,
                start_sample=STARTUP,
                vf=clipped,
            )
            counts.tp += m.tp
            counts.fn += m.fn
            counts.fp += m.fp
            counts.n_segments += 1
            counts.detections_startup += int((detections.startup & in_segment).sum())
            counts.detections_reliable += len(reliable)
            result.false_negatives += [(name, start_s, int(x)) for x in m.false_negatives]
            result.false_positives += [(name, start_s, int(x)) for x in m.false_positives]
        result.counts[name] = counts
    return result


def _gross(outcome: Outcome) -> tuple[int, int, int]:
    return (
        sum(c.tp for c in outcome.counts.values()),
        sum(c.fn for c in outcome.counts.values()),
        sum(c.fp for c in outcome.counts.values()),
    )


@pytest.mark.requirement("SRS-023")
@pytest.mark.needs_data
def test_segments_are_the_1440_of_the_requirement(outcome: Outcome) -> None:
    assert len(STARTS_S) == 30 and STARTS_S[0] == 0 and STARTS_S[-1] == 29 * 60
    assert set(outcome.counts) == set(MITDB_RECORDS) and len(MITDB_RECORDS) == 48
    assert all(c.n_segments == 30 for c in outcome.counts.values())
    assert sum(c.n_segments for c in outcome.counts.values()) == 1440
    # Only reliable detections are scored, and start-up detections do occur.
    assert sum(c.detections_startup for c in outcome.counts.values()) > 0
    tp, _, fp = _gross(outcome)
    assert sum(c.detections_reliable for c in outcome.counts.values()) >= tp + fp - 1


@pytest.mark.requirement("SRS-023")
@pytest.mark.needs_data
def test_continuation_and_short_continuations(outcome: Outcome) -> None:
    # Only the last segment (29:00 to 30:00) of each record is followed by fewer than 2876
    # samples (650000 - 649... = 2000 left): 48 in all.
    assert all(c.short_continuations == 1 for c in outcome.counts.values())
    text = REPORT.read_text(encoding="utf-8").split("## Start of stream", 1)[1]
    assert re.search(r"\| Continuation after each segment \| 2876 samples", text)
    assert re.search(r"\| Segments with a shorter continuation \| 48 \|", text)


@pytest.mark.requirement("SRS-023")
@pytest.mark.needs_data
def test_gross_sensitivity_at_least_99_5_percent(outcome: Outcome) -> None:
    tp, fn, _ = _gross(outcome)
    assert tp + fn > 0
    assert Fraction(tp, tp + fn) >= TARGET, (
        f"gross Se {100 * tp / (tp + fn):.4f} % (TP {tp}, FN {fn}), target 99.5 %; "
        f"FN allowed {(tp + fn) // 200}"
    )


@pytest.mark.requirement("SRS-023")
@pytest.mark.needs_data
def test_gross_positive_predictivity_at_least_99_5_percent(outcome: Outcome) -> None:
    tp, _, fp = _gross(outcome)
    assert tp + fp > 0
    assert Fraction(tp, tp + fp) >= TARGET, (
        f"gross +P {100 * tp / (tp + fp):.4f} % (TP {tp}, FP {fp}), target 99.5 %"
    )


def _report_rows() -> dict[str, tuple[int, int, int, int]]:
    """Section "Start of stream", results per record: name -> (segments, TP, FN, FP)."""
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("\n## Start of stream\n", 1)[1]
    section = section.split("### Results per record\n", 1)[1].split("\n### ", 1)[0]
    rows: dict[str, tuple[int, int, int, int]] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 8 and (cells[0].isdigit() or cells[0] == "Gross"):
            rows[cells[0]] = (int(cells[2]), int(cells[3]), int(cells[4]), int(cells[5]))
    return rows


@pytest.mark.requirement("SRS-023")
@pytest.mark.needs_data
def test_report_states_the_same_figures(outcome: Outcome) -> None:
    rows = _report_rows()
    assert set(rows) == set(MITDB_RECORDS) | {"Gross"}
    for name, c in outcome.counts.items():
        assert rows[name] == (c.n_segments, c.tp, c.fn, c.fp), name
    tp, fn, fp = _gross(outcome)
    assert rows["Gross"] == (1440, tp, fn, fp)
    section = REPORT.read_text(encoding="utf-8").split("## Start of stream", 1)[1]
    se_result = "pass" if Fraction(tp, tp + fn) >= TARGET else "fail"
    pp_result = "pass" if Fraction(tp, tp + fp) >= TARGET else "fail"
    se_row = rf"\| Gross Se \| {100 * tp / (tp + fn):.2f} \| ≥ 99\.50 \| {se_result} \|"
    pp_row = rf"\| Gross \+P \| {100 * tp / (tp + fp):.2f} \| ≥ 99\.50 \| {pp_result} \|"
    assert re.search(se_row, section)
    assert re.search(pp_row, section)
