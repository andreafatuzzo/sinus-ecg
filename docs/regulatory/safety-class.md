# Software safety classification

_Inspired by IEC 62304:2006+A1:2015 §4.3. Version 0.1, 2026-09-28. Status: draft (Milestone 0)._

## Result

Assumed classification of the Sinus software system: **Class B**, meaning that a hazardous situation can result from the software, but the worst credible harm after external risk controls is **non-serious injury**.

All software items inherit Class B until the architecture segregates items well enough to justify a lower class for some of them (IEC 62304 §4.3 d).

## Classes (IEC 62304 §4.3)

| Class | The software can contribute to a hazardous situation that, after external risk controls, leads to… |
|---|---|
| A | no injury or damage to health |
| B | non-serious injury |
| C | death or serious injury |

## Intended use (basis of the classification)

The classification is only valid for this intended use:

- Sinus is a personal engineering project that records and displays a single-lead ECG, detects heartbeats and computes heart rate and heart-rate variability for **technical demonstration**.
- It is **not** intended for diagnosis, for monitoring a medical condition, or for generating alarms, and it must not be used to make health decisions.
- The device runs only on battery power while electrodes are attached.

## Rationale

1. **No therapeutic or life-sustaining function.** The software controls no energy delivery, drug delivery or other therapy.
2. **No alarm function.** No output is designed to prompt urgent action, so a failure cannot directly delay an emergency response that the system was relied on to trigger.
3. **Foreseeable misuse remains.** A user might still read the heart rate or beat labels as health information. Wrong output (missed beats, false beats, wrong heart rate) could then:
   - falsely reassure the user, who delays seeking care for a real symptom;
   - falsely alarm the user, causing anxiety or an unnecessary medical visit.

   The analysis in [`risk-analysis.md`](risk-analysis.md) (HAZ-001 to HAZ-003) treats this as the worst credible harm and rates it non-serious, **given** the external risk controls: the intended-use labeling and the absence of alarms.
4. **Electrical safety is not a software matter.** Electric shock through the electrodes (HAZ-005) is controlled by battery-only operation in the hardware design and labeling, not by software.

Following IEC 62304 §4.3 a, the classification assumes that the software **fails** (probability 1): the class depends on the severity of the resulting harm, not on how likely a failure is.

## Limits of this classification

- A real product with the same algorithms, marketed for detecting arrhythmias, would likely be **Class B or C** depending on its claims. Monitoring with alarms, or detection of life-threatening arrhythmias, points to **Class C**.
- Adding any alarm, notification or diagnostic claim invalidates this classification and requires a new analysis.

## Review triggers

Revisit this document when any of the following changes: the intended use, the addition of alarms or notifications, the features that interpret the ECG (e.g. beat classification with abstention at Milestone 6), or the external risk controls.
