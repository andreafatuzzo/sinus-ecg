# Cybersecurity

_Inspired by IEC 81001-5-1:2021. Version 0.2.1, 2026-10-06. Status: draft (Milestone 1); the changes of v0.2 approved by the project owner on 2026-10-06; v0.2.1 updates the status of controls, with no design change._

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
| 0.2 | 2026-10-05 | Security policy and vulnerability monitoring (OP-045; approved by the project owner on 2026-10-06). SC-2: actions updated through reviewed pull requests, a new third-party action with movable tags pinned to a commit SHA, tools downloaded in CI verified against a pinned SHA-256. SC-4 made concrete: `SECURITY.md`, Dependabot alerts, OSV-Scanner scan of the SBOM in CI, read-only CI token. §6: the SBOM is scanned. §7: sources, choice of the scanner and rejected alternatives, the CI step and when it fails, the triage procedure and its records, timing confirmed, updates of dependencies, CI token, repository settings |
| 0.2.1 | 2026-10-06 | Status of controls, no design change. OP-045 closed on 2026-10-06: SC-2 and SC-4 are in place, with the repository settings made by the project owner on 2026-10-06, including the list of actions allowed to run (§7.4); `SECURITY.md` and the configuration of Dependabot version updates take effect on the default branch with the Milestone 1 release. SC-5 is in place for the reference data since Milestone 1 (SRS-001, SRS-013, SRS-016); its golden-vector part applies from Milestone 2, when CI first uses golden vectors. §9: OP-045 stays listed, as closed open points do |

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
| SC-2 | Dependencies pinned by lock file and installed with `uv sync --locked`. CI actions pinned to exact versions and updated through reviewed pull requests (§7.4); an action whose release tags can be moved, other than GitHub's own `actions/*`, is pinned to a full commit SHA. Tools that CI downloads are verified against a SHA-256 pinned in the workflow before they run | TH-19, TH-20 | M0 (lock file, versions); M1 (verified downloads, updates) | In place (OP-045, closed): the download of OSV-Scanner is verified in `ci.yml`; only actions created by GitHub and `astral-sh/setup-uv` are allowed to run (repository setting, 2026-10-06, §7.4); Dependabot version updates run from the Milestone 1 release, when `.github/dependabot.yml` reaches the default branch |
| SC-3 | An SBOM of each software item is generated in CI (§6) | TH-19 | M0 (`dsp`); later items: OP-046 | In place for `dsp` |
| SC-4 | Security policy (`SECURITY.md`) with private vulnerability reporting; Dependabot alerts; a scan of every SBOM for known vulnerabilities in CI on every push and pull request, which fails on an untriaged finding; read-only CI token; the triage of §7 with its records | TH-19, TH-20 | M1 | In place (OP-045, closed): repository settings made by the project owner on 2026-10-06 (§7.4); scan and read-only token in the workflows; GitHub shows `SECURITY.md` as the security policy from the Milestone 1 release, when it reaches the default branch (private reporting is already enabled). The SBOMs of later items are scanned when they are added (OP-046) |
| SC-5 | Reference data verified against published checksums (RC-004: SRS-001, SRS-013, SRS-016). Integrity rests on two local checks: the SHA-256 of each published checksum list is pinned in the code, and a file counts as verified only when the local copy has the SHA-256 that the list gives for it; every command that uses the data verifies it first, including the copy restored from the CI cache. Integrity does not rest on the transport: downloads are requested from PhysioNet over HTTPS, but redirects issued by the server are followed, possibly to another host or to a connection that is not HTTPS, and whatever is received is subject to the same two checks. Listed paths are confined to the database folder, so a download writes nowhere else (`architecture.md` §8.3). Golden vectors are regenerated in the same CI run as the checks that use them (`architecture.md` §7.5) | TH-21 | M1 | In place for the reference data (SRS-001, SRS-013, SRS-016; `architecture.md` §8.3, §8.11); for golden vectors from Milestone 2, when CI first uses them (`architecture.md` §7.5) |
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
- **Scan.** Every SBOM generated in CI is scanned for known vulnerabilities in the same job (§7).
- **`dsp`: in place.** The SBOM describes an environment with the locked runtime dependencies only (artifact `sbom-dsp`), with the rules of [ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md) §9.
- **Other items: OP-046.**
  - Portable library (Milestone 2): the toolchain and its C++ standard library.
  - Desktop application (Milestone 3): the Qt modules and the WFDB implementation.
  - Firmware (Milestone 4): the ESP-IDF components, FreeRTOS and the toolchain.
  - Backend (Milestone 5).

## 7. Vulnerability handling

### 7.1 Sources

