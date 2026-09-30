# Risk analysis

_Inspired by ISO 14971:2019. Version 0.3.2, 2026-09-29. Status: draft (Milestone 0)._

## Conventions

- Hazards are identified as `HAZ-001`, risk controls as `RC-001`.
- A risk control implemented in software links to the `SRS-xxx` requirement(s) that implement it, and each of those requirements lists the control.
- Every change that affects behavior is reviewed against this document.
- User-level hazards come from the use scenarios in [`functional-analysis.md`](functional-analysis.md); use-related hazards are also listed in [`usability.md`](usability.md).
- IDs HAZ-008, HAZ-009, RC-009 and RC-010 remain reserved for battery overheating and skin reaction to electrodes (OP-025), analysed with the hardware at Milestone 4. HAZ-006, HAZ-007, RC-007 and RC-008, reserved in v0.2 for electrode contact loss and stale data, are now used for those hazards.
- A risk control whose implementing requirements belong to a later milestone names that milestone and its open point. Its hazard is acceptable only once those requirements are written and verified.

## Revision history

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-28 | First draft: HAZ-001 to HAZ-005, RC-001 to RC-006 |
| 0.2 | 2026-09-28 | Review against the functional analysis (OP-019): acceptability rule for S4; HAZ-005 rated S4; causes added to HAZ-001 and HAZ-002; HAZ-010 and RC-011 added; "Implemented by" updated for SRS v0.2 (SRS-010 to SRS-012) |
| 0.3 | 2026-09-29 | Aligned with functional analysis v0.2 (new roadmap: portable real-time library, desktop application with replay, ESP32-S3 device). Added HAZ-006 (contact loss and low signal quality), HAZ-007 (stale data), HAZ-011 (low battery), HAZ-012 (device fault, watchdog reset, data gaps), HAZ-013 (replayed or test data taken for the live signal), HAZ-014 (beat class shown where the system should abstain); RC-007, RC-008, RC-012 to RC-016. Causes added to HAZ-001, HAZ-002 (real-time implementation differs from the reference), HAZ-004 (performance known only on clean data) and HAZ-005 (wired test link). RC-004 extended to SRS-013, SRS-014 and SRS-016. Milestone references renumbered |
| 0.3.1 | 2026-09-29 | Security causes added to HAZ-001, HAZ-002 and HAZ-013, from the threat model in cybersecurity.md (TH-2, TH-4, TH-7, TH-18) |
| 0.3.2 | 2026-09-29 | Process review: header version; HAZ-007 acceptability now cites Milestones 2 to 4 (heart-rate tracking at Milestone 2) |

## Scope

- **Intended use and foreseeable misuse:** see [`safety-class.md`](safety-class.md). The main foreseeable misuse is reading Sinus output as health information.
- **Covered now:** hazards arising from the system as a whole, from the Milestone 1 software (offline filtering, QRS detection, validation and golden-vector export), and from published or exported results. Hazards of the later milestones that can already be stated from the functional analysis (signal quality, stale data, low battery, device faults, replay, abstention) are listed with their controls; their implementing requirements are written at the milestone that introduces them.
- **To be analysed at the milestone that introduces them:**
  - wireless link: corruption, reordering and unauthorised access (Milestone 4, OP-012; security in `cybersecurity.md`);
  - real-time latency and sampling jitter (Milestone 4, OP-014);
  - battery overheating and skin reaction (Milestone 4, OP-025);
  - stored personal data, authentication and privacy (Milestone 5, OP-016);
  - beat classification as a whole, and the review of the safety classification (Milestone 6, OP-017).

## Scales

**Severity**

| Level | Meaning |
|---|---|
| S1 Negligible | Inconvenience or temporary discomfort |
| S2 Minor | Temporary anxiety, an unnecessary medical visit, or a short delay in seeking care for a non-urgent condition |
| S3 Serious | Injury or impairment requiring medical intervention, or a significant delay in treating an urgent condition |
| S4 Critical | Death or permanent impairment |

**Probability of harm** (the software itself is assumed to fail; this is the probability that a failure leads to harm)

| Level | Meaning |
|---|---|
| P1 Improbable | Requires several unlikely events together |
| P2 Remote | Could happen, but is unlikely over the life of the project |
| P3 Occasional | Likely to happen sometimes |

**Acceptability:** S1 is acceptable at any probability. S2 is acceptable at P1–P2. S3 is acceptable only at P1. S4 is acceptable only at P1, and only when the reduction to P1 comes from an inherent-safety-by-design control that is verified by inspection; otherwise S4 is not acceptable.

## Hazards

