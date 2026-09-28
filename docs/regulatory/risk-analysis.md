# Risk analysis

_Inspired by ISO 14971:2019. Version 0.2, 2026-09-28. Status: draft (Milestone 0)._

## Conventions

- Hazards are identified as `HAZ-001`, risk controls as `RC-001`.
- A risk control implemented in software links to the `SRS-xxx` requirement(s) that implement it, and each of those requirements lists the control.
- Every change that affects behavior is reviewed against this document.
- User-level hazards come from the use scenarios in [`functional-analysis.md`](functional-analysis.md). IDs HAZ-006 to HAZ-009 and RC-007 to RC-010 are reserved for hazards already identified there and analysed at the milestone that introduces them: electrode contact loss (OP-020), stale data on screen (OP-021), battery overheating and skin reaction (OP-025).

## Revision history

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-28 | First draft: HAZ-001 to HAZ-005, RC-001 to RC-006 |
| 0.2 | 2026-09-28 | Review against the functional analysis (OP-019): acceptability rule for S4; HAZ-005 rated S4; causes added to HAZ-001 and HAZ-002; HAZ-010 and RC-011 added; "Implemented by" updated for SRS v0.2 (SRS-010 to SRS-012) |

## Scope

- **Intended use and foreseeable misuse:** see [`safety-class.md`](safety-class.md). The main foreseeable misuse is reading Sinus output as health information.
- **Covered now:** hazards arising from the system as a whole, from the Milestone 1 software (offline filtering, QRS detection and validation), and from published or exported results.
- **To be analysed at the milestone that introduces them:**
  - BLE data loss or corruption (Milestone 2, OP-012);
  - real-time latency (Milestone 3, OP-014);
  - stored personal data, authentication and privacy (Milestone 4, OP-016);
  - beat classification (Milestone 5, OP-017).

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
| HAZ-001 | QRS complexes missed (false negatives), including when pacing spikes of a wearer with a pacemaker are taken for beats and mask missed ones; the heart rate shown is too low or irregular beats go unseen | User is falsely reassured and delays seeking care for a real symptom | S2 | P3 | RC-001, RC-004, RC-005 | P2 | Yes |
| HAZ-002 | Noise, baseline wander, mains interference (including a mains frequency setting wrong for the place of use) or pacing spikes detected as beats (false positives); the heart rate shown is too high or irregular | User is falsely alarmed: anxiety or an unnecessary medical visit | S2 | P3 | RC-001, RC-002, RC-004, RC-005 | P2 | Yes |
| HAZ-003 | Invalid input (non-finite samples, wrong sampling frequency, too-short record) processed silently, and meaningless output presented as valid | As HAZ-001 or HAZ-002 | S2 | P3 | RC-003, RC-005 | P1 | Yes |
| HAZ-004 | Validation results do not represent real performance (corrupted data, non-standard scoring, results that cannot be reproduced), so the algorithm is trusted more than it deserves | Increases the probability of HAZ-001 and HAZ-002 | S2 | P2 | RC-004 | P1 | Yes |
| HAZ-005 | Current flows through the electrodes when the worn device is connected to mains-powered equipment (USB, charger) | Electric shock; current across the chest can cause ventricular fibrillation | S4 | P2 | RC-006 | P1 | Yes (S4 rule: RC-006 is inherent safety by design, verified by inspection) |
| HAZ-010 | Published or exported results (validation report, later the FHIR export) are taken by a reader, a clinician or another system as clinical-grade data | Overtrust in the algorithm, or a wrong decision about the wearer | S2 | P2 | RC-005, RC-011 | P1 | Yes |

S3 for HAZ-001/002 would require an alarm or diagnostic claim. The intended use excludes both (see [`safety-class.md`](safety-class.md)), so the worst credible harm is rated S2.

HAZ-005 is rated S4 because the worst credible harm of mains current across the chest is death. It is controlled in hardware, not by software (see `safety-class.md` §Rationale, point 4), and its acceptability depends on the inspection of the schematic (OP-013).

## Risk controls

| ID | Risk control | Type (ISO 14971 §7.1) | Implemented by | Verified by |
|---|---|---|---|---|
| RC-001 | QRS detection meets a quantified performance target on a reference database | Inherent safety by design | SRS-006, SRS-007 | EC57 validation report |
| RC-002 | Baseline wander and mains interference are filtered out, and detection meets its criteria when they are present | Inherent safety by design | SRS-004, SRS-005, SRS-010 | Tests of SRS-004, SRS-005 and SRS-010 |
| RC-003 | Invalid input is rejected with an explicit error; no filtered signal or detections are produced from it | Protective measure | SRS-003 | Tests of SRS-003 |
| RC-004 | Validation uses checksum-verified reference data, standard EC57 scoring and statistics, and a reproducible report of defined content | Protective measure | SRS-001, SRS-008, SRS-009, SRS-011, SRS-012 | Tests of SRS-001, SRS-008, SRS-009, SRS-011 and SRS-012 |
| RC-005 | Intended-use labeling: "Not a medical device, not for diagnosis or health decisions", shown in the README, in the validation report and later in the app | Information for safety | README; validation report (SRS-012); app (Milestone 3, OP-015) | Inspection; test of SRS-012 |
| RC-006 | Battery-only operation while worn: no electrical path to mains through the device, plus warning labeling | Inherent safety by design (hardware) + information for safety | Hardware design (charging concept OP-024); README | Inspection of schematic (Milestone 2, OP-013) |
| RC-011 | Published and exported results state their non-medical origin and carry no clinical interpretation | Information for safety | Validation report (SRS-012); FHIR export (Milestone 4, OP-027) | Test of SRS-012; export: to be defined with OP-027 |

## Residual risk

All hazards are acceptable after their risk controls. The overall residual risk is acceptable **for the stated intended use**, and depends on RC-005: using Sinus as a health monitor falls outside this analysis.
