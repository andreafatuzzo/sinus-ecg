# Software Requirements Specification

_Inspired by IEC 62304 §5.2. Version 0.9.1, 2026-10-11. Status: version 0.9 (Milestone 3 requirements SRS-039 to SRS-054 and the amendment of SRS-029) decided and confirmed by the project owner on 2026-10-11; version 0.9.1 clarifies SRS-045 (pause of a replay). Version 0.8 confirmed by the project owner on 2026-10-07 (Milestone 2 requirements SRS-017 to SRS-038, and the changes to SRS-003 and SRS-007). The equivalence tolerances of SRS-034 (OP-005) and the memory limit of SRS-032 (OP-049) were approved by the project owner on 2026-10-08. The changes of version 0.8.1 to SRS-022, SRS-029 and SRS-030 were decided by the project owner on 2026-10-07; its clarifications of SRS-023, SRS-024, SRS-026, SRS-027 and SRS-033 were confirmed by the project owner on 2026-10-08. The change of version 0.8.3 to SRS-023 was decided by the project owner on 2026-10-09; version 0.8.4 records the status of SRS-029 at the Milestone 2 release (no change to any requirement)._

## Conventions

- Each requirement is a heading of the form `### SRS-001: Short title`, followed by its text, rationale, and related risk-control IDs (see `risk-analysis.md`).
- IDs are never reused or renumbered. A removed requirement keeps its heading, marked as _Deleted_.
- Code that implements a requirement cites its ID in a comment or docstring.
- Tests that verify a requirement are marked with `@pytest.mark.requirement("SRS-001")` (Python) or preceded by a `// Verifies: SRS-001` line directly above the GoogleTest macro (C++), as set out in ADR 0004.
- `docs/regulatory/traceability.md` is generated from these sources by `dsp/scripts/traceability.py`.
- "Software item" names which item implements the requirement (see `sdp.md` §1).
- "Verification level" assigns the functional verification: `Requirement` tests are written by QA in `<item>/tests/requirements/`, `System` tests by the test engineer in `<item>/tests/system/` (for example `dsp/tests/…`, `libs/sinus-dsp/tests/…`) (see `sdp.md` §6). The implementer never verifies their own code functionally.
- "Milestone" names the roadmap milestone (`README.md`) that delivers the requirement. A pull request into `main` fails CI unless every requirement of a milestone that is in progress or released (see [`milestones.md`](milestones.md)) has a verifying test ([ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md)). A requirement implemented by several software items (several names on its "Software item" line, other than `CI workflow`) needs a verifying test in each of them ([ADR 0006](../adr/0006-verification-per-software-item.md)); the script reads the "Software item" line, so it must name the items exactly.
- Requirements are derived from the features in [`functional-analysis.md`](functional-analysis.md).

## Scope of this version

This version covers:
- Milestone 1: the offline DSP reference implementation and its validation pipeline (`dsp/`), features F1.1 to F1.12 of the functional analysis (SRS-001 to SRS-016);
- Milestone 2: the portable real-time signal-processing library (`libs/sinus-dsp/`) and the reference functions and validation it is checked against, features F2.5, F2.7, F2.8, F2.9, F3.4 and F2.10 of the functional analysis (SRS-017 to SRS-038);
- Milestone 3: the desktop application (`desktop/`) with replay, a test input, the live view, session recording and identification, the display low-pass stage of the reference and the library, and the check of the mains interference removal under a deviation of the mains frequency, features F2.4, F3.1 to F3.3, F3.6 to F3.14 of the functional analysis (SRS-039 to SRS-054). The amendment of SRS-029 (median criterion) is part of this version. The desktop application is verified on Windows and on Linux in Milestone 3; macOS is not (OP-080).

Requirements for the firmware (Milestone 4), the backend (Milestone 5) and beat classification (Milestone 6) are added at the milestones that introduce them, from the features listed for them in [`functional-analysis.md`](functional-analysis.md) §5.

Terms used by the Milestone 3 requirements:
- **The application** is the desktop application; **the library** is the real-time library `libs/sinus-dsp/`, with which the application computes every result it displays.
- A **source** is where the stream comes from: a replay, the test input, or (Milestone 4) the device. One source feeds the application at a time.
- The **signal status** is the state "usable" or "not usable" of SRS-045; a **withheld** heart rate is one that the application shows as "--" with its reason.

Terms used by the Milestone 2 requirements:
- **The reference** is the offline implementation in `dsp/`; **the real-time library** is `libs/sinus-dsp/`.
- A **stream** is the sequence of samples given to the real-time library since its configuration or its last reset; its first sample has index 0. For the reference, the input of one call plays the role of a stream.
- A **delay** is counted from the moment the real-time library has been given the sample concerned to the moment it reports the output, as a number of samples given, converted to seconds with the sampling frequency.
- A value written `[OP-xxx: …]` is a figure that the tech lead proposes with the detailed design and the project owner approves; the open point tracks it until then. The requirement that contains it is confirmed, and its verification cannot pass before the figure is set. (No requirement contains such a value in version 0.8.2.)

## Revision history

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-28 | First draft: SRS-001 to SRS-009 |
| 0.2 | 2026-09-28 | Review against the functional analysis (OP-019). Changed SRS-001 to SRS-004 and SRS-006 to SRS-009; SRS-005 verification extended to 250 Hz; SRS-003 lower sampling-frequency bound raised to 125 Hz. Added SRS-010 (detection with interference), SRS-011 (detection statistics, split from SRS-008) and SRS-012 (validation report content, split from SRS-009) |
| 0.3 | 2026-09-29 | Scope aligned with functional analysis v0.2 (new roadmap, features F1.10 to F1.12). Added SRS-013 (verified download of the noise stress test database), SRS-014 (detection performance versus signal-to-noise ratio), SRS-015 (golden-vector export) and SRS-016 (subset validation report in continuous integration). SRS-001 to SRS-012 unchanged. Confirmed by the project owner on 2026-09-29 |
| 0.4 | 2026-09-29 | Aligned with the approved detailed design (closes OP-053). SRS-008: EC57 scoring with the rules of the WFDB comparator `bxb`, decided by the project owner on 2026-09-29: sequential pairing in time order instead of a maximum matching, `bxb`'s rules at 5:00, ventricular flutter and fibrillation episodes not scored; rationale and verification cases updated. SRS-002: rationale states the use of the `[` and `]` annotations; verification includes them. SRS-005: verification inputs last at least 2 s. SRS-016: rationale no longer refers to an undecided point. Confirmed by the project owner on 2026-09-29 |
| 0.4.1 | 2026-09-30 | SRS-012: the report also states what was not scored (ventricular flutter and fibrillation episodes, beats and detections excluded), as decided by the project owner. Version 0.4 and this change confirmed by the project owner |
| 0.5 | 2026-09-30 | Decisions of the project owner on the open points raised while implementing Milestone 1. SRS-002: a channel that the record does not have, and signal units other than mV, are rejected with an explicit error; verification cases added (closes OP-060; the error behaviours of SRS-008 and SRS-011 stay design behaviours, verified by unit tests). SRS-005: a mains setting other than 50 Hz or 60 Hz is rejected with an explicit error; verification cases added (closes OP-054). SRS-006: exactly one index per QRS complex is required for a noise-free input with a heart rate between 30 and 200 bpm; verification adds 30 and 200 bpm; rationale gives the reason for the range (closes OP-055). SRS-010: states the heart-rate range of SRS-006 and the one-index-per-QRS criterion explicitly; verification at the heart rates of SRS-006 (OP-055). SRS-008: the samples of the onset and offset annotations belong to an episode for detections too; verification adds an episode without an offset annotation (OP-059). SRS-012: the figures on what was not scored cover the part of each record from 5:00 to its end: episodes in the record, episodes that reach 5:00 or later, their duration from 5:00, and the reference beats and unpaired detections inside them; rationale and verification updated (closes OP-059). Confirmed by the project owner on 2026-09-30 |
| 0.6 | 2026-10-01 | Decisions of the project owner on the first Milestone 1 validation results. SRS-002: a header that states no units for the channel means mV; rationale and verification updated; risk control RC-003 linked. SRS-005: risk control RC-003 linked. SRS-006: the range of 30 to 200 bpm applies to a regular rhythm, and the rationale states why; the 150 ms criterion concerns the position of each detected QRS complex, and false detections are measured by SRS-007. SRS-007: rationale corrected, the first stored signal is MLII in 45 records and a modified V5 in records 102, 104 and 114. SRS-010: a regular rhythm between 30 and 200 bpm, as in SRS-006. SRS-012: the lowest-value lists contain only records whose value is defined, a threshold whose value is not defined is reported as fail, a sample shared by two episodes counts once in their duration, and the number of episodes in the record covers the whole record; rationale updated; verification adds an episode that contains 5:00, a detection left unscored by the rule at 5:00 inside an episode, and these three cases. Confirmed by the project owner on 2026-10-01 |
| 0.7 | 2026-10-03 | Decisions of the project owner on the software identity of `dsp` (OP-061, `sdp.md` §4) and on SRS-006. SRS-012 and SRS-015: the report and each golden-vector file state the software version with an identifier of the source code that produced them, because the version stays the same while a milestone is developed; their verification compares the identifier with one computed by the test itself. SRS-012: the report also states the versions of the third-party software used at run time, and its verification compares them with those of the environment that runs the test; rationale updated. SRS-009 and SRS-015: byte-identical output is required for the same software version and source code and the same versions of the third-party software used, and for SRS-015 on the same computer, as in the approved design (`architecture.md` §7.4, §8.10); rationales updated. SRS-006: an input of constant value (a flat line) gives an output with no index, so that the verification case with a flat input follows from the statement; rationale updated. Confirmed by the project owner on 2026-10-03 |
| 0.7.1 | 2026-10-05 | Decisions of the project owner on the verification of the subset records, as in the approved design (`architecture.md` §7.2, §8.3, §8.11, §8.12). SRS-016: the subset report states the outcome of the verification of the files of the six records, in place of the outcome of the SRS-001 verification, which covers the whole database that the build does not obtain; no subset report is written if that verification fails, as its verification already checked. SRS-015: the record segments are written where the files of the records of the SRS-016 subset are available and verified against the checksum list of SRS-001, instead of "where the verified database is available". Verifications unchanged. Confirmed by the project owner on 2026-10-05 |
| 0.7.2 | 2026-10-05 | Licence of the databases in the reports (OP-064). SRS-012 and SRS-014: the report states the licence under which each database used is published, with the address of the licence text, because a work produced from a database and used publicly must carry a notice that its content comes from the database and is available under that licence (Open Data Commons Attribution License v1.0, §4.3); rationales and verifications updated. SRS-016 includes the item through the items of SRS-012, unchanged. Decided by the project owner on 2026-10-05. SRS-015: the record segments are written for all six records of the subset of SRS-016 or for none of them, as in the approved design (`architecture.md` §7.2, §8.12); its verification names the case of one record whose files fail verification; confirmed by the project owner on 2026-10-05 |
| 0.8 | 2026-10-07 | Milestone 2 requirements, from functional analysis v0.3, with the decisions of the project owner of 2026-10-07 on OP-005, OP-021, OP-031, OP-032, OP-049, OP-056, OP-063, OP-067, OP-068 and OP-070. Added SRS-017 to SRS-038 for the portable real-time library and the reference functions it is checked against: configuration checks and invalid samples (SRS-017, SRS-018); signal conditioning, streaming detection and its delay (SRS-019 to SRS-021); start-up marks of detections and detection at the start of real recordings (SRS-022, SRS-023; OP-068); heart rate (SRS-024 to SRS-026; OP-021); signal quality index, its validation on the noise stress records and the new report sections (SRS-027 to SRS-030; OP-032); restart and fixed memory (SRS-031, SRS-032); golden vectors of the new functions and equivalence with the reference on the computer, on every push, on the ESP32-S3 and on the whole reference databases (SRS-033 to SRS-038; OP-005). The tolerances of SRS-034 (OP-005) and the memory limit of SRS-032 (OP-049) are figures that the tech lead proposes with the detailed design, for approval by the project owner. Adaptive interference reduction (F2.6) moves to Milestone 4, and the removal of high-frequency noise to the displayed waveform of Milestone 3 (OP-070), so neither has a requirement in this version. SRS-003: an input that contains a sample whose magnitude exceeds 1000 mV is also rejected, as by the real-time library (SRS-018; OP-063). **This changes a requirement released with Milestone 1**: the reference and the requirement tests of SRS-003 must be updated, and SRS-003 verified again, in Milestone 2. SRS-007: its verification result is recorded in the milestone verification report, the report written at the release of each milestone (OP-069). Confirmed by the project owner on 2026-10-07, except the figures of OP-005 and OP-049 named above |
| 0.8.1 | 2026-10-07 | Readings of the approved Milestone 2 design of `dsp` (`architecture.md` v0.3, §13). Decided by the project owner on 2026-10-07: SRS-022, the verification of the start-up mark after detection learns its signal levels again uses the synthetic input documented in `architecture.md` §13.9, in which one beat 20 times larger than the others makes detection miss beats until it learns its levels again, and requires at least one detection in the 2 s from which the levels are learned again; the input it named before, a flat stretch followed by the ECG, leaves that stretch without detections, so the check passed without testing the mark. SRS-029: each criterion names the windows it is computed on, each signal-to-noise ratio (over its two records) and each noise record on its own, records 118 and 119 together, and a window from 5:00 starts at or after 5:00; SRS-030 uses the same terms. Clarifications that state the readings of the approved design, confirmed by the project owner on 2026-10-08: SRS-023, only the detections marked reliable are scored, so a reference beat after the start-up period found only by a detection marked start-up is a false negative, and the reference beats and episodes of each segment are those of its record that lie in it; SRS-024 and SRS-033, the heart rate is also reported when the reason for which it is withheld changes; SRS-026, "not enough beats" holds from the first sample of the stream, a detection counts from the sample at which it is reported, the new intervals after "no recent beat" are those whose detections have their index after its start, "no recent beat" is the reason when both reasons apply, the verification gives each detection at the sample of its index and checks a stretch without detections while "not enough beats" holds, and the rationale states why a stretch a little shorter than 3 s can also give "no recent beat"; SRS-027, at a sampling frequency that is not a whole number of hertz, the spacing of 1 s is rounded to a whole number of samples and a window lasts ten spacings. The heart rate in irregular rhythms, which no requirement specifies, is tracked by OP-073 (Milestone 6) |
| 0.8.2 | 2026-10-08 | Figures of the detailed design of the Milestone 2 library, approved by the project owner on 2026-10-08 with architecture version 0.4 (ADR 0006, 0007, 0008). SRS-032: memory of one processing chain at most 64 KiB (65 536 bytes) (OP-049). SRS-034: tolerances of 2e-5 mV for each conditioning stage, 0 samples for the index of a detection, 1e-4 bpm for a heart rate and 0.01 for the index of a signal quality window (OP-005); the report sample of a detection is added to the compared outputs, with a tolerance of 0 samples; the rationale states that signal conditioning is computed in binary64 (ADR 0008). Conventions: a requirement implemented by several software items needs a verifying test in each of them (ADR 0006). No requirement contains a placeholder figure any more |
| 0.8.3 | 2026-10-09 | SRS-023 (decided by the project owner on 2026-10-09, correction of the evaluation method): each segment is processed with a continuation on its record for the documented maximum delay of a detection, or to the end of the record; only the reference beats and the detections whose index lies in the segment are scored; rationale states the correction. `architecture-m2.md` §13.7.2 (v0.4.3) |
| 0.8.4 | 2026-10-11 | SRS-029: status at the Milestone 2 release, not met on three criteria, accepted as a known anomaly by the project owner on 2026-10-11 (OP-074). No change to any statement, criterion or verification |
| 0.9 | 2026-10-11 | Milestone 3 requirements SRS-039 to SRS-054 and the amendment of SRS-029, decided by the project owner on 2026-10-11, to be confirmed by the project owner. Added: replay source, replay gives the results of the library, data source indication, test input, live waveform with beat marks, display low-pass, signal status, heart-rate display, data interruption, signal quality mark, intended-use statement, mains frequency setting, session recording, identification, accessible text, and mains interference removal under a deviation of the mains frequency (OP-007, OP-015, OP-020, OP-022, OP-037, OP-070, OP-071, OP-072, OP-076 for the desktop application). SRS-029: the median criterion is replaced by "the median index is above the usable threshold at 24 dB and below it at 0 dB and −6 dB"; the 6 dB and electrode-motion criteria are unchanged and stay a known anomaly (OP-074, Milestone 6). Platforms: scope stated above (OP-080) |
| 0.9.1 | 2026-10-11 | Version 0.9 confirmed by the project owner. SRS-045: the 1 s rule on arriving samples applies while the source is playing; a paused replay shows "replay paused" and resumes without a restart (clarification from the design, `architecture-m3.md` §15.8) |

