"""Subset report for regression checking in continuous integration (architecture §8.11).

SRS-016: six records of the MIT-BIH Arrhythmia Database are obtained (a cached copy is
allowed), each of their files is verified against the pinned checksum list of the database,
and the QRS detection and the EC57 evaluation run on them with the settings of the full
evaluation. The subset report rendered from the results is compared, byte for byte, with the
subset report stored in the repository. A failed verification stops the check before any
report is rendered or written; any difference fails it, and the differences are named.

The stored report states the software identity (architecture §8.14), and the comparison
makes no exception for it: a change of the package, of its version or of a runtime version
changes the stored report, which is updated in the same change.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from sinus_dsp.data.physionet import (
    MITDB,
    Database,
    FetchFunction,
    download_database,
    fetch_https,
    verify_database,
)
from sinus_dsp.data.records import load_record
from sinus_dsp.errors import MalformedFileError, SubsetReportMismatchError
from sinus_dsp.evaluation.report import render_subset_report
from sinus_dsp.evaluation.run import (
    DEFAULT_SETTINGS,
    Detector,
    EvaluationSettings,
    RecordLoader,
    ValidationResults,
    _write_atomically,
    evaluate_records,
)
from sinus_dsp.pipeline import detect_beats
from sinus_dsp.version import software_identity

#: SRS-016: the records of the subset report: a clean recording (100), heavy noise (105),
#: large P and T waves with noise (108), ventricular bigeminy (119), multiform ventricular
#: ectopy with noise (203), and ventricular flutter with bundle branch block (207).
SUBSET_RECORDS: Final = ("100", "105", "108", "119", "203", "207")

# At most this many differences are named; the others are counted.
_MAX_DIFFERENCES: Final = 20

# Line endings, as the differences name them.
_LF: Final = "LF"
_CR_LF: Final = "CR LF"
_NO_LINE_FEED: Final = "none (no final line feed)"


def run_subset(
    data_root: Path,
    *,
    database: Database = MITDB,
    settings: EvaluationSettings = DEFAULT_SETTINGS,
    detector: Detector = detect_beats,
    loader: RecordLoader = load_record,
    fetch: FetchFunction | None = fetch_https,
) -> ValidationResults:
    """Verify the records of the subset, then evaluate them.

    SRS-016: records 100, 105, 108, 119, 203 and 207 (:data:`SUBSET_RECORDS`) are obtained
    and every file that the checksum list publishes under their names is verified, before
    anything is evaluated. The records are then evaluated in the order of their names, with
    the settings given (by default those of the full evaluation, channel 0 and 60 Hz).

    1. With ``fetch`` given, the records are obtained and verified with
       :func:`~sinus_dsp.data.physionet.download_database`, which downloads only what is
       missing or altered (a cached copy is used as it is when it verifies); with
       ``fetch=None``, they are only verified, without the network.
    2. The six records are evaluated with
       :func:`~sinus_dsp.evaluation.run.evaluate_records`.
    3. The identity of the running software is taken once, with
       :func:`~sinus_dsp.version.software_identity`.

    Args:
        data_root: The data folder; the database is in ``data_root / database.slug``.
        database: The MIT-BIH Arrhythmia Database.
        settings: Settings of the detection.
        detector: Detection function.
        loader: Function that loads a record.
        fetch: Function that fetches a URL, or ``None`` to verify only.

    Returns:
        The results, with ``subset=True`` and no noise stress test.

    Raises:
        DataVerificationError: If the checksum list or a file of the six records is missing
            or altered; nothing is evaluated.
        MalformedFileError: If the checksum list does not follow its format.
        InvalidInputError: If the evaluation of a record rejects its input.
        OSError: If a file of the package cannot be read for its source digest.
    """
    root = Path(data_root)
    if fetch is None:
        verification = verify_database(database, root, records=SUBSET_RECORDS)
    else:
        verification = download_database(database, root, records=SUBSET_RECORDS, fetch=fetch)
    records = evaluate_records(
        root / database.slug,
        sorted(SUBSET_RECORDS),
        settings,
        detector=detector,
        loader=loader,
    )
    return ValidationResults(
        software=software_identity(),
        settings=settings,
        mitdb=verification,
        records=records,
        noise_stress=None,
        subset=True,
    )


def compare_reports(stored: bytes, regenerated: str, stored_name: str) -> None:
    """Compare the stored subset report with the regenerated one, byte for byte.

    SRS-016: any difference fails the check and is named. The bytes of the stored report are
    compared with the UTF-8 encoding of the regenerated one. If they differ, both are split
    into lines at line feeds (a carriage return before a line feed ends the line with CR LF;
    a last line without a line feed has no ending), and:

    - each line whose text differs is named as ``line <n>: stored <text>, regenerated
      <text>``, with ``n`` from 1; a line that only one of the two has is named too, with
      ``(no line)`` for the other, and an empty line is written ``(empty line)``;
    - if every line has the same text, each line whose ending differs is named as
      ``line <n>: same text, line ending stored <ending>, regenerated <ending>``, where the
      ending is ``LF``, ``CR LF`` or ``none (no final line feed)``.

    At most 20 differences are named, followed by ``… and <k> more`` for the others.

    Args:
        stored: The bytes of the stored report.
        regenerated: The regenerated report.
        stored_name: Name of the stored report in errors, e.g. its path.

    Raises:
        SubsetReportMismatchError: If the two reports differ; ``differences`` names them.
        MalformedFileError: If the stored report differs and is not UTF-8 text.
    """
    if stored == regenerated.encode("utf-8"):
        return
    try:
        stored_text = stored.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MalformedFileError(stored_name, None, "not UTF-8 text") from error
    stored_lines = _lines(stored_text)
    regenerated_lines = _lines(regenerated)
    differences = _text_differences(stored_lines, regenerated_lines)
    if not differences:
        differences = _ending_differences(stored_lines, regenerated_lines)
    raise SubsetReportMismatchError(_at_most(differences, _MAX_DIFFERENCES))


def check_subset_report(
    stored_path: Path,
    data_root: Path,
    *,
    regenerated_path: Path | None = None,
    database: Database = MITDB,
    settings: EvaluationSettings = DEFAULT_SETTINGS,
    detector: Detector = detect_beats,
    loader: RecordLoader = load_record,
    fetch: FetchFunction | None = fetch_https,
) -> None:
    """Regenerate the subset report and compare it with the stored one.

    SRS-016: the records of the subset are verified and evaluated (:func:`run_subset`); a
    failed verification stops the check before any report is rendered or written. The
    subset report is rendered, written to ``regenerated_path`` if one is given (UTF-8, line
    feeds, written atomically through ``<name>.part~``, the folder created if needed), and
    compared with the stored report (:func:`compare_reports`). A stored report that does not
    exist is one difference.

    With ``regenerated_path`` equal to ``stored_path``, the stored report is replaced by the
    regenerated one, after a successful verification, and the comparison passes: this is how
    the stored report is updated.

    Args:
        stored_path: The stored subset report, e.g. ``docs/validation/qrs-ec57-subset-report.md``.
        data_root: The data folder; the database is in ``data_root / database.slug``.
        regenerated_path: Where to write the regenerated report, or ``None``.
        database: The MIT-BIH Arrhythmia Database.
        settings: Settings of the detection.
        detector: Detection function.
        loader: Function that loads a record.
        fetch: Function that fetches a URL, or ``None`` to verify only.

    Raises:
        DataVerificationError: If the records of the subset are not verified; no report is
            rendered or written.
        SubsetReportMismatchError: If the stored report differs from the regenerated one, or
            does not exist.
        MalformedFileError: If the checksum list does not follow its format, or if the stored
            report differs and is not UTF-8 text.
        InvalidInputError: If the evaluation of a record rejects its input.
        OSError: If the stored report exists but cannot be read.
    """
    results = run_subset(
        data_root,
        database=database,
        settings=settings,
        detector=detector,
        loader=loader,
        fetch=fetch,
    )
    regenerated = render_subset_report(results)
    if regenerated_path is not None:
        _write_atomically(Path(regenerated_path), regenerated.encode("utf-8"))
    stored_file = Path(stored_path)
    try:
        stored = stored_file.read_bytes()
    except FileNotFoundError as error:
        raise SubsetReportMismatchError((f"no stored report: {stored_file}",)) from error
    compare_reports(stored, regenerated, str(stored_file))


def _lines(text: str) -> list[tuple[str, str]]:
    """The lines of a text, each as ``(text, ending)``.

    The text is split at line feeds. A carriage return before a line feed is part of the
    ending (``CR LF``), not of the text; a last line that is not followed by a line feed has
    no ending. A text that ends with a line feed has no empty last line.
    """
    pieces = text.split("\n")
    lines = [
        (piece[:-1], _CR_LF) if piece.endswith("\r") else (piece, _LF) for piece in pieces[:-1]
    ]
    if pieces[-1]:
        lines.append((pieces[-1], _NO_LINE_FEED))
    return lines


def _text_differences(
    stored: Sequence[tuple[str, str]], regenerated: Sequence[tuple[str, str]]
) -> list[str]:
    """One entry per line whose text differs, or that only one of the two texts has."""
    differences: list[str] = []
    for index in range(max(len(stored), len(regenerated))):
        stored_text = stored[index][0] if index < len(stored) else None
        regenerated_text = regenerated[index][0] if index < len(regenerated) else None
        if stored_text != regenerated_text:
            differences.append(
                f"line {index + 1}: stored {_shown(stored_text)}, "
                f"regenerated {_shown(regenerated_text)}"
            )
    return differences


def _ending_differences(
    stored: Sequence[tuple[str, str]], regenerated: Sequence[tuple[str, str]]
) -> list[str]:
    """One entry per line whose ending differs, for two texts with the same lines."""
    return [
        f"line {number}: same text, line ending stored {stored_ending}, "
        f"regenerated {regenerated_ending}"
        for number, ((_, stored_ending), (_, regenerated_ending)) in enumerate(
            zip(stored, regenerated, strict=True), start=1
        )
        if stored_ending != regenerated_ending
    ]


def _shown(text: str | None) -> str:
    """A line as a difference shows it."""
    if text is None:
        return "(no line)"
    return text if text else "(empty line)"


def _at_most(differences: Sequence[str], limit: int) -> tuple[str, ...]:
    """The first ``limit`` differences, then ``… and <k> more`` for the others."""
    if len(differences) <= limit:
        return tuple(differences)
    return (*differences[:limit], f"… and {len(differences) - limit} more")