| ID | Hazard / hazardous situation | Possible harm | S | P before | Risk controls | P after | Acceptable |
|---|---|---|---|---|---|---|---|
| HAZ-001 | QRS complexes missed (false negatives), including when pacing spikes of a wearer with a pacemaker are taken for beats and mask missed ones, or when the real-time implementation behaves differently from the validated reference, or when packets are injected or altered on the wireless link or the firmware is altered (cybersecurity.md TH-4, TH-18); the heart rate shown is too low or irregular beats go unseen | User is falsely reassured and delays seeking care for a real symptom | S2 | P3 | RC-001, RC-004, RC-005, RC-012 | P2 | Yes |
| HAZ-002 | Noise, baseline wander, mains interference (including a mains frequency setting wrong for the place of use) or pacing spikes detected as beats (false positives), including when the real-time implementation behaves differently from the validated reference, or when packets are injected or altered on the wireless link or the firmware is altered (cybersecurity.md TH-4, TH-18); the heart rate shown is too high or irregular | User is falsely alarmed: anxiety or an unnecessary medical visit | S2 | P3 | RC-001, RC-002, RC-004, RC-005, RC-012 | P2 | Yes |
| HAZ-003 | Invalid input (non-finite samples, wrong sampling frequency, too-short record) processed silently, and meaningless output presented as valid | As HAZ-001 or HAZ-002 | S2 | P3 | RC-003, RC-005 | P1 | Yes |
| HAZ-004 | Validation results do not represent real performance (corrupted data, non-standard scoring, results that cannot be reproduced, performance known only on clean recordings), so the algorithm is trusted more than it deserves | Increases the probability of HAZ-001 and HAZ-002 | S2 | P2 | RC-004 | P1 | Yes |
| HAZ-005 | Current flows through the electrodes when the worn device is connected to mains-powered equipment (USB, charger, or a wired test or debug link to a computer) | Electric shock; current across the chest can cause ventricular fibrillation | S4 | P2 | RC-006 | P1 | Yes, pending verification of RC-006 (OP-013, OP-024, OP-038); S4 rule: RC-006 is inherent safety by design, verified by inspection |
| HAZ-006 | Electrode contact lost or poor, or signal quality too low (motion artefact, noise): beats and a heart rate computed from noise, or a flat line, are shown as if valid | As HAZ-001 or HAZ-002 | S2 | P3 | RC-007, RC-005 | P2 | Yes, once the requirements of RC-007 are written and verified (Milestones 2 to 4, OP-020, OP-032) |
| HAZ-007 | Data stop arriving (wireless link lost, device in error state or restarting, desktop application stalled, replay ended) and the last waveform and heart rate stay on screen as if current, or a heart rate is carried forward or predicted across the missing beats | As HAZ-001 | S2 | P3 | RC-008, RC-014 | P2 | Yes, once the requirements of RC-008 and RC-014 are written and verified (Milestones 2 to 4, OP-021, OP-036) |
| HAZ-010 | Published or exported results (validation report, later the FHIR export) are taken by a reader, a clinician or another system as clinical-grade data | Overtrust in the algorithm, or a wrong decision about the wearer | S2 | P2 | RC-005, RC-011 | P1 | Yes |
| HAZ-011 | Battery runs low during a session: the device stops without notice, or its front end acquires a degraded signal (clipping, added noise) that is processed and shown as valid; the session recording is lost or truncated | As HAZ-001 or HAZ-002; loss of the session | S2 | P3 | RC-013, RC-007 | P2 | Yes, once the requirements of RC-013 are written and verified (Milestone 4, OP-035) |
| HAZ-012 | Device fault or watchdog restart during a session, or samples lost on the wireless link: if the gap is not detected and marked, the recording and the derived beat intervals join samples across it, so a spurious pause or wrong heart rate is shown or stored; the recording made before the fault is lost | As HAZ-001 or HAZ-002; loss of the session | S2 | P3 | RC-014 | P2 | Yes, once the requirements of RC-014 are written and verified (Milestone 4, OP-036) |
| HAZ-013 | Replayed reference data, a recorded session or a test input is taken for the wearer's live signal (e.g. a record with ventricular ectopy replayed while the device is worn), or data from a spoofed or wrong device, or from another process on the test input (cybersecurity.md TH-2, TH-7) | User is falsely alarmed or falsely reassured about their own heart | S2 | P3 | RC-015, RC-005 | P2 | Yes, once the requirements of RC-015 are written and verified (Milestone 3, OP-037) |
| HAZ-014 | A beat class is shown for a beat whose signal quality or classification confidence is too low (abstention missing or thresholds wrong), and is read as health information | As HAZ-001 or HAZ-002 | S2 | P3 | RC-016, RC-005 | P2 | Provisional: analysed with beat classification (Milestone 6, OP-017, OP-039) |

S3 for HAZ-001/002 would require an alarm or diagnostic claim. The intended use excludes both (see [`safety-class.md`](safety-class.md)), so the worst credible harm is rated S2.

HAZ-005 is rated S4 because the worst credible harm of mains current across the chest is death. It is controlled in hardware, not by software (see `safety-class.md` §Rationale, point 4), and its acceptability depends on the inspection of the schematic (OP-013).

