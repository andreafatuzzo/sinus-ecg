# Software Requirements Specification

_Inspired by IEC 62304 §5.2. Version 0.7.2, 2026-10-05. Status: confirmed by the project owner (Milestone 1)._

## Conventions

- Each requirement is a heading of the form `### SRS-001: Short title`, followed by its text, rationale, and related risk-control IDs (see `risk-analysis.md`).
- IDs are never reused or renumbered. A removed requirement keeps its heading, marked as _Deleted_.
- Code that implements a requirement cites its ID in a comment or docstring.
- Tests that verify a requirement are marked with `@pytest.mark.requirement("SRS-001")` (Python) or preceded by a `// Verifies: SRS-001` line directly above the GoogleTest macro (C++), as set out in ADR 0004.
- `docs/regulatory/traceability.md` is generated from these sources by `dsp/scripts/traceability.py`.
- "Software item" names which item implements the requirement (see `sdp.md` §1).
- "Verification level" assigns the functional verification: `Requirement` tests are written by QA in `<item>/tests/requirements/`, `System` tests by the test engineer in `<item>/tests/system/` (for example `dsp/tests/…`, `libs/sinus-dsp/tests/…`) (see `sdp.md` §6). The implementer never verifies their own code functionally.
- "Milestone" names the roadmap milestone (`README.md`) that delivers the requirement. A pull request into `main` fails CI unless every requirement of a milestone that is in progress or released (see [`milestones.md`](milestones.md)) has a verifying test ([ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md)).
- Requirements are derived from the features in [`functional-analysis.md`](functional-analysis.md).

## Scope of this version

This version covers the Milestone 1 software item only: the offline DSP reference implementation and its validation pipeline (`dsp/`), features F1.1 to F1.12 of the functional analysis. Requirements for the portable real-time signal-processing library (Milestone 2), the desktop application (Milestone 3), the firmware (Milestone 4), the backend (Milestone 5) and beat classification (Milestone 6) are added at the milestones that introduce them, from the features listed for them in [`functional-analysis.md`](functional-analysis.md) §5.

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
- is empty or contains non-finite values (NaN or ±infinity);
- is shorter than 10 s;
- or has a sampling frequency that is not finite or lies outside 125–1000 Hz (bounds included).

**Rationale:** Meaningless input must not produce output that looks valid. 10 s holds at least five beats at 30 bpm, the minimum for detection to establish its signal level. 125 Hz keeps the 60 Hz mains frequency below the Nyquist limit; 1000 Hz covers common ECG front ends. The device samples at 360 Hz (OP-004, closed), inside this range.
**Verification level:** Requirement (QA)
**Verification:** Test, for the filters of SRS-004 and SRS-005 and the detection of SRS-006. Rejected with an error and no output: an empty input; an input with one NaN, one with +infinity and one with −infinity; 9.99 s; 124.9 Hz; 1000.1 Hz; a non-finite sampling frequency. Accepted: 10 s at 125 Hz and at 1000 Hz.
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
**Verification:** Analysis, from the validation report generated per SRS-009 and SRS-012. A test that requires the local database checks both thresholds; it is skipped in CI, where the database is not available, and its result is recorded in the milestone's validation report.
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
