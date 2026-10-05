"""Golden vectors: the file format, its writer and readers, and the export (architecture §7, §8.12).

SRS-015: a single command writes one golden-vector file for each input of the set of
architecture §7.2: the 18 synthetic ECGs of :mod:`sinus_dsp.synthetic`, and the first 60 s of
each record of the subset of SRS-016, first stored signal, where the files of these records
are available and verified. Each file holds the input identifier, its sampling frequency, the
mains setting, the software version with the digest of the package source, the input samples
in mV, the output of each conditioning stage in the order applied, and the detected QRS sample
indices, in the text format of architecture §7.3. Floats are written as the shortest decimal
text that reads back to the same binary64 value, so reading a file gives exactly the values
computed. The content depends only on the inputs, the settings, the software identity and the
computations of NumPy and SciPy, so two runs on the same computer write byte-identical files.

The vectors let every other implementation of the conditioning and the detection (the
real-time library of Milestone 2) be compared with this reference on the same inputs.
"""

from __future__ import annotations

import math
import numbers
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt

from sinus_dsp._files import write_atomically
from sinus_dsp._types import FloatArray, IndexArray
from sinus_dsp._units import round_samples
from sinus_dsp.data.physionet import MITDB, Database, VerificationResult, verify_database
from sinus_dsp.data.records import load_record
from sinus_dsp.errors import (
    DataVerificationError,
    InvalidInputError,
    MalformedFileError,
    NonFiniteOutputError,
)
from sinus_dsp.evaluation.run import DEFAULT_SETTINGS, RecordLoader
from sinus_dsp.evaluation.subset import SUBSET_RECORDS
from sinus_dsp.pipeline import STAGES, run_pipeline
from sinus_dsp.synthetic import synthetic_set
from sinus_dsp.version import SoftwareIdentity, software_identity

#: Value of the header key ``format``.
FORMAT_NAME: Final = "sinus-golden-vector"
#: Value of the header key ``format_version``.
FORMAT_VERSION: Final = 1
#: Length of a record segment, in seconds from the first sample of the record.
GOLDEN_SEGMENT_S: Final = 60  # s
#: Suffix of a golden-vector file: ``<input identifier>.golden.txt``.
GOLDEN_FILE_SUFFIX: Final = ".golden.txt"

#: The header keys, in the order of the file.
_HEADER_KEYS: Final = (
    "format",
    "format_version",
    "input_id",
    "input_source",
    "input_parameters",
    "sampling_frequency_hz",
    "mains_frequency_hz",
    "software_version",
    "source_sha256",
    "stages",
    "n_samples",
    "n_beats",
    "n_reference_beats",
)
_COEFFICIENTS: Final = "[coefficients]"
_SIGNALS: Final = "[signals]"
_BEATS: Final = "[beats]"
_REFERENCE_BEATS: Final = "[reference_beats]"
_END: Final = "[end]"
_COEFFICIENT_COLUMNS: Final = "stage,section,b0,b1,b2,a1,a2"
_INDEX_COLUMN: Final = "sample_index"
_SECTION_WIDTH: Final = 6  # b0, b1, b2, a0, a1, a2
_A0_COLUMN: Final = 3
_SYNTHETIC_SOURCE: Final = "synthetic"
_MAINS_VALUES: Final = (50, 60)

_INPUT_ID: Final = re.compile(r"[A-Za-z0-9_-]+")
_STAGE_NAME: Final = re.compile(r"[a-z][a-z0-9_]*")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_FLOAT: Final = re.compile(r"-?[0-9]+(\.[0-9]+)?(e[+-][0-9]+)?")
_INTEGER: Final = re.compile(r"0|[1-9][0-9]*")
# Characters that no line of a file holds, and that no header value holds (with the line feed).
_LINE_FORBIDDEN: Final = ((" ", "a space"), ("\t", "a tab"), ("\r", "a carriage return"))
_BYTE_ORDER_MARK: Final = "﻿"


