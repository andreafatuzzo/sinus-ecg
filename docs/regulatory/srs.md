# Software Requirements Specification

_Inspired by IEC 62304 §5.2. Version 0.2, 2026-09-28. Status: draft (Milestone 0)._

## Conventions

- Each requirement is a heading of the form `### SRS-001: Short title`, followed by its text, rationale, and related risk-control IDs (see `risk-analysis.md`).
- IDs are never reused or renumbered. A removed requirement keeps its heading, marked as _Deleted_.
- Code that implements a requirement cites its ID in a comment or docstring.
- Tests that verify a requirement are marked with `@pytest.mark.requirement("SRS-001")`.
- `docs/regulatory/traceability.md` is generated from these sources by `dsp/scripts/traceability.py`.
- "Software item" names which item implements the requirement (see `sdp.md` §1).
- "Verification level" assigns the functional verification: `Requirement` tests are written by QA in `dsp/tests/requirements/`, `System` tests by the test engineer in `dsp/tests/system/` (see `sdp.md` §6). The implementer never verifies their own code functionally.
- Requirements are derived from the features in [`functional-analysis.md`](functional-analysis.md).

## Scope of this version

This version covers the Milestone 1 software item only: the offline DSP reference implementation and its validation pipeline (`dsp/`), features F1.1 to F1.9 of the functional analysis. Requirements for firmware, app and backend are added at the milestones that introduce them.

## Revision history

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-28 | First draft: SRS-001 to SRS-009 |
| 0.2 | 2026-09-28 | Review against the functional analysis (OP-019). Changed SRS-001 to SRS-004 and SRS-006 to SRS-009; SRS-005 verification extended to 250 Hz; SRS-003 lower sampling-frequency bound raised to 125 Hz. Added SRS-010 (detection with interference), SRS-011 (detection statistics, split from SRS-008) and SRS-012 (validation report content, split from SRS-009) |

## Requirements

### SRS-001: Verified download of the reference database

**Software item:** dsp (scripts)
**Statement:** The software shall obtain version 1.0.0 of the MIT-BIH Arrhythmia Database from PhysioNet into a local data directory, and verify every file listed in the SHA-256 checksum list that PhysioNet publishes for that version. If any listed file is missing or its checksum does not match, the software shall report the database as not verified, with an error naming each such file.
**Rationale:** Validation results are only meaningful on intact, known reference data (README goal 4: reproducibility).
**Verification level:** Requirement (QA)
**Verification:** Test, without network. With a local fixture of files and a checksum list, an intact set is reported as verified; a set with one altered and one missing file is reported as not verified, with an error naming both files. The download from PhysioNet itself is exercised by the system run of SRS-007.
**Risk controls:** RC-004.

### SRS-002: Loading a reference record

**Software item:** dsp
**Statement:** For a given record and channel, the software shall provide:
- the ECG signal of that channel in millivolts;
- its sampling frequency in Hz;
- the reference beat annotations, as sample index and label, restricted to the PhysioNet beat annotation codes N, L, R, B, A, a, J, S, V, r, F, e, j, n, E, /, f, Q and ?;
- all other annotations (e.g. rhythm changes, signal-quality marks, ventricular flutter episodes), separately from the beat annotations.

**Rationale:** Every algorithm and evaluation consumes records the same way, so all of them see the same data. Non-beat annotations are kept because the evaluation may need them (SRS-008).
**Verification level:** Requirement (QA)
**Verification:** Test on a synthetic WFDB record written by the test, with beat annotations of several codes and non-beat annotations (a rhythm change and a signal-quality mark). The returned signal equals the written one within one quantization step of the record; the sampling frequency is equal; the beat annotations are equal and contain no non-beat annotation; every non-beat annotation is returned in the separate list.
**Risk controls:** none.

### SRS-003: Input validation

**Software item:** dsp
**Statement:** Before filtering or detection, the software shall reject, with an explicit error and without producing a filtered signal or detections, an input that:
- is empty or contains non-finite values (NaN or ±infinity);
- is shorter than 10 s;
- or has a sampling frequency that is not finite or lies outside 125–1000 Hz (bounds included).

