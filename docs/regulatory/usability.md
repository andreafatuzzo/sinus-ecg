# Usability: use specification and use-related hazards

_Inspired by IEC 62366-1:2015+A1:2020. Version 0.2, 2026-10-11. Status: draft; version 0.2 specifies the Milestone 3 user interface, decided by the project owner on 2026-10-11._

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
| 0.1.1 | 2026-10-07 | Open points only: the heart rate and the signal quality indicator (§1.4) and UP-2 and UP-3 (§2) cite OP-071 and OP-072, the display parts of OP-021 and OP-032, which were closed with the Milestone 2 requirements (`srs.md` v0.8). No other change |
| 0.2 | 2026-10-11 | Milestone 3, with `srs.md` v0.9: §1.4 rewritten (text banners for the source and the intended-use statement, signal quality as a mark with a reason word and no number, heart rate rules, no judging colours, no alarms or sounds, accessibility of the main readings); UP-1 to UP-4 and UP-8 cite their requirements instead of open points; §4 lists the requirements by element; §5 states the plan of the formative evaluation (3 participants, success criteria per scenario), with the repeat with the device as OP-079 (Milestone 4). Decided by the project owner on 2026-10-11 |

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

The desktop application has one main (live) view. Its layout is a design choice (the technology is decided in the architecture). The elements below are required by the functional analysis; meaning is always carried by text, never by colour alone:

| Element | Content | Feature | Risk control |
|---|---|---|---|
| Data source indication | Text banner at the top, in the same place for every source: "REPLAY" with the record or session name and speed, "TEST INPUT", "DEVICE" (Milestone 4); the word REPLAY also on the waveform area; always visible | F3.10 | RC-015 (SRS-041) |
| Intended-use statement | "Not a medical device, not for diagnosis or health decisions"; fixed bar at the top, beside the source banner, never scrolled, hidden, overlaid or closable, at least as large as the other status text; also in the About box and in the title of any exported image | F3.6 | RC-005 (SRS-049) |
| Waveform | ECG against time over 10 s, with detected beats marked; the display is delayed by 0.5 s | F3.1, F3.12 | RC-019 (SRS-043, SRS-044) |
| Heart rate | Integer in bpm, 30 to 200, refreshed at least once per second; otherwise "--" with the reason in words; no colour scale, no normal range | F3.2 | RC-007, RC-008 (SRS-046) |
| Signal quality mark | "Signal usable" or "Signal not usable" with a reason word, next to the heart rate, refreshed every second; no number, bar or graded colour | F3.9 | RC-007 (SRS-048) |
| Signal status | Usable or not usable, with the reason in words, highest priority first (data interrupted, replay paused or ended, low quality); contact lost and device state from Milestone 4 (OP-078) | F3.3 | RC-007, RC-008 (SRS-045, SRS-047) |
| Device state | Connection, battery level, low battery, error, restart | F4.5, F4.6, F4.7 | RC-013, RC-014 (OP-035, OP-036) |
| Recording control | Start and stop recording of a replay or test input, with a visible recording indicator | F2.4 | RC-015, RC-020 (SRS-051) |
| Replay controls | Select a record or session, start position, speed (1, 2, 5, 10 times), play, pause, resume, stop; "Replay ended" at the end | F3.8 | RC-015 (SRS-039) |
| Test input selection | UDP on the local host only, off by default, with the statement that it is never used with a worn device | F3.11 | RC-006, RC-015 (SRS-042) |
| Mains frequency setting | 50 Hz or 60 Hz, default 50 Hz, visible on the live view; 60 Hz for the MIT-BIH and NSTDB records, shown in the source banner | F3.7 | RC-002 (SRS-050) |
| About box | Version and source identifier, intended-use statement | F3.13, F3.6 | RC-005 (SRS-052, SRS-049) |

The application has **no alarms, sounds or notifications**, and no label that judges the signal (such as "normal", "abnormal" or a colour scale for the heart rate), because any of these would change the intended use (see `safety-class.md` §Review triggers). The signal quality is a mark with a reason word, not a graded value, because the index does not grade the levels below about 0 dB (OP-074).

**Accessibility.** The heart rate, its reason when withheld and the signal status are exposed as text with accessible names, so that a screen reader can read them (SRS-053). No conformance to an accessibility standard is claimed.

The physical interface of the device (power switch, indicators, electrode connector, charging port) is defined with the hardware at Milestone 4 (OP-024, OP-038).

### 1.5 Operating principle

The device acquires the ECG and sends it over the wireless link; the desktop application conditions the signal, detects beats, tracks the heart rate, assesses signal quality, displays the result and records the session. In replay, a stored record takes the place of the device and follows the same path.