@dataclass(frozen=True)
class GoldenVector:
    """The content of one golden-vector file (SRS-015, architecture §7.3).

    Attributes:
        input_id: Input identifier, matching ``[A-Za-z0-9_-]+``, e.g.
            ``syn-fs360-hr075-bw-mains60`` or ``mitdb-100-first60s``.
        input_source: ``synthetic``, or the slug of the database of a record segment.
        input_parameters: ``name=value`` pairs separated by ``;``: the generator parameters,
            or the database, its version, the record, the signal, the first sample and the
            duration of a record segment.
        fs_hz: Sampling frequency, in Hz.
        mains_hz: Mains setting, 50 or 60 Hz.
        software_version: Package version (:attr:`SoftwareIdentity.version`).
        source_sha256: Digest of the package source (:attr:`SoftwareIdentity.source_sha256`).
        stages: Names of the conditioning stages, in the order applied: ``("baseline",
            "mains")``.
        coefficients: Second-order-section matrix of each stage, shape ``(n_sections, 6)``,
            rows ``[b0, b1, b2, 1.0, a1, a2]``.
        input_mv: The input, in mV.
        stage_outputs_mv: Output of each stage, in mV, as long as the input.
        beats: Detected QRS sample indices, strictly increasing.
        reference_beats: True or annotated beat sample indices, non-decreasing.
    """

    input_id: str
    input_source: str
    input_parameters: str
    fs_hz: float
    mains_hz: int
    software_version: str
    source_sha256: str
    stages: tuple[str, ...]
    coefficients: tuple[FloatArray, ...]
    input_mv: FloatArray
    stage_outputs_mv: tuple[FloatArray, ...]
    beats: IndexArray
    reference_beats: IndexArray


@dataclass(frozen=True)
class ExportSummary:
    """What an export wrote and skipped (SRS-015).

    Attributes:
        written: File names, in the order written.
        skipped: Identifiers of the record segments not exported, in code-point order of the
            record names; empty if none was skipped.
        skip_reason: Why they were skipped: the message of the failed verification, or
            ``None`` if nothing was skipped.
    """

    written: tuple[str, ...]
    skipped: tuple[str, ...]
    skip_reason: str | None


def golden_vector(
    input_id: str,
    input_source: str,
    input_parameters: str,
    signal_mv: npt.ArrayLike,
    fs_hz: float,
    mains_hz: int,
    reference_beats: npt.ArrayLike,
    *,
    software: SoftwareIdentity,
) -> GoldenVector:
    """Compute the golden vector of one input.

    SRS-015: the vector holds exactly what the public functions compute on the input: the
    conditioning chain and the detection of :func:`~sinus_dsp.pipeline.run_pipeline`, run
    once, with the coefficients and the output of each stage in the order applied, and the
    identity of the software.

    In this order:

    1. ``input_id`` must match ``[A-Za-z0-9_-]+``; ``input_source`` and
       ``input_parameters`` must not be empty and must hold no space, tab, carriage return or
       line feed.
    2. :func:`~sinus_dsp.pipeline.run_pipeline` checks the input and the mains setting, then
       filters and detects.
    3. ``reference_beats`` must be one-dimensional, of integer kind (an empty sequence is
       allowed), non-decreasing and within ``[0, n_samples)``.

    Args:
        input_id: Input identifier.
        input_source: ``synthetic``, or the slug of the database of a record segment.
        input_parameters: The parameters of the input, ``name=value`` pairs separated by
            ``;``.
        signal_mv: The input, in mV. It is not modified.
        fs_hz: Its sampling frequency, in Hz.
        mains_hz: The mains setting, 50 or 60 Hz.
        reference_beats: The true or annotated beat sample indices.
        software: Identity of the software (:func:`~sinus_dsp.version.software_identity`).

    Returns:
        The vector. ``fs_hz`` and ``mains_hz`` are the values checked by the pipeline (a
        ``float`` and an ``int``); ``reference_beats`` is a new int64 array.

    Raises:
        InvalidInputError: At the first check that fails, including the input checks of
            architecture §8.5 and a mains setting other than 50 or 60 Hz.
    """
    if not isinstance(input_id, str) or _INPUT_ID.fullmatch(input_id) is None:
        raise InvalidInputError(f"input_id does not match [A-Za-z0-9_-]+: {input_id!r}")
    for name, value in (("input_source", input_source), ("input_parameters", input_parameters)):
        problem = _text_value_problem(value)
        if problem is not None:
            raise InvalidInputError(f"{name} {problem}: {value!r}")

    result = run_pipeline(signal_mv, fs_hz, mains_hz)
    reference = _checked_reference_beats(reference_beats, int(result.input_mv.shape[0]))
    return GoldenVector(
        input_id=input_id,
        input_source=input_source,
        input_parameters=input_parameters,
        fs_hz=result.fs_hz,
        mains_hz=result.mains_hz,
        software_version=software.version,
        source_sha256=software.source_sha256,
        stages=STAGES,
        coefficients=result.coefficients,
        input_mv=result.input_mv,
        stage_outputs_mv=(result.baseline_mv, result.mains_mv),
        beats=result.beats,
        reference_beats=reference,
    )


