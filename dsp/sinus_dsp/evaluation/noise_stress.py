"""Noise stress test: records, SNR per record and aggregation per SNR (architecture §8.10).

SRS-014: the 12 ECG records of the MIT-BIH Noise Stress Test Database are records 118 and
119 of the MIT-BIH Arrhythmia Database with electrode motion noise added at signal-to-noise
ratios of 24, 18, 12, 6, 0 and -6 dB. They are evaluated with the channel and mains setting
of the main evaluation, and their gross statistics per SNR are compared with those of records
118 and 119 without added noise.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sinus_dsp.data.physionet import VerificationResult
from sinus_dsp.errors import InvalidInputError
from sinus_dsp.evaluation.metrics import AggregateStatistics, RecordCounts, aggregate_statistics
from sinus_dsp.evaluation.run import (
    Detector,
    EvaluationSettings,
    RecordEvaluation,
    RecordLoader,
    evaluate_records,
)

#: SRS-014: the 12 noise stress records, by record and by decreasing SNR.
NOISE_STRESS_RECORDS: Final = (
    "118e24",
    "118e18",
    "118e12",
    "118e06",
    "118e00",
    "118e_6",
    "119e24",
    "119e18",
    "119e12",
    "119e06",
    "119e00",
    "119e_6",
)

#: SRS-014: the MIT-BIH Arrhythmia records without added noise, the reference for comparison.
CLEAN_RECORDS: Final = ("118", "119")

# A noise stress record name: the record number, "e" (electrode motion noise), then the SNR
# in dB, with "_" in place of a minus sign.
_NOISE_STRESS_NAME: Final = re.compile(r"[0-9]+e(_?)([0-9]+)")


@dataclass(frozen=True)
class SnrStatistics:
    """Statistics of the noise stress records at one SNR (SRS-014).

    Attributes:
        snr_db: The signal-to-noise ratio, in dB.
        statistics: Gross statistics over the records at this SNR, from their summed counts.
    """

    snr_db: int
    statistics: AggregateStatistics


@dataclass(frozen=True)
class NoiseStressResults:
    """Results of the noise stress test (SRS-014).

    Attributes:
        nstdb: Outcome of the verification of the Noise Stress Test Database.
        records: Evaluation of each record, in the order of :data:`NOISE_STRESS_RECORDS`.
        by_snr: Statistics per SNR, in decreasing order of SNR (24, 18, 12, 6, 0, -6 dB).
        clean: Statistics of MIT-BIH Arrhythmia records 118 and 119, without added noise.
    """

    nstdb: VerificationResult
    records: tuple[RecordEvaluation, ...]
    by_snr: tuple[SnrStatistics, ...]
    clean: AggregateStatistics


def snr_db(record: str) -> int:
    """Return the SNR of a noise stress record, in dB, from its name.

    SRS-014: the suffix after ``e`` gives the SNR: digits give a positive value (or 0), and
    ``_`` followed by digits a negative one. ``"118e24"`` gives 24, ``"119e_6"`` gives -6.
    The part before ``e`` is the record number, in digits.

    Raises:
        InvalidInputError: If ``record`` is not a noise stress record name.
    """
    match = _NOISE_STRESS_NAME.fullmatch(record) if isinstance(record, str) else None
    if match is None:
        raise InvalidInputError(f"not a noise stress record name: {record!r}")
    value = int(match.group(2))
    return -value if match.group(1) else value


def evaluate_noise_stress(
    nstdb_dir: Path,
    mitdb_records: Sequence[RecordEvaluation],
    settings: EvaluationSettings,
    *,
    nstdb: VerificationResult,
    detector: Detector,
    loader: RecordLoader,
) -> NoiseStressResults:
    """Evaluate the noise stress records and aggregate them per SNR.

    SRS-014: each record of :data:`NOISE_STRESS_RECORDS` is evaluated as the records of the
    MIT-BIH Arrhythmia Database (SRS-008, SRS-011), with the same settings and its reference
    annotations. The gross Se and +P of each SNR come from the summed counts of the two
    records at that SNR. The comparison values are the gross statistics of records 118 and
    119 of the MIT-BIH Arrhythmia Database, taken from ``mitdb_records``.

    Args:
        nstdb_dir: Folder of the Noise Stress Test Database, e.g. ``data/nstdb``.
        mitdb_records: The evaluations of the MIT-BIH Arrhythmia records; they include
            records 118 and 119.
        settings: Settings of the detection.
        nstdb: Outcome of the verification of the Noise Stress Test Database, which the
            results carry into the report.
        detector: Detection function.
        loader: Function that loads a record.

    Returns:
        The results of the noise stress test.

    Raises:
        InvalidInputError: If ``mitdb_records`` does not hold records 118 and 119 exactly
            once each (checked before any record is loaded), or if the evaluation of a
            record rejects its input.
    """
    clean = _clean_counts(mitdb_records)
    records = evaluate_records(
        nstdb_dir, NOISE_STRESS_RECORDS, settings, detector=detector, loader=loader
    )
    snrs = sorted({snr_db(name) for name in NOISE_STRESS_RECORDS}, reverse=True)
    by_snr = tuple(
        SnrStatistics(
            snr_db=snr,
            statistics=aggregate_statistics(
                [
                    evaluation.counts
                    for name, evaluation in zip(NOISE_STRESS_RECORDS, records, strict=True)
                    if snr_db(name) == snr
                ]
            ),
        )
        for snr in snrs
    )
    return NoiseStressResults(
        nstdb=nstdb,
        records=records,
        by_snr=by_snr,
        clean=aggregate_statistics(clean),
    )


def _clean_counts(mitdb_records: Sequence[RecordEvaluation]) -> list[RecordCounts]:
    """The counts of records 118 and 119, in the order of :data:`CLEAN_RECORDS`."""
    counts: list[RecordCounts] = []
    for name in CLEAN_RECORDS:
        found = [evaluation for evaluation in mitdb_records if evaluation.record == name]
        if len(found) != 1:
            raise InvalidInputError(
                f"the noise stress comparison needs record {name} of the MIT-BIH Arrhythmia "
                f"Database once among the evaluated records; it is there {len(found)} times"
            )
        counts.append(found[0].counts)
    return counts
