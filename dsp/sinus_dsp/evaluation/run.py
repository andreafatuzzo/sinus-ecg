"""Detection and evaluation on a set of records, and the validation run (architecture §8.10).

The run verifies the reference databases, runs the QRS detection with fixed settings on every
record, matches the detections to the reference beats (SRS-008), and keeps the counts and the
figures on what was not scored (SRS-012). The report itself is rendered by
:mod:`sinus_dsp.evaluation.report`.

Import order: :mod:`sinus_dsp.evaluation.noise_stress` imports the types of this module, and
:mod:`sinus_dsp.evaluation.report` imports both. This module therefore imports
``NoiseStressResults`` only for type checking, and imports the two functions it calls from
those modules inside the functions that call them.
"""

from __future__ import annotations

import numbers
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sinus_dsp._files import write_atomically
from sinus_dsp._types import FloatArray, IndexArray
from sinus_dsp.data.physionet import (
    MITDB,
    NSTDB,
    Database,
    FetchFunction,
    VerificationResult,
    download_database,
    fetch_https,
    verify_database,
)
from sinus_dsp.data.records import Annotation, Record, load_record
from sinus_dsp.errors import InvalidInputError, MalformedFileError
from sinus_dsp.evaluation.matching import (
    Episode,
    learning_period_samples,
    match_beats,
    match_window_samples,
    vf_episodes,
)
from sinus_dsp.evaluation.metrics import RecordCounts
from sinus_dsp.pipeline import detect_beats
from sinus_dsp.version import SoftwareIdentity, software_identity

if TYPE_CHECKING:
    from sinus_dsp.evaluation.noise_stress import NoiseStressResults

#: (signal_mv, fs_hz, mains_hz) -> sample indices of the detected beats.
Detector = Callable[[FloatArray, float, int], IndexArray]

#: (record path without extension, channel) -> the loaded record.
RecordLoader = Callable[[Path, int], Record]

#: SRS-007: the target of 99.50 %, for the gross Se and the gross +P, in hundredths of a
#: percent, so that the comparison is exact on integers.
TARGET_HUNDREDTHS_OF_PERCENT: Final = 9950

#: Name of the file that lists the records of a database, one per line.
RECORD_LIST_NAME: Final = "RECORDS"

_FLUTTER_WAVE: Final = "!"
# The record-name rule of architecture §8.3: a name is used as a file name in the database
# folder.
_RECORD_NAME: Final = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class EvaluationSettings:
    """Settings of the detection in an evaluation.

    SRS-007: the first stored signal of each record (channel 0) and the mains interference
    filter set to 60 Hz, since the MIT-BIH databases were recorded on 60 Hz mains.

    Attributes:
        channel: Channel of each record given to the detection; channel 0 is the first
            stored signal.
        mains_hz: Setting of the mains interference filter, in Hz.
    """

    channel: int = 0
    mains_hz: int = 60


#: The settings of SRS-007, ``EvaluationSettings()``: the default of every ``settings``
#: argument. An argument default is never a call; the instance is frozen, so sharing it is
#: safe (architecture §8.2, argument defaults).
DEFAULT_SETTINGS: Final = EvaluationSettings()


@dataclass(frozen=True)
class RecordEvaluation:
    """Evaluation of one record (SRS-011, SRS-012).

    The figures on what is not scored cover the scored part of the record, from 5:00 to its
    end (architecture §8.8.1, §8.8.3), except ``vf_episodes``, which covers the whole record.

    Attributes:
        record: Name of the record.
        signal_name: Name of the signal evaluated, e.g. ``MLII``.
        fs_hz: Sampling frequency of the record, in Hz.
        counts: TP, FN and FP of the matching.
        vf_episodes: Ventricular flutter and fibrillation episodes annotated in the record.
        vf_episodes_scored: Of those, the episodes with at least one sample in the scored
            part.
        vf_samples_scored: Samples of the scored part that lie inside an episode.
        reference_excluded: Reference beats at or after 5:00 inside an episode.
        detections_excluded: Detections at or after 5:00 inside an episode and not paired.
        flutter_waves_outside_vf: ``!`` annotations from 5:00 outside every episode.
    """

    record: str
    signal_name: str
    fs_hz: float
    counts: RecordCounts
    vf_episodes: int
    vf_episodes_scored: int
    vf_samples_scored: int
    reference_excluded: int
    detections_excluded: int
    flutter_waves_outside_vf: int