def render_golden_vector(vector: GoldenVector) -> str:
    """Return the text of the golden-vector file of a vector (architecture §7.3).

    SRS-015: floats are written as ``repr(float(value))``, the shortest decimal text that
    reads back to the same binary64 value (a NumPy scalar is converted to a Python
    ``float`` first, since NumPy 2 writes ``np.float64(...)``); integers in decimal. The text
    has line feeds only, ends with one line feed after ``[end]``, and holds no space, tab or
    carriage return. Every text returned is accepted by :func:`parse_golden_vector`, which
    gives back an equal vector.

    Args:
        vector: The vector.

    Returns:
        The text of the file.

    Raises:
        NonFiniteOutputError: If a float of the vector (sampling frequency, coefficients,
            input or stage outputs) is not finite; checked before anything else.
        InvalidInputError: For any other content that would give a file that the reader
            rejects: a header value, a length or a shape, an a0 other than 1, the order or
            the range of the beats.
    """
    if not _all_finite(vector):
        raise NonFiniteOutputError(vector.input_id)
    _check_vector(vector)

    stages = vector.stages
    n_samples = int(vector.input_mv.shape[0])
    lines = [
        f"format={FORMAT_NAME}",
        f"format_version={FORMAT_VERSION}",
        f"input_id={vector.input_id}",
        f"input_source={vector.input_source}",
        f"input_parameters={vector.input_parameters}",
        f"sampling_frequency_hz={_float_text(vector.fs_hz)}",
        f"mains_frequency_hz={int(vector.mains_hz)}",
        f"software_version={vector.software_version}",
        f"source_sha256={vector.source_sha256}",
        f"stages={','.join(stages)}",
        f"n_samples={n_samples}",
        f"n_beats={int(vector.beats.shape[0])}",
        f"n_reference_beats={int(vector.reference_beats.shape[0])}",
        _COEFFICIENTS,
        _COEFFICIENT_COLUMNS,
    ]
    for stage, matrix in zip(stages, vector.coefficients, strict=True):
        for section, row in enumerate(matrix.tolist()):
            b0, b1, b2, _a0, a1, a2 = row
            numbers_text = ",".join(_float_text(value) for value in (b0, b1, b2, a1, a2))
            lines.append(f"{stage},{section},{numbers_text}")
    lines.append(_SIGNALS)
    lines.append(_signal_columns(stages))
    columns = [vector.input_mv.tolist(), *(output.tolist() for output in vector.stage_outputs_mv)]
    lines.extend(
        ",".join(_float_text(value) for value in row) for row in zip(*columns, strict=True)
    )
    for section_line, beats in ((_BEATS, vector.beats), (_REFERENCE_BEATS, vector.reference_beats)):
        lines.append(section_line)
        lines.append(_INDEX_COLUMN)
        lines.extend(str(int(sample)) for sample in beats.tolist())
    lines.append(_END)
    return "\n".join(lines) + "\n"


def parse_golden_vector(text: str, source: str) -> GoldenVector:
    """Read the text of a golden-vector file (architecture §7.3).

    SRS-015: reading a file gives back exactly the values written. Every reader rule of
    architecture §7.3 is applied, in the order of the file; the first failure raises, with
    the 1-based number of the offending line (the last line for a text that ends too early).
    The text is split at line feeds only, so a carriage return is never removed: a file with
    CR LF line endings is rejected at its first line.

    Args:
        text: The text of the file.
        source: Name of the file in errors, e.g. its path.

    Returns:
        The vector: ``fs_hz`` a ``float``, ``mains_hz`` an ``int``, float64 signals and
        coefficient matrices (with a0 = 1), int64 beats.

    Raises:
        MalformedFileError: At the first rule that the text breaks.
    """
    reader = _LineReader(text, source)
    header = _read_header(reader)
    stages = tuple(header["stages"].split(","))
    n_samples = int(header["n_samples"])

    reader.expect(_COEFFICIENTS)
    reader.expect(_COEFFICIENT_COLUMNS)
    coefficients = _read_coefficients(reader, stages)
    reader.expect(_signal_columns(stages))
    columns = _read_signals(reader, len(stages) + 1, n_samples)
    reader.expect_section(_BEATS, after=_SIGNALS, n_rows=n_samples, count_key="n_samples")
    reader.expect(_INDEX_COLUMN)
    beats = _read_indices(reader, int(header["n_beats"]), n_samples, strictly_increasing=True)
    reader.expect_section(_REFERENCE_BEATS, after=_BEATS, n_rows=len(beats), count_key="n_beats")
    reader.expect(_INDEX_COLUMN)
    reference = _read_indices(
        reader, int(header["n_reference_beats"]), n_samples, strictly_increasing=False
    )
    reader.expect_section(
        _END, after=_REFERENCE_BEATS, n_rows=len(reference), count_key="n_reference_beats"
    )
    reader.finish()

    return GoldenVector(
        input_id=header["input_id"],
        input_source=header["input_source"],
        input_parameters=header["input_parameters"],
        fs_hz=float(header["sampling_frequency_hz"]),
        mains_hz=int(header["mains_frequency_hz"]),
        software_version=header["software_version"],
        source_sha256=header["source_sha256"],
        stages=stages,
        coefficients=coefficients,
        input_mv=np.array(columns[0], dtype=np.float64),
        stage_outputs_mv=tuple(np.array(column, dtype=np.float64) for column in columns[1:]),
        beats=np.array(beats, dtype=np.int64),
        reference_beats=np.array(reference, dtype=np.int64),
    )


