# Software Requirements Specification

_Inspired by IEC 62304 §5.2. Version 0.1, 2026-09-28. Status: draft (Milestone 0)._

## Conventions

- Each requirement is a heading of the form `### SRS-001: Short title`, followed by its text, rationale, and related risk-control IDs (see `risk-analysis.md`).
- IDs are never reused or renumbered. A removed requirement keeps its heading, marked as _Deleted_.
- Code that implements a requirement cites its ID in a comment or docstring.
- Tests that verify a requirement are marked with `@pytest.mark.requirement("SRS-001")`.
- `docs/regulatory/traceability.md` is generated from these sources by `dsp/scripts/traceability.py`.
- "Software item" names which item implements the requirement (see `sdp.md` §1).
- "Verification level" assigns the functional verification: `Requirement` tests are written by QA in `dsp/tests/requirements/`, `System` tests by the test engineer in `dsp/tests/system/` (see `sdp.md` §6). The implementer never verifies their own code functionally.

## Scope of this version

This version covers the Milestone 1 software item only: the offline DSP reference implementation and its validation pipeline (`dsp/`). Requirements for firmware, app and backend are added at the milestones that introduce them.

## Requirements

### SRS-001: Verified download of the reference database

**Software item:** dsp (scripts)
**Statement:** The software shall download version 1.0.0 of the MIT-BIH Arrhythmia Database from PhysioNet into a local data directory. It shall verify every downloaded file against the SHA-256 checksums published by PhysioNet, and shall fail with an error naming each missing or mismatching file.
**Rationale:** Validation results are only meaningful on intact, known reference data (README goal 4: reproducibility).
**Verification level:** Requirement (QA)
**Verification:** Test. With a local fixture of files and checksums (no network), an intact set passes, while a set with one altered and one missing file fails with an error naming both files.
**Risk controls:** RC-004.

### SRS-002: Loading a reference record

**Software item:** dsp
**Statement:** Given a record name and a channel index, the software shall return:
- the ECG signal of that channel in millivolts;
- its sampling frequency in Hz;
- the reference beat annotations (sample index and beat label), excluding non-beat annotations such as rhythm changes and signal-quality marks.

**Rationale:** Every algorithm and evaluation consumes records through one interface, so all of them see the same data.
**Verification level:** Requirement (QA)
**Verification:** Test on a synthetic WFDB record written by the test. The returned signal, sampling frequency and beat annotations equal the written ones, and the non-beat annotations are absent.
**Risk controls:** none.

### SRS-003: Input validation

**Software item:** dsp
**Statement:** The software shall reject, with an explicit error and without producing any detections, an input signal that:
- contains non-finite values (NaN or ±infinity);
- is shorter than 10 s;
- or has a sampling frequency outside 100–1000 Hz.

**Rationale:** Meaningless input must not produce output that looks valid.
**Verification level:** Requirement (QA)
**Verification:** Test. Each invalid case raises an error and returns no detections. A valid signal at 100 Hz and at 1000 Hz, 10 s long, is accepted.
**Risk controls:** RC-003.

### SRS-004: Baseline wander removal

**Software item:** dsp
**Statement:** The software shall provide a baseline wander filter that attenuates sinusoidal components at 0.1 Hz and below by at least 20 dB. Components between 1 Hz and 40 Hz shall change in amplitude by no more than ±0.5 dB.
**Rationale:** Baseline wander (respiration, electrode motion) distorts the waveform and causes false detections.
**Verification level:** Requirement (QA)
**Verification:** Test with sinusoids at 360 Hz sampling: 0.05 Hz and 0.1 Hz (attenuation ≥ 20 dB); 1, 5, 10, 20 and 40 Hz (gain within ±0.5 dB). Gain is measured after the filter transient.
**Risk controls:** RC-002.

### SRS-005: Mains interference removal

**Software item:** dsp
**Statement:** The software shall provide a mains interference filter configurable for 50 Hz or 60 Hz. It shall attenuate a sinusoid at the configured frequency by at least 30 dB. Components between 1 Hz and 40 Hz shall change in amplitude by no more than ±0.5 dB.
**Rationale:** Mains interference is common in ECG recordings. MIT-BIH was recorded on 60 Hz mains, while the Sinus device will be used on 50 Hz mains.
**Verification level:** Requirement (QA)
**Verification:** Test at 360 Hz sampling for both settings: attenuation at the configured frequency is ≥ 30 dB, and gain at 1, 5, 10, 20 and 40 Hz is within ±0.5 dB.
**Risk controls:** RC-002.

### SRS-006: QRS detection

**Software item:** dsp
**Statement:** For an input accepted by SRS-003, the software shall output the sample index of each detected QRS complex, in strictly increasing order, with no two detections closer than 200 ms.
**Rationale:** Beat positions are the basis of heart rate, HRV and beat classification. 200 ms is the physiological refractory period.
**Verification level:** Requirement (QA)
**Verification:** Test on a synthetic ECG with known beat positions, at 360 Hz and at 250 Hz. Every known beat is detected within 150 ms, there are no extra detections, and the output order and minimum spacing hold.
**Risk controls:** RC-001.

### SRS-007: QRS detection performance

**Software item:** dsp
**Statement:** On all 48 records of the MIT-BIH Arrhythmia Database (first channel), evaluated as specified in SRS-008, QRS detection shall achieve a gross sensitivity (Se) of at least 99.5% and a gross positive predictive value (+P) of at least 99.5%.
**Rationale:** Quantified detection performance is the main control against missed and false beats. The target is close to the results published for Pan–Tompkins (Se 99.76%, +P 99.56%).
**Verification level:** System (test engineer)
**Verification:** Analysis, from the validation report generated per SRS-009. A test that requires the local database checks both thresholds; it is skipped in CI, where the database is not available, and its result is recorded in the milestone's validation report.
**Risk controls:** RC-001.

### SRS-008: EC57 beat-by-beat evaluation

**Software item:** dsp
**Statement:** The software shall compare detected beats with reference beat annotations beat by beat, following ANSI/AAMI EC57:
- A detection matches a reference beat if it lies within 150 ms of it, and each detection and each reference beat is matched at most once.
- The first 5 minutes of each record are excluded from scoring.

It shall report, per record, true positives, false negatives, false positives, Se and +P. For the whole set it shall report gross Se and +P (from summed counts) and average Se and +P (mean of per-record values).
**Rationale:** A standard scoring method makes the results comparable with published work and hard to inflate unintentionally.
**Verification level:** Requirement (QA)
**Verification:** Test with synthetic reference and detection lists whose correct counts are known. The cases cover: matches at exactly 150 ms and just beyond; two detections near one reference beat; beats inside the first 5 minutes; and gross versus average statistics.
**Risk controls:** RC-004.

### SRS-009: Reproducible validation report

**Software item:** dsp (scripts)
**Statement:** A single command shall run QRS detection and the SRS-008 evaluation on the reference database and write the complete report to `docs/validation/`. Two runs on the same inputs and software version shall produce byte-identical reports.
**Rationale:** Anyone can re-run every published result (README goal 4). Byte-identical output makes any change in results visible in version control.
**Verification level:** Requirement (QA)
**Verification:** Test. The report is generated twice from fixture records, and the two outputs are compared byte for byte.
**Risk controls:** RC-004.
