# ADR 0005: Device sampling rate: 360 Hz

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** project owner (decision; closes OP-004); tech lead (consequences)
- **Related:** SRS-003, SRS-004, SRS-005, SRS-006, SRS-010, SRS-015; HAZ-001, HAZ-002; OP-014, OP-028; [ADR 0001](0001-mcu-and-firmware-framework.md); [`architecture.md`](../regulatory/architecture.md) §4.2, §6.1

## Context

The device (Milestone 4) samples the ECG at a fixed rate, which the functional analysis requires to be documented (FB-01). The software accepts 125–1000 Hz (SRS-003). The MIT-BIH Arrhythmia Database, on which detection is validated (SRS-007), is sampled at 360 Hz.

## Options considered

1. **250 Hz**, common in wearable devices: a lower data rate and processing load. Validation results at 360 Hz would not apply directly, and replay and golden vectors from the reference database would need resampling.
2. **360 Hz**, the rate of the reference database.
3. **500 Hz**, common in resting ECG recorders: finer time resolution, with the same resampling drawback as 250 Hz.
4. **1000 Hz**: resolves short events such as pacing spikes better. Most of the bandwidth is unused, because the analog front end limits it, and data and processing load are highest.

## Decision

The device samples at **360 Hz**, fixed.

## Consequences

**Positive**
- The validated detection performance applies at the device rate without resampling.
- Replay of reference records and golden vectors run at the device rate, with no resampling step to verify.
- One sample every 2.78 ms is well within the 150 ms EC57 matching window. The Nyquist frequency (180 Hz) is far above the band of the analog front end and of QRS detection.
- The data rate is small for Bluetooth LE: 360 samples/s at 16 bits is about 5.8 kbit/s before framing.

**Negative and risks, with mitigations**
- **Pacing spikes.** Pacemaker pulses last less than about 2 ms. At 360 Hz, after the analog front-end filter, they cannot be reliably captured or recognised, so detection cannot identify them. This is a cause already listed in HAZ-001 and HAZ-002, and an input to the wearer exclusions (OP-028).
- **Sampling on the ESP32-S3.**
  - The ADC runs in continuous mode, hardware-timed, at an integer multiple of 360 Hz (e.g. 3600 Hz), and the firmware decimates to 360 Hz with an anti-aliasing filter from the portable library. This also averages ADC noise ([ADR 0001](0001-mcu-and-firmware-framework.md)).
  - The ADC clock dividers may not give an exact multiple of 360 Hz. The achieved rate is therefore measured on the bench together with sampling jitter, and must match 360 Hz within the target of OP-014.
- **Generality kept.** The 250 Hz verification cases of SRS-004 to SRS-006 and SRS-010 remain, and SRS-003 keeps accepting 125–1000 Hz, so that the software is not tied to one rate.