def read_golden_vector(path: Path) -> GoldenVector:
    """Read a golden-vector file (architecture §7.3).

    SRS-015: the bytes are decoded as UTF-8, then read with :func:`parse_golden_vector`.

    Args:
        path: The file.

    Returns:
        The vector.

    Raises:
        MalformedFileError: ``(str(path), None, "not UTF-8 text")`` if the bytes are not
            UTF-8 text; otherwise at the first reader rule that the text breaks.
        OSError: If the file cannot be read.
    """
    content = Path(path).read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MalformedFileError(str(path), None, "not UTF-8 text") from error
    return parse_golden_vector(text, str(path))


def export_golden_vectors(
    output_dir: Path,
    *,
    data_root: Path,
    database: Database = MITDB,
    records: Sequence[str] = SUBSET_RECORDS,
    loader: RecordLoader = load_record,
) -> ExportSummary:
    """Write one golden-vector file for each input of the set (architecture §7.2, §8.12).

    SRS-015: the 18 synthetic inputs, then the first 60 s of each record of ``records``
    (by default the records of the subset of SRS-016), first stored signal, where the files
    of these records are available and verified. The export never downloads.

    1. The files of the records are verified against the pinned checksum list of the
       database (:func:`~sinus_dsp.data.physionet.verify_database`). An invalid or empty
       ``records`` raises here, before anything is computed or written. A failed
       verification does not stop the export: the record segments are skipped, and the
       message of the failure is the reason.
    2. The software identity is taken once, for all the files.
    3. Each synthetic input of :func:`~sinus_dsp.synthetic.synthetic_set`, in that order, is
       computed (:func:`golden_vector`), rendered and written to
       ``output_dir / (<input_id> + ".golden.txt")``.
    4. If the records are verified, for each record name in code-point order: channel 0 of
       the record is loaded, its first 60 s (``round_samples(60, fs)`` samples) are the
       input, its beat annotations below that sample are the reference beats, and the
       vector ``<slug>-<record>-first60s`` is computed with the settings of SRS-007
       (channel 0, mains 60 Hz), rendered and written. The segment is processed on its own,
       from its first sample.

    Each file is written as soon as it is computed, atomically (through ``<name>.part~``;
    the folder is created if needed). An error stops the export and leaves the files already
    written, each complete. Files of ``output_dir`` with the names written are replaced;
    other files are left untouched.

    Args:
        output_dir: Folder of the files, e.g. ``data/golden``.
        data_root: The data folder; the database is in ``data_root / database.slug``.
        database: The database of the record segments.
        records: Names of the records of the segments.
        loader: Function that loads a record.

    Returns:
        The names of the files written, and the record segments skipped with the reason.

    Raises:
        InvalidInputError: If ``records`` is invalid or empty (before anything is written),
            if the loader rejects a record, or if a record is shorter than its segment.
        MalformedFileError: If the checksum list does not follow its format, or if an
            annotation file is malformed.
        NonFiniteOutputError: If an output is not finite.
        OSError: If a file cannot be read or written.
    """
    if records is None:
        raise InvalidInputError("records is None: give the names of the records")
    root = Path(data_root)
    verification: VerificationResult | None
    try:
        verification = verify_database(database, root, records=records)
    except DataVerificationError as error:
        verification = None
        skip_reason: str | None = str(error)
    else:
        skip_reason = None

    software = software_identity()
    output = Path(output_dir)
    written: list[str] = []

    for ecg in synthetic_set():
        vector = golden_vector(
            ecg.input_id,
            _SYNTHETIC_SOURCE,
            ecg.parameters,
            ecg.signal_mv,
            ecg.fs_hz,
            ecg.mains_hz,
            ecg.r_peaks,
            software=software,
        )
        written.append(_write_vector(output, vector))

    if verification is None:
        names = sorted(set(records))
        skipped = tuple(_segment_id(database, name) for name in names)
        return ExportSummary(written=tuple(written), skipped=skipped, skip_reason=skip_reason)

    for name in verification.records or ():
        record = loader(root / database.slug / name, DEFAULT_SETTINGS.channel)
        n_samples = round_samples(GOLDEN_SEGMENT_S, record.fs_hz)
        if record.n_samples < n_samples:
            raise InvalidInputError(
                f"record {name} is shorter than its {GOLDEN_SEGMENT_S} s segment: "
                f"{record.n_samples} samples at {record.fs_hz!r} Hz, {n_samples} needed"
            )
        reference = record.beat_samples[record.beat_samples < n_samples]
        parameters = (
            f"database={database.slug};database_version={database.version};record={name};"
            f"signal={DEFAULT_SETTINGS.channel};start_sample=0;duration_s={GOLDEN_SEGMENT_S}"
        )
        vector = golden_vector(
            _segment_id(database, name),
            database.slug,
            parameters,
            record.signal_mv[:n_samples],
            record.fs_hz,
            DEFAULT_SETTINGS.mains_hz,
            reference,
            software=software,
        )
        written.append(_write_vector(output, vector))
    return ExportSummary(written=tuple(written), skipped=(), skip_reason=None)