@dataclass(frozen=True)
class ValidationResults:
    """Everything a validation report states (SRS-012, SRS-014).

    SRS-016: the results of the subset check have ``subset`` true and no noise stress test;
    the subset report states them.

    Attributes:
        software: Identity of the software that produced the results: package version,
            source digest, and the versions of Python and of the runtime SOUP
            (:func:`~sinus_dsp.version.software_identity`).
        settings: Settings of the detection.
        mitdb: Outcome of the verification of the MIT-BIH Arrhythmia Database.
        records: Evaluation of each record, sorted by record name.
        noise_stress: Results of the noise stress test, or ``None`` in the subset report.
        subset: Whether the results cover a subset of the records.
    """

    software: SoftwareIdentity
    settings: EvaluationSettings
    mitdb: VerificationResult
    records: tuple[RecordEvaluation, ...]
    noise_stress: NoiseStressResults | None
    subset: bool


def read_record_list(database_dir: Path) -> tuple[str, ...]:
    """Return the record names listed in the ``RECORDS`` file of a database.

    SRS-009: the evaluation covers every record that the database lists. The file
    holds one name per line; blank lines are ignored, and so are the spaces around a name.
    Lines end with a line feed; a carriage return before it is not part of the line.

    Args:
        database_dir: Folder of the database, e.g. ``data/mitdb``.

    Returns:
        The names, sorted in code-point order.

    Raises:
        MalformedFileError: If the file is not UTF-8 text, if a name is not a valid record
            name (``[A-Za-z0-9_]+``) or is listed twice (with its 1-based line number), or if
            the file lists no record.
        OSError: If the file cannot be read.
    """
    path = Path(database_dir) / RECORD_LIST_NAME
    source = str(path)
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise MalformedFileError(source, None, "not UTF-8 text") from error
    names: set[str] = set()
    for number, raw_line in enumerate(text.split("\n"), start=1):
        name = raw_line.removesuffix("\r").strip()
        if not name:
            continue
        if _RECORD_NAME.fullmatch(name) is None:
            raise MalformedFileError(source, number, f"invalid record name: {name!r}")
        if name in names:
            raise MalformedFileError(source, number, f"record listed twice: {name}")
        names.add(name)
    if not names:
        raise MalformedFileError(source, None, "the record list has no record")
    return tuple(sorted(names))


def episode_coverage(
    episodes: Sequence[Episode], first_sample: int, last_sample: int
) -> tuple[int, int]:
    """Return how many episodes reach a range of samples, and how many samples they cover.

    SRS-012: with the range ``S … n - 1`` (the scored part of a record), the number of
    episodes that reach 5:00 or later and their duration from 5:00, the samples of the onset
    and offset annotations included. An episode that contains ``first_sample`` counts from
    it; an episode that ends before it counts in neither figure.

    The episodes are taken in the order that :func:`~sinus_dsp.evaluation.matching.vf_episodes`
    returns them. With ``covered_to = first_sample - 1``, for each episode:
    ``hi = min(end_sample, last_sample)``; the episode is counted if
    ``max(start_sample, first_sample) <= hi``; then, with
    ``lo = max(start_sample, covered_to + 1)``, if ``hi >= lo`` the samples ``lo … hi`` are
    added and ``covered_to = hi``. A sample shared by two consecutive episodes is counted
    once. An empty range (``last_sample < first_sample``) gives ``(0, 0)``.

    Args:
        episodes: The episodes, in the order of their onsets.
        first_sample: First sample of the range.
        last_sample: Last sample of the range, inclusive.

    Returns:
        ``(episodes, samples)``: the number of episodes with at least one sample in the
        range, and the number of samples of the range that lie inside at least one episode.
    """
    count = 0
    samples = 0
    covered_to = first_sample - 1
    for episode in episodes:
        hi = min(episode.end_sample, last_sample)
        if max(episode.start_sample, first_sample) <= hi:
            count += 1
        lo = max(episode.start_sample, covered_to + 1)
        if hi >= lo:
            samples += hi - lo + 1
            covered_to = hi
    return count, samples