## Requirements

### SRS-001: Verified download of the reference database

**Software item:** dsp (scripts)
**Milestone:** M1
**Statement:** The software shall obtain version 1.0.0 of the MIT-BIH Arrhythmia Database from PhysioNet into a local data directory, and verify every file listed in the SHA-256 checksum list that PhysioNet publishes for that version. If any listed file is missing or its checksum does not match, the software shall report the database as not verified, with an error naming each such file.
**Rationale:** Validation results are only meaningful on intact, known reference data (README goal 4: reproducibility).
**Verification level:** Requirement (QA)
**Verification:** Test, without network. With a local fixture of files and a checksum list, an intact set is reported as verified; a set with one altered and one missing file is reported as not verified, with an error naming both files. The download from PhysioNet itself is exercised by the system run of SRS-007.
**Risk controls:** RC-004.

### SRS-002: Loading a reference record

**Software item:** dsp
**Milestone:** M1
**Statement:** For a given record and channel, the software shall provide:
- the ECG signal of that channel in millivolts;
- its sampling frequency in Hz;
- the reference beat annotations, as sample index and label, restricted to the PhysioNet beat annotation codes N, L, R, B, A, a, J, S, V, r, F, e, j, n, E, /, f, Q and ?;
- all other annotations (e.g. rhythm changes, signal-quality marks, ventricular flutter episodes), separately from the beat annotations.

If the record does not have the requested channel, or the signal units of that channel, as stated in the record header, are not mV, the software shall reject the request with an explicit error and provide none of the above. Signal units that the record header does not state are mV.

**Rationale:** Every algorithm and evaluation consumes records the same way, so all of them see the same data. Non-beat annotations are kept because the EC57 evaluation excludes ventricular flutter and fibrillation episodes, marked by `[` and `]` annotations, from scoring (SRS-008). Every amplitude in these requirements is in millivolts, and every result must come from the signal that its settings name (SRS-012), so a record in other units, or without the requested channel, is rejected instead of being processed. In the WFDB header format, signal units that are not stated are mV; the headers of the MIT-BIH Arrhythmia and Noise Stress Test databases state none.
**Verification level:** Requirement (QA)
**Verification:** Test on a synthetic WFDB record written by the test, with beat annotations of several codes and non-beat annotations (a rhythm change, a signal-quality mark, and a ventricular flutter onset and offset). The returned signal equals the written one within one quantization step of the record; the sampling frequency is equal; the beat annotations are equal and contain no non-beat annotation; every non-beat annotation is returned in the separate list. The same record with a header that states no units is loaded in the same way, with the signal in mV. Rejected with an error, with no signal or annotations returned: a request for the channel after the last channel of the record, and for a negative channel number; the same record written with signal units of µV.
**Risk controls:** RC-003.

### SRS-003: Input validation

**Software item:** dsp
**Milestone:** M1
**Statement:** Before filtering or detection, the software shall reject, with an explicit error and without producing a filtered signal or detections, an input that:
- is empty, contains non-finite values (NaN or ±infinity), or contains a sample whose magnitude exceeds 1000 mV;
- is shorter than 10 s;
- or has a sampling frequency that is not finite or lies outside 125–1000 Hz (bounds included).

**Rationale:** Meaningless input must not produce output that looks valid. 10 s holds at least five beats at 30 bpm, the minimum for detection to establish its signal level. 125 Hz keeps the 60 Hz mains frequency below the Nyquist limit; 1000 Hz covers common ECG front ends. The device samples at 360 Hz (OP-004, closed), inside this range. 1000 mV is far above any ECG and any electrode offset that a front end passes, so a larger sample can only come from a defect; inputs of extreme amplitude made the filters return non-finite samples, or detection end in an error that no requirement described (OP-063). The real-time library rejects the same samples (SRS-018). The bound was added in Milestone 2, after the release of this requirement with Milestone 1.
**Verification level:** Requirement (QA)
**Verification:** Test, for the filters of SRS-004 and SRS-005 and the detection of SRS-006. Rejected with an error and no output: an empty input; an input with one NaN, one with +infinity and one with −infinity; an input with one sample equal to the smallest float64 value greater than 1000 mV, and one with the negative of that value; 9.99 s; 124.9 Hz; 1000.1 Hz; a non-finite sampling frequency. Accepted: 10 s at 125 Hz and at 1000 Hz; an input of 10 s at 360 Hz that contains samples equal to 1000 mV and to −1000 mV.
**Risk controls:** RC-003.

### SRS-004: Baseline wander removal

**Software item:** dsp
**Milestone:** M1
**Statement:** The software shall provide a baseline wander filter that attenuates a constant offset and sinusoidal components at 0.1 Hz and below by at least 20 dB, while components between 1 Hz and 40 Hz change in amplitude by no more than ±0.5 dB.
**Rationale:** Baseline wander (respiration, electrode motion) and electrode offset distort the waveform and cause false detections.
**Verification level:** Requirement (QA)
**Verification:** Test at 360 Hz and at 250 Hz sampling. Attenuation is at least 20 dB for a 1 mV constant offset and for sinusoids at 0.05 Hz and 0.1 Hz; gain is within ±0.5 dB at 1, 5, 10, 20 and 40 Hz. Each input lasts at least ten periods of its frequency (60 s for the offset), and amplitude is measured on its second half.
**Risk controls:** RC-002.

### SRS-005: Mains interference removal

**Software item:** dsp
**Milestone:** M1
**Statement:** The software shall provide a mains interference filter configurable for 50 Hz or 60 Hz. It shall attenuate a sinusoid at the configured frequency by at least 30 dB. Components between 1 Hz and 40 Hz shall change in amplitude by no more than ±0.5 dB. A setting other than 50 Hz or 60 Hz shall be rejected with an explicit error, without producing a filtered signal.
**Rationale:** Mains interference is common in ECG recordings. MIT-BIH was recorded on 60 Hz mains, while the Sinus device will be used on 50 Hz mains. Tolerance to deviations of the mains frequency is left to the live-use analysis (OP-022). Any other setting is rejected because a filter set to a frequency that is not a mains frequency would leave the interference in the signal while its output looks filtered.
**Verification level:** Requirement (QA)
**Verification:** Test at 360 Hz and at 250 Hz sampling, for both settings: attenuation at the configured frequency is at least 30 dB, and gain at 1, 5, 10, 20 and 40 Hz is within ±0.5 dB. Each input lasts at least ten periods of its frequency and at least 2 s, so that the start-up transient of a narrow mains filter does not affect the measurement, and amplitude is measured on its second half. Settings of 49 Hz, 51 Hz, 59 Hz, 61 Hz and 100 Hz, and a non-finite setting, are each rejected with an error, and no filtered signal is produced.
**Risk controls:** RC-002, RC-003.

### SRS-006: QRS detection

**Software item:** dsp
**Milestone:** M1
**Statement:** For an input accepted by SRS-003, the software shall output the sample indices of the detected QRS complexes, in the time base of the input (index 0 = first input sample), such that the index of each detected QRS complex lies within 150 ms of that complex, indices are strictly increasing, and no two indices are closer than 200 ms. For a noise-free input with a regular rhythm between 30 and 200 bpm (bounds included), the output shall contain exactly one index for each QRS complex and no other indices. For an input of constant value (a flat line), the output shall contain no index.
**Rationale:** Beat positions are the basis of heart rate, HRV and beat classification, and are scored against reference annotations on the input time base (SRS-008). The 150 ms criterion concerns the position of each QRS complex that is detected; it does not by itself exclude indices that mark no QRS complex. Such false detections are excluded for the noise-free input of the second sentence and for a flat line, and measured on real recordings by SRS-007. 200 ms is the physiological refractory period (at most 300 bpm). The range of 30 to 200 bpm covers the heart rates expected in the intended use, an adult at rest or in light activity ([`functional-analysis.md`](functional-analysis.md) §2.3); 30 bpm is also the rate on which the 10 s minimum of SRS-003 is based. The range is stated for a regular rhythm, that is a constant heart rate, so that it bounds every interval between consecutive QRS complexes, from 300 ms at 200 bpm to 2 s at 30 bpm; an irregular rhythm can contain a much shorter interval whatever its average heart rate. Above 200 bpm, one index for each QRS complex is not required: at 300 bpm the QRS complexes are exactly 200 ms apart, so no output could meet both this criterion and the minimum spacing, and between the two rates the result depends on the waveform. A QRS complex that follows the previous one more closely than this range allows, as in a fast ventricular tachycardia or a very early premature beat, can be missed (a cause of HAZ-001); detection performance on real recordings, irregular rhythms included, is measured by SRS-007.
**Verification level:** Requirement (QA)
**Verification:** Test on synthetic ECGs with a regular rhythm and known QRS positions, at 360 Hz and at 250 Hz, at 30, 40, 75, 180 and 200 bpm. Every known QRS has exactly one detection within 150 ms, there are no other detections, and the order and minimum spacing hold. A flat input of 10 s produces no detections and no error.
**Risk controls:** RC-001.