# --- export helpers -------------------------------------------------------------------------


def _segment_id(database: Database, name: str) -> str:
    """Identifier of the record segment of a record: ``<slug>-<record>-first60s``."""
    return f"{database.slug}-{name}-first{GOLDEN_SEGMENT_S}s"


def _write_vector(output_dir: Path, vector: GoldenVector) -> str:
    """Render a vector, write its file, and return the file name."""
    name = vector.input_id + GOLDEN_FILE_SUFFIX
    write_atomically(output_dir / name, render_golden_vector(vector).encode("utf-8"))
    return name


# --- rules shared by the writer and the reader -----------------------------------------------


def _text_value_problem(value: object) -> str | None:
    """Why a text header value cannot be written, or ``None``: empty, or a forbidden character."""
    if not isinstance(value, str):
        return "is not a string"
    if not value:
        return "is empty"
    for character, name in (*_LINE_FORBIDDEN, ("\n", "a line feed")):
        if character in value:
            return f"holds {name}"
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return "is not encodable as UTF-8"
    return None


def _stages_problem(stages: Sequence[str]) -> str | None:
    """Why a list of stage names is not valid, or ``None``."""
    if not stages:
        return "no stage given"
    seen: set[str] = set()
    for stage in stages:
        if not isinstance(stage, str) or _STAGE_NAME.fullmatch(stage) is None:
            return f"invalid stage name {stage!r}: expected [a-z][a-z0-9_]*"
        if stage in seen:
            return f"stage {stage} given twice"
        seen.add(stage)
    return None


def _signal_columns(stages: Sequence[str]) -> str:
    """The column line of ``[signals]``: ``input_mv``, then ``<stage>_mv`` for each stage."""
    return ",".join(["input_mv", *(f"{stage}_mv" for stage in stages)])


def _float_text(value: float) -> str:
    """A float64 value as Python's ``repr`` of it as a Python ``float``."""
    return repr(float(value))


# --- writer checks ----------------------------------------------------------------------------


def _all_finite(vector: GoldenVector) -> bool:
    """Whether every float of the vector that is a number or a float array is finite.

    Content of another type is left to :func:`_check_vector`.
    """
    arrays = [
        *_as_sequence(vector.coefficients),
        vector.input_mv,
        *_as_sequence(vector.stage_outputs_mv),
    ]
    fs = vector.fs_hz
    if isinstance(fs, numbers.Real) and not isinstance(fs, bool) and not math.isfinite(fs):
        return False
    return all(
        bool(np.isfinite(array).all())
        for array in arrays
        if isinstance(array, np.ndarray) and array.dtype.kind == "f"
    )


def _as_sequence(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, tuple | list) else ()


def _check_vector(vector: GoldenVector) -> None:
    """Raise ``InvalidInputError`` for content that would give a file the reader rejects."""
    if not isinstance(vector.input_id, str) or _INPUT_ID.fullmatch(vector.input_id) is None:
        raise InvalidInputError(f"input_id does not match [A-Za-z0-9_-]+: {vector.input_id!r}")
    for name, value in (
        ("input_source", vector.input_source),
        ("input_parameters", vector.input_parameters),
    ):
        problem = _text_value_problem(value)
        if problem is not None:
            raise InvalidInputError(f"{name} {problem}: {value!r}")
    fs = vector.fs_hz
    if isinstance(fs, bool) or not isinstance(fs, numbers.Real) or not float(fs) > 0.0:
        raise InvalidInputError(f"sampling frequency is not a positive number: {fs!r}")
    mains = vector.mains_hz
    if isinstance(mains, bool) or not isinstance(mains, numbers.Integral):
        raise InvalidInputError(f"mains setting is not an integer: {mains!r}")
    if int(mains) not in _MAINS_VALUES:
        raise InvalidInputError(f"mains setting is not 50 or 60 Hz: {mains!r}")
    problem = _text_value_problem(vector.software_version)
    if problem is not None:
        raise InvalidInputError(f"software_version {problem}: {vector.software_version!r}")
    digest = vector.source_sha256
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise InvalidInputError(f"source_sha256 is not 64 lowercase hexadecimal digits: {digest!r}")

    stages = vector.stages
    if not isinstance(stages, tuple):
        raise InvalidInputError(f"stages is not a tuple: {stages!r}")
    problem = _stages_problem(stages)
    if problem is not None:
        raise InvalidInputError(f"stages: {problem}")
    _check_coefficients(vector.coefficients, stages)

    n_samples = _check_signal("input_mv", vector.input_mv, None)
    outputs = vector.stage_outputs_mv
    if not isinstance(outputs, tuple) or len(outputs) != len(stages):
        raise InvalidInputError(
            f"stage_outputs_mv is not a tuple of one array per stage ({len(stages)})"
        )
    for stage, output in zip(stages, outputs, strict=True):
        _check_signal(f"output of the stage {stage}", output, n_samples)
    _check_indices("beats", vector.beats, n_samples, strictly_increasing=True)
    _check_indices("reference_beats", vector.reference_beats, n_samples, strictly_increasing=False)