| Source | What it covers | When |
|---|---|---|
| Scan of the SBOM in CI (§7.2) | Every component of each SBOM generated in CI (`dsp`: the runtime packages of `dsp/uv.lock`) on the branch being built, so also what the next release will contain | Every push and pull request |
| Dependabot alerts (repository setting) | The packages of `dsp/uv.lock` on the default branch, `main`, including the development tools, and the actions that the workflows reference by version; GitHub raises an alert when its advisory database lists a vulnerability for a version in use | Continuously, without a CI run |
| Vendor advisories | Components outside the SBOM: the Python interpreter (security releases of the 3.11 series, [`soup.md`](soup.md)); from later milestones ESP-IDF, Qt and the backend frameworks | At each milestone, and when a triage needs them |
| Private vulnerability reporting (repository setting) | Reports from anyone, as described in [`SECURITY.md`](../../SECURITY.md) | When a report arrives |

### 7.2 Scan of the SBOM in CI

- **Scanner: OSV-Scanner** (Google, Apache-2.0). It reads a CycloneDX SBOM by the Package URLs of its components and queries the OSV database (`osv.dev`), which collects, among others, the PyPA advisory database and the GitHub advisory database. It is a single binary: CI downloads a pinned release from the project's GitHub releases and verifies its SHA-256 before running it. It is a development tool, not SOUP ([`soup.md`](soup.md)).
- **Why this scanner:**
  - it scans the SBOM that CI publishes, so the scanned list and the published list are the same; the same step will scan the SBOMs of the C++ items (OP-046);
  - its configuration file records each triaged finding in the repository, with a reason and an expiry date (`ignoreUntil`), and an expired entry makes the scan fail again;
  - it needs no local vulnerability database.
- **Rejected alternatives:**
  - **pip-audit** (PyPA): it reads requirement files, `pyproject.toml` or an installed environment, not a CycloneDX SBOM, and covers Python packages only. It would scan a second description of the dependencies and could not scan the C++ items.
  - **Grype** (Anchore): it reads CycloneDX SBOMs and covers many ecosystems, but downloads its vulnerability database on every run, matches components that have no Package URL by CPE, which gives false positives for C and C++ components, and its ignore rules have no expiry date. To be reconsidered with OP-046 if the OSV database proves too thin for ESP-IDF, FreeRTOS or Qt.
  - **Dependabot alerts alone:** they cover only the default branch, so a vulnerable version added on `develop` would be seen only after its release, and they keep no record of the triage in the repository.
- **Checked on 2026-10-05** with OSV-Scanner 2.6.0 on an SBOM generated locally as CI does: the 33 components found, no vulnerability, exit status 0. The same SBOM with urllib3 2.2.1 in place of 2.8.0: exit status 1 and the published advisories listed. An `[[IgnoredVulns]]` entry for each of them: exit status 0, the aliases of each ID filtered too. The same entries with an `ignoreUntil` date in the past: exit status 1. A missing configuration file: exit status 127.
- **CI step.** In the job `dsp` of `.github/workflows/ci.yml`, after the SBOM has been generated and uploaded, from `dsp/`:

  ```
  osv-scanner scan source --config=osv-scanner.toml -L <runner temporary folder>/sbom-dsp.cdx.json
  ```

  The step, and so the job, fails when:
  - a component of the SBOM has a known vulnerability that `dsp/osv-scanner.toml` does not list in an `[[IgnoredVulns]]` entry whose `ignoreUntil` date has not passed (any severity);
  - the scanner fails: no component found in the SBOM, the configuration file missing or invalid, or the OSV service unreachable (the job is then re-run).

  The ruleset on `main` requires the job `dsp`, so a release cannot carry an untriaged finding. A vulnerability published after the last change is found by the next push, even if no dependency changed; on `main` between releases, Dependabot alerts find it (§7.1). The SBOM is uploaded before the scan, so that it is available when the scan fails.

### 7.3 Triage and records

- **Triage.** For each vulnerability in a SOUP item, determine:
  - whether the vulnerable code is reachable in Sinus (what Sinus uses of each item is recorded in [`soup.md`](soup.md));
  - its effect on safety (hazards, §8) and on security (threats, §4).

  The outcome is one of: update the component, mitigate, or accept with a recorded rationale. A vulnerability in a development tool is triaged the same way; its effect is on the integrity of the pipeline (A-6, TH-19).