def evaluate_record(
    record: Record, settings: EvaluationSettings, detector: Detector = detect_beats
) -> RecordEvaluation:
    """Detect the beats of one record and match them to its reference beats.

    SRS-008, SRS-011: the detections are matched to the reference beats with the parameters
    of the record's sampling frequency (a match window of 150 ms, 5:00 not scored, the
    ventricular flutter and fibrillation episodes of the record not scored), which gives the
    counts. SRS-012: the figures on what was not scored, with ``S`` the first scored sample
    and ``n`` the number of samples: every episode annotated in the record; the episodes
    with at least one sample in ``S … n - 1`` and the samples of that range inside an
    episode (:func:`episode_coverage`); and the reference beats and the unpaired detections
    at or after ``S`` inside an episode (from the matching). The ``!`` annotations are
    counted over the same range ``S … n - 1``, outside every episode (architecture §8.8):
    the only part where a ``!`` can change a count. Only the number of episodes covers the
    whole record.

    Args:
        record: The record, loaded with the channel of ``settings``.
        settings: Settings of the detection.
        detector: Detection function, called once with the signal of the record, its
            sampling frequency and ``settings.mains_hz``.

    Returns:
        The counts and the figures of the record.

    Raises:
        InvalidInputError: If the channel of the record is not the one of ``settings``, or
            if the detector, the episodes or the matching reject their input.
    """
    if record.channel != settings.channel:
        raise InvalidInputError(
            f"record {record.name} holds channel {record.channel}, but the settings name "
            f"channel {settings.channel}"
        )
    fs_hz = record.fs_hz
    n_samples = record.n_samples
    episodes = vf_episodes(record.other_annotations, n_samples)
    start = learning_period_samples(fs_hz)
    window = match_window_samples(fs_hz)
    detections = detector(record.signal_mv, fs_hz, settings.mains_hz)
    result = match_beats(
        record.beat_samples,
        detections,
        window_samples=window,
        start_sample=start,
        vf=episodes,
    )
    episodes_scored, samples_scored = episode_coverage(episodes, start, n_samples - 1)
    return RecordEvaluation(
        record=record.name,
        signal_name=record.signal_name,
        fs_hz=fs_hz,
        counts=RecordCounts(record=record.name, tp=result.tp, fn=result.fn, fp=result.fp),
        vf_episodes=len(episodes),
        vf_episodes_scored=episodes_scored,
        vf_samples_scored=samples_scored,
        reference_excluded=result.reference_excluded,
        detections_excluded=result.detections_excluded,
        flutter_waves_outside_vf=_flutter_waves_outside(
            record.other_annotations, episodes, start, n_samples - 1
        ),
    )


def evaluate_records(
    database_dir: Path,
    records: Sequence[str],
    settings: EvaluationSettings,
    *,
    detector: Detector = detect_beats,
    loader: RecordLoader = load_record,
) -> tuple[RecordEvaluation, ...]:
    """Evaluate records of a database, in the order given.

    SRS-008, SRS-011, SRS-012: each record is loaded with ``loader(database_dir / name,
    settings.channel)`` and evaluated with :func:`evaluate_record`.

    Args:
        database_dir: Folder of the database.
        records: Names of the records, each a valid record name (``[A-Za-z0-9_]+``) given
            once.
        settings: Settings of the detection.
        detector: Detection function.
        loader: Function that loads a record.

    Returns:
        The evaluation of each record, in the order of ``records``.

    Raises:
        InvalidInputError: If ``records`` is a ``str`` in place of a sequence of names, if a
            name is invalid or given twice (before any record is loaded), or if the
            evaluation of a record rejects its input.
    """
    names = _checked_names(records)
    directory = Path(database_dir)
    return tuple(
        evaluate_record(loader(directory / name, settings.channel), settings, detector)
        for name in names
    )


