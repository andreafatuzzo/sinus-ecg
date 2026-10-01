# Cybersecurity

_Inspired by IEC 81001-5-1:2021. Version 0.1.2, 2026-09-30. Status: draft (Milestone 0)._

> Sinus is not a medical device and claims no compliance with IEC 81001-5-1. This document borrows, in a light form, the structure of its security activities: security context, assets, threat model, security controls, software bill of materials (SBOM) and vulnerability handling. The aim is that security is designed in from the first interface, not added at the end.

## Conventions

- Threats are identified as `TH-1`, `TH-2`, … and security controls as `SC-1`, `SC-2`, … These IDs are stable and never reused.
- Hazards (`HAZ-xxx`) and risk controls (`RC-xxx`) are those of [`risk-analysis.md`](risk-analysis.md). Interfaces (`IF-x`) and software items are those of [`architecture.md`](architecture.md).
- A threat that can lead to harm to the wearer is linked to its hazard (§8). Privacy threats are handled in this document and in OP-016.
- Every item still to be defined cites its open point `OP-xxx` in [`open-points.md`](open-points.md).

## Revision history

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-29 | First draft: security context, assets, attack surface, threat model TH-1 to TH-21, security controls SC-1 to SC-20 per milestone, SBOM, vulnerability handling, link to the risk analysis |
| 0.1.1 | 2026-09-29 | SC-5 made concrete by the Milestone 1 detailed design: pinned digest of each checksum list, paths confined to the database folder, HTTPS only |
| 0.1.2 | 2026-09-30 | SC-5 and TH-21 corrected (OP-058): the download follows redirects, so "HTTPS only" did not hold; SC-5 now states that integrity rests on the pinned digest of each checksum list and on the local verification of every file, not on the transport |

## 1. Scope and security context

- **Software items in scope:**
  - the firmware and its Bluetooth LE link (IF-4);
  - the desktop application, with its test inputs (IF-5) and files (IF-6);
  - the backend, with its API (IF-7) and export (IF-8);
  - the development and build pipeline (supply chain).
- **The offline pipeline** (`dsp`) processes public data and, from Milestone 4, recorded sessions (A-1). It is in scope for the integrity of reference data, golden vectors and reports.
- **Operational context.** Sinus is a personal demonstration project:
  - one owner, or a few users;
  - the device is worn only in demonstration sessions;
  - the desktop application runs on a personal computer;
  - the project owner operates the backend (Milestone 5).

  There is no clinical network and no connection to health-care systems.
- **Data.**
  - From Milestone 4, an ECG recorded from a real wearer is personal data concerning health (a special category under the GDPR), and so is everything derived from it.
  - The public reference databases are de-identified public data.
  - No personal data is ever committed to the repository.

## 2. Assets

| ID | Asset | Where | Property to protect |
|---|---|---|---|
| A-1 | ECG stream and recordings of a wearer, with derived beats and heart rate | Bluetooth LE link, files on the computer, backend storage, exports | Confidentiality, integrity |
| A-2 | Session metadata (start time, device identifier, owner) | Desktop application, backend | Confidentiality, integrity |
| A-3 | User credentials and session tokens | Desktop application, backend | Confidentiality |
| A-4 | Bluetooth LE bonding keys | Device, computer | Confidentiality |
| A-5 | Firmware image and device configuration | Device | Integrity |
| A-6 | Source code, CI pipeline, released artifacts | Repository, CI | Integrity |
| A-7 | Reference data, golden vectors, validation reports | `dsp`, `docs/validation/` | Integrity |
| A-8 | Continuity of the live stream | Bluetooth LE link, desktop application | Availability (safety-relevant: HAZ-007) |

## 3. Attack surface and trust boundaries

| Entry point | Interface | Milestone |
|---|---|---|
| Bluetooth LE radio between device and computer | IF-4 | M4 |
| Serial and UDP test inputs of the desktop application | IF-5 | M3 |
| Files opened by the desktop application and by `dsp`: records, sessions, golden vectors | IF-2, IF-6 | M1, M3 |
| HTTPS API of the backend | IF-7 | M5 |
| FHIR export received by an external system | IF-8 | M5 |
| USB, JTAG and serial interfaces of the device (physical access) | — | M4 |
| Third-party dependencies, CI and the repository | — | From M0 |

