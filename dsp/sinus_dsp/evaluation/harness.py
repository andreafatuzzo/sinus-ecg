"""The real-time library as a detector for the evaluation (architecture-m2.md 14.14).

SRS-038: the shared library ``sinus_dsp_harness`` of ``libs/sinus-dsp`` (a C interface, built
for the computer) is loaded with :mod:`ctypes` and used through the ``Detector`` injection of
:mod:`sinus_dsp.evaluation.run`, so that the records are scored by the same code (SRS-008,
SRS-011) for the reference and for the library, and their counts can be compared per record.
"""

from __future__ import annotations

import ctypes
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

from sinus_dsp._types import FloatArray, IndexArray
from sinus_dsp.data.records import load_record
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.metrics import RecordCounts
from sinus_dsp.evaluation.run import (
    Detector,
    EvaluationSettings,
    RecordLoader,
    evaluate_records,
)
from sinus_dsp.pipeline import detect_beats

#: Names of the status codes of ``libs/sinus-dsp`` (``Status``), by value: the harness returns
#: ``-1 - status`` on an error.
_STATUS_NAMES: Final = (
    "ok",
    "not configured",
    "invalid sampling frequency",
    "invalid mains frequency",
    "invalid sample",
    "stopped",
    "invalid argument",
)

#: First size of the output arrays, in detections; a longer record makes a second call.
_FIRST_CAPACITY: Final = 4096


@dataclass(frozen=True)
class DetectionComparison:
    """Counts of one record for the reference and for a candidate detector (SRS-038).

    Attributes:
        record: Name of the record.
        reference: Counts of the reference detector.
        candidate: Counts of the candidate detector.
    """

    record: str
    reference: RecordCounts
    candidate: RecordCounts

    @property
    def equal(self) -> bool:
        """Whether the true positives, false negatives and false positives are the same."""
        return (
            self.reference.tp == self.candidate.tp
            and self.reference.fn == self.candidate.fn
            and self.reference.fp == self.candidate.fp
        )


class LibraryHarness:
    """The loaded shared library ``sinus_dsp_harness`` (SRS-038).

    Use :func:`load_harness` to create one.
    """

    def __init__(self, library: ctypes.CDLL) -> None:
        detect = library.sinus_dsp_harness_detect
        detect.restype = ctypes.c_int64
        detect.argtypes = [
            ctypes.c_double,
            ctypes.c_int32,
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint64,
        ]
        identity = library.sinus_dsp_harness_identity
        identity.restype = ctypes.c_char_p
        identity.argtypes = []
        self._library = library
        self._detect = detect
        self._identity = identity

    def identity(self) -> str:
        """Return ``"<version>;<source SHA-256>"`` of the library."""
        text = self._identity()
        if text is None:
            raise InvalidInputError("the harness returned no identity")
        return str(text.decode("ascii"))

    def detect(self, signal_mv: FloatArray, fs_hz: float, mains_hz: int) -> IndexArray:
        """Run a newly configured library on a signal and return the beats it detects.

        SRS-038: it is a ``Detector`` of :mod:`sinus_dsp.evaluation.run`. The signal is
        converted to a contiguous ``float32`` array, the sample type of the library.

        Args:
            signal_mv: The signal, in mV.
            fs_hz: Sampling frequency, in Hz.
            mains_hz: Setting of the mains filter, 50 or 60.

        Returns:
            The fiducial samples of the detections, in the order the library reports them.

        Raises:
            InvalidInputError: If the library rejects the configuration or a sample.
        """
        samples = np.ascontiguousarray(signal_mv, dtype=np.float32)
        if samples.ndim != 1:
            raise InvalidInputError("the signal must be one-dimensional")
        capacity = _FIRST_CAPACITY
        for _ in range(2):
            indices = np.zeros(capacity, dtype=np.uint64)
            startup = np.zeros(capacity, dtype=np.uint8)
            reported_at = np.zeros(capacity, dtype=np.uint64)
            total = int(
                self._detect(
                    float(fs_hz),
                    int(mains_hz),
                    samples.ctypes.data,
                    samples.size,
                    indices.ctypes.data,
                    startup.ctypes.data,
                    reported_at.ctypes.data,
                    capacity,
                )
            )
            if total < 0:
                code = -1 - total
                name = _STATUS_NAMES[code] if code < len(_STATUS_NAMES) else f"status {code}"
                raise InvalidInputError(f"the library rejected the input: {name}")
            if total <= capacity:
                return indices[:total].astype(np.int64)
            capacity = total
        raise InvalidInputError("the library changed its count between two calls")


def load_harness(path: Path) -> LibraryHarness:
    """Load the shared library ``sinus_dsp_harness`` (SRS-038).

    Args:
        path: The shared library file, e.g. ``sinus_dsp_harness.dll`` of the release build.

    Raises:
        InvalidInputError: If the file does not exist or cannot be loaded as a library with
            the functions of the harness.
    """
    library_path = Path(path)
    if not library_path.is_file():
        raise InvalidInputError(f"harness library not found: {library_path}")
    try:
        library = ctypes.CDLL(str(library_path))
        return LibraryHarness(library)
    except (OSError, AttributeError) as error:
        raise InvalidInputError(
            f"cannot load the harness library {library_path}: {error}"
        ) from error


def compare_detection(
    database_dir: Path,
    records: Sequence[str],
    settings: EvaluationSettings,
    candidate: Detector,
    *,
    reference: Detector = detect_beats,
    loader: RecordLoader = load_record,
) -> tuple[DetectionComparison, ...]:
    """Evaluate records with the reference and with a candidate detector (SRS-038).

    Each record is scored as in :func:`~sinus_dsp.evaluation.run.evaluate_records` (SRS-008,
    SRS-011), once with each detector, and the counts are paired.

    Args:
        database_dir: Folder of the database.
        records: Names of the records, as for ``evaluate_records``.
        settings: Settings of the detection.
        candidate: The detector under comparison, e.g. :meth:`LibraryHarness.detect`.
        reference: The reference detector.
        loader: Function that loads a record.

    Returns:
        One comparison per record, in the order of ``records``.

    Raises:
        InvalidInputError: As ``evaluate_records``.
    """
    expected = evaluate_records(database_dir, records, settings, detector=reference, loader=loader)
    actual = evaluate_records(database_dir, records, settings, detector=candidate, loader=loader)
    return tuple(
        DetectionComparison(record=e.record, reference=e.counts, candidate=a.counts)
        for e, a in zip(expected, actual, strict=True)
    )