**Rationale:** Meaningless input must not produce output that looks valid. 10 s holds at least five beats at 30 bpm, the minimum for detection to establish its signal level. 125 Hz keeps the 60 Hz mains frequency below the Nyquist limit; 1000 Hz covers common ECG front ends. The device sampling rate is still open (OP-004).
**Verification level:** Requirement (QA)
**Verification:** Test, for the filters of SRS-004 and SRS-005 and the detection of SRS-006. Rejected with an error and no output: an empty input; an input with one NaN, one with +infinity and one with −infinity; 9.99 s; 124.9 Hz; 1000.1 Hz; a non-finite sampling frequency. Accepted: 10 s at 125 Hz and at 1000 Hz.
**Risk controls:** RC-003.

### SRS-004: Baseline wander removal

**Software item:** dsp
**Statement:** The software shall provide a baseline wander filter that attenuates a constant offset and sinusoidal components at 0.1 Hz and below by at least 20 dB, while components between 1 Hz and 40 Hz change in amplitude by no more than ±0.5 dB.
**Rationale:** Baseline wander (respiration, electrode motion) and electrode offset distort the waveform and cause false detections.
**Verification level:** Requirement (QA)
**Verification:** Test at 360 Hz and at 250 Hz sampling. Attenuation is at least 20 dB for a 1 mV constant offset and for sinusoids at 0.05 Hz and 0.1 Hz; gain is within ±0.5 dB at 1, 5, 10, 20 and 40 Hz. Each input lasts at least ten periods of its frequency (60 s for the offset), and amplitude is measured on its second half.
**Risk controls:** RC-002.

### SRS-005: Mains interference removal

**Software item:** dsp
**Statement:** The software shall provide a mains interference filter configurable for 50 Hz or 60 Hz. It shall attenuate a sinusoid at the configured frequency by at least 30 dB. Components between 1 Hz and 40 Hz shall change in amplitude by no more than ±0.5 dB.
**Rationale:** Mains interference is common in ECG recordings. MIT-BIH was recorded on 60 Hz mains, while the Sinus device will be used on 50 Hz mains. Tolerance to deviations of the mains frequency is left to the live-use analysis (OP-022).
**Verification level:** Requirement (QA)
**Verification:** Test at 360 Hz and at 250 Hz sampling, for both settings: attenuation at the configured frequency is at least 30 dB, and gain at 1, 5, 10, 20 and 40 Hz is within ±0.5 dB. Each input lasts at least ten periods of its frequency, and amplitude is measured on its second half.
**Risk controls:** RC-002.

### SRS-006: QRS detection

**Software item:** dsp
**Statement:** For an input accepted by SRS-003, the software shall output the sample indices of the detected QRS complexes, in the time base of the input (index 0 = first input sample), such that each index lies within 150 ms of the QRS complex it represents, indices are strictly increasing, and no two indices are closer than 200 ms.
**Rationale:** Beat positions are the basis of heart rate, HRV and beat classification, and are scored against reference annotations on the input time base (SRS-008). 200 ms is the physiological refractory period (at most 300 bpm).
**Verification level:** Requirement (QA)
**Verification:** Test on synthetic ECGs with known QRS positions, at 360 Hz and at 250 Hz, at 40, 75 and 180 bpm. Every known QRS has exactly one detection within 150 ms, there are no other detections, and the order and minimum spacing hold. A flat input of 10 s produces no detections and no error.
**Risk controls:** RC-001.

### SRS-007: QRS detection performance

**Software item:** dsp
**Statement:** On all 48 records of the MIT-BIH Arrhythmia Database, using the first stored signal of each record and the mains interference filter set to 60 Hz, and evaluated as specified in SRS-008 and SRS-011, QRS detection shall achieve a gross sensitivity (Se) of at least 99.5% and a gross positive predictive value (+P) of at least 99.5%.
**Rationale:** Quantified detection performance is the main control against missed and false beats. The target is close to the results published for Pan–Tompkins (Se 99.76%, +P 99.56%). The first stored signal is MLII in 46 records and a modified V5 in records 102 and 104.
**Verification level:** System (test engineer)
**Verification:** Analysis, from the validation report generated per SRS-009 and SRS-012. A test that requires the local database checks both thresholds; it is skipped in CI, where the database is not available, and its result is recorded in the milestone's validation report.
**Risk controls:** RC-001.

### SRS-008: EC57 beat-by-beat matching