## 4. Threat model

Threats are listed per entry point, with their STRIDE category:
- **S**poofing;
- **T**ampering;
- **R**epudiation;
- **I**nformation disclosure;
- **D**enial of service;
- **E**levation of privilege.

### 4.1 Bluetooth LE link (Milestone 4)

| ID | Threat | STRIDE | Assets | Hazard | Controls |
|---|---|---|---|---|---|
| TH-1 | A nearby receiver eavesdrops on the ECG stream | I | A-1 | — | SC-9 |
| TH-2 | A different or spoofed device, advertising the Sinus service, streams to the desktop application, which shows the data as the wearer's signal | S | A-1 | HAZ-013 | SC-9, SC-10 |
| TH-3 | An unauthorised computer connects to the device and reads the stream or changes its settings | S, I, E | A-1, A-5 | — | SC-9, SC-10 |
| TH-4 | A man-in-the-middle during pairing, or an attacker injecting or modifying packets | T, I | A-1, A-4 | HAZ-001, HAZ-002 | SC-9 (pairing method: OP-044), SC-12 |
| TH-5 | Jamming, connection flooding or loss of the link: data stop arriving | D | A-8 | HAZ-007, HAZ-012 | SC-12 |
| TH-6 | The wearer is tracked through a fixed Bluetooth address | I | Privacy | — | SC-11 |

### 4.2 Desktop application (Milestones 3 and 4)

| ID | Threat | STRIDE | Assets | Hazard | Controls |
|---|---|---|---|---|---|
| TH-7 | Another process or host sends data to the UDP test input, and it is shown as a signal | S, T | A-1 | HAZ-013 | SC-7 |
| TH-8 | A crafted record, session or golden-vector file exploits a file reader (memory corruption, crash, stall) | T, D, E | Computer, A-8 | HAZ-007 | SC-6, SC-8 |
| TH-9 | Recordings on the computer are read by another user of the computer or leak through backups | I | A-1, A-2 | — | SC-13 |
| TH-10 | Backend credentials are stolen from the computer | I | A-3 | — | SC-20 |

### 4.3 Backend and export (Milestone 5)

| ID | Threat | STRIDE | Assets | Hazard | Controls |
|---|---|---|---|---|---|
| TH-11 | Unauthenticated access, or access to another user's sessions | S, I, E | A-1, A-2 | — | SC-15 |
| TH-12 | Password guessing or credential stuffing | S | A-3 | — | SC-15 |
| TH-13 | Interception or modification of data in transit | I, T | A-1, A-2, A-3 | — | SC-16 |
| TH-14 | Theft of stored data (disk, database dump, backups) | I | A-1, A-2 | — | SC-17 |
| TH-15 | Injection or malicious uploads (oversized or malformed files) | T, D, E | Backend | — | SC-18 |
| TH-16 | Personal data written to logs | I | A-1, A-2 | — | SC-19 |
| TH-17 | Exported data altered by the receiving system, or taken as clinical data | T, R | A-1 | HAZ-010 | RC-011 (content: OP-027), SC-16 |

### 4.4 Device platform (Milestone 4)

| ID | Threat | STRIDE | Assets | Hazard | Controls |
|---|---|---|---|---|---|
| TH-18 | With physical access, the firmware is replaced or read out, or keys are extracted, through the USB, JTAG or serial interfaces | T, I | A-4, A-5 | HAZ-001, HAZ-002 (altered processing) | SC-14 |

A cable connected to a worn device is an electrical safety hazard, not a security threat. It is controlled in hardware: HAZ-005, RC-006, OP-024, OP-038.

### 4.5 Development and supply chain (from Milestone 0)