def _check_coefficients(coefficients: object, stages: tuple[str, ...]) -> None:
    if not isinstance(coefficients, tuple) or len(coefficients) != len(stages):
        raise InvalidInputError(
            f"coefficients is not a tuple of one matrix per stage ({len(stages)})"
        )
    for stage, matrix in zip(stages, coefficients, strict=True):
        if not isinstance(matrix, np.ndarray) or matrix.dtype != np.float64:
            raise InvalidInputError(f"coefficients of the stage {stage} are not a float64 array")
        if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] != _SECTION_WIDTH:
            raise InvalidInputError(
                f"coefficients of the stage {stage} do not have the shape (n_sections, 6) with "
                f"at least one section: shape {matrix.shape}"
            )
        if not bool((matrix[:, _A0_COLUMN] == 1.0).all()):
            raise InvalidInputError(f"coefficients of the stage {stage} have an a0 other than 1")


def _check_signal(name: str, signal: object, n_samples: int | None) -> int:
    """Check a signal of the vector and return its length."""
    if not isinstance(signal, np.ndarray) or signal.dtype != np.float64 or signal.ndim != 1:
        raise InvalidInputError(f"{name} is not a one-dimensional float64 array")
    length = int(signal.shape[0])
    if n_samples is None and length == 0:
        raise InvalidInputError(f"{name} is empty")
    if n_samples is not None and length != n_samples:
        raise InvalidInputError(f"{name} has {length} samples, the input {n_samples}")
    return length


def _check_indices(
    name: str, indices: object, n_samples: int, *, strictly_increasing: bool
) -> None:
    if not isinstance(indices, np.ndarray) or indices.ndim != 1 or indices.dtype.kind not in "iu":
        raise InvalidInputError(f"{name} is not a one-dimensional array of integers")
    problem = _indices_problem(indices.tolist(), n_samples, strictly_increasing)
    if problem is not None:
        raise InvalidInputError(f"{name}: {problem}")


def _indices_problem(
    values: Sequence[int], n_samples: int, strictly_increasing: bool
) -> str | None:
    """Why sample indices are out of order or out of range, or ``None``."""
    previous: int | None = None
    for index, value in enumerate(values):
        if not 0 <= value < n_samples:
            return f"sample {value} at index {index} is outside 0 to {n_samples - 1}"
        if previous is not None and (
            value <= previous if strictly_increasing else value < previous
        ):
            order = "greater than" if strictly_increasing else "at least"
            return f"sample {value} at index {index} is not {order} the one before it, {previous}"
        previous = value
    return None


def _checked_reference_beats(reference_beats: npt.ArrayLike, n_samples: int) -> IndexArray:
    """Check the reference beats given to :func:`golden_vector` and return them as int64."""
    try:
        array = np.asarray(reference_beats)
    except (TypeError, ValueError) as error:
        raise InvalidInputError(f"reference beats do not convert to an array: {error}") from error
    if array.ndim != 1:
        raise InvalidInputError(
            f"reference beats are not one-dimensional: {array.ndim} dimensions, shape {array.shape}"
        )
    if array.shape[0] == 0:
        return np.zeros(0, dtype=np.int64)
    if array.dtype.kind not in "iu":
        raise InvalidInputError(f"reference beats are not integers: dtype {array.dtype}")
    problem = _indices_problem(array.tolist(), n_samples, strictly_increasing=False)
    if problem is not None:
        raise InvalidInputError(f"reference beats: {problem}")
    return np.array(array, dtype=np.int64)


# --- reader -----------------------------------------------------------------------------------