### SRS-007: QRS detection performance

**Software item:** dsp
**Milestone:** M1
**Statement:** On all 48 records of the MIT-BIH Arrhythmia Database, using the first stored signal of each record and the mains interference filter set to 60 Hz, and evaluated as specified in SRS-008 and SRS-011, QRS detection shall achieve a gross sensitivity (Se) of at least 99.5% and a gross positive predictive value (+P) of at least 99.5%.
**Rationale:** Quantified detection performance is the main control against missed and false beats. The target is close to the results published for Pan–Tompkins (Se 99.76%, +P 99.56%). The first stored signal is MLII in 45 records and a modified V5 in records 102, 104 and 114.
**Verification level:** System (test engineer)
**Verification:** Analysis, from the validation report generated per SRS-009 and SRS-012. A test that requires the local database checks both thresholds; it is skipped in CI, where the database is not available, and its result is recorded in the milestone verification report.
**Risk controls:** RC-001.

### SRS-008: EC57 beat-by-beat matching

**Software item:** dsp
**Milestone:** M1
**Statement:** The software shall match detected beats to the reference beat annotations of SRS-002 beat by beat, following ANSI/AAMI EC57 as implemented by the beat-by-beat comparator `bxb` of the WFDB software package:
- a detection and a reference beat can match if they are at most 150 ms apart;
- detections and reference beats are paired in time order. The earlier of the current detection and the current reference beat (the reference beat, if both are at the same sample) is paired with the other if they can match, unless the item that follows the earlier one in its own list is at least as close to the later one as the earlier one is, and is no closer to the item that follows the later one in its list than to the later one. After a pair, the next item of each list becomes current; otherwise the earlier one stays unmatched and the next item of its list becomes current. Each detection and each reference beat belongs to at most one match;
- reference beats before 5:00 (the first 5 minutes of the record) are not scored, and neither are detections before 5:00, except that the last detection before 5:00 is paired with the first scored reference beat if they can match and it is closer to that beat than the next detection is. The first detection at or after 5:00 is not scored if it is at most 150 ms after 5:00 and either the next detection is closer to the first scored reference beat or no reference beat is scored;
- reference beats from a ventricular flutter or fibrillation onset annotation (`[`) to the next offset annotation (`]`), both included, are not scored; an episode without an offset annotation lasts until the end of the record. A detection inside such an episode (the samples of the onset and offset annotations included) that is not paired is not scored; one that is paired with a scored reference beat outside the episode is a match;
- a scored reference beat without a match is a false negative; a scored detection without a match is a false positive.

**Rationale:** A standard scoring method makes the results comparable with published work and hard to inflate unintentionally. Published EC57 results are produced with `bxb`, whose sequential pairing is not a maximum matching; following its rules keeps the counts comparable. Ventricular flutter and fibrillation have no distinct beats to match, so their episodes are left out of beat-by-beat scoring, as in `bxb`. The rules are stated here in full so that they can be verified without `bxb`; in corner cases where `bxb` behaves differently (for example, it rounds the match window above 150 ms at some sampling frequencies), these rules apply.
**Verification level:** Requirement (QA)
**Verification:** Test at 360 Hz with synthetic reference and detection lists whose correct counts are known. Each case checks the pairs, the false negatives, the false positives and the items not scored:
- detections exactly 150 ms and 150 ms plus one sample from a reference beat: paired; not paired;
- two detections near one reference beat: the closer one is paired; two detections equidistant from it, one before and one after: the later one is paired;
- one detection between two reference beats that are both within 150 ms of it: paired with the closer one; one detection equidistant from both: paired with the later one;
- reference beats just before and at 5:00: not scored; scored. The last detection before 5:00, within 150 ms of the first scored reference beat: paired if it is closer to that beat than the next detection, otherwise not scored. The first detection within 150 ms after 5:00, when the next detection is closer to the first scored reference beat: not scored;
- reference beats and an unpaired detection inside a ventricular flutter episode: none of them scored; a detection inside the episode within 150 ms of a scored reference beat outside it: paired; an episode without an offset annotation: reference beats and unpaired detections from its onset to the end of the record are not scored;
- an empty detection list: every scored reference beat is a false negative; an empty reference list: every detection at or after 5:00 is a false positive, except the first one if it is at most 150 ms after 5:00.

**Risk controls:** RC-004.

### SRS-009: Reproducible validation report

**Software item:** dsp (scripts)
**Milestone:** M1
**Statement:** A single command shall run QRS detection and the evaluation of SRS-008 and SRS-011 on the reference database and write the report specified in SRS-012 to `docs/validation/`. Two runs on the same inputs, with the same software version and source code and the same versions of the third-party software used, shall produce byte-identical reports.
**Rationale:** Anyone can re-run every published result (README goal 4). Byte-identical output makes any change in results visible in version control. The software version stays the same while a milestone is developed (`sdp.md` §4), so the condition names the source code too; numerical results can also depend on the versions of third-party software.
**Verification level:** Requirement (QA)
**Verification:** Test. The report is generated twice from fixture records, and the two outputs are compared byte for byte.
**Risk controls:** RC-004.

### SRS-010: QRS detection with baseline wander and mains interference

**Software item:** dsp
**Milestone:** M1
**Statement:** The software shall meet all the criteria of SRS-006, including exactly one index for each QRS complex and no other indices, on an ECG with a regular rhythm between 30 and 200 bpm (bounds included) and 1 mV QRS amplitude, to which a 0.3 Hz sinusoidal baseline wander of 1 mV amplitude and a sinusoid at the configured mains frequency (50 Hz or 60 Hz) of 0.2 mV amplitude have been added.
**Rationale:** Baseline wander and mains interference are the most common artefacts in ECG recordings and cause missed and false beats (HAZ-001, HAZ-002). This checks the effect of RC-002 on detection, whatever the internal processing. The range of regular rhythms is that of SRS-006.
**Verification level:** Requirement (QA)
**Verification:** Test on the synthetic ECGs of SRS-006 (30, 40, 75, 180 and 200 bpm), at 360 Hz and at 250 Hz, with the interference added and the mains setting matching it (one case at 50 Hz and one at 60 Hz): the pass criteria of SRS-006 hold.
**Risk controls:** RC-002.

### SRS-011: Detection statistics

**Software item:** dsp
**Milestone:** M1
**Statement:** From the matches of SRS-008, the software shall report for each record the true positives (TP), false negatives (FN), false positives (FP), Se = TP / (TP + FN) and +P = TP / (TP + FP) in percent; and for the set of records, gross Se and +P computed from the summed counts, and average Se and +P as the mean of the per-record values. A value whose denominator is zero shall be reported as not defined, and excluded from the averages.
**Rationale:** EC57 reports both gross and average statistics. Undefined values must not appear as 0% or 100%.
**Verification level:** Requirement (QA)
**Verification:** Test with per-record counts whose statistics are known, including a record with TP + FN = 0. Per-record, gross and average values equal the expected ones to within 0.01 percentage points, and the undefined value is reported as not defined and excluded from the averages.
**Risk controls:** RC-004.

### SRS-012: Validation report content

**Software item:** dsp (scripts)
**Milestone:** M1
**Statement:** The validation report shall contain:
- the per-record and aggregate statistics of SRS-011;
- the five records with the lowest Se and the five records with the lowest +P, among the records whose value is defined (fewer than five if fewer records have a defined value), ties ordered by record name;
- the pass or fail of each SRS-007 threshold; a threshold whose value is not defined (SRS-011) is reported as fail;
- the database name and version, and the outcome of its SRS-001 verification;
- the licence under which the database is published, with the address of the licence text;
- the software version, with an identifier of the source code that produced the report, and the settings used (channel, mains frequency);
- the versions of the third-party software used at run time;
- what was not scored under SRS-008 because of ventricular flutter or fibrillation episodes. The first 5 minutes of a record are not scored in any case, so these figures cover the part of each record from 5:00 to its end, except the number of episodes in the record, which covers the whole record. For each record with at least one episode: the number of episodes in the record; the number of episodes that reach 5:00 or later; the total duration of those episodes, counted from 5:00 and including the samples of the onset and offset annotations, a sample that lies in two episodes being counted once; the number of reference beats at or after 5:00 that lie inside an episode; and the number of detections at or after 5:00 that lie inside an episode and are not paired. The detection left unscored by the rule at 5:00 (SRS-008) is not included. A statement is given instead when no record has an episode;
- the statement "Technical evaluation only. Sinus is not a medical device; these results are not a clinical validation."

The report shall not be written if the SRS-001 verification fails.
**Rationale:** A reader must be able to tell what was measured, on which data and software, where performance is weakest, what was left out of the scoring, and what the results do not mean (HAZ-004, HAZ-010). The software version stays the same while a milestone is developed (`sdp.md` §4), so the report also identifies the source code that produced it, and it states the versions of the third-party software, on which numerical results can depend (SRS-009). Episodes in the first 5 minutes are counted but not measured, because that part of the record is not scored for another reason. Only a defined value can be ranked, or show that a target is met (SRS-011). Version 1.0.0 of the database is published by PhysioNet under the Open Data Commons Attribution License v1.0: a work produced from the database and used publicly, as the report is, must carry a notice that its content comes from the database and is available under that licence (licence §4.3), so the report states the licence with its address (OP-064).
**Verification level:** Requirement (QA)
**Verification:** Test with fixture records. The report contains each listed item, with values matching the fixture and the worst records in the expected order. The software version and the identifier of the source code are those of the software under test: the test computes the identifier itself from the source files, with the method documented in `architecture.md`, and compares it with the report. The stated versions of the third-party software used at run time are those of the environment in which the test runs, in the form documented in `architecture.md`. The licence of the database and the address of its text are stated in the form documented in `architecture.md`; for version 1.0.0 of the MIT-BIH Arrhythmia Database, the licence is the Open Data Commons Attribution License v1.0. Further cases:
- one fixture record has two ventricular flutter episodes, one that ends before 5:00 and one after 5:00, each with reference beats and an unpaired detection inside it: the report gives two episodes in the record and one from 5:00, the duration of the second episode, and the numbers of reference beats and detections inside the second episode only;
- an episode that contains 5:00, with reference beats and unpaired detections inside it before and after 5:00: it counts as an episode from 5:00, its duration is counted from 5:00, and only the reference beats and the unpaired detections at or after 5:00 are counted;
- a detection left unscored by the rule at 5:00 that lies inside an episode: it is not counted among the detections not scored;
- two episodes that share a sample: that sample is counted once in the duration;
- fewer than five records whose Se, or +P, is defined: the list contains only those records;
- a gross Se or +P that is not defined: its threshold is reported as fail;
- fixtures that have no episode: the report says so;
- a fixture database that fails verification: no report is written and an error is raised.

**Risk controls:** RC-004, RC-005, RC-011.

### SRS-013: Verified download of the noise stress test database

**Software item:** dsp (scripts)
**Milestone:** M1
**Statement:** The software shall obtain version 1.0.0 of the MIT-BIH Noise Stress Test Database from PhysioNet into the local data directory, and verify every file listed in the SHA-256 checksum list that PhysioNet publishes for that version. If any listed file is missing or its checksum does not match, the software shall report the database as not verified, with an error naming each such file.
**Rationale:** Noise stress results (SRS-014) are only meaningful on intact, known reference data, as for SRS-001.
**Verification level:** Requirement (QA)
**Verification:** Test, without network. With a local fixture of files and a checksum list for this database, an intact set is reported as verified; a set with one altered and one missing file is reported as not verified, with an error naming both files. The download from PhysioNet itself is exercised when the Milestone 1 validation report is generated (SRS-007).
**Risk controls:** RC-004.

### SRS-014: Detection performance versus signal-to-noise ratio

**Software item:** dsp (scripts)
**Milestone:** M1
**Statement:** The command of SRS-009 shall also run QRS detection, with the channel and mains setting of SRS-007, on the 12 ECG records of the MIT-BIH Noise Stress Test Database (records 118 and 119 with electrode motion noise added at signal-to-noise ratios (SNR) of 24, 18, 12, 6, 0 and −6 dB), evaluate them as specified in SRS-008 and SRS-011, and add to the report of SRS-012 a noise stress section that contains:
- for each record, its SNR and the statistics of SRS-011;
- for each SNR, the gross Se and +P computed from the summed counts of the two records at that SNR;
- the gross Se and +P of records 118 and 119 of the MIT-BIH Arrhythmia Database, without added noise, as the reference for comparison;
- the database name and version, and the outcome of its SRS-013 verification;
- the licence under which the database is published, with the address of the licence text.