## 2. Use problems and use-related hazards

Known and foreseeable use problems, from the foreseeable misuse in `functional-analysis.md` §2.4 and from problems common to heart-rate displays and ECG viewers:

| ID | Use problem | Hazard | User-interface control | Open point |
|---|---|---|---|---|
| UP-1 | The heart rate, beat marks or (later) beat classes are read as health information, or shown to a clinician | HAZ-001, HAZ-002, HAZ-010 | Intended-use statement always visible; no judging labels or alarms | SRS-049 |
| UP-2 | Data stops arriving but the screen still looks live, and the last heart rate is taken as current | HAZ-007 | Interruption shown within 2 s of the last sample; heart rate withheld; device state shown | SRS-045, SRS-046, SRS-047; OP-036 |
| UP-3 | The signal quality indicator or the "not usable" status is not noticed, and a heart rate computed from noise is read | HAZ-006 | Heart rate withheld while not usable, not just flagged; quality mark next to the heart rate | SRS-045, SRS-046, SRS-048 |
| UP-4 | A replayed record or a recorded session is taken for the wearer's live signal | HAZ-013 | Data source always visible, also at higher replay speeds; replayed recordings marked | SRS-039, SRS-041, SRS-051 |
| UP-5 | The low-battery indication is missed and the session ends without the wearer noticing | HAZ-011 | Low battery shown before the signal degrades; the end of acquisition is shown and recorded | OP-035 |
| UP-6 | A gap after a device restart is not noticed, and the missing beats are read as a pause of the heart | HAZ-012 | Restart and gap shown; no beat intervals across a gap | OP-036 |
| UP-7 | A charger, a computer cable or the wired test input is connected to the device while it is worn | HAZ-005 | Warnings in the README, the hardware documentation and the test input selection; charging concept that excludes it | SRS-042; OP-024, OP-038 |
| UP-8 | The mains frequency setting does not match the place of use | HAZ-002 | Setting visible on the live view | SRS-050 |
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

The requirements for the user interface are written as `SRS-xxx` entries at Milestone 3 (desktop application, `srs.md` v0.9) and Milestone 4 (device), from the elements in §1.4 and the controls in §2. Milestone 3 requirements by element:

| Element or use problem | Requirements |
|---|---|
| Replay controls, replay source | SRS-039, SRS-040 |
| Data source indication (UP-4) | SRS-041 |
| Test input selection (UP-7) | SRS-042 |
| Waveform with beat marks, display low-pass | SRS-043, SRS-044 |
| Signal status (UP-2, UP-3) | SRS-045, SRS-047 |
| Heart rate (UP-2, UP-3) | SRS-046 |
| Signal quality mark (UP-3) | SRS-048 |
| Intended-use statement (UP-1) | SRS-049 |
| Mains frequency setting (UP-8) | SRS-050, SRS-054 |
| Recording control | SRS-051 |
| About box (identification) | SRS-052 |
| Text access for screen readers | SRS-053 |

## 5. Evaluation plan

- **Formative evaluation, Milestone 3 (OP-040):** run on the finished Milestone 3 application with replay.
  - Participants: 3, none of them the developer of the user interface (the project owner may be one; at least two should not know the project). 20 minutes each, think-aloud protocol, scenarios HRS-1, HRS-2 and HRS-3.
  - Success criteria, for every participant and without prompting: HRS-1, the participant states that the data is a replay and names the record; HRS-2, the participant states, within 10 s after the interruption starts, that the heart rate is no longer current; HRS-3, the participant states that no valid heart rate is available and gives the reason in their own words.
  - A failure leads to a change of the user interface and a repeat of that scenario with one new participant.
  - Scope: it looks for use errors in the three hazard-related scenarios; it is not a validation of the user interface. It supports SRS-041, SRS-045, SRS-046 and SRS-047.
- **Repeat with the device, Milestone 4 (OP-079):** HRS-4 and HRS-5, and HRS-1 to HRS-3 again with the device connected.
- Results are recorded in the milestone verification report in `docs/validation/`.

## 6. Open points referenced

OP-023, OP-024, OP-028, OP-035 to OP-040, OP-074, OP-078, OP-079. See [`open-points.md`](open-points.md). OP-021 and OP-032, cited by version 0.1, were closed on 2026-10-07 for Milestone 2; their display parts (OP-071, OP-072) and OP-015, OP-020, OP-022, OP-033 and OP-037 were closed with the Milestone 3 requirements (decided by the project owner on 2026-10-11). OP-040 stays open until the Milestone 3 verification report.