**Software item:** dsp
**Statement:** The software shall match detected beats to reference beat annotations beat by beat, following ANSI/AAMI EC57:
- a detection and a reference beat can match if they are at most 150 ms apart;
- each detection and each reference beat belongs to at most one match, and the number of matches is the largest possible under these rules;
- reference beats in the first 5 minutes of the record, and detections in the first 5 minutes that do not match a scored reference beat, are not scored;
- a scored reference beat without a match is a false negative; a scored detection without a match is a false positive.

**Rationale:** A standard scoring method makes the results comparable with published work and hard to inflate unintentionally.
**Verification level:** Requirement (QA)
**Verification:** Test with synthetic reference and detection lists whose correct counts are known. The cases cover: detections at exactly 150 ms and at 150 ms plus one sample; two detections near one reference beat; one detection between two reference beats that are both within 150 ms of it; reference beats just before and at 5:00; an empty detection list; an empty reference list.
**Risk controls:** RC-004.

### SRS-009: Reproducible validation report

**Software item:** dsp (scripts)
**Statement:** A single command shall run QRS detection and the evaluation of SRS-008 and SRS-011 on the reference database and write the report specified in SRS-012 to `docs/validation/`. Two runs on the same inputs and software version shall produce byte-identical reports.
**Rationale:** Anyone can re-run every published result (README goal 4). Byte-identical output makes any change in results visible in version control.
**Verification level:** Requirement (QA)
**Verification:** Test. The report is generated twice from fixture records, and the two outputs are compared byte for byte.
**Risk controls:** RC-004.

### SRS-010: QRS detection with baseline wander and mains interference

**Software item:** dsp
**Statement:** The software shall meet the criteria of SRS-006 on an ECG with 1 mV QRS amplitude to which a 0.3 Hz sinusoidal baseline wander of 1 mV amplitude and a sinusoid at the configured mains frequency (50 Hz or 60 Hz) of 0.2 mV amplitude have been added.
**Rationale:** Baseline wander and mains interference are the most common artefacts in ECG recordings and cause missed and false beats (HAZ-001, HAZ-002). This checks the effect of RC-002 on detection, whatever the internal processing.
**Verification level:** Requirement (QA)
**Verification:** Test on the synthetic ECGs of SRS-006, at 360 Hz and at 250 Hz, with the interference added and the mains setting matching it (one case at 50 Hz and one at 60 Hz): the pass criteria of SRS-006 hold.
**Risk controls:** RC-002.

### SRS-011: Detection statistics

**Software item:** dsp
**Statement:** From the matches of SRS-008, the software shall report for each record the true positives (TP), false negatives (FN), false positives (FP), Se = TP / (TP + FN) and +P = TP / (TP + FP) in percent; and for the set of records, gross Se and +P computed from the summed counts, and average Se and +P as the mean of the per-record values. A value whose denominator is zero shall be reported as not defined, and excluded from the averages.
**Rationale:** EC57 reports both gross and average statistics. Undefined values must not appear as 0% or 100%.
**Verification level:** Requirement (QA)
**Verification:** Test with per-record counts whose statistics are known, including a record with TP + FN = 0. Per-record, gross and average values equal the expected ones to within 0.01 percentage points, and the undefined value is reported as not defined and excluded from the averages.
**Risk controls:** RC-004.

### SRS-012: Validation report content

**Software item:** dsp (scripts)
**Statement:** The validation report shall contain:
- the per-record and aggregate statistics of SRS-011;
- the five records with the lowest Se and the five records with the lowest +P (ties ordered by record name);
- the pass or fail of each SRS-007 threshold;
- the database name and version, and the outcome of its SRS-001 verification;
- the software version and the settings used (channel, mains frequency);
- the statement "Technical evaluation only. Sinus is not a medical device; these results are not a clinical validation."

The report shall not be written if the SRS-001 verification fails.
**Rationale:** A reader must be able to tell what was measured, on which data and software, where performance is weakest, and what the results do not mean (HAZ-004, HAZ-010).
**Verification level:** Requirement (QA)
**Verification:** Test with fixture records. The report contains each listed item, with values matching the fixture and the worst records in the expected order. With a fixture database that fails verification, no report is written and an error is raised.
**Risk controls:** RC-004, RC-005, RC-011.