The report shall not be written if the SRS-013 verification fails.
**Rationale:** ANSI/AAMI EC57 includes a noise stress test for QRS detectors, and results on clean records alone overstate real performance (HAZ-004). Electrode motion noise is the artefact that most resembles a QRS complex. Performance versus SNR shows where detection degrades, which is input to the signal quality index (Milestone 2) and to the abstention of beat classification (Milestone 6). The first 5 minutes of each record carry no added noise and are not scored (SRS-008). No pass threshold is set for now (OP-031). Version 1.0.0 of this database is also published by PhysioNet under the Open Data Commons Attribution License v1.0, so the noise stress section states its licence, for the reason given in SRS-012.
**Verification level:** Requirement (QA)
**Verification:** Test with fixture records that have the names, SNR levels and annotations structure of the noise stress records, and known detection counts. The noise stress section contains every listed item, with values matching the fixture, ordered by record and by decreasing SNR. The licence of the database and the address of its text are checked as for SRS-012; for version 1.0.0 of the MIT-BIH Noise Stress Test Database, the licence is the Open Data Commons Attribution License v1.0. With a fixture database that fails verification, no report is written and an error is raised.
**Risk controls:** RC-004.

### SRS-015: Golden-vector export

**Software item:** dsp (scripts)
**Milestone:** M1
**Statement:** A single command shall write one golden-vector file for each input of the following set:
- synthetic ECGs generated deterministically by the software from documented parameters: sampling frequencies of 250 Hz and 360 Hz; heart rates of 40, 75 and 180 bpm; each without interference, and with the baseline wander and mains interference of SRS-010 at 50 Hz and at 60 Hz;
- the first 60 s of each record of the subset of SRS-016, first stored signal, if the files of all these records are available and verified against the checksum list of SRS-001; otherwise, none of these record segments.

Each file shall contain: an identifier of the input; its sampling frequency in Hz; the settings used (mains frequency); the software version, with an identifier of the source code that produced the file; the input samples in mV; the output of each signal conditioning stage of SRS-004 and SRS-005, in the order in which the stages are applied; and the detected QRS sample indices of SRS-006. The file format shall be documented in `architecture.md`. Numeric values shall be written so that reading them back gives exactly the values computed. Two runs on the same computer and the same inputs, with the same software version and source code and the same versions of the third-party software used, shall produce byte-identical files.
**Rationale:** Every other implementation of signal conditioning and beat detection (the real-time library of Milestone 2, used by the desktop application and the device) is checked against this validated reference on the same inputs, within a tolerance to be defined (OP-005). Synthetic inputs give exact, license-free cases; record segments add real morphology and noise. Files derived from database records are regenerated where the data is available and are not stored in the repository. They are written for all the records of the subset or for none, so that a set of record segments, when it exists, is always complete. Computed values can differ in their last digits between computers, so byte-identical files are required on one computer only.
**Verification level:** Requirement (QA)
**Verification:** Test. The command is run twice on the synthetic set and on a fixture record: the two outputs are byte-identical; every file contains each listed item; the software version and the identifier of the source code in each file are those of the software under test, checked as for SRS-012; the set of files matches the list above, also when a file of one of the records fails verification; and the values read back from each file are equal to the outputs of the conditioning and detection functions called directly on the same input.
**Risk controls:** RC-012.

### SRS-016: Subset validation report in continuous integration

**Software item:** dsp (scripts); CI workflow
**Milestone:** M1
**Statement:** On every push, the automated build shall obtain records 100, 105, 108, 119, 203 and 207 of version 1.0.0 of the MIT-BIH Arrhythmia Database (a cached copy is allowed), verify each of their files against the SHA-256 checksum list of SRS-001, run QRS detection with the settings of SRS-007 and the evaluation of SRS-008 and SRS-011 on them, and regenerate a subset report. The subset report shall contain the items of SRS-012 for these records, with the outcome of the verification of their files in place of the outcome of the SRS-001 verification and without the pass or fail of the SRS-007 thresholds, and shall state that it covers a subset of records for regression checking and is not the performance evaluation of SRS-007. The build shall fail, and no subset report shall be written, if the verification fails; it shall also fail if the regenerated subset report differs from the subset report stored in the repository.
**Rationale:** Every change is checked against real reference data, and any change in detection results becomes visible in review instead of only when the full evaluation (SRS-007) is run locally. The records cover a clean recording (100), heavy noise (105), large P and T waves with noise (108), ventricular bigeminy (119, also the basis of the noise stress records), multiform ventricular ectopy with noise (203), and ventricular flutter with bundle branch block (207, whose ventricular flutter episodes exercise the exclusion of SRS-008): about 3 hours of ECG.
**Verification level:** Requirement (QA)
**Verification:** Test with fixture records and a fixture checksum list. When the stored subset report equals the regenerated one, the check passes; when one value in the stored report differs, the check fails and names the difference; when a record file fails verification, the check fails and no report is written. Inspection of the CI configuration confirms that the check runs on every push.
**Risk controls:** RC-004.

### SRS-017: Configuration checks of the real-time library

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** The real-time library shall reject, with an explicit error status, a configuration whose sampling frequency is not finite or lies outside 125–1000 Hz (bounds included), or whose mains setting is other than 50 Hz or 60 Hz. Signal conditioning, beat detection, heart rate and the signal quality index shall produce no output until they are validly configured.
**Rationale:** The real-time library accepts the sampling frequencies and mains settings that the reference accepts (SRS-003, SRS-005), so every configuration it accepts is one for which the reference defines the result (SRS-034). A function used without a valid configuration must not produce output that looks valid (HAZ-003). A stream has no length to check, so the minimum duration of SRS-003 has no counterpart here; the start of a stream is covered by SRS-022.
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer. Configurations with a sampling frequency of 124.9 Hz, 1000.1 Hz, NaN, +infinity or −infinity, and with a mains setting of 49, 51, 59, 61 or 100 Hz, are each rejected with an error status, and samples given afterwards produce no output of any kind. Configurations at 125 Hz and at 1000 Hz, with each mains setting, are accepted.
**Risk controls:** RC-003.

### SRS-018: Invalid input samples in the real-time library

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** The real-time library shall not process an input sample that is not finite (NaN or ±infinity) or whose magnitude exceeds 1000 mV. It shall report such a sample with an explicit error status, and produce no conditioned sample, detection, heart rate or signal quality index from that sample onwards until it is reset.
**Rationale:** Every supported source gives finite samples far below the limit (the MIT-BIH Arrhythmia Database was digitised over a 10 mV range), so such a sample comes from a defect upstream, and filtering it would corrupt every later output of the stream (HAZ-003). Stopping until a reset lets the caller treat the event as a gap in the data: processing starts again as a new stream (SRS-031), with the start-up marks of SRS-022, as the desktop application does at every gap (`architecture.md` §4.2). The limit also keeps every computation of the library finite in binary32, and it is the limit of the reference (SRS-003). Decided by the project owner on 2026-10-07 (OP-063).
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer, with a synthetic ECG of SRS-006 at 360 Hz in which one sample, after at least 10 s, is replaced in turn by NaN, +infinity, −infinity, the smallest binary32 value greater than the limit, and its negative: each case gives an error status at that sample and no output of any kind afterwards until a reset; after the reset, the outputs equal those of a newly configured library given the same samples. A sample equal to the limit, and one equal to its negative, are processed without an error status.
**Risk controls:** RC-003.

### SRS-019: Real-time signal conditioning

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** The real-time library shall remove baseline wander and then mains interference from a stream, one input sample at a time, each stage meeting the attenuation and band criteria of its requirement (SRS-004 for baseline wander, SRS-005 for mains interference), and shall output the conditioned value of each input sample before the next input sample is given (a delay of 0 samples).
**Rationale:** The stages, their order and their criteria are those of the validated reference (`architecture.md` §7.1), so that the validation of the reference applies to the real-time conditioning within the equivalence of SRS-034; removing the baseline first keeps the input of the mains stage small, which preserves precision in binary32. Any delay would add to the time between acquisition and display (OP-014); the reference and the library are compared sample by sample without a delay allowance (SRS-034), so the conditioning adds none (decided by the project owner on 2026-10-07, OP-049). Removing high-frequency noise is not part of this conditioning: beat detection limits the band of its own input, and the removal for the displayed waveform is OP-070.
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer, at 360 Hz and 250 Hz, with the inputs and the measurement rule of SRS-004 and SRS-005 (each input at least ten periods and at least 2 s long, amplitude measured on its second half), given one sample at a time: the output of each stage meets the criteria of its requirement, for both mains settings, and the conditioned value of every input sample is output before the next input sample is given.
**Risk controls:** RC-002.

### SRS-020: Streaming QRS detection

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** The real-time library shall detect QRS complexes in the conditioned signal of SRS-019, one sample at a time, and report each detection with its sample index in the time base of the stream. For the inputs of SRS-006 and SRS-010, the detections shall meet every criterion of those requirements.
**Rationale:** The live view, and later the device, need the beats while the samples arrive (`functional-analysis.md` F2.7). Stating the criteria of SRS-006 and SRS-010 for the real-time detection makes them verifiable on the library itself, beside its equivalence with the reference (SRS-034). The performance on real recordings (SRS-007, SRS-014) is carried over by SRS-038.
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer, with the synthetic inputs and the pass criteria of SRS-006 and SRS-010 (regular rhythms at 30, 40, 75, 180 and 200 bpm, at 360 Hz and 250 Hz, without interference and with the interference of SRS-010 at 50 Hz and at 60 Hz with the matching mains setting), given one sample at a time: the pass criteria of those requirements hold. A flat input of 10 s gives no detection and no error status.
**Risk controls:** RC-001, RC-002.

### SRS-021: Delay of streaming detection

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** The real-time library shall report each detection no later than the maximum delay documented in `architecture.md` for the detection rules (about 8 s) after the sample at its index. For a noise-free input with a regular rhythm between 30 and 200 bpm (bounds included), it shall report each detection whose index lies after the start-up period of SRS-022 at most 0.35 s after the sample at its index.
**Rationale:** A beat mark or a heart rate that appears long after the beat adds to the time between acquisition and display (OP-014). Some detections can only be confirmed later than others: those of the first seconds of a stream, while detection learns its signal levels, and those found by search-back, a second look with lower thresholds at a stretch without a detected beat (`architecture.md` §8.7.3, §8.7.4). Hence a general maximum and a smaller bound for a regular rhythm. With the approved rules, a detection found by the normal thresholds is reported at most about 0.29 s after its index (at 250 Hz and 360 Hz, `architecture.md` §8.7.4), within 0.35 s. The maximum is that of the approved rules, which stay unchanged in Milestone 2 (OP-056): about 8 s, the time without a detected QRS complex after which detection learns its levels again. Decided by the project owner on 2026-10-07 (OP-049).
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer, at 360 Hz and 250 Hz. On the synthetic inputs of SRS-006, the delay of every detection after the start-up period is at most 0.35 s. On synthetic inputs documented in `architecture.md` that make detection report a beat found during its learning period, a beat found by search-back and a beat found after detection has learned its signal levels again, every delay is within the documented maximum.
**Risk controls:** None.

### SRS-022: Start-up mark of detections

**Software item:** dsp and libs/sinus-dsp
**Milestone:** M2
**Statement:** The reference and the real-time library shall report each detection with a mark: start-up, if its index lies in a stretch of 2 s from which detection learns its signal levels, that is the first 2 s of the stream (its start-up period) or the 2 s from which detection learns its levels again after a stretch without detected QRS complexes (`architecture.md` §8.7.3); reliable otherwise. The mark shall not change which detections are reported or their indices.
**Rationale:** At the start of a stream, detection learns its signal levels from the first seconds, which may hold artefacts while the electrodes settle; on the MIT-BIH Arrhythmia Database the reference reported detections in the first 50 ms of records 104, 107 and 116, before the first annotated beat (OP-068). Marking these detections, instead of removing them, keeps the detections of SRS-006 and the results of SRS-007 unchanged, and lets the heart rate leave them out (SRS-024). The same holds when detection learns its levels again after a stretch without beats, for example after a loss of electrode contact; when the signal comes back later than that stretch, the heart rate is in any case withheld until enough new intervals are available (SRS-026). The mark is compared between the reference and the library like every other output (SRS-034). The detections in the first 50 ms of records 104, 107 and 116 lie in the start-up period; whether 2 s is enough on real recordings is measured by SRS-023. Decided by the project owner on 2026-10-07 (OP-068).
**Verification level:** Requirement (QA)
**Verification:** Test on the reference and on the build for the computer, at 360 Hz and 250 Hz. On the synthetic ECGs of SRS-006 at 40, 75 and 180 bpm, the detections whose index lies in the first 2 s are marked start-up and all others reliable, and the detections of the reference equal those of SRS-006 on the same input. After a reset of the real-time library, the same holds from the reset. On the synthetic input documented in `architecture.md` §13.9 in which one beat 20 times larger than the others makes detection miss beats until it learns its signal levels again: detection learns its levels again, and at least one detection has its index in the 2 s from which it learns them; the detections whose index lies in the first 2 s or in those 2 s are marked start-up, and all others reliable.
**Risk controls:** RC-017.

### SRS-023: Detection at the start of real recordings

