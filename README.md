# Sinus

**Open-source wearable ECG: firmware, real-time signal processing, and arrhythmia detection to be validated per ANSI/AAMI EC57, documented following IEC 62304.**

> ⚠️ **Not a medical device.** Sinus is a personal engineering and portfolio project. It is not certified, not intended for diagnosis or monitoring of any medical condition, and must not be used to make health decisions.
>
> ⚡ **Electrical safety:** the device must run **only on battery power** while electrodes are attached to a person. Never connect it to USB, a charger, or any mains-powered equipment while it is being worn.

---

## Why this project

Most hobby ECG projects stop at "the waveform shows up on screen". Sinus aims to go the full distance a real medical-device team would: from analog front-end to cloud, with **validated algorithms** and **regulatory-style documentation** as first-class deliverables, not an afterthought.

Goals:

1. Build a complete, working end-to-end system (hardware → firmware → desktop application → backend).
2. Validate the signal-processing algorithms on public reference databases using industry-standard metrics.
3. Develop the software following a lightweight version of the processes required for medical device software (IEC 62304, ISO 14971).
4. Keep everything reproducible: anyone can clone the repo, download the data, and re-run every result.

## System overview

```
┌──────────────┐    ┌──────────────┐  BLE   ┌──────────────┐  HTTPS  ┌──────────────┐
│ Analog front │ →  │   Firmware   │ ─────→ │ Desktop app  │ ──────→ │   Backend    │
│ end + MCU    │    │ sampling,    │        │ live plot,   │         │ storage,     │
│ (electrodes) │    │ processing,  │        │ R-peaks, HR, │         │ FHIR export  │
└──────────────┘    │ BLE stream   │        │ quality,     │         └──────────────┘
                    └──────────────┘        │ replay       │
                           ▲                └──────────────┘
                           │                       ▲
                           └──── C++ DSP library ──┘
                                        ▲  golden vectors (equivalence within tolerance)
              Python reference + offline validation on MIT-BIH / PhysioNet
```

One portable C++ signal-processing library runs on the device and in the desktop application, so there is a single real-time implementation. The Python implementation is the validated reference: it exports golden vectors, and the C++ library must reproduce them within a defined tolerance. The desktop application can replay reference records as if they came from the device, so the whole chain can be demonstrated and tested without hardware.

| Component | Technology | Notes |
|---|---|---|
| Analog front end | AD8232 via the MCU ADC (first prototype, single lead) → ADS1293 with a register-level SPI driver (later) | Battery-powered only |
| MCU | ESP32-S3 | BLE streaming |
| Firmware | C++17 on ESP-IDF with FreeRTOS | Tasks with explicit priorities for acquisition, processing and BLE; fixed sampling rate with jitter and latency measured; BLE GATT service with packet sequence numbers; watchdog, explicit error state, low-battery handling |
| Real-time DSP library (`libs/sinus-dsp`) | C++17, no dynamic allocation in the real-time path; builds for host and ESP32 | FIR/IIR filters, adaptive (LMS) interference reduction, streaming Pan–Tompkins QRS detection, Kalman heart-rate tracking, per-window signal quality index |
| Reference and validation (`dsp/`) | Python (NumPy, SciPy, `wfdb`) | Reference implementation, EC57 evaluation, noise stress test, golden-vector export |
| Desktop application | C++17 with Qt 6 | Live waveform, R-peaks, heart rate, signal quality, recording, replay mode; BLE, plus serial or UDP test input for tests without hardware |
| Backend | Python (FastAPI) | Session storage, HL7 FHIR R4 `Observation` export |

## Algorithms and validation

**QRS detection**
- Baseline: Pan–Tompkins.
- Evaluated on the MIT-BIH Arrhythmia Database with beat-by-beat matching as specified by ANSI/AAMI EC57.
- Reported metrics: sensitivity (Se) and positive predictive value (+P), per record and aggregate.
- Noise stress test on the MIT-BIH Noise Stress Test Database: Se and +P versus signal-to-noise ratio.
- A subset report is regenerated in CI on every push, so any change in detection results shows up in review.

**Real-time implementation**
- The C++ library is checked against golden vectors exported by the Python reference, within a defined tolerance.
- A per-window signal quality index marks the signal as not usable, so that no heart rate is shown from noise.

**Heart-rate variability**
- Time-domain (SDNN, RMSSD) and frequency-domain (LF/HF) metrics from detected RR intervals.

**Beat classification**
- AAMI beat classes (N, SVEB, VEB, F, Q).
- Classical feature-based model vs. a small neural network.
- **Inter-patient split** (no beats from the same patient in both train and test) to avoid the data leakage common in published results.
- **Abstention:** no class is given when signal quality or model confidence is too low. Metrics are reported on all beats and on accepted beats, together with the abstention rate.
- Dataset card and model card.