- **Procedure:**
  1. For a vulnerability that is already public (a scan finding, a Dependabot alert, a vendor advisory), open a GitHub issue labelled `security`. A vulnerability reported privately in Sinus's own code stays in its private security advisory until it is fixed.
  2. For a scan finding, add an entry to `dsp/osv-scanner.toml`: `id` = the ID that the scanner reports, `ignoreUntil` = 30 days after the first failing scan, `reason` = `Triage open: #<issue>`. CI passes again while the triage is open, and fails again if it is not concluded in time.
  3. Record the outcome and its rationale in the issue, then:
     - **update:** update the locked version (`uv lock --upgrade-package <name>`), review the known anomalies of the new version ([`soup.md`](soup.md)), regenerate the validation reports, whose `Runtime` row changes when a runtime package of that row changes ([`architecture.md`](architecture.md) §8.14), and remove the entry;
     - **mitigate** or **accept:** change the reason to `Mitigated: #<issue>, <rationale>` or `Accepted: #<issue>, <rationale>`, with `ignoreUntil` at most 180 days later; when it expires, the scan fails and the triage is repeated;
     - in every case, dismiss the matching Dependabot alert, if there is one, with the corresponding reason and a link to the issue.
  4. Record the outcome in the "Known anomalies reviewed" column of [`soup.md`](soup.md), and in [`risk-analysis.md`](risk-analysis.md) when the vulnerability affects safety.
- **Records.** The GitHub issue labelled `security` (or the private security advisory); the entries of `dsp/osv-scanner.toml`; the "Known anomalies reviewed" column of [`soup.md`](soup.md); [`risk-analysis.md`](risk-analysis.md) when the vulnerability affects safety. Fixes follow the normal problem-resolution flow (`sdp.md` §8).
- **Timing** (decided by the project owner for OP-045; confirmed in v0.2):
  - triage within 30 days of the first report from any source; for a scan finding, the expiry of the entry of step 2 enforces it;
  - a reachable vulnerability with an effect on safety is fixed before the next worn session (from Milestone 4, when the device is first worn);
  - other fixes land with the next milestone at the latest;
  - a mitigated or accepted finding is triaged again at least every 180 days.

### 7.4 Updates, CI token and repository settings

- **Updates of dependencies:**
  - The Python packages of `dsp/uv.lock` are updated deliberately: when a triage concludes "update", and when a milestone starts. A new version of a runtime package changes the software that the reports state and needs a review of its known anomalies, so no automatic pull request updates them.
  - The actions used by the workflows are pinned to exact versions (`@vX.Y.Z`) and updated by Dependabot version updates (`.github/dependabot.yml`): one grouped pull request into `develop` per week, only for releases at least 7 days old.
  - **Version tags or commit SHAs.** A commit SHA cannot be moved, a tag can. The actions in use are GitHub's own `actions/*`, and `astral-sh/setup-uv`, whose release v10.2.0 is marked immutable on GitHub (its tag cannot be moved; checked on 2026-10-05). They stay pinned by version: Dependabot raises alerts only for actions referenced by version, and the tests of SRS-016 check the versions of the cache and upload actions. An action added later is pinned to a full commit SHA, with its version in a comment, unless it is one of GitHub's `actions/*` or its release is immutable.
  - Dependabot security updates stay disabled: they open pull requests into the default branch, `main`, which changes only through release pull requests (`sdp.md` §4). The fix of an alert is made on `develop` instead.
  - The OSV-Scanner release is updated by hand, version and SHA-256 together in `ci.yml`, at least when a milestone starts.
- **CI token.** Every workflow sets `permissions: contents: read`: the token of a run can read the repository and nothing else, and the checkout step does not store it in the Git configuration of the runner (`persist-credentials: false`). No step needs more. The repository default is also read-only, and workflows cannot approve pull requests.
- **Repository settings,** made by the project owner on 2026-10-06 and checked the same day through the GitHub API (OP-045, closed):
  - private vulnerability reporting enabled;
  - dependency graph and Dependabot alerts enabled; the dependency graph of the default branch lists the packages of its `dsp/uv.lock` and the actions of its workflows;
  - Dependabot security updates disabled;
  - label `security` created, for the issues of §7.3;
  - default workflow token read-only, and workflows cannot create or approve pull requests;
  - only actions created by GitHub and the selected action `astral-sh/setup-uv` (pattern `astral-sh/setup-uv@*`) allowed to run, which covers every action the workflows use, so that a new third-party action needs the owner's approval.

  GitHub shows the security policy (`SECURITY.md`) and reads the configuration of Dependabot version updates (`.github/dependabot.yml`) from the default branch, `main`. Both files are on `develop`, so they take effect with the Milestone 1 release; until then, private vulnerability reporting and Dependabot alerts work without them, and Dependabot opens no version update.

### 7.5 Disclosure and support

- **Disclosure.** Coordinated with the reporter. Fixed vulnerabilities are noted in the pull request and in the milestone verification report. A GitHub security advisory is published for a vulnerability in Sinus's own code.
- **Support.** Only the latest milestone release is maintained ([`SECURITY.md`](../../SECURITY.md)).

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