**Software item:** dsp (scripts)
**Milestone:** M2
**Statement:** On segments of 60 s of the 48 records of the MIT-BIH Arrhythmia Database, starting at the first sample of each record and at each whole minute from 1:00 to 29:00 (30 segments per record, 1440 in all), each processed by the reference as a stream of its own from the first sample of the segment, continuing on the record after the last sample of the segment for the documented maximum delay of a detection (SRS-021), or to the end of the record if that comes first, with the channel and mains setting of SRS-007, and evaluated as specified in SRS-008 and SRS-011 with the start-up period of SRS-022 (the first 2 s of the segment) in place of the first 5 minutes, the detections marked reliable shall achieve, over all the segments, a gross Se of at least 99.5% and a gross +P of at least 99.5%. Only the detections marked reliable are scored: a reference beat after the start-up period that is detected only by a detection marked start-up, as can happen in a stretch from which detection learns its signal levels again, is a false negative. Only the reference beats and the detections whose index lies in the segment are scored; the continuation is not scored. The reference beats and the ventricular flutter and fibrillation episodes of a segment are those of its record that lie in the segment, so that an episode that begins before the segment is not scored in it.
**Rationale:** A live stream starts at any point of the cardiac cycle, and its first reliable detections give the first heart rate (OP-068). SRS-007 scores each record only from 5:00, and SRS-006 checks the start of a stream only on synthetic ECGs, so no other requirement measures the detections that follow the start-up period on real recordings (HAZ-001, HAZ-002). The thresholds are those of SRS-007. The real-time library starts like the reference: their equivalence is checked on record segments that begin at the first sample of their record (SRS-034). Decided by the project owner on 2026-10-07 (OP-068). The continuation after each segment was added by the project owner on 2026-10-09 as a correction of the evaluation method: in the first run, the beats at the end of each segment were not yet reported when the input ended and were counted as false negatives. The detection algorithm did not change.
**Verification level:** System (test engineer)
**Verification:** Analysis, from the validation report generated per SRS-009 and SRS-030. A test that requires the local database checks both thresholds; it is skipped in CI, where the database is not available, and its result is recorded in the milestone verification report.
**Risk controls:** RC-017.

### SRS-024: Heart rate from detections

**Software item:** dsp and libs/sinus-dsp
**Milestone:** M2
**Statement:** The reference and the real-time library shall report a heart rate in bpm at each detection marked reliable and at each change of its validity or of the reason for which it is withheld, as valid or as withheld with its reason (SRS-026), computed only from intervals between consecutive detections of the stream that are both marked reliable. For the detections of a regular rhythm between 30 and 200 bpm (bounds included), every heart rate reported as valid shall be within 2 bpm of the true rate; after a change from one such rhythm to another, every heart rate reported as valid from the fifth interval of the new rhythm onwards shall be within 2 bpm of the new rate.
**Rationale:** The heart rate is the main value of the live view (`functional-analysis.md` F2.8, F3.2). Detections marked start-up are left out (SRS-022, OP-068), and no interval spans the start of a stream, so none spans a reset (SRS-031). The first criterion bounds the error for a regular rhythm; the second makes the heart rate follow a real change of rhythm instead of treating it as isolated detection errors (SRS-025), which would show a heart rate that is too low or too high (HAZ-001, HAZ-002). The rhythm range is that of SRS-006. At 360 Hz, one sample of rounding changes a single interval at 200 bpm by about 1.9 bpm, hence 2 bpm. The method of computation is a design choice (`architecture.md`). Values decided by the project owner on 2026-10-07 (OP-021).
**Verification level:** Requirement (QA)
**Verification:** Test on the reference and on the build for the computer, with sequences of detections marked reliable at the positions of a regular rhythm, rounded to the sample at 360 Hz and at 250 Hz. At 30, 40, 75, 180 and 200 bpm, every valid heart rate is within 2 bpm of the true rate. With changes from 40 to 180 bpm, from 180 to 40 bpm, from 75 to 120 bpm and from 120 to 75 bpm, every valid heart rate from the fifth interval of the new rhythm onwards is within 2 bpm of the new rate. A sequence that begins with detections marked start-up gives the same heart rates as the sequence of its reliable detections alone.
**Risk controls:** RC-017, RC-018.

### SRS-025: Heart rate with an isolated missed or extra detection

**Software item:** dsp and libs/sinus-dsp
**Milestone:** M2
**Statement:** For the detections of a regular rhythm between 30 and 200 bpm (bounds included) from which one detection is missing, or to which one detection is added at least 200 ms from the detections before and after it, every heart rate that the reference and the real-time library report as valid shall differ from the true rate by no more than 5 bpm.
**Rationale:** Detection misses or adds isolated beats: on the MIT-BIH Arrhythmia Database about one beat in 360 is missed and one detection in 580 is false (SRS-007, [`docs/validation/qrs-ec57-report.md`](../validation/qrs-ec57-report.md)). One such error must not make the heart rate jump (`functional-analysis.md` F2.8; HAZ-001, HAZ-002). An added detection is at least 200 ms from its neighbours because detection never reports two indices closer than that (SRS-006). A plain mean of recent intervals would not meet 5 bpm (one missed beat at 75 bpm moves a mean of eight intervals to about 67 bpm), which is the purpose of the criterion; SRS-024 makes sure that a real change is still followed. Value decided by the project owner on 2026-10-07 (OP-021).
**Verification level:** Requirement (QA)
**Verification:** Test on the reference and on the build for the computer, with sequences of detections marked reliable at 360 Hz, at 30, 40, 75, 180 and 200 bpm: one detection removed after the first valid heart rate; and, at the rates whose interval is at least 400 ms, one detection added in the middle of an interval and one added 200 ms after a detection. Every valid heart rate is within 5 bpm of the true rate.
**Risk controls:** RC-018.

### SRS-026: Withheld heart rate

**Software item:** dsp and libs/sinus-dsp
**Milestone:** M2
**Statement:** The reference and the real-time library shall report the heart rate as withheld, with the reason:
- "not enough beats", from the first sample of the stream until 4 intervals between consecutive detections marked reliable are available in the stream;
- "no recent beat", from the first sample that lies at least 3 s after the index of the last detection marked reliable reported up to and including that sample, until 4 intervals whose detections all have their index after that sample are available;
- "out of range", when the heart rate computed lies outside 30–200 bpm (bounds included).

When "not enough beats" and "no recent beat" both apply, the reason shall be "no recent beat".

**Rationale:** A heart rate must not be shown before enough beats are available, nor carried forward or predicted across missing beats beyond a defined time (RC-008, HAZ-007), nor outside the range in which detection is specified (SRS-006). Four intervals are enough to set aside one wrong interval; the first heart rate then comes about 3 s after the start-up period at 75 bpm and 8 s at 30 bpm. 3 s is longer than the longest interval of the range (2 s at 30 bpm). A detection is reported some time after its index (SRS-021), so with the detections of a stream a stretch without detections a little shorter than 3 s can also give "no recent beat": the detection that ends it is reported only after the 3 s have passed. How the desktop application shows a withheld heart rate, and the signal status that also withholds it while the signal is not usable, are specified with the desktop application (Milestone 3; OP-020, OP-071). Values decided by the project owner on 2026-10-07 (OP-021).
**Verification level:** Requirement (QA)
**Verification:** Test on the reference and on the build for the computer, at 360 Hz, with sequences of detections marked reliable, each reported at the sample of its index. The first valid heart rate comes with the fourth interval. At 30 bpm and at 75 bpm, a stretch without detections longer than 3 s gives "no recent beat" from the first sample at least 3 s after the last detection, and the next valid heart rate comes with the fourth interval after it; a stretch shorter than 3 s gives none. A stretch longer than 3 s that follows the second detection of the stream, while the heart rate is withheld as "not enough beats", gives "no recent beat" from the first sample at least 3 s after that detection. Regular rhythms at 29 bpm and at 201 bpm give "out of range"; at 30 bpm and at 200 bpm they do not.
**Risk controls:** RC-008.

### SRS-027: Signal quality index per window

**Software item:** dsp and libs/sinus-dsp
**Milestone:** M2
**Statement:** The reference and the real-time library shall compute a signal quality index between 0 and 1 (higher meaning better quality) for each window of 10 s of the stream, from its input and conditioned samples, a new window starting every 1 s from the first sample of the stream (at a sampling frequency that is not a whole number of hertz, 1 s is rounded to a whole number of samples as documented in `architecture.md`, and a window lasts ten times that number), and mark each window usable if its index is at or above the threshold documented in `architecture.md`, and not usable otherwise. Each window shall be reported with its index, its mark and the sample indices of its first and last samples in the time base of the stream, at most 0.5 s after its last sample.
**Rationale:** Beats and a heart rate computed from noise or a flat line must not be presented as valid (HAZ-006). The index is what the signal status of the desktop application uses to withhold them (Milestone 3, OP-020), and what beat classification will use to abstain (Milestone 6). A window of 10 s holds at least five beats at 30 bpm, as the minimum duration of SRS-003, and a new window every second keeps the indication of the live view current; the detections inside a window are known at most about 0.3 s after its end (SRS-021), hence 0.5 s. The quality measures, how they are combined and the threshold are design choices (`architecture.md`), fixed before the evaluation on the reference databases (SRS-029); a threshold or measure changed after those results have been seen is recorded as tuned on the evaluation data (`sdp.md` §6). Decided by the project owner on 2026-10-07 (OP-032, OP-049).
**Verification level:** Requirement (QA)
**Verification:** Test on the reference and on the build for the computer, at 360 Hz and 250 Hz, on a synthetic ECG of SRS-006 of 60 s: the windows last 10 s, start every 1 s from the first sample, carry the sample indices of their first and last samples, have an index between 0 and 1, and are marked as their index and the documented threshold require; each is reported at most 0.5 s after its last sample. After a reset of the real-time library, the windows start again from the reset.
**Risk controls:** RC-007.

### SRS-028: Signal quality index on defined signals

**Software item:** dsp and libs/sinus-dsp
**Milestone:** M2
**Statement:** The reference and the real-time library shall mark usable every window that lies entirely in a noise-free ECG with a regular rhythm between 30 and 200 bpm (bounds included), with or without the interference of SRS-010, and begins at least 2 s after the first sample of the stream. They shall mark not usable every window that lies entirely in a flat line (a constant value) or in white noise without ECG of any RMS amplitude from 0.01 mV to 1 mV, and every window in which the input stays at one value for a continuous stretch of at least 5 s, half of the window (a saturated signal, held at the limit of the acquisition range).
**Rationale:** These are the cases of `functional-analysis.md` F2.9. A clean ECG must stay usable, so that the index does not withhold a valid heart rate without reason; the first 2 s are left out because the mains interference filter needs them to settle, as in the verification of SRS-005. A flat line (lost contact, a disconnected lead), noise alone and a saturated signal must be marked not usable, because detection on them gives false beats or none (HAZ-006). Real noise is covered by SRS-029. Decided by the project owner on 2026-10-07 (OP-032).
**Verification level:** Requirement (QA)
**Verification:** Test on the reference and on the build for the computer, at 360 Hz and 250 Hz. Every window of the synthetic ECGs of SRS-006 and SRS-010 at 30, 40, 75, 180 and 200 bpm that begins at least 2 s after the first sample is marked usable. Every window of a flat input of 60 s at 0 mV and at 1 mV, and of white Gaussian noise of RMS 0.01 mV, 0.1 mV and 1 mV, is marked not usable. On a synthetic ECG of SRS-006 of 60 s whose input is held at 2 mV from 20 s to 40 s, every window that contains at least 5 s of that stretch is marked not usable.
**Risk controls:** RC-007.

### SRS-029: Signal quality index on the noise stress records

**Software item:** dsp (scripts)
**Milestone:** M2
**Statement:** With the reference, the first stored signal, the mains setting of SRS-007 and the windows of SRS-027, applied to the 12 ECG records of the MIT-BIH Noise Stress Test Database (records 118 and 119 with noise added at each of six SNRs), to records 118 and 119 of the MIT-BIH Arrhythmia Database and to the three noise records of the Noise Stress Test Database (baseline wander, electrode motion and muscle artefact), where the windows at an SNR are the windows of the two records at that SNR that lie entirely in the stretches to which noise was added, and a window from 5:00 is one that starts at or after 5:00:
- the median index of the windows at 24 dB shall be above the threshold of SRS-027 (usable), and the median index of the windows at 0 dB and at −6 dB, each on its own, shall be below it (not usable);
- at least 95% of the windows from 5:00 of records 118 and 119 of the MIT-BIH Arrhythmia Database, counted over the two records together, shall be marked usable;
- at 24 dB and at 18 dB, each SNR on its own, at least 90% of the windows at that SNR shall be marked usable;
- at 6 dB, at 0 dB and at −6 dB, each SNR on its own, at most 20% of the windows at that SNR shall be marked usable;
- for each of the three noise records on its own, at most 10% of its windows shall be marked usable.