| ID | Threat | STRIDE | Assets | Hazard | Controls |
|---|---|---|---|---|---|
| TH-19 | A dependency (SOUP) has a known vulnerability, or a compromised release is installed | T, E | A-6, all | Depends on the component | SC-2, SC-3, SC-4 |
| TH-20 | The main branch or the CI pipeline is tampered with (e.g. a compromised third-party CI action) | T | A-6 | Depends on the change | SC-1, SC-2, SC-4 |
| TH-21 | Reference data or golden vectors are altered, so validation or equivalence results are wrong. Reference data can be altered on the server, in transit (including through a redirect to another server), in the local copy or in the CI cache | T | A-7 | HAZ-004 | SC-5 |

## 5. Security controls per milestone

| ID | Control | Threats | Milestone | Status |
|---|---|---|---|---|
| SC-1 | `main` changes only through pull requests with green CI; force pushes and deletion are blocked (`sdp.md` §4) | TH-20 | M0 | In place |
| SC-2 | Dependencies pinned by lock file and installed with `uv sync --locked`; CI actions pinned to exact versions | TH-19, TH-20 | M0 | In place |
| SC-3 | An SBOM of each software item is generated in CI (§6) | TH-19 | M0 (`dsp`); later items: OP-046 | In place for `dsp` |
| SC-4 | Security policy with private vulnerability reporting, dependency alerts, a vulnerability scan of the SBOMs, least-privilege CI token permissions, and the triage of §7 | TH-19, TH-20 | M1 | OP-045 |
| SC-5 | Reference data verified against published checksums (RC-004: SRS-001, SRS-013, SRS-016). Integrity rests on two local checks: the SHA-256 of each published checksum list is pinned in the code, and a file counts as verified only when the local copy has the SHA-256 that the list gives for it; every command that uses the data verifies it first, including the copy restored from the CI cache. Integrity does not rest on the transport: downloads are requested from PhysioNet over HTTPS, but redirects issued by the server are followed, possibly to another host or to a connection that is not HTTPS, and whatever is received is subject to the same two checks. Listed paths are confined to the database folder, so a download writes nowhere else (`architecture.md` §8.3). Golden vectors are regenerated in the same CI run as the checks that use them (`architecture.md` §7.5) | TH-21 | M1 | Specified |
| SC-6 | Memory safety of the portable library: no dynamic memory, fixed-size buffers with bounds checks, host tests with AddressSanitizer and UndefinedBehaviorSanitizer, static analysis (OP-043) | TH-8 | M2 | Planned |
| SC-7 | Test inputs off by default; UDP listens on the local host only unless the user changes it; the data source is always shown (RC-015) | TH-7 | M3 | Planned |
| SC-8 | File readers check headers, sizes and value ranges, and reject malformed files with an error; tested with malformed and fuzzed inputs | TH-8 | M3 | Planned |
| SC-9 | The Bluetooth LE link uses LE Secure Connections pairing with bonding. The stream and control characteristics are accessible only over an encrypted, bonded link (pairing method: OP-044) | TH-1, TH-2, TH-3, TH-4 | M4 | OP-044 |
| SC-10 | The desktop application connects only to a bonded device chosen by the user and shows its identity. The device accepts one connection at a time and stops advertising while connected | TH-2, TH-3 | M4 | OP-044 |
| SC-11 | Bluetooth LE privacy: resolvable private addresses | TH-6 | M4 | OP-044 |
| SC-12 | Stream continuity: packet sequence numbers and sample counter; loss of data is shown within a defined time, and the heart rate is withheld (RC-008, RC-014) | TH-4, TH-5 | M3, M4 | Planned |
| SC-13 | Protection of recordings stored on the computer | TH-9 | M4 | OP-048 |
| SC-14 | Device platform: debug interfaces in release builds, secure boot, flash encryption, firmware update method | TH-18 | M4 | OP-047 |
| SC-15 | Authentication on every backend endpoint, and access to a session by its owner only; passwords stored as salted, deliberately slow hashes; rate limiting of login attempts | TH-11, TH-12 | M5 | OP-016 |
| SC-16 | HTTPS only, with current TLS versions and HTTP Strict Transport Security; no plain HTTP | TH-13, TH-17 | M5 | Planned |
| SC-17 | Encryption at rest of stored sessions and backups, with key management | TH-14 | M5 | OP-016 |
| SC-18 | Validation of uploads (size limits, format checks); parameterised database queries; uploaded content never executed | TH-15 | M5 | Planned |
| SC-19 | Logs contain no signal data and no personal data beyond pseudonymous identifiers; log retention is defined | TH-16 | M5 | OP-016 |
| SC-20 | Backend credentials on the computer are kept in the operating system's credential store, never in plain files | TH-10 | M5 | OP-016 |