def meets_target(
    tp: int, other: int, target_hundredths: int = TARGET_HUNDREDTHS_OF_PERCENT
) -> bool:
    """Return whether ``100 * tp / (tp + other)`` reaches a target, compared exactly.

    SRS-007: the gross Se (``other`` = FN) and the gross +P (``other`` = FP) are each
    compared with 99.50 % as ``10000 * tp >= target_hundredths * (tp + other)``, on
    integers. A value that is not defined (``tp + other == 0``) does not meet the target.

    Args:
        tp: True positives.
        other: False negatives for Se, false positives for +P.
        target_hundredths: The target in hundredths of a percent, from 0 to 10000.

    Raises:
        InvalidInputError: If a count is negative or is not an integer, or if the target is
            not an integer from 0 to 10000.
    """
    tp_count = _non_negative_integer(tp, "tp")
    other_count = _non_negative_integer(other, "other")
    target = _non_negative_integer(target_hundredths, "target_hundredths")
    if target > 10000:
        raise InvalidInputError(f"target_hundredths is above 10000: {target}")
    total = tp_count + other_count
    if total == 0:
        return False
    return 10000 * tp_count >= target * total


def run_validation(
    data_root: Path,
    *,
    mitdb: Database = MITDB,
    nstdb: Database = NSTDB,
    settings: EvaluationSettings = DEFAULT_SETTINGS,
    detector: Detector = detect_beats,
    loader: RecordLoader = load_record,
    fetch: FetchFunction | None = fetch_https,
) -> ValidationResults:
    """Verify the two databases, then evaluate every record and the noise stress records.

    SRS-007, SRS-009: QRS detection and the evaluation of SRS-008 and SRS-011 on every
    record of the MIT-BIH Arrhythmia Database, with the settings given (by default channel
    0 and 60 Hz). SRS-014: the 12 records of the Noise Stress Test Database are evaluated
    the same way. SRS-012, SRS-014: both databases are verified before anything is
    evaluated, so a failed verification stops the run before any report is rendered.

    1. With ``fetch`` given, each database is obtained and verified with
       :func:`~sinus_dsp.data.physionet.download_database`; with ``fetch=None``, it is only
       verified, without the network.
    2. The records listed in the ``RECORDS`` file of the MIT-BIH Arrhythmia Database are
       evaluated in the order of their names.
    3. The noise stress records are evaluated, and compared with records 118 and 119 of
       step 2.
    4. The identity of the running software is taken once, with
       :func:`~sinus_dsp.version.software_identity`.

    Args:
        data_root: The data folder; each database is in ``data_root / database.slug``.
        mitdb: The MIT-BIH Arrhythmia Database.
        nstdb: The MIT-BIH Noise Stress Test Database.
        settings: Settings of the detection.
        detector: Detection function.
        loader: Function that loads a record.
        fetch: Function that fetches a URL, or ``None`` to verify only.

    Returns:
        The results, with ``subset=False``.

    Raises:
        DataVerificationError: If a database is not verified; nothing is evaluated.
        MalformedFileError: If a checksum list or the record list does not follow its
            format.
        InvalidInputError: If the evaluation of a record rejects its input, or if records
            118 and 119 are not among the evaluated records.
        OSError: If a file of the package cannot be read for its source digest.
    """
    # Called here, not imported at the top: noise_stress imports this module.
    from sinus_dsp.evaluation.noise_stress import evaluate_noise_stress

    root = Path(data_root)
    if fetch is None:
        mitdb_verification = verify_database(mitdb, root)
        nstdb_verification = verify_database(nstdb, root)
    else:
        mitdb_verification = download_database(mitdb, root, fetch=fetch)
        nstdb_verification = download_database(nstdb, root, fetch=fetch)

    mitdb_dir = root / mitdb.slug
    records = evaluate_records(
        mitdb_dir, read_record_list(mitdb_dir), settings, detector=detector, loader=loader
    )
    noise_stress = evaluate_noise_stress(
        root / nstdb.slug,
        records,
        settings,
        nstdb=nstdb_verification,
        detector=detector,
        loader=loader,
    )
    return ValidationResults(
        software=software_identity(),
        settings=settings,
        mitdb=mitdb_verification,
        records=records,
        noise_stress=noise_stress,
        subset=False,
    )