**Rationale:** The index is validated where the effect of noise on detection is known (SRS-014): in the Milestone 1 validation report, detection is unchanged at 24 dB and 18 dB SNR and degrades below, mostly through false detections (gross +P 95.69% at 12 dB, 79.16% at 6 dB). The index must keep a usable signal usable and mark as not usable the levels at which detection is no longer reliable (HAZ-006). The windows at 12 dB, where detection starts to degrade, are reported without a criterion (SRS-030). These criteria take the place of minimum detection results per SNR (OP-031). Which stretches of each record carry added noise is documented with the database; the first 5 minutes carry none. Each SNR and each noise record is judged on its own, so that a good result at one cannot make up for a poor result at another; records 118 and 119 are counted together, as the clean counterpart of the noise stress records made from them. Decided by the project owner on 2026-10-07 (OP-032), with the reading of each criterion stated above. Amended in version 0.9 (decided by the project owner on 2026-10-11): the first criterion claimed that the index grades the levels below 0 dB, which the measured behaviour does not support (the median has a flat floor near 0.35 at the low SNRs), and the application shows the index as a usable or not usable mark only (SRS-048); the criterion now states what the mark relies on, that a clean level and the degraded levels fall on opposite sides of the threshold. The other criteria are the protection against presenting a degraded signal as usable (HAZ-006); they are not relaxed to fit the measured data.
**Verification level:** System (test engineer)
**Verification:** Analysis, from the validation report generated per SRS-009 and SRS-030. A test that requires the local databases checks each criterion; it is skipped in CI, where the databases are not available, and its result is recorded in the milestone verification report.
**Risk controls:** RC-007.
**Status:** at the Milestone 2 release it was not met on three of its criteria (6 dB, the electrode motion noise record, the order of the medians below 0 dB); accepted as a known anomaly by the project owner on 2026-10-11 (`sdp.md` §8; Milestone 2 verification report). With the median criterion amended in version 0.9, the two remaining criteria (at most 20% usable at 6 dB; at most 10% usable for the electrode motion record) stay a known anomaly, to be addressed in Milestone 6 by improving the index and checking it on unseen recordings (OP-074, OP-029). The median criterion is to be checked again against the Milestone 2 evaluation results (median 0.3455 at 0 dB and 0.3566 at −6 dB, below the threshold).

### SRS-030: Signal quality and start-of-stream sections of the validation report

**Software item:** dsp (scripts)
**Milestone:** M2
**Statement:** The command of SRS-009 shall also compute the results of SRS-023 and SRS-029 and add to the report of SRS-012:
- a signal quality section that contains, with the windows at an SNR and the windows from 5:00 as in SRS-029: the window length, the window spacing and the threshold of SRS-027; for each SNR of the noise stress records, the number of windows at that SNR, their median index and the share of them marked usable; the same figures for the windows from 5:00 of records 118 and 119 together, and for the windows of each noise record; for each of the 48 records of SRS-007, the share of its windows from 5:00 marked usable, and the numbers of false negatives and false positives of SRS-008 that lie in at least one window marked not usable; and the pass or fail of each criterion of SRS-029;
- a start-of-stream section that contains: the start-up period of SRS-022; the starting points of SRS-023; the statistics of SRS-011 for each record, summed over its segments, and for all the segments; and the pass or fail of each threshold of SRS-023.

**Rationale:** The results of SRS-023 and SRS-029 are published with the other validation results and regenerated by the same command, so that anyone can reproduce them (README goal 4, SRS-009). The false negatives and false positives that fall in windows marked not usable show how much of the risk of HAZ-006 the index can control (RC-007); they are reported without a threshold, so that no threshold is fitted to these records.
**Verification level:** Requirement (QA)
**Verification:** Test with fixture records that have the names and structure of the records concerned, and known detections and indices: each section contains every listed item, with values matching the fixture, and a criterion or threshold that is not met is reported as fail.
**Risk controls:** RC-004, RC-007.

### SRS-031: Restart of the real-time library

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** After a reset, the outputs of the real-time library for the samples given after the reset (conditioned samples, detections and their marks, heart rates, signal quality windows) shall be identical to those of a newly configured library given the same samples; no interval, heart rate or window shall use a sample given before the reset.
**Rationale:** The desktop application starts a new continuous segment at every gap in the data (lost samples, a device restart) and resets the processing there, so that beat intervals and the heart rate are never computed across a gap (`architecture.md` §4.2; HAZ-012, RC-014). A reset is also how processing resumes after an invalid sample (SRS-018).
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer, at 360 Hz: a synthetic ECG with the interference of SRS-010 is processed for 20 s, the library is reset and the ECG continues; the outputs after the reset are identical, value for value, to those of a newly configured library given the samples after the reset, for resets at several points of the cardiac cycle and during the start-up period.
**Risk controls:** RC-014.

### SRS-032: Fixed memory of the real-time library

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** The real-time library shall use memory of a size fixed before processing starts: it shall not obtain or release memory dynamically while it is configured, processes samples or is reset, and one complete processing chain (signal conditioning, detection, heart rate and signal quality index) shall occupy at most 64 KiB (65 536 bytes) for any accepted sampling frequency.
**Rationale:** On the device, memory obtained while processing can run out during a session or delay the processing of a sample unpredictably; a fixed size can be checked against the memory of the ESP32-S3 before the firmware is written (`functional-analysis.md` F2.5). The limit is 12.5 % of the 512 KiB of internal memory of the ESP32-S3, so that the firmware tasks and the Bluetooth LE stack keep most of it, with a margin of about 20 % over the size computed from the design (`architecture.md` §14.10); the project owner approved it on 2026-10-08 (OP-049).
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer: with every dynamic memory request of the test process counted, the configuration at 125, 250, 360 and 1000 Hz, the processing of the inputs of the golden vectors of SRS-015 and SRS-033 and a reset make no request; the size of a complete processing chain, as given by the build, is at most the limit.
**Risk controls:** None.

### SRS-033: Golden vectors of the real-time functions

**Software item:** dsp (scripts)
**Milestone:** M2
**Statement:** Each golden-vector file of SRS-015 shall also contain: the mark of each detection (SRS-022); the heart rate reported at each detection marked reliable and at each change of its validity or of the reason for which it is withheld, with its sample index, its validity and, when withheld, its reason (SRS-024, SRS-026); and each signal quality window with the sample indices of its first and last samples, its index and its mark (SRS-027). The set of inputs of SRS-015 shall also include synthetic inputs, documented in `architecture.md`, on which a detection is marked start-up after detection has learned its signal levels again, the heart rate is withheld for each reason of SRS-026, and at least one window is marked not usable.
**Rationale:** The real-time library is checked against the reference on these outputs (SRS-034), so the vectors must hold them. The synthetic ECGs of SRS-015 are clean regular rhythms of 30 s, on which no window is not usable and the heart rate is withheld only at the start, so further inputs are needed to exercise every mark and reason. The format is documented in `architecture.md`, as for SRS-015.
**Verification level:** Requirement (QA)
**Verification:** Test, as for SRS-015: each file contains each listed item, and the values read back equal the outputs of the reference functions called directly on the same input. The set of files contains a detection marked start-up after detection has learned its signal levels again, a heart rate withheld for each reason, and a window marked not usable.
**Risk controls:** RC-012.

### SRS-034: Equivalence with the reference on the computer

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** For every golden-vector file of SRS-015 and SRS-033, the real-time library built for the computer, configured with the sampling frequency and the mains setting of the file and given its input samples one at a time, shall produce:
- for each conditioning stage, an output within 2e-5 mV of the file's at every sample;
- as many detections as the file, each with the same mark as the corresponding detection of the file, the same index (a tolerance of 0 samples) and the same report sample (the sample at which the library reports it; a tolerance of 0 samples);
- heart rates with the same validity and reason at the same samples, each valid one within 1e-4 bpm of the file's;
- the same signal quality windows (first and last samples), with the same marks, each index within 0.01 of the file's.

**Rationale:** The validation results of the reference (SRS-007, SRS-014, SRS-023, SRS-029) apply to the real-time library only if it computes the same results (RC-012; HAZ-001, HAZ-002). The reference is causal and shares the filter design, the stage order and the initial state with the library, so the outputs are compared sample by sample, without a delay allowance; the tolerances absorb the rounding differences between the real-time library, which computes signal conditioning in binary64 and the rest in binary32 (ADR 0008), and the binary64 reference (`architecture.md` §7.1; OP-057). The counts, marks, validity, reasons, usable marks, indices and report samples must be the same, and the values agree within tolerances, as decided by the project owner on 2026-10-07; no difference of detection is allowed in advance, not even a near tie between two band-pass lobes (OP-056 (b)): if a file fails for such a reason, the project owner decides then. The report sample is compared because the heart rates must be reported at the same samples, and comparing it names the cause of a failure. The tolerances follow from the numerical analysis of each stage and from the largest differences measured with a model of the library on the golden vectors and the reference databases (`architecture.md` §14.11), and were approved by the project owner on 2026-10-08 (OP-005).
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer, with the golden vectors exported from the same commit: every file passes. A copy of a file in which one value of each compared output is changed by more than its tolerance, or from which one detection is removed, fails, and the failure names the file, the output and the sample.
**Risk controls:** RC-012.

### SRS-035: Equivalence check on every change

**Software item:** dsp (scripts); libs/sinus-dsp; CI workflow
**Milestone:** M2
**Statement:** On every push, the automated build shall export the golden vectors of SRS-015 and SRS-033 from the commit under test, including the record segments, whose records it obtains and verifies as for SRS-016, and run the check of SRS-034 on all of them. The build shall fail if a file of the set is missing or fails the check.
**Rationale:** Any change of the reference that the library does not follow, or the reverse, fails at once (`functional-analysis.md` F3.4). The export skips the record segments when the files of their records are not verified (SRS-015), so the build also fails on a missing file (`architecture.md` §7.5). Whether golden vectors of record segments may be passed between steps of the build as public artifacts, and with which notices, is OP-067.
**Verification level:** Requirement (QA)
**Verification:** Test and inspection. The check run on a set from which one file is missing fails and names the file. Inspection of the CI configuration confirms that the export and the check run on every push.
**Risk controls:** RC-012.

### SRS-036: Equivalence on the device processor

**Software item:** libs/sinus-dsp (build for the ESP32-S3); CI workflow
**Milestone:** M2
**Statement:** On every push, the real-time library built for the ESP32-S3 shall run the check of SRS-034, with the tolerances of SRS-034, on the golden vectors of SRS-035, including the record segments, in an emulator of the ESP32-S3; the build shall fail if a file of the set is missing or fails the check.
**Rationale:** The desktop application and the device use one implementation (`functional-analysis.md` F2.10), so the build for the device processor is checked against the same reference as the build for the computer. The check runs in the emulator, as decided by the project owner (OP-051, closed); a development board on the bench, with no person connected, is the fallback. With the same tolerances on both builds, one statement of equivalence covers both, and the record segments keep real ECG in the check on the device processor; the build artifacts that carry them carry the notice of their database (OP-067). Decided by the project owner on 2026-10-07 (OP-005).
**Verification level:** System (test engineer)
**Verification:** Inspection and test. The CI configuration and the log of a run show that the check runs in the emulator on every push, on the set of SRS-035; a run with a file changed by more than a tolerance fails.
**Risk controls:** RC-012.

### SRS-037: Content of the equivalence results

**Software item:** libs/sinus-dsp
**Milestone:** M2
**Statement:** The check of SRS-034 and SRS-036 shall report, for each golden-vector file and each compared output, the largest difference found, its tolerance and the outcome (pass or fail). It shall also state the build target (computer or ESP32-S3), the reference software that wrote the vectors (the software version and the identifier of the source code read from the files), and the version of the real-time library with an identifier of its source code, in the form documented in `architecture.md` (OP-062).
**Rationale:** The equivalence results are the evidence of RC-012 and are quoted in the milestone verification report (`sdp.md` §6). Like the validation reports (SRS-012), they must identify the software on both sides, and a version alone does not identify the code while a milestone is developed (`sdp.md` §4; OP-062).
**Verification level:** Requirement (QA)
**Verification:** Test on the build for the computer. With a set of golden vectors in which one output of one file is changed by a known amount, larger than every other difference of that output and within its tolerance, the reported largest difference for that file and output equals that amount within the rounding of the comparison. The reported reference software equals that stated in the files. The reported version of the library and the identifier of its source code equal those that the test computes itself with the method documented in `architecture.md`.
**Risk controls:** RC-012.

### SRS-038: Detection by the real-time library on the reference databases