class _LineReader:
    """The lines of a text, split at line feeds, read in order.

    Each line read must exist, must not be empty and must hold no space, tab or carriage
    return; otherwise the reader raises ``MalformedFileError`` with the line number.
    """

    def __init__(self, text: str, source: str) -> None:
        pieces = text.split("\n")
        self._source = source
        # Lines followed by a line feed, then the text after the last line feed, if any.
        self._complete = len(pieces) - 1
        self._lines = pieces if pieces[-1] else pieces[:-1]
        self._next = 0

    def error(self, number: int | None, reason: str) -> MalformedFileError:
        return MalformedFileError(self._source, number, reason)

    def take(self, expected: str) -> tuple[int, str]:
        """The number and the text of the next line, which must be a valid line."""
        if self._next >= len(self._lines):
            raise self.error(max(len(self._lines), 1), f"the file ends before {expected}")
        number = self._next + 1
        line = self._lines[self._next]
        self._next += 1
        if not line:
            raise self.error(number, "empty line")
        if number == 1 and line.startswith(_BYTE_ORDER_MARK):
            raise self.error(number, "the file starts with a byte-order mark")
        for character, name in _LINE_FORBIDDEN:
            if character in line:
                raise self.error(number, f"the line holds {name}")
        return number, line

    def expect(self, expected: str) -> None:
        """The next line must be ``expected`` (a section or column line)."""
        number, line = self.take(expected)
        if line != expected:
            raise self.error(number, f"expected {expected}, found {_shown(line)}")

    def expect_section(self, section: str, *, after: str, n_rows: int, count_key: str) -> None:
        """The next line must be the section line ``section``, after the rows of ``after``."""
        number, line = self.take(section)
        if line == section:
            return
        if not line.startswith("["):
            raise self.error(
                number, f"{after} has more rows than {count_key} ({n_rows}): expected {section}"
            )
        raise self.error(number, f"expected {section}, found {_shown(line)}")

    def finish(self) -> None:
        """After ``[end]``: it must be followed by a line feed, and by nothing else."""
        number = self._next
        if number > self._complete:
            raise self.error(number, "no line feed after [end]")
        if self._next < len(self._lines):
            raise self.error(self._next + 1, "text after [end]")


def _shown(line: str) -> str:
    """A line as an error shows it: at most 40 characters."""
    return line if len(line) <= 40 else line[:40] + "…"


def _read_header(reader: _LineReader) -> dict[str, str]:
    """Read the header lines and check their values; return the values by key."""
    values: dict[str, str] = {}
    for key in _HEADER_KEYS:
        number, line = reader.take(f"the header key {key}")
        found, separator, value = line.partition("=")
        if not separator:
            raise reader.error(number, f"not a key=value line: expected the header key {key}")
        if found != key:
            if found in values:
                reason = f"header key {found} given twice"
            elif found in _HEADER_KEYS:
                reason = f"header key {found} out of order: expected {key}"
            else:
                reason = f"unknown header key {_shown(found)}: expected {key}"
            raise reader.error(number, reason)
        problem = _header_value_problem(key, value)
        if problem is not None:
            raise reader.error(number, problem)
        values[key] = value
    return values


def _header_value_problem(key: str, value: str) -> str | None:
    """Why a header value read from a file breaks the rules of its key, or ``None``."""
    if key == "format":
        return None if value == FORMAT_NAME else f"unknown format {_shown(value)}"
    if key == "format_version":
        return None if value == str(FORMAT_VERSION) else f"unknown format version {_shown(value)}"
    if key == "input_id":
        if _INPUT_ID.fullmatch(value) is None:
            return f"input_id does not match [A-Za-z0-9_-]+: {_shown(value)}"
        return None
    if key in ("input_source", "input_parameters", "software_version"):
        return None if value else f"{key} is empty"
    if key == "sampling_frequency_hz":
        problem = _float_problem(value)
        if problem is not None:
            return f"sampling_frequency_hz: {problem}"
        return None if float(value) > 0.0 else f"sampling_frequency_hz is not positive: {value}"
    if key == "mains_frequency_hz":
        if value not in tuple(str(mains) for mains in _MAINS_VALUES):
            return f"mains_frequency_hz is not 50 or 60: {_shown(value)}"
        return None
    if key == "source_sha256":
        if _SHA256.fullmatch(value) is None:
            return "source_sha256 is not 64 lowercase hexadecimal digits"
        return None
    if key == "stages":
        problem = _stages_problem(value.split(",") if value else [])
        return None if problem is None else f"stages: {problem}"
    # n_samples, n_beats, n_reference_beats
    problem = _integer_problem(value)
    if problem is not None:
        return f"{key}: {problem}"
    if key == "n_samples" and int(value) < 1:
        return "n_samples is not at least 1"
    return None