Beat classification (Milestone 6) adds no new interface. Its datasets are verified like the other reference data (SC-5).

## 6. Software bill of materials (SBOM)

- **Format.** CycloneDX, JSON.
- **Content.** For each software item, every component in its runtime or build output, with version and licence, including transitive dependencies. [`soup.md`](soup.md) lists only the direct runtime dependencies, with their purpose and the review of their known anomalies.
- **Generation.** In CI, from the locked dependency definitions, on every build. The SBOM is published as a build artifact and is not committed.
- **`dsp`: in place.** The SBOM describes an environment with the locked runtime dependencies only (artifact `sbom-dsp`), with the rules of [ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md) §9.
- **Other items: OP-046.**
  - Portable library (Milestone 2): the toolchain and its C++ standard library.
  - Desktop application (Milestone 3): the Qt modules and the WFDB implementation.
  - Firmware (Milestone 4): the ESP-IDF components, FreeRTOS and the toolchain.
  - Backend (Milestone 5).

## 7. Vulnerability handling

- **Sources:**
  - dependency alerts on the repository;
  - a scan of the SBOMs against public vulnerability databases in CI;
  - vendor advisories for ESP-IDF, Qt and the Python packages;
  - reports from anyone, through private vulnerability reporting.

  Setting them up: OP-045.
- **Triage.** For each vulnerability in a SOUP item, determine:
  - whether the vulnerable code is reachable in Sinus;
  - its effect on safety (hazards, §8) and on security (threats, §4).

  The outcome is one of: update the component, mitigate, or accept with a recorded rationale.
- **Records.** A GitHub issue labelled `security`. The "Known anomalies reviewed" column of [`soup.md`](soup.md). [`risk-analysis.md`](risk-analysis.md), when the vulnerability affects safety. Fixes follow the normal problem-resolution flow (`sdp.md` §8).
- **Timing** (Milestone 1, as decided for OP-045):
  - triage within 30 days of an alert;
  - a reachable vulnerability with an effect on safety is fixed before the next worn session;
  - other fixes land with the next milestone at the latest.
- **Disclosure.** Coordinated with the reporter. Fixed vulnerabilities are noted in the pull request and in the milestone verification report.
- **Support.** Only the latest milestone release is maintained.

## 8. Link to the risk analysis

| Threat | Hazard | Existing risk controls | Risk-analysis open point |
|---|---|---|---|
| TH-2 (spoofed or wrong device), TH-7 (foreign data on the test input) | HAZ-013 | RC-015 | OP-012 |
| TH-4 (injected or modified packets), TH-18 (altered firmware) | HAZ-001, HAZ-002 | RC-012 (on the reference implementation only) | OP-012 |
| TH-5 (link loss), TH-8 (reader crash or stall) | HAZ-007, HAZ-012 | RC-008, RC-014 | OP-012 |
| TH-17 (exported data taken as clinical) | HAZ-010 | RC-011 | OP-027 |
| TH-21 (altered reference data) | HAZ-004 | RC-004 | — |

The privacy threats (TH-1, TH-3, TH-6, TH-9 to TH-16) do not lead to physical harm to the wearer, and are handled in this document and with the analysis of stored personal data and privacy (OP-016). The security causes of the hazards above were added in [`risk-analysis.md`](risk-analysis.md) v0.3.1 (TH-2, TH-4, TH-7, TH-18); the remaining threats to the wireless link are analysed with OP-012 (Milestone 4).

## 9. Open points referenced

OP-012, OP-016, OP-024, OP-027, OP-038, OP-043, OP-044, OP-045, OP-046, OP-047, OP-048. See [`open-points.md`](open-points.md).