**Software item:** libs/sinus-dsp; dsp (scripts)
**Milestone:** M2
**Statement:** QRS detection by the real-time library built for the computer, with the channel and mains setting of SRS-007, on the 48 records of the MIT-BIH Arrhythmia Database and on the 12 ECG records of the MIT-BIH Noise Stress Test Database, evaluated as specified in SRS-008 and SRS-011, shall give for each record the same numbers of true positives, false negatives and false positives as the reference.
**Rationale:** The golden vectors hold 6 minutes of real ECG. The comparison on the whole databases shows that the results of SRS-007 and SRS-014 hold for the implementation that runs in real time (RC-012; HAZ-001, HAZ-002). Identical counts per record are required, so that those results can be stated for the real-time library without qualification. Decided by the project owner on 2026-10-07 (OP-005).
**Verification level:** System (test engineer)
**Verification:** Analysis. A test that requires the local databases compares the counts of each record with those of the reference; it is skipped in CI, where the databases are not available, and its result is recorded in the milestone verification report.
**Risk controls:** RC-012.

### SRS-039: Replay source

**Software item:** desktop
**Milestone:** M3
**Statement:** The application shall replay a record in WFDB format (signal format 16 or 212, first stored signal, as in SRS-002) or a recorded session (SRS-051) as a stream with the content and timing of a device stream, at 1, 2, 5 or 10 times the original rate. The user shall be able to pause, resume and stop the replay, and to choose the start position before the replay starts; a change of start position or speed takes effect only by stopping and starting a new replay, which starts a new continuous segment (SRS-031). When the end of the record is reached the application shall stop the replay and show "Replay ended". A record or session that cannot be read is rejected with a message that names the cause, and no stream is produced. The samples of a replayed record shall equal those that the offline loader of SRS-002 returns for the same record. At 1 times the original rate, the time taken to deliver 60 s of the record shall differ from 60 s by less than 1%; at the other speeds, from 60 s divided by the speed by less than 1%.
**Rationale:** Replay is the only source before the device exists (Milestone 4) and the way the display rules are verified on real records (`functional-analysis.md` F3.8; OP-037). Processing is per sample, so the results do not depend on the speed (SRS-040); the speed is shown with the source (SRS-041) so that a fast replay is not read as live (HAZ-013). A jump in the record is a discontinuity, so it is a stop and a new replay and not a seek. Pause and the end are visible states that withhold the heart rate (SRS-045, SRS-046), so that a frozen screen does not look current (HAZ-007). Values decided by the project owner on 2026-10-11 (OP-037).
**Verification level:** Requirement (QA)
**Verification:** Test with fixture records in format 16 and in format 212, and a recorded session: at each of the four speeds the replay delivers the samples of the offline loader, value for value; the timing criterion holds over 60 s at 1, 2, 5 and 10 times; pause stops the delivery and resume continues it from the next sample; stop ends it; a start position of 30 s starts the replay at that sample; at the end of a fixture record "Replay ended" is shown and no further sample is delivered. A truncated file, a header that names an unsupported format and a record of 0 samples are each rejected with a message and produce no stream.
**Risk controls:** RC-015.

### SRS-040: Replay gives the results of the real-time library

**Software item:** desktop
**Milestone:** M3
**Statement:** For each of the six records of the subset of SRS-016, for all the 48 records of the MIT-BIH Arrhythmia Database, and for records 118e06 and 119e06 and the three noise records of the MIT-BIH Noise Stress Test Database, replayed through the application without its display, with the channel and mains frequency of SRS-007 (SRS-050), at each replay speed of SRS-039, the application shall obtain: the conditioned samples within 2e-5 mV; the detections with the same index, mark and report sample; the heart rates with the same validity and reason, each valid one within 1e-4 bpm; and the signal quality windows with the same first and last samples and marks, each index within 0.01, as the library given the same samples directly. The tolerances are those of SRS-034.
**Rationale:** The application adds replay, framing, status rules and display around the library. This checks that none of them changes a result the library computes, so that the validation results of SRS-007, SRS-014, SRS-023 and SRS-029 apply to what the user sees (RC-012; HAZ-001, HAZ-002). It is the method of integration verification by replay of `sdp.md` §6 for Milestone 3 (OP-007); the device step follows in Milestone 4 and the backend step in Milestone 5. Decided by the project owner on 2026-10-11.
**Verification level:** System (test engineer)
**Verification:** Test and analysis. The six records of the subset run in CI. The whole database and the noise stress records need the local databases; that test is skipped in CI and its result is recorded in the milestone verification report. A run in which one detection of the library output is removed or one heart rate is changed by more than its tolerance fails and names the record and the output.
**Risk controls:** RC-012.

### SRS-041: Data source indication

**Software item:** desktop
**Milestone:** M3
**Statement:** In every state of the application, a text banner in a fixed place at the top of the main window shall show the source: for a replay, "REPLAY", the name of the record or session, the speed and the mains frequency of the record (SRS-050); for the test input, "TEST INPUT" and its address and port (SRS-042). The word "REPLAY" shall also be shown in the waveform area while a replay is the source. The indication shall not rely on colour alone. One source feeds the application at a time: changing the source stops the first, resets the processing (SRS-031) and clears the displayed heart rate and marks; a frame or sample that carries the tag of a source other than the current one is dropped and does not reach the library.
**Rationale:** A replay or a test signal read as a live measurement is the hazard HAZ-013 (RC-015, use scenario HRS-1 of `usability.md`). A fixed place and words, not colour, make the source readable in every state, and an exclusive source prevents a replay and a device (Milestone 4) from mixing. Decided by the project owner on 2026-10-11 (OP-037).
**Verification level:** Requirement (QA)
**Verification:** Test: the banner text is checked in each state (no source, playing at each speed, paused, ended, interrupted, test input receiving) and has the same position; the waveform area shows "REPLAY" during a replay. A frame tagged with a source other than the current one, sent while a replay runs, produces no change in the detections, heart rate or windows and is counted as dropped. Starting another source stops the first and the outputs after the change equal those of a newly configured library (SRS-031).
**Risk controls:** RC-015.

### SRS-042: Test input (UDP, local host only)

**Software item:** desktop
**Milestone:** M3
**Statement:** The application shall provide a test input that receives the stream as UDP datagrams, in the frame format documented in `architecture.md`. The input shall be off at every start of the application, and shall accept datagrams only from the local host. While it is on, the source indication is "TEST INPUT" (SRS-041) and the application states that the test input is never to be used with a worn device. A malformed datagram (wrong length, wrong content, a sample that is not finite or exceeds 1000 mV in magnitude) shall be rejected, counted and not given to the library; a lost or out-of-order frame shall be treated as a gap in the data and start a new continuous segment (SRS-031).
**Rationale:** The test engineer needs a source that can inject faults (gaps, malformed frames, noise) in CI, because the replay cannot (HRS-2, SRS-047). Local host only and off by default keep it from being reached from the network. The link where a worn device could be connected to a computer, a serial link, is left to Milestone 4 (HAZ-005, RC-006), and the statement keeps the test input apart from any use with a person. A gap is never bridged (HAZ-012, RC-014). Decided by the project owner on 2026-10-11 (OP-038: UDP part; serial in Milestone 4).
**Verification level:** Requirement (QA)
**Verification:** Test: after a start of the application the input is off and a datagram sent to its port is not accepted. With the input on, valid frames of a synthetic ECG from the local host give detections and a heart rate, and the warning text is shown. A datagram sent from an address other than the local host (or a connection attempt to the port on another address of the computer) is not accepted. Malformed datagrams of each kind listed are rejected and counted, with no change of the outputs. A stream from which one frame is removed gives a gap: the outputs after it equal those of a newly configured library.
**Risk controls:** RC-006, RC-015.

### SRS-043: Live waveform with beat marks

**Software item:** desktop
**Milestone:** M3
**Statement:** The application shall draw the display waveform of SRS-044 continuously over a window of the last 10 s. The display shall be delayed by 0.5 s after the acquisition of the sample drawn, so that every beat mark reported within the delay of SRS-021 (0.35 s) is drawn at the position of its index, within 20 ms of the R peak of the drawn waveform. A mark reported later (by search-back, up to the maximum delay of SRS-021) shall be added at the position of its index onto the part of the trace already drawn. While the signal status is not usable (SRS-045) no new beat mark shall be drawn, and the waveform shall continue to be drawn.
**Rationale:** The waveform with the beat marks lets the user see what the algorithm did (`functional-analysis.md` F3.1); a mark that disagrees with the waveform makes beats look missed or added (HAZ-001, HAZ-002; RC-019). The display delay is the price of marks that agree with the trace, and 0.5 s covers the normal reporting delay (0.35 s) with margin. The waveform stays visible while the signal is not usable so that the user can see why; marks drawn earlier stay, because quality windows overlap and the stretch has no clean boundary. Whether the window sweeps or scrolls is a design choice (`architecture.md`). Decided by the project owner on 2026-10-11.
**Verification level:** Requirement (QA)
**Verification:** Test on the data given to the drawing, with the synthetic ECG of SRS-006 at 75 and 180 bpm at 360 Hz and 250 Hz: the drawn window spans 10 s; each mark is within 20 ms of the R peak of the drawn waveform; a sample is drawn 0.5 s after its acquisition, within 20 ms. With the synthetic input of `architecture.md` that makes detection report a beat by search-back, the mark appears after the trace at its index position. With a flat stretch of 30 s inside the ECG, no mark is added from the moment the status is not usable, and the trace continues.
**Risk controls:** RC-019.

### SRS-044: Display low-pass

**Software item:** dsp and libs/sinus-dsp
**Milestone:** M3
**Statement:** The reference and the real-time library shall provide a display stage applied to the conditioned signal (SRS-019), as a separate output that does not feed detection, heart rate or signal quality. At 360 Hz and at 250 Hz: its gain shall be within ±1 dB of that of the unfiltered signal from 1 Hz to 30 Hz; its attenuation shall be at least 20 dB at every frequency from 80 Hz to the Nyquist frequency; its group delay shall vary by no more than 20 ms from 1 Hz to 30 Hz and shall be constant and documented in `architecture.md`; the peak R-wave amplitude of the synthetic ECG of SRS-006 shall be kept to at least 90%; and on that ECG with added white noise in the band from 40 Hz to the Nyquist frequency, the RMS of the noise in the output shall be at least 6 dB below that of the input. The detections, heart rates and signal quality windows shall be identical with the stage on and with it off. The reference shall be written first and export the display output in the golden vectors (SRS-015, SRS-033); the library shall equal it within the tolerance of the conditioning stages of SRS-034 (2e-5 mV), checked on every push (SRS-035) and on the ESP32-S3 (SRS-036).
**Rationale:** The conditioned signal keeps high-frequency noise that detection tolerates but that makes the waveform hard to read (OP-070, option (c) decided on 2026-10-07; `functional-analysis.md` F3.12). The stage must not change what is detected, so that the validation results of SRS-007 and SRS-014, obtained without a low-pass, keep holding (RC-019; HAZ-001, HAZ-002). The delay variation bound keeps the QRS shape and the alignment of the marks of SRS-043. The figures are chosen for the project and do not claim any standard; the feasibility of the criteria on the muscle band is checked by the tech lead in the design. Decided by the project owner on 2026-10-11 (OP-070).
**Verification level:** Requirement (QA)
**Verification:** Test on the reference and on the build for the computer: the gain and attenuation are measured with sinusoids at 1, 5, 10, 20, 30, 80, 100 and 120 Hz (and the Nyquist frequency), each of at least 2 s, on the second half; the group delay at 1, 10, 20 and 30 Hz; the R-wave amplitude on the synthetic ECGs of SRS-006 at 30, 75 and 200 bpm; the noise RMS on that ECG with white Gaussian noise of 0.1 mV RMS in the band, over 60 s. The detections, heart rates and windows with the stage on equal those with it off on the synthetic ECGs of SRS-010 and on the golden-vector input signals. The equivalence of the library with the reference is checked on the golden vectors.
**Risk controls:** RC-019.

### SRS-045: Signal status

**Software item:** desktop
**Milestone:** M3
**Statement:** The application shall show the signal status as "usable" only when all of the following hold: the latest signal quality window reported by the library is marked usable (SRS-027); samples arrive, that is, no more than 1 s has passed on the clock of the application since the last sample; and the source is playing (not paused, not ended). Otherwise the status is "not usable" and its reason is stated in words, with the first of these that applies: "data interrupted", "replay paused" or "replay ended", "low signal quality". The 1 s rule applies while the source is playing: while a replay is paused the reason is "replay paused", not "data interrupted", and resuming the replay continues the stream without a restart. Until the first quality window after the start of a stream or after a reset has been reported, the status is "not usable" with the reason "checking signal quality". A status of "not usable" caused by an interruption, a pause or the end of the replay shall be shown within 2 s of its cause; for a signal that becomes constant (flat or saturated), within 7 s of the start of the constant stretch. While the status is "not usable" the heart rate is withheld (SRS-046), no new beat mark is drawn (SRS-043) and the waveform is still drawn.
**Rationale:** Beats and a heart rate from noise, a flat line or a stopped stream must not be presented as valid (HAZ-006, HAZ-007; RC-007, RC-008; `functional-analysis.md` F3.3). The status combines the three conditions that exist without the device; electrode contact and device state are added with the device in Milestone 4 (OP-078). The 7 s bound comes from the window-based index: a stretch counts only when it fills 5 s of a window (SRS-028), the window is reported up to 0.5 s after its end (SRS-027) and a new window starts every 1 s, so a signal that turns flat is shown as not usable after at most 5 s + 0.5 s + 1 s (display refresh) = 6.5 s; noise has no such bound, because the index decides on the window (known limit, OP-074). There is no hysteresis in Milestone 3, because the windows already smooth the index. Decided by the project owner on 2026-10-11 (OP-020).
**Verification level:** Requirement (QA)
**Verification:** Test with synthetic streams (SRS-006 ECG, with a flat stretch, a stretch of white noise of 0.1 mV RMS, a pause, a stop of the data for 3 s, the end of the record): the status and the reason follow the rules above, the status is shown within 2 s for an interruption, a pause and the end, and within 7 s of the start of a flat stretch of 30 s; the status is "not usable" with "checking signal quality" from the start up to the first window; with several causes the reason is the first of the list; while not usable, no mark is added and the waveform continues.
**Risk controls:** RC-007, RC-008.

