# Open points

_Single register of pending decisions, deferred work and known gaps. Status: living document._

## Conventions

- Each open point has an ID `OP-001`, `OP-002`, … IDs are never reused or renumbered.
- **Refs** names the specification items the open point concerns, by ID: `SRS-xxx` (requirements), `HAZ-xxx` / `RC-xxx` (risk analysis). When no ID exists yet, it names the document and section, e.g. `README §License`.
- `dsp/scripts/traceability.py` shows the open points of each requirement in the traceability matrix. It fails if an open point cites an ID that does not exist.
- A document placeholder ("to be defined", "TBD") cites the open point that tracks it.
- Closing an open point: set **Status** to `Closed`, move the row to [Closed](#closed), and record the resolution and where it landed (commit, PR or document). Closed rows are never deleted.
- **Target** is the milestone by which the point must be closed.

## Open

| ID | Open point | Refs | Opened | Target | Status |
|---|---|---|---|---|---|
| OP-001 | Choose the license for hardware files (schematics, BOM). A CERN-OHL variant (P, W or S) is planned. | README §License | 2026-09-28 | M2 | Open |
| OP-002 | Choose the MCU: ESP32-S3 or nRF52840. | sdp.md §1, architecture.md | 2026-09-28 | M2 | Open |
| OP-003 | Choose the firmware framework (ESP-IDF or Zephyr), and define the C coding standard and static analysis tools. | sdp.md §5 | 2026-09-28 | M2 | Open |
| OP-004 | Define the device sampling rate. SRS-003 accepts 125–1000 Hz, but filters and detection are only specified and tested at 360 Hz (MIT-BIH) and 250 Hz. | SRS-003, SRS-004, SRS-005, SRS-006, SRS-010 | 2026-09-28 | M2 | Open |
| OP-005 | Real-time C port: filters and QRS detection must run causally on the MCU. Specify latency and numeric-equivalence requirements against the Python reference. | SRS-004, SRS-005, SRS-006, SRS-010, RC-002 | 2026-09-28 | M3 | Open |
| OP-006 | Choose the app platform (web or mobile). | sdp.md §1 | 2026-09-28 | M3 | Open |
| OP-007 | Define the integration verification method: replaying recorded signals through firmware, app and backend. | sdp.md §6 | 2026-09-28 | M3 | Open |
| OP-008 | Write the architecture document for the dsp software item (modules and interfaces), then extend it per milestone. | architecture.md | 2026-09-28 | M1 | Open |
| OP-009 | Review the known anomalies of the SOUP items NumPy, SciPy and wfdb (currently TBD). | soup.md | 2026-09-28 | M1 | Open |
| OP-010 | SRS-007 is verified locally only, because CI has no copy of MIT-BIH. Decide whether CI should download and cache the database, so that the performance test runs on every push. | SRS-007, RC-001 | 2026-09-28 | M1 | Open |
| OP-011 | Probability estimates for HAZ-001 and HAZ-002 are qualitative. Revisit them with the measured Se / +P from the Milestone 1 validation report. | HAZ-001, HAZ-002, SRS-007 | 2026-09-28 | M1 | Open |
| OP-012 | Risk analysis of BLE data loss or corruption. | risk-analysis.md §Scope | 2026-09-28 | M2 | Open |
| OP-013 | Inspect the schematic to verify battery-only operation (no electrical path to mains while worn). | RC-006, HAZ-005 | 2026-09-28 | M2 | Open |
| OP-014 | Risk analysis of real-time latency and dropped samples. | risk-analysis.md §Scope | 2026-09-28 | M3 | Open |
| OP-015 | Show the intended-use labeling ("Not a medical device…") in the app. | RC-005 | 2026-09-28 | M3 | Open |
| OP-016 | Risk analysis of stored personal data, authentication and privacy, including GDPR notes. | risk-analysis.md §Scope | 2026-09-28 | M4 | Open |
| OP-017 | Risk analysis of beat classification, and review of the safety classification when classification lands. | risk-analysis.md §Scope, safety-class.md §Review triggers | 2026-09-28 | M5 | Open |
| OP-018 | Decide whether architecture segregation justifies a lower safety class for some software items (e.g. backend storage). | safety-class.md §Result | 2026-09-28 | M4 | Open |
| OP-020 | Define how electrode contact loss and interrupted data are detected and reported as "signal not usable", and specify that no beats or heart rate are presented while the signal is not usable. | HAZ-001, HAZ-002, SRS-003, functional-analysis.md FB-05, F2.3, F3.3 | 2026-09-28 | M2 | Open |
| OP-021 | Define the displayed heart rate: number of beats or time window averaged, update interval, displayed range, when it is withheld, and how the display shows that data has stopped arriving. | HAZ-001, HAZ-002, RC-005, functional-analysis.md FB-08, F3.2, F3.3 | 2026-09-28 | M3 | Open |
| OP-022 | Decide how the mains frequency (50 Hz or 60 Hz) is selected for live use: fixed at 50 Hz, user setting, or automatic detection. Include the tolerance to deviations of the mains frequency. | SRS-005, SRS-010, HAZ-002, RC-002, functional-analysis.md F3.7 | 2026-09-28 | M3 | Open |
| OP-023 | Define the target duration of a worn session (continuous acquisition on one battery charge). | functional-analysis.md §2.3, F2.1 | 2026-09-28 | M2 | Open |
| OP-024 | Choose the charging concept that makes charging while worn impossible (e.g. charge port reachable only with the electrode cable disconnected, or removable battery). OP-013 then verifies it on the schematic. | HAZ-005, RC-006, functional-analysis.md F2.1 | 2026-09-28 | M2 | Open |
| OP-025 | Extend the risk analysis to hardware hazards to the wearer other than electric shock: battery overheating or fire while worn, and skin reaction to electrodes or adhesive. | risk-analysis.md §Scope, HAZ-005 | 2026-09-28 | M2 | Open |
| OP-026 | Decide where a stored session is reviewed (in the app, in a web view served by the backend, or only through export to external tools) and what the review shows. | functional-analysis.md US-6, F4.2 | 2026-09-28 | M4 | Open |
| OP-027 | Define the content of the FHIR export (heart rate only, or also the waveform; codes used) and how each exported resource states that it does not come from a medical device. | HAZ-010, RC-005, RC-011, functional-analysis.md FB-13, F4.3 | 2026-09-28 | M4 | Open |
| OP-028 | Define wearer exclusions and use-environment limits for the labeling (e.g. minimum age, implanted pacemaker or defibrillator, water exposure, sleep). | RC-005, safety-class.md §Intended use, functional-analysis.md §2.2 | 2026-09-28 | M2 | Open |
| OP-029 | Decide on independent evidence for QRS detection beyond MIT-BIH, which is also used during development: a second reference database and a noise stress test. | SRS-007, RC-001, HAZ-004, README §Data sources, functional-analysis.md F5.3 | 2026-09-28 | M5 | Open |

## Closed

| ID | Open point | Refs | Opened | Closed | Resolution |
|---|---|---|---|---|---|
| OP-019 | Write the functional analysis (intended use, use scenarios, functional architecture, feature list per milestone), then check SRS v0.1 (SRS-001 to SRS-009) against it. Owner: project manager. | sdp.md §3, SRS-001, SRS-002, SRS-003, SRS-004, SRS-005, SRS-006, SRS-007, SRS-008, SRS-009 | 2026-09-28 | 2026-09-28 | Functional analysis v0.1 written and confirmed; SRS v0.2 and risk analysis v0.2 updated from the review (2026-09-28). Landed in `functional-analysis.md` v0.1, `srs.md` v0.2 (SRS-010 to SRS-012 added) and `risk-analysis.md` v0.2 (HAZ-010, RC-011 added). |