def _float_problem(text: str) -> str | None:
    """Why a text is not a float of the file format, or ``None``."""
    if _FLOAT.fullmatch(text) is None:
        return f"not a float: {_shown(text)}"
    if not math.isfinite(float(text)):
        return f"not a finite float: {_shown(text)}"
    return None


def _integer_problem(text: str) -> str | None:
    """Why a text is not an integer of the file format, or ``None``."""
    if _INTEGER.fullmatch(text) is None:
        return f"not an integer: {_shown(text)}"
    try:
        int(text)
    except ValueError:
        return f"integer with too many digits: {_shown(text)}"
    return None


def _read_float(reader: _LineReader, number: int, text: str) -> float:
    problem = _float_problem(text)
    if problem is not None:
        raise reader.error(number, problem)
    return float(text)


def _read_integer(reader: _LineReader, number: int, text: str) -> int:
    problem = _integer_problem(text)
    if problem is not None:
        raise reader.error(number, problem)
    return int(text)


def _read_coefficients(reader: _LineReader, stages: tuple[str, ...]) -> tuple[FloatArray, ...]:
    """Read the rows of ``[coefficients]`` and the line ``[signals]`` that ends them."""
    rows: list[list[list[float]]] = [[] for _ in stages]
    current = 0
    while True:
        number, line = reader.take(_SIGNALS)
        if line.startswith("["):
            if line != _SIGNALS:
                raise reader.error(number, f"expected {_SIGNALS}, found {_shown(line)}")
            missing = next(
                (stage for stage, got in zip(stages, rows, strict=True) if not got), None
            )
            if missing is not None:
                raise reader.error(number, f"no coefficient row for the stage {missing}")
            break
        fields = line.split(",")
        if len(fields) != 7:
            raise reader.error(number, f"coefficient row with {len(fields)} fields, expected 7")
        stage = fields[0]
        if stage != stages[current]:
            if rows[current] and current + 1 < len(stages) and stage == stages[current + 1]:
                current += 1
            else:
                raise reader.error(number, _unexpected_stage(stage, stages, current, rows))
        section = _read_integer(reader, number, fields[1])
        if section != len(rows[current]):
            raise reader.error(
                number,
                f"section {section} of the stage {stage}, expected section {len(rows[current])}",
            )
        b0, b1, b2, a1, a2 = (_read_float(reader, number, field) for field in fields[2:])
        rows[current].append([b0, b1, b2, 1.0, a1, a2])
    return tuple(np.array(stage_rows, dtype=np.float64) for stage_rows in rows)


def _unexpected_stage(
    stage: str, stages: tuple[str, ...], current: int, rows: Sequence[Sequence[object]]
) -> str:
    expected = [stages[current]]
    if rows[current]:
        expected.append(stages[current + 1] if current + 1 < len(stages) else _SIGNALS)
    return f"coefficient row of the stage {_shown(stage)}, expected {' or '.join(expected)}"


def _read_signals(reader: _LineReader, width: int, n_samples: int) -> list[list[float]]:
    """Read the ``n_samples`` rows of ``[signals]``, ``width`` floats each, by column."""
    columns: list[list[float]] = [[] for _ in range(width)]
    for index in range(n_samples):
        number, line = reader.take(f"row {index + 1} of {_SIGNALS}")
        if line.startswith("["):
            raise reader.error(number, f"{_SIGNALS} has {index} rows, n_samples is {n_samples}")
        fields = line.split(",")
        if len(fields) != width:
            raise reader.error(number, f"row with {len(fields)} fields, expected {width}")
        for column, field in zip(columns, fields, strict=True):
            column.append(_read_float(reader, number, field))
    return columns


def _read_indices(
    reader: _LineReader, count: int, n_samples: int, *, strictly_increasing: bool
) -> list[int]:
    """Read the ``count`` rows of a beat section, one sample index each."""
    section = _BEATS if strictly_increasing else _REFERENCE_BEATS
    count_key = "n_beats" if strictly_increasing else "n_reference_beats"
    values: list[int] = []
    for index in range(count):
        number, line = reader.take(f"row {index + 1} of {section}")
        if line.startswith("["):
            raise reader.error(number, f"{section} has {index} rows, {count_key} is {count}")
        fields = line.split(",")
        if len(fields) != 1:
            raise reader.error(number, f"row with {len(fields)} fields, expected 1")
        value = _read_integer(reader, number, fields[0])
        if value >= n_samples:
            raise reader.error(number, f"sample {value} is outside 0 to {n_samples - 1}")
        if values and (value <= values[-1] if strictly_increasing else value < values[-1]):
            order = "greater than" if strictly_increasing else "at least"
            raise reader.error(
                number, f"sample {value} is not {order} the one before it, {values[-1]}"
            )
        values.append(value)
    return values