def write_validation_report(
    output_path: Path,
    data_root: Path,
    *,
    mitdb: Database = MITDB,
    nstdb: Database = NSTDB,
    settings: EvaluationSettings = DEFAULT_SETTINGS,
    detector: Detector = detect_beats,
    loader: RecordLoader = load_record,
    fetch: FetchFunction | None = fetch_https,
) -> None:
    """Run the validation and write the full report.

    SRS-009: one call runs the detection and the evaluation on the reference database and
    writes the report; the report is a deterministic function of the verified data, the
    software identity (version, source digest and runtime versions) and the settings.
    SRS-012, SRS-014: the report is written only after the verification of both databases
    and everything else has succeeded.

    The text of :func:`~sinus_dsp.evaluation.report.render_full_report` is written in UTF-8
    with line feeds, atomically: to ``<name>.part~`` in the same folder, then renamed. The
    folder is created if needed.

    Args:
        output_path: Path of the report, e.g. ``docs/validation/qrs-ec57-report.md``.
        data_root: The data folder.
        mitdb: The MIT-BIH Arrhythmia Database.
        nstdb: The MIT-BIH Noise Stress Test Database.
        settings: Settings of the detection.
        detector: Detection function.
        loader: Function that loads a record.
        fetch: Function that fetches a URL, or ``None`` to verify only.

    Raises:
        DataVerificationError: If a database is not verified; nothing is written.
        MalformedFileError: If a checksum list or the record list does not follow its
            format; nothing is written.
        InvalidInputError: As :func:`run_validation`; nothing is written.
    """
    # Called here, not imported at the top: report imports this module.
    from sinus_dsp.evaluation.report import render_full_report

    results = run_validation(
        data_root,
        mitdb=mitdb,
        nstdb=nstdb,
        settings=settings,
        detector=detector,
        loader=loader,
        fetch=fetch,
    )
    write_atomically(Path(output_path), render_full_report(results).encode("utf-8"))


def _checked_names(records: Sequence[str]) -> tuple[str, ...]:
    """Check the names of the records to evaluate and return them in their order."""
    if isinstance(records, str):
        raise InvalidInputError(f"records is a string, not a sequence of record names: {records!r}")
    names = tuple(records)
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or _RECORD_NAME.fullmatch(name) is None:
            raise InvalidInputError(f"invalid record name: {name!r}")
        if name in seen:
            raise InvalidInputError(f"record given twice: {name}")
        seen.add(name)
    return names


def _flutter_waves_outside(
    annotations: Sequence[Annotation],
    episodes: Sequence[Episode],
    first_sample: int,
    last_sample: int,
) -> int:
    """Number of ``!`` annotations from ``first_sample`` to ``last_sample`` outside every episode.

    Both bounds of the range are included, and so are the onset and offset samples of an
    episode: a ``!`` on either is inside the episode. An empty range gives 0.
    """
    return sum(
        1
        for annotation in annotations
        if annotation.symbol == _FLUTTER_WAVE
        and first_sample <= annotation.sample <= last_sample
        and not any(
            episode.start_sample <= annotation.sample <= episode.end_sample for episode in episodes
        )
    )


def _non_negative_integer(value: int, name: str) -> int:
    """Check a count and return it as an ``int``."""
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise InvalidInputError(f"{name} is not an integer: {value!r}")
    number = int(value)
    if number < 0:
        raise InvalidInputError(f"{name} is negative: {number}")
    return number