### SRS-046: Heart-rate display

**Software item:** desktop
**Milestone:** M3
**Statement:** The application shall show the heart rate as the value reported by the library, rounded to a whole number of bpm, with no further smoothing, refreshed at least once per second and never more than 1 s behind the latest value reported. A heart rate outside 30–200 bpm is not shown as a value. When the heart rate is withheld the application shall show "--" and the reason in words next to it: "not enough beats", "no recent beat", "out of range" (reasons of SRS-026), "signal not usable", "data interrupted", "replay paused" or "replay ended" (SRS-045); the last value shall never be shown, greyed or not, while the heart rate is withheld. While the signal status is "not usable" the heart rate is withheld; after the status has become "usable" again it stays withheld, with the reason "not enough beats", until 4 intervals between detections marked reliable whose index lies after the sample at which the status became usable are available. The display shall use no colour scale, normal range, judging label, sound or alarm.
**Rationale:** The heart rate is the main value of the live view (`functional-analysis.md` F3.2); a value from the noise detections or the last value after a stop would be read as current (HAZ-001, HAZ-002, HAZ-006, HAZ-007; RC-007, RC-008). The library value is already robust (SRS-024, SRS-025), so smoothing would add delay without a verified benefit. One second makes beat-by-beat flicker unnecessary and is easy to verify; a whole bpm is within the 2 bpm accuracy of SRS-024. The restart rule is that of the start of a stream (SRS-026) applied after a not usable stretch. No judging labels, because the intended use excludes interpretation and alarms (`safety-class.md`). Decided by the project owner on 2026-10-11 (OP-071).
**Verification level:** Requirement (QA)
**Verification:** Test with sequences of detections and statuses at 360 Hz: the displayed value equals the library value rounded, is not more than 1 s old, and an out-of-range value is shown as "--" with "out of range"; each reason of the list gives "--" and its words in the matching case; no case shows the previous value; after a stretch of status "not usable" the heart rate is withheld until the fourth interval of detections that came after the status became usable, even if the library reports a valid value earlier; inspection that the display has no colour scale, label or sound.
**Risk controls:** RC-007, RC-008.

### SRS-047: Data interruption

**Software item:** desktop
**Milestone:** M3
**Statement:** When no sample arrives for 1 s (measured on the clock of the application, not on the stream), the application shall show "data interrupted" within 2 s of the last sample, shown as the status reason (SRS-045) and as the reason of the withheld heart rate (SRS-046), and shall not show the last heart rate as current. When samples arrive again, the application shall start a new continuous segment: the library is reset (SRS-031), the detections of its start-up period are marked start-up (SRS-022), and the heart rate stays withheld until 4 intervals of reliable detections after the restart are available (SRS-026). A gap of less than 1 s (lost frames) starts a new segment in the same way without the indication "data interrupted".
**Rationale:** A stopped data stream with the last heart rate on the screen is the main use error of HAZ-007 (use scenario HRS-2 of `usability.md`; RC-008). One packet lasts far less than 1 s, so 1 s without samples is a real interruption, and 2 s leaves the user with a few seconds at most of a stale value. Intervals and the heart rate are never computed across a gap (HAZ-012, RC-014). Decided by the project owner on 2026-10-11 (OP-071).
**Verification level:** System (test engineer)
**Verification:** Test with the test input of SRS-042 sending a synthetic ECG with a pause of 3 s in the data, and with a pause of 0.5 s, on the clock of the test: the interruption is shown within 2 s of the last sample sent, the displayed heart rate is "--" with "data interrupted" from then on, and the last value is shown at no time after it; after the data resumes the outputs of the library equal those of a newly configured library given the samples after the pause, the first detections are marked start-up and the heart rate is withheld until the fourth interval; the pause of 0.5 s gives the restart without the indication.
**Risk controls:** RC-008.

### SRS-048: Signal quality mark

**Software item:** desktop
**Milestone:** M3
**Statement:** For each signal quality window reported by the library, the application shall show a mark in words next to the heart rate, "Signal usable" or "Signal not usable: low quality", within 1 s of the report of the window. The application shall show no number, bar, scale or other graded display of the index.
**Rationale:** The index separates a clean signal from a heavily degraded one but does not grade the levels between, and not below 0 dB (SRS-029, OP-074); a graded display would claim a precision that is not verified. The mark is what the signal status needs (RC-007; HAZ-006; `functional-analysis.md` F3.9). A window is reported every 1 s (SRS-027), so the mark is refreshed every second. The mark lags the signal by the window (see SRS-045). Decided by the project owner on 2026-10-11 (OP-072).
**Verification level:** Requirement (QA)
**Verification:** Test with a stream of windows from the library on synthetic ECG with a noisy stretch and a flat stretch: the mark text follows the usable mark of each window, within 1 s of its report; no number or bar is present in the quality display (inspection of the elements of the main window).
**Risk controls:** RC-007.

### SRS-049: Intended-use statement

**Software item:** desktop
**Milestone:** M3
**Statement:** The main window of the application shall show, in every state, the text "Not a medical device, not for diagnosis or health decisions" in a fixed bar at the top, beside the source indication (SRS-041). The bar shall not scroll, and shall not be hidden, overlaid or closable; its text shall be at least as large as the status text of SRS-045 and SRS-046. The same text shall be in the About box. The application shall show no sound, notification or alarm.
**Rationale:** The application is not a medical device and the user must always be able to see it (RC-005; HAZ-001, HAZ-002, HAZ-010; `safety-class.md`). The top bar is where the source is read (HRS-1). A dialog at the first start adds nothing, because a click-through is not read, so none is required. Decided by the project owner on 2026-10-11 (OP-015).
**Verification level:** Requirement (QA)
**Verification:** Test: the exact text is found in the main window, visible and not overlapped, in every state of SRS-041 and for the smallest and the largest size of the window; the bar has no close control; the About box contains the text. Inspection that the text is at least as large as the status text and that the application has no sound or notification.
**Risk controls:** RC-005.

### SRS-050: Mains frequency setting

**Software item:** desktop
**Milestone:** M3
**Statement:** The application shall let the user choose a mains frequency of 50 Hz or 60 Hz for the test input and for the device. The setting is 50 Hz at every start of the application, and the frequency in use is shown in the main window. A change of the setting resets the processing (SRS-031). A replay of a record of the MIT-BIH Arrhythmia Database or the MIT-BIH Noise Stress Test Database uses 60 Hz, a property of the record, shown in the source indication (SRS-041) and not changed by the setting; a replay of a recorded session uses the mains frequency stored in the recording (SRS-051).
**Rationale:** A filter set to the wrong mains frequency leaves the interference in a signal that looks filtered (HAZ-002; RC-002; SRS-005). Automatic detection would add an algorithm whose failure is the hazard itself; a visible setting is testable. The reference records were made on 60 Hz mains (SRS-007), so a replay with the default 50 Hz would filter the wrong frequency; the tolerance of the filter to the deviation of the mains frequency is SRS-054. Decided by the project owner on 2026-10-11 (OP-022).
**Verification level:** Requirement (QA)
**Verification:** Test: the setting at start is 50 Hz and is shown; selecting 60 Hz changes the library configuration, and the outputs after the change equal those of a newly configured library at 60 Hz given the samples after the change; the replay of record 100 shows 60 Hz in the banner and gives the outputs of the library at 60 Hz whichever setting is chosen; no other value can be selected.
**Risk controls:** RC-002.

### SRS-051: Session recording

**Software item:** desktop
**Milestone:** M3
**Statement:** On the user's command the application shall save the session of a replay or of the test input as a record in WFDB format 16, with the samples as given by the source (not the display waveform of SRS-044), and with the metadata: start date and time (UTC), sampling frequency, scale to mV, software version and source digest (SRS-052), the mains frequency in use, and the data source with the name of the record and the mark "replayed" or "test". Gaps and interruptions shall be saved as events at their position in the samples; no sample shall be invented or left out. The detected beats are not saved. A recording of a replay of a recorded session is again marked "replayed". The record shall load in the offline functions of SRS-002 without conversion, and each sample shall equal the sample of the source within half of the resolution of the format. If writing fails (for example the disk is full), the application shall report the failure, and shall leave no file that looks complete.
**Rationale:** Without the device there is no worn session; recording a replay or a test input exercises the writer, the metadata and the gap events, and the round trip through the offline functions (`functional-analysis.md` F2.4; OP-050, OP-034 closed: WFDB only). Replayed or test data that lost its mark could later be taken for a measurement (HAZ-013, RC-015), and an incomplete or altered session processed as complete is HAZ-015 (RC-020). The detections are not saved because they are recomputed offline from the samples. Decided by the project owner on 2026-10-11.
**Verification level:** Requirement (QA)
**Verification:** Test: the first 60 s of a fixture record are replayed and recorded; the record loads with the loader of SRS-002, its samples equal the source within half of the resolution, and its metadata and marks are as stated. A session of the test input with a gap of 3 s has the gap as an event at its position and the sample count of the source. The recording of a replay of that recording is marked "replayed". A target that cannot be written (read-only folder, no space) gives an error message and no file, or a file that names itself incomplete, and no file that loads as complete.
**Risk controls:** RC-015, RC-020.

### SRS-052: Identification

**Software item:** desktop
**Milestone:** M3
**Statement:** The application shall show its version and the identifier of its source code in its About box, and shall write both into each recording (SRS-051).
**Rationale:** A version alone does not identify the code while a milestone is developed; like the library and the reports, the application states both (`sdp.md` §4; `functional-analysis.md` F3.13; OP-076, desktop part). Decided by the project owner on 2026-10-11.
**Verification level:** Requirement (QA)
**Verification:** Test: the version and identifier shown in the About box and written in a recording equal those that the test computes itself with the method documented in `architecture.md`.
**Risk controls:** None.

### SRS-053: Accessible text of heart rate, reason and signal status

**Software item:** desktop
**Milestone:** M3
**Statement:** The application shall expose the heart rate (the value or "--"), its reason and the signal status as text with accessible names to the accessibility interface of the operating system, so that a screen reader can read them, and the text shall equal the text shown and change when it changes. The application does not claim conformance to an accessibility standard.
**Rationale:** The information that decides whether a value may be read must not depend on sight alone (`functional-analysis.md` F3.14; `usability.md`). No conformance claim is made, because the project does not verify against such a standard. Decided by the project owner on 2026-10-11.
**Verification level:** Requirement (QA)
**Verification:** Test through the accessibility interface: for each state of SRS-045 and SRS-046 the accessible name and text of the heart rate, its reason and the status are present and equal the visible text, and update when the display changes.
**Risk controls:** None.

### SRS-054: Mains interference removal under a deviation of the mains frequency

**Software item:** dsp
**Milestone:** M3
**Statement:** The reference shall meet all the criteria of SRS-010 when the mains frequency of the interference deviates by up to ±0.5 Hz from the configured frequency, for the setting of 50 Hz (interference at 49.5 Hz and 50.5 Hz) and of 60 Hz (59.5 Hz and 60.5 Hz).
**Rationale:** The public supply varies around its nominal frequency, and the filter is narrow (SRS-005), so an interference that is not exactly at the configured frequency could pass (HAZ-002; RC-002; OP-022). The criterion of SRS-010 is kept so that the check is the same as for the nominal frequency. If it is not met, the result is reported with the deviations that hold and a new open point is opened; it is not hidden. Decided by the project owner on 2026-10-11 (OP-022).
**Verification level:** System (test engineer)
**Verification:** Test on the synthetic ECGs of SRS-010 (30, 40, 75, 180 and 200 bpm) at 360 Hz and at 250 Hz, with the interference at each of the four frequencies above and the mains setting at the nominal frequency: the pass criteria of SRS-006 hold. The result is recorded in the milestone verification report, with any deviation for which it does not hold.
**Risk controls:** RC-002.