All results are regenerated by a single script and published in `docs/validation/`.

## Regulatory-style process (lightweight)

This project does **not** claim compliance with any standard. It uses their structure as a discipline, to practice how medical device software is actually built.

| Artifact | Inspired by | Location |
|---|---|---|
| Software development plan | IEC 62304 §5.1 | `docs/regulatory/sdp.md` |
| Software safety classification (assumed Class B) | IEC 62304 §4.3 | `docs/regulatory/safety-class.md` |
| Functional analysis (intended use, functional architecture) | IEC 62304 §5.2 (input to requirements) | `docs/regulatory/functional-analysis.md` |
| Software requirements (IDs `SRS-xxx`) | IEC 62304 §5.2 | `docs/regulatory/srs.md` |
| Architecture | IEC 62304 §5.3 | `docs/regulatory/architecture.md` |
| Architecture decision records | IEC 62304 §5.3 | `docs/adr/` |
| Risk analysis | ISO 14971 | `docs/regulatory/risk-analysis.md` |
| Usability (use specification, use-related hazards) | IEC 62366-1 | `docs/regulatory/usability.md` |
| Cybersecurity (BLE, backend) | IEC 81001-5-1 | `docs/regulatory/cybersecurity.md` |
| SOUP list (third-party software) | IEC 62304 §8.1.2 | `docs/regulatory/soup.md` |
| Software bill of materials (SBOM) | FDA and EU cybersecurity practice | Generated in CI (CycloneDX), workflow artifact `sbom-dsp` |
| Traceability matrix (SRS → code → tests) | IEC 62304 §5.1.1 | `docs/regulatory/traceability.md` |
| Milestone register (release status) | IEC 62304 §5.8 | `docs/regulatory/milestones.md` |
| Open points (pending decisions, deferred work, IDs `OP-xxx`) | IEC 62304 §9 (problem resolution) | `docs/regulatory/open-points.md` |
| Verification report | IEC 62304 §5.7 | `docs/validation/` |
| Development process with AI assistance | — | `docs/process/ai-assisted-development.md` |

Rules followed throughout the project:
- Every requirement has an ID and a milestone. It is verified by at least one test that cites it, in `tests/requirements/` or `tests/system/` according to its verification level. Whoever implements a requirement does not write its verifying tests.
- Every change that affects behavior updates the risk analysis if needed.
- Every new dependency is added to the SOUP list.
- On every push, CI runs the tests and the traceability checks, and publishes an SBOM of the Python reference and scans it for known vulnerabilities. The checks fail when:
  - the traceability matrix is out of date;
  - a requirement cited in the code has no verifying test;
  - a test cites a requirement from the wrong folder;
  - the subset validation report, regenerated from six records of the MIT-BIH Arrhythmia Database, differs from the stored one ([`docs/validation/qrs-ec57-subset-report.md`](docs/validation/qrs-ec57-subset-report.md));
  - a component listed in the SBOM has a known vulnerability that has not been triaged ([`docs/regulatory/cybersecurity.md`](docs/regulatory/cybersecurity.md) §7).
- Vulnerabilities are reported privately, as described in [`SECURITY.md`](SECURITY.md).
- A milestone is merged into `main` only when every one of its requirements has a verifying test: CI enforces this on pull requests into `main` ([ADR 0004](docs/adr/0004-test-tagging-and-traceability-gates.md)).

## Repository structure

