# Usability: use specification and use-related hazards

_Inspired by IEC 62366-1:2015+A1:2020. Version 0.1, 2026-09-29. Status: draft (Milestone 0)._

> Sinus is not a medical device and claims no compliance with IEC 62366-1. This document borrows, in a light form, the structure of a usability engineering file: it describes who uses Sinus, where and through which user interface, and which use errors could lead to the hazards in [`risk-analysis.md`](risk-analysis.md), so that the user interface is designed around them.

## Conventions

- Use problems are identified as `UP-1`, `UP-2`, … and hazard-related use scenarios as `HRS-1`, `HRS-2`, … These IDs are stable and never reused.
- Hazards (`HAZ-xxx`) and risk controls (`RC-xxx`) are those of [`risk-analysis.md`](risk-analysis.md); functions and features are those of [`functional-analysis.md`](functional-analysis.md).
- Every item still to be defined cites its open point `OP-xxx` in [`open-points.md`](open-points.md).
- **Scope:** the desktop application (Milestone 3 with replay, Milestone 4 with the device) and the handling of the worn device. The offline validation pipeline is used by developers through documented commands; what it shows to readers is the validation report, whose content is fixed by SRS-012.

## Revision history

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-29 | First draft: use specification, user-interface elements related to safety, use problems UP-1 to UP-9, hazard-related use scenarios HRS-1 to HRS-5, evaluation plan |

## 1. Use specification

### 1.1 Intended use

As stated in [`safety-class.md`](safety-class.md) §Intended use, which this document must not contradict:

- Sinus records and displays a single-lead ECG, detects heartbeats and computes heart rate and heart-rate variability **for technical demonstration**.
- There is **no medical indication** and no patient population. Sinus is not intended for diagnosis, for monitoring a medical condition, or for generating alarms or notifications, and its output must not be used to make health decisions.
- The device runs **only on battery power** while electrodes are attached, and communicates with the computer only over the wireless link while worn.

### 1.2 User profiles

| User | Uses | Characteristics relevant to use |
|---|---|---|
| Developer | Desktop application (replay, live view, recording, test input), offline pipeline | Adult, technically trained, knows ECG basics and this documentation; reads English |
| Wearer | Device (electrodes, power), desktop application (live view) | Adult volunteer, usually the developer; no medical training assumed; may be distracted by the demonstration; may be anxious about what the screen shows about their own heart |
| Reader | Published reports and documentation only | Any background; may be a clinician or reviewer; may take numbers out of context |

Wearer exclusions and use-environment limits (e.g. minimum age, implanted pacemaker or defibrillator) are to be defined before the first worn session (OP-028).

### 1.3 Use environment

- Indoors, at a desk or nearby, in normal room lighting; the computer screen is viewed from about 0.5 to 1 m.
- The wearer is at rest or in light activity, for a demonstration session of limited duration (OP-023).
- The computer running the desktop application may be mains-powered, because the worn device is linked to it only wirelessly. A wired test input exists only for sources that are not worn (replay tools, simulators, a device on the bench without a person connected).
- Replay use needs no device and no person connected.

### 1.4 User interface

The desktop application has one main (live) view. Its layout and the user-interface technology are decided at Milestone 3 (OP-033). The elements below are required by the functional analysis:

| Element | Content | Feature | Risk control |
|---|---|---|---|
| Data source indication | Device, replay (with the record or session name) or test input; always visible | F3.10 | RC-015 (OP-037) |
| Intended-use statement | "Not a medical device, not for diagnosis or health decisions"; always visible | F3.6 | RC-005 (OP-015) |
| Waveform | Conditioned ECG against time, with detected beats marked | F3.1 | — |
| Heart rate | In bpm, shown only while valid; otherwise withheld, with the reason | F3.2 | RC-007, RC-008 (OP-021) |
| Signal quality indicator | Quality of the current window; not-usable windows shown as such | F3.9 | RC-007 (OP-032) |
| Signal status | Usable or not usable, with the reason (low quality, contact lost, data interrupted, device state) | F3.3 | RC-007, RC-008 (OP-020) |
| Device state | Connection, battery level, low battery, error, restart | F4.5, F4.6, F4.7 | RC-013, RC-014 (OP-035, OP-036) |
| Recording control | Start and stop recording, with a visible recording indicator | F2.4 | — |
| Replay controls | Select a record or session, play, pause, stop | F3.8 | RC-015 (OP-037) |
| Test input selection | Wired or network test input, with the statement that it is never used with a worn device | F3.11 | RC-006 (OP-038) |
| Mains frequency setting | 50 Hz or 60 Hz, or automatic | F3.7 | RC-002 (OP-022) |