## Risk controls

| ID | Risk control | Type (ISO 14971 §7.1) | Implemented by | Verified by |
|---|---|---|---|---|
| RC-001 | QRS detection meets a quantified performance target on a reference database | Inherent safety by design | SRS-006, SRS-007 | EC57 validation report |
| RC-002 | Baseline wander and mains interference are filtered out, and detection meets its criteria when they are present | Inherent safety by design | SRS-004, SRS-005, SRS-010 | Tests of SRS-004, SRS-005 and SRS-010 |
| RC-003 | Invalid input is rejected with an explicit error; no filtered signal or detections are produced from it | Protective measure | SRS-003 | Tests of SRS-003 |
| RC-004 | Validation uses checksum-verified reference data, standard EC57 scoring and statistics, performance under noise, and a reproducible report of defined content, regenerated on a subset of records at every change | Protective measure | SRS-001, SRS-008, SRS-009, SRS-011, SRS-012, SRS-013, SRS-014, SRS-016 | Tests of SRS-001, SRS-008, SRS-009, SRS-011, SRS-012, SRS-013, SRS-014 and SRS-016 |
| RC-005 | Intended-use labeling stating that Sinus is not a medical device and not for diagnosis or health decisions, shown in the README, in the validation report (with the wording fixed by SRS-012) and later in the desktop application | Information for safety | README; validation report (SRS-012); desktop application (Milestone 3, OP-015) | Inspection; test of SRS-012 |
| RC-006 | Battery-only operation while worn: no electrical path to mains through the device, including any wired data or debug link, plus warning labeling in the README, the hardware documentation and the desktop application | Inherent safety by design (hardware) + information for safety | Hardware design (charging concept OP-024; wired links OP-038); README; desktop application (Milestone 3) | Inspection of schematic (Milestone 4, OP-013) |
| RC-007 | The signal is assessed as usable or not usable from electrode contact and a per-window signal quality index; while it is not usable, no beats or heart rate are presented as valid, and the signal quality is shown | Protective measure | Signal quality index (Milestone 2), desktop application (Milestone 3), contact detection (Milestone 4); OP-020, OP-032 | Tests of the Milestone 2 to 4 requirements |
| RC-008 | The desktop application shows within a defined time that data has stopped arriving, stops presenting the last waveform and heart rate as current, and never shows an estimated heart rate across missing beats beyond a defined time | Protective measure | Desktop application (Milestone 3), heart-rate tracking (Milestone 2); OP-021 | Tests of the Milestone 2 and 3 requirements; replay of interrupted streams |
| RC-011 | Published and exported results state their non-medical origin and carry no clinical interpretation | Information for safety | Validation report (SRS-012); FHIR export (Milestone 5, OP-027) | Test of SRS-012; export: to be defined with OP-027 |
| RC-012 | Every real-time implementation of signal conditioning and beat detection gives the same results as the validated reference, within a defined tolerance, on golden vectors exported by the reference | Protective measure | SRS-015 (export); equivalence requirements of Milestone 2 (OP-005) | Test of SRS-015; equivalence tests (Milestone 2) |
| RC-013 | The device monitors its battery; at a defined low level it reports a low-battery state to the desktop application before the signal degrades, then stops acquisition in an orderly way, and the session recording is closed with the event marked | Protective measure | Firmware and desktop application (Milestone 4, OP-035) | Tests of the Milestone 4 requirements |
| RC-014 | The device has an explicit error state and a watchdog; faults, restarts and lost samples are detected (packet sequence numbers), reported to the desktop application, marked as gaps in the recording and excluded from beat intervals and heart rate; the recording made before a fault is kept | Protective measure | Firmware and desktop application (Milestone 4, OP-036) | Tests of the Milestone 4 requirements; fault injection |
| RC-015 | The desktop application shows the data source at all times (live device, replay with the record name, test input), and recordings of replayed or test data are marked as such | Information for safety | Desktop application (Milestone 3, OP-037) | Tests of the Milestone 3 requirements; usability evaluation (OP-040) |
| RC-016 | Beat classification abstains when signal quality or classification confidence is below a threshold, shows abstained beats as not classified, and reports metrics on all beats, on accepted beats and the abstention rate | Protective measure | Beat classification (Milestone 6, OP-039) | Tests of the Milestone 6 requirements; validation report |

## Residual risk

All hazards are acceptable after their risk controls; for HAZ-005 this holds once RC-006 is verified (OP-013, OP-024, OP-038). For HAZ-006, HAZ-007 and HAZ-011 to HAZ-013 it holds once the requirements implementing their controls are written and verified at the milestones named above; HAZ-014 is re-assessed with beat classification (OP-017). The overall residual risk is acceptable **for the stated intended use**, and depends on RC-005: using Sinus as a health monitor falls outside this analysis.