```
sinus-ecg/
├── firmware/            # ESP32-S3 firmware: C++17 on ESP-IDF + FreeRTOS
├── libs/
│   └── sinus-dsp/       # Portable C++17 real-time DSP library (host and ESP32)
├── dsp/                 # Python reference implementation + validation pipeline
│   ├── sinus_dsp/
│   ├── scripts/         # download data, EC57 and noise stress evaluation, golden vectors
│   └── tests/
├── desktop/             # Qt 6 desktop application (live view, recording, replay)
├── backend/             # FastAPI server: session storage, FHIR R4 export
├── hardware/            # Schematics, BOM, wiring and safety notes
├── docs/
│   ├── regulatory/      # IEC 62304 / ISO 14971 / IEC 62366-1 / IEC 81001-5-1 style artifacts
│   ├── adr/             # Architecture decision records
│   ├── process/         # Development process
│   └── validation/      # Generated validation reports, milestone verification reports
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

## Roadmap

**Milestone 0: Foundations**
- [x] Repository, CI, license, contribution rules
- [x] Software development plan and safety classification
- [x] Functional analysis, first version of requirements (SRS) and risk analysis
- [x] Usability draft (use specification, use-related hazards)
- [x] Architecture decision records, cybersecurity and development-process documents

**Milestone 1: Python reference**
- [x] MIT-BIH download script and data loader
- [x] Filtering (baseline wander, powerline noise)
- [x] Pan–Tompkins QRS detector
- [x] EC57-style evaluation with Se / +P report
- [x] Noise stress test (MIT-BIH Noise Stress Test Database): performance versus SNR
- [x] Golden-vector export for the C++ library
- [x] EC57 subset report regenerated in CI

**Milestone 2: Portable C++ DSP library**
- [ ] `libs/sinus-dsp`: C++17, no dynamic allocation in the real-time path, builds for host and ESP32
- [ ] FIR/IIR biquad filters: baseline high-pass, 50/60 Hz notch, low-pass
- [ ] LMS adaptive filter for mains and motion artefacts (accelerometer reference if present)
- [ ] Streaming Pan–Tompkins QRS detector
- [ ] Kalman filter for heart rate from RR intervals
- [ ] Per-window signal quality index (SQI)
- [ ] Equivalence with the Python reference on golden vectors, within a defined tolerance

**Milestone 3: Qt desktop application with replay**
- [ ] Live plot with R-peak marks, heart rate and SQI indicator
- [ ] Recording in WFDB format
- [ ] Replay of MIT-BIH records as if they came from the device
- [ ] Serial or UDP test input for tests without hardware (BLE comes with Milestone 4)

**Milestone 4: Hardware, firmware and integration**
- [ ] AD8232 + ESP32-S3 prototype, battery-powered
- [ ] ESP-IDF / FreeRTOS firmware: acquisition, processing and BLE tasks with explicit priorities, queues and ring buffers
- [ ] BLE GATT streaming with packet sequence numbers
- [ ] Watchdog, explicit error state, low-battery handling
- [ ] Fixed sampling rate, with jitter and latency measurements
- [ ] Integration with the desktop application

**Milestone 5: Backend and interoperability**
- [ ] Session upload and storage (FastAPI)
- [ ] HL7 FHIR R4 `Observation` export: heart rate, with a reference to the recording
- [ ] Minimal authentication, encryption at rest, GDPR notes

**Milestone 6: Classification, HRV and final report**
- [ ] AAMI beat classification: classical model vs. small neural network, inter-patient split
- [ ] Abstention on low signal quality or low confidence, with metrics on all beats, on accepted beats and the abstention rate
- [ ] Dataset card and model card
- [ ] HRV analysis
- [ ] Final verification report and project write-up

**After Milestone 6**
- [ ] ADS1293 front end with a register-level SPI driver (OP-042)

## Getting started

Each component has a README with the instructions to build, test and run it. So far:

- [`dsp/`](dsp/README.md): the Python reference and the validation pipeline (requires [uv](https://docs.astral.sh/uv/)).

## Data sources

- [MIT-BIH Arrhythmia Database, version 1.0.0](https://physionet.org/content/mitdb/1.0.0/) (PhysioNet, https://doi.org/10.13026/C2F305)
- [MIT-BIH Noise Stress Test Database, version 1.0.0](https://physionet.org/content/nstdb/1.0.0/) (PhysioNet, https://doi.org/10.13026/C2HS3T), for noise stress testing
- A further database, not used during development, is planned for independent evidence (OP-029 in [open-points.md](docs/regulatory/open-points.md)).

Datasets are downloaded by script and never committed to the repository.

Both databases are made available by PhysioNet under the [Open Data Commons Attribution License v1.0](https://opendatacommons.org/licenses/by/1-0/). The validation reports in [`docs/validation/`](docs/validation/README.md) contain information from the MIT-BIH Arrhythmia Database and the MIT-BIH Noise Stress Test Database, which are made available under that licence; each report states the database, its version and its licence.

PhysioNet asks users of these databases to cite the original publication of each database and the standard citation for PhysioNet:
- MIT-BIH Arrhythmia Database: Moody GB, Mark RG. The impact of the MIT-BIH Arrhythmia Database. IEEE Eng in Med and Biol 20(3):45-50 (May-June 2001). (PMID: 11446209)
- MIT-BIH Noise Stress Test Database: Moody GB, Muldrow WE, Mark RG. A noise stress test for arrhythmia detectors. Computers in Cardiology 1984; 11:381-384.
- PhysioNet: Pollard, T., Moody, B. E., Lehman, L., Gow, B., Fernandes, C., Xie, C., Johnson, A., Mark, R. G., & Heldt, T. (2026). PhysioNet as a global platform for biomedical research. Nature Health. https://doi.org/10.1038/s44360-026-00096-z. Available from: https://rdcu.be/faatM

## License

Code (firmware, DSP library and reference, desktop application, backend) is licensed under the [Apache License 2.0](LICENSE). The license for hardware files (schematics, BOM) is still to be decided; a CERN-OHL variant is planned (tracked as OP-001 in [open-points.md](docs/regulatory/open-points.md)).

## Status

🚧 Early development: Milestone 0 (foundations) and Milestone 1 (Python reference) released.