The application has **no alarms, sounds or notifications**, and no label that judges the signal (such as "normal", "abnormal" or a colour scale for the heart rate), because any of these would change the intended use (see `safety-class.md` §Review triggers).

The physical interface of the device (power switch, indicators, electrode connector, charging port) is defined with the hardware at Milestone 4 (OP-024, OP-038).

### 1.5 Operating principle

The device acquires the ECG and sends it over the wireless link; the desktop application conditions the signal, detects beats, tracks the heart rate, assesses signal quality, displays the result and records the session. In replay, a stored record takes the place of the device and follows the same path.

## 2. Use problems and use-related hazards

Known and foreseeable use problems, from the foreseeable misuse in `functional-analysis.md` §2.4 and from problems common to heart-rate displays and ECG viewers:

| ID | Use problem | Hazard | User-interface control | Open point |
|---|---|---|---|---|
| UP-1 | The heart rate, beat marks or (later) beat classes are read as health information, or shown to a clinician | HAZ-001, HAZ-002, HAZ-010 | Intended-use statement always visible; no judging labels or alarms | OP-015 |
| UP-2 | Data stops arriving but the screen still looks live, and the last heart rate is taken as current | HAZ-007 | Interruption shown within a defined time; heart rate withheld; device state shown | OP-021, OP-036 |
| UP-3 | The signal quality indicator or the "not usable" status is not noticed, and a heart rate computed from noise is read | HAZ-006 | Heart rate withheld while not usable, not just flagged; quality indicator next to the heart rate | OP-020, OP-032 |
| UP-4 | A replayed record or a recorded session is taken for the wearer's live signal | HAZ-013 | Data source always visible; replayed recordings marked | OP-037 |
| UP-5 | The low-battery indication is missed and the session ends without the wearer noticing | HAZ-011 | Low battery shown before the signal degrades; the end of acquisition is shown and recorded | OP-035 |
| UP-6 | A gap after a device restart is not noticed, and the missing beats are read as a pause of the heart | HAZ-012 | Restart and gap shown; no beat intervals across a gap | OP-036 |
| UP-7 | A charger, a computer cable or the wired test input is connected to the device while it is worn | HAZ-005 | Warnings in the README, the hardware documentation and the test input selection; charging concept that excludes it | OP-024, OP-038 |
| UP-8 | The mains frequency setting does not match the place of use | HAZ-002 | Setting visible on the live view | OP-022 |
| UP-9 | Beats left unclassified are overlooked, or a class is read as a diagnosis (Milestone 6) | HAZ-014 | Unclassified beats shown as such; abstention rate shown with the results | OP-039 |

## 3. Hazard-related use scenarios

Scenarios selected for evaluation, because a use error in them leads to one of the hazards above:

| ID | Scenario | Use problems | Milestone |
|---|---|---|---|
| HRS-1 | A user joins a demonstration while a record is being replayed and tells whether the waveform is replayed or live, and from which source | UP-4 | M3 |
| HRS-2 | During a replay, the stream is interrupted; the user tells within a few seconds that the heart rate is no longer current | UP-2 | M3 |
| HRS-3 | A replayed segment with low signal quality (e.g. a noise stress record at low SNR) is shown; the user tells that no valid heart rate is available and why | UP-3 | M3 |
| HRS-4 | During a worn session the battery runs low, then the device restarts; the user tells what happened and which part of the recording is valid | UP-5, UP-6 | M4 |
| HRS-5 | The wearer prepares and starts a worn session following the documentation, without connecting any cable to the device | UP-7 | M4 |

## 4. User-interface specification

The requirements for the user interface are written as `SRS-xxx` entries at Milestone 3 (desktop application) and Milestone 4 (device), from the elements in §1.4 and the controls in §2.

## 5. Evaluation plan

- **Formative evaluation, Milestone 3:** the hazard-related use scenarios HRS-1 to HRS-3 are run with replay by at least one person other than the developer of the user interface, with a think-aloud protocol. Findings feed the user-interface requirements. Method, participants and success criteria: OP-040.
- **Repeat with the device, Milestone 4:** HRS-4 and HRS-5, and HRS-1 to HRS-3 again with the device connected (OP-040).
- Results are recorded in the milestone verification report in `docs/validation/`.

## 6. Open points referenced

OP-015, OP-020 to OP-024, OP-028, OP-032, OP-033, OP-035 to OP-040. See [`open-points.md`](open-points.md).
