# Software development plan

_Inspired by IEC 62304 §5.1. Version 0.4, 2026-10-02. Status: draft (Milestone 0); the changes of version 0.4 are pending approval by the project owner._

> Sinus is not a medical device and claims no compliance with IEC 62304. This plan borrows the standard's structure so that the project is developed the way medical device software is.
>
> Sinus has **no quality management system**: ISO 13485 is out of scope. The project borrows only the structure of the software life cycle (IEC 62304) and of risk management (ISO 14971), and, in a light form, of usability engineering (IEC 62366-1) and security (IEC 81001-5-1).

## Revision history

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-28 | First draft |
| 0.2 | 2026-09-28 | Repository URL, reviewer role, detailed design scope |
| 0.3 | 2026-09-29 | Software items aligned with the roadmap M0 to M6:<br>- portable C++17 library;<br>- Qt 6 desktop application;<br>- ESP32-S3 firmware in C++17 on ESP-IDF with FreeRTOS;<br>- backend.<br>Also:<br>- no quality management system;<br>- traceability gates and milestone register (ADR 0004);<br>- tools in use and planned per milestone, including the SBOM;<br>- development with AI assistance;<br>- equivalence, integration-by-replay and usability verification levels;<br>- definition of done per component |
| 0.3.1 | 2026-09-29 | §6: rule for parameters tuned on the evaluation data |
| 0.4 | 2026-10-02 | Software version and identification of `dsp` (OP-061; pending approval by the project owner). §4: the version follows the milestones, and every report and golden vector states the version and a digest of the package source; tags of correction releases. §3, activity 7: the release sets the version and regenerates the validation reports from the released code. §5.1: the release check of the reports. §6: results apply to the software they state; tuned parameters are recorded with the software identity before and after. §9: validation reports regenerated at each release |

## 1. Purpose and scope

This plan defines how the Sinus software is specified, built, verified, released and maintained. It covers every software item in the repository:

| Software item | Location | Language and platform | Milestones |
|---|---|---|---|
| DSP reference implementation and validation pipeline | `dsp/` | Python 3.11 | M1 (reference, validation, golden vectors); M6 (HRV, beat classification) |
| Portable real-time signal-processing library | `libs/sinus-dsp/` | C++17, CMake; host and ESP32-S3 | M2 |
| Desktop application | `desktop/` | C++17, Qt 6 (user-interface technology: OP-033) | M3 (replay, test input); M4 (device) |
| Firmware | `firmware/` | C++17 on ESP-IDF with FreeRTOS; ESP32-S3 | M4 |
| Backend | `backend/` | Python, FastAPI; HL7 FHIR R4 | M5 |

The roadmap is in `README.md`, and the status of each milestone in [`milestones.md`](milestones.md). The architecture of the items and their interfaces is in [`architecture.md`](architecture.md). Hardware design (`hardware/`) is out of scope for this plan, except where it creates software requirements or risk controls.

## 2. Software safety classification

Assumed **Class B**. The rationale and its limits are in [`safety-class.md`](safety-class.md). The activities below are those IEC 62304 requires for Class B.

Beyond the Class B minimum, a detailed design section (IEC 62304 §5.4) is written for every requirement. The reason is that the Python reference is the basis against which the real-time C++ library is verified (golden vectors, [ADR 0002](../adr/0002-portable-cpp-dsp-library.md)).

## 3. Lifecycle model

Development is **incremental**: one milestone per increment (see the roadmap in `README.md`). Each increment runs the same activities, and each activity has an owner role (§3.1):

1. **Functional analysis and requirements** (project manager):
   - update [`functional-analysis.md`](functional-analysis.md);
   - then write new or changed `SRS-xxx` entries in [`srs.md`](srs.md), in the format defined there, each naming its milestone;
   - the project owner confirms the requirements.
2. **Risk analysis** (project manager, with the tech lead for technical causes):
   - update [`risk-analysis.md`](risk-analysis.md), and, when the increment touches them, [`usability.md`](usability.md) and [`cybersecurity.md`](cybersecurity.md);
   - new risk controls become requirements.
3. **Architecture and detailed design** (tech lead):
   - update [`architecture.md`](architecture.md), including a design section per requirement;
   - record significant decisions as architecture decision records in [`docs/adr/`](../adr/README.md);
   - the project owner approves architectural changes and accepts the ADRs.
4. **Implementation and unit testing** (developer): the code cites the requirement IDs it implements, and unit tests go in the item's `tests/unit/` folder.
5. **Requirement verification** (QA):
   - functional tests derived from the SRS, in the item's `tests/requirements/` folder;
   - each is tagged with the requirements it verifies: a pytest marker `@pytest.mark.requirement(...)` or, in C++, a `// Verifies:` comment (ADR 0004);
   - defects go back to step 4.
6. **System verification** (test engineer), when a macro feature is complete:
   - end-to-end and performance tests in the item's `tests/system/` folder;
   - the EC57 validation;
   - the milestone verification report in `docs/validation/`.
7. **Increment review**:
   - every requirement of the milestone has a verifying test. CI enforces this on the pull request into `main` with the release gate ([ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md));
   - the traceability matrix has no other gaps for the increment's requirements;
   - no open point still targets the milestone (enforced by the release gate, ADR 0004);
   - the process compliance review (Reviewer role, §3.1) reports no blocking findings;
   - the pull request sets the milestone to `Released` in [`milestones.md`](milestones.md) and the release version (§4), and the validation reports in `docs/validation/` are regenerated from the code being released. CI checks on the pull request into `main` that the version is not a development version and that every report states the released software;
   - the project owner merges it into `main` and tags it (§4).

### 3.1 Roles

Roles hand work to each other through the documents above. Every decision reserved to the project owner stays with the project owner.

| Role | Owns | Must not |
|---|---|---|
| Project manager | Functional analysis, SRS, open points, user-level hazards | Design software, write code or tests |
| Tech lead | Architecture, detailed design, ADRs, SOUP and technology choices, code conventions | Change what the product must do; implement features |
| Developer | Production code, unit tests (`tests/unit/`) | Write requirement or system tests; change requirements or interfaces |
| QA | Requirement verification tests (`tests/requirements/`), defect reports | Edit production code or unit tests; weaken tests |
| Test engineer | System tests (`tests/system/`), validation pipeline, verification reports | Edit production code; tune algorithms on the evaluation data |
| Reviewer | Process compliance review before merging into `main` | Edit anything |

**Independence of verification.** The implementer never verifies their own code functionally. CI enforces this with the traceability checks ([ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md)), the same for Python and C++:
- a requirement tag is accepted only in a `tests/requirements/` or `tests/system/` folder, and only in the folder of the requirement's Verification level;
- a requirement cited in production code must have a verifying test (implemented ⇒ tested);
- on a pull request into `main`, every requirement of a milestone that is in progress or released must have a verifying test (release gate).

The same rules apply to work drafted with AI assistance (§5.3).

## 4. Configuration management

- **Version control**: Git, hosted at `github.com/andreafatuzzo/sinus-ecg`.
- **Branches**:
  - `main` holds reviewed, releasable states;
  - `develop` is the integration branch;
  - work happens on `feature/*` branches off `develop`.
- **Protection of `main`** (GitHub ruleset): changes arrive only through pull requests, the CI job `dsp` must pass on an up-to-date branch and, for pull requests into `main`, the check `release-gate` must pass, and force pushes and deletion are blocked.
- **Releases**:
  - [`milestones.md`](milestones.md) is the release register. A milestone becomes `In progress` when its work starts on `develop`, and the pull request that merges it into `main` sets it to `Released`.
  - After the merge, the project owner tags `main` as `m<N>` (e.g. `m1`). The tag identifies the exact code, documents and validation results of that increment.
  - A correction released into `main` between milestone releases raises the patch number of the version (below) and is tagged `m<N>.<P>` (e.g. `m1.1` for version `0.1.1`).
- **Software version and identification of `dsp`** (rule and checks: [`architecture.md`](architecture.md) §8.14):
  - The version is written in `dsp/pyproject.toml` and `sinus_dsp/__init__.py`, always equal, and follows the milestone register: `0.N.0.dev0` while milestone N is `In progress` (the lowest one, if several are); `0.N.0` when milestone N is released; `0.N.P`, with P raised by 1, for each correction released into `main` before the next milestone starts. Milestone 0 was released as `0.0.1`.
  - The version changes only with the milestone register. Changes within a milestone keep the same version, and are told apart by the **source digest**: a SHA-256 digest of the source files of the package, computed when a report or golden vector is produced. The same version and digest mean the same source code.
  - Every validation report and golden vector states the version and the source digest. The reports also state the versions of Python and of the runtime SOUP.
  - The stored subset report (SRS-016) states them too and is compared byte for byte on every push. A change to the package, its version, the Python version or a runtime SOUP version therefore updates the stored subset report in the same change, as for the traceability matrix.
  - Checks: on every push, `traceability.py --check` fails if the two version strings differ or if the version does not follow the register, and `uv sync --locked` fails if `dsp/uv.lock` was not regenerated; on a pull request into `main`, the release gate rejects a development version, and `dsp/scripts/software_check.py` fails unless every report in `docs/validation/` that states the software states the code being released. That the patch number is raised for a correction release is checked by the release review.
  - The versioning of the C++ items is defined with their detailed design, from Milestone 2.
- **Dependencies**:
  - `dsp/uv.lock` pins every Python dependency to an exact version, and CI installs with `uv sync --locked`;
  - for the C++ items, the versions of the SDKs and toolchains (ESP-IDF and its container image, Qt, CMake minimum version) are pinned in the item's build files;
  - runtime dependencies are SOUP and are listed in [`soup.md`](soup.md) (§7).
- **Data**: reference databases are downloaded by script, verified by checksum and never committed. Golden vectors are regenerated, never committed ([`architecture.md`](architecture.md) §7.5).

## 5. Development standards and tools

### 5.1 In use

| Concern | Standard or tool |
|---|---|
| Python style and lint | ruff (format and lint), configured in `dsp/pyproject.toml` |
| Python types | mypy `--strict` on `sinus_dsp` |
| Tests | pytest with `--strict-markers` |
| Environment | uv, Python 3.11 pinned in `dsp/.python-version` |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |
| Traceability | `dsp/scripts/traceability.py`: generated matrix, `--check` on every push (including the version rule of §4), `--release-gate` on pull requests into `main` ([ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md)) |
| Software identity of the reports | `dsp/scripts/software_check.py`, on pull requests into `main`: every report in `docs/validation/` states the software being released (§4; [`architecture.md`](architecture.md) §8.14) |
| SBOM | CycloneDX JSON of the `dsp` runtime environment, generated in CI with `cyclonedx-py` from the `cyclonedx-bom` package (a development tool), published as a build artifact ([`cybersecurity.md`](cybersecurity.md) §6) |

### 5.2 Planned, introduced with the milestone that first needs them

| Tool | Purpose | Milestone |
|---|---|---|
| CMake with presets for the host, the ESP32-S3 and the desktop application | Build of all C++ code | M2 (host, ESP32-S3); M3 (desktop) |
| GCC and Clang on the host; the ESP-IDF toolchain for the ESP32-S3 | C++17 compilers | M2 |
| clang-format | C++ formatting | M2 |
| clang-tidy or cppcheck | C++ static analysis | M2 |
| GoogleTest, with coverage (gcov or llvm-cov reports) | C++ unit, requirement and equivalence tests | M2 |
| AddressSanitizer and UndefinedBehaviorSanitizer | Host test builds of the C++ items | M2 |
| Official ESP-IDF container image, pinned version | Reproducible builds for the ESP32-S3 in CI: the library (M2), on-target equivalence tests in Espressif's QEMU emulator in CI (OP-051 closed), the firmware (M4) | M2 |
| Qt 6, pinned version, installed and cached in CI | Build and tests of the desktop application | M3 |
| CycloneDX SBOM of the C++ items and the backend | Complete SBOM (OP-046) | M2 to M5 |
| SonarCloud (optional) | Code quality dashboard | M2 or later |
| ruff, mypy, pytest, with the FastAPI test client | Backend | M5 |

The C++17 coding standard, the formatting configuration and the static-analysis rule set are defined in OP-043. Until then, the constraints of `architecture.md` §5.1 apply to all C++ code.

### 5.3 AI-assisted development

Development is assisted by Claude Code (an AI coding assistant). All AI-generated changes go through the same pull-request, CI and review gates as any other change. The project owner reviews and approves every merge into `main`. What the assistant is used for, which decisions stay with people and how its output is checked are described in [`docs/process/ai-assisted-development.md`](../process/ai-assisted-development.md).

## 6. Verification strategy

| Level | Method | Evidence |
|---|---|---|
| Unit (developer) | Unit tests of internal behaviour in each item's `tests/unit/` (pytest; GoogleTest for C++). They do not count as requirement verification | CI log |
| Requirement (QA) | Tests in `tests/requirements/`, tagged with the requirement ID and checking its pass criterion, for SRS entries with Verification level `Requirement` | CI log; [`traceability.md`](traceability.md) |
| System (test engineer) | Tests in `tests/system/` for SRS entries with Verification level `System`. They include the ANSI/AAMI EC57 beat-by-beat evaluation on the MIT-BIH Arrhythmia Database. The noise stress results are part of the system validation report, while SRS-014 itself is verified by QA | Milestone verification report in `docs/validation/`, regenerated by a single script |
| Equivalence (from Milestone 2) | The real-time C++ library runs on the golden vectors exported by the Python reference (SRS-015), and its outputs are compared with the reference within the tolerances of OP-005 (RC-012). This runs on the host in CI on every change, and on the ESP32-S3 in Espressif's QEMU emulator in CI (OP-051 closed) | CI log; equivalence section of the milestone verification report |
| Integration (from Milestone 3) | By replay (OP-007): reference records and recorded sessions are replayed through the desktop application (M3), then through the device, the desktop application and the backend (M4, M5). The results are compared with the offline reference on the same records | Milestone verification report |
| Usability (from Milestone 3) | Formative evaluation of the hazard-related use scenarios ([`usability.md`](usability.md) §5, OP-040) | Milestone verification report |
| Process | `traceability.py --check` on every push and `--release-gate` on pull requests into `main` (ADR 0004); `software_check.py` on pull requests into `main` (§4); process compliance review (Reviewer role) before merging into `main` | CI log; pull request |

A requirement counts as verified only when at least one test checks its pass criterion and that test passes in CI. Tests that need the complete reference databases run locally, and their output is captured in the validation report of the milestone. CI obtains a subset of records and checks the subset report on every push (SRS-016).

Every validation report and golden vector states the software that produced it: version and source digest (§4). Its results apply to that code. A released report states the released code (§3, activity 7).

**Tuning on evaluation data** (decided by the project owner, 2026-09-29). The algorithm parameters are fixed in the approved detailed design before the first run on the full MIT-BIH Arrhythmia Database. Any parameter change made after results on that database, or on the Noise Stress Test Database, have been seen is recorded in the milestone verification report as *tuned on the evaluation data*, with the parameters before and after, the results of both, and the software identity (version and source digest, §4) of both runs. Results after such a change are reported as such, and independent evidence on a database not used during development (OP-029) is needed before claiming generalisation.

## 7. SOUP management

- Every third-party runtime component is recorded in [`soup.md`](soup.md) in the same change that introduces it. Each entry records its purpose and version, and the review of its known anomalies. Components planned for later milestones are listed there too.
- SDKs, frameworks and libraries linked into the product are SOUP: ESP-IDF, FreeRTOS, Qt, FastAPI, and the C and C++ runtime libraries of the toolchains.
- Development-only tools are not SOUP: compilers, CMake, test frameworks, linters, formatters, SBOM generators.
- Security vulnerabilities in SOUP are handled as described in [`cybersecurity.md`](cybersecurity.md) §7.

## 8. Problem resolution

- Defects and anomalies are tracked as GitHub Issues labelled `bug`. Security vulnerabilities are labelled `security`, and handled as described in `cybersecurity.md` §7.
- Each defect records the affected requirement(s), and is assessed for impact on [`risk-analysis.md`](risk-analysis.md).
- A fix references the issue, adds or updates a test that reproduces the defect, and follows the normal pull-request flow.
- Known anomalies still open at the end of a milestone are listed in that milestone's verification report.
- Pending decisions, deferred work and known gaps that are not defects go in [`open-points.md`](open-points.md) as `OP-xxx`, citing the specification IDs they concern. Every "to be defined" or "TBD" in a document cites its open point. At the end of each milestone, every open point targeting that milestone is either closed or moved to a later target, with the reason recorded.

## 9. Deliverables

| Document | Updated |
|---|---|
| `sdp.md`, `safety-class.md` | Milestone 0; revised when scope or intended use changes |
| `functional-analysis.md` | By the project manager, at the start of every milestone that adds functions |
| `srs.md`, `risk-analysis.md`, `architecture.md`, `soup.md` | Every milestone that changes them |
| `usability.md`, `cybersecurity.md` | Every milestone that changes the user interface, an interface between items, or stored data |
| `docs/adr/` | For every significant architecture decision |
| `docs/process/` | When the development process changes |
| `open-points.md` | Whenever something is deferred or decided; reviewed at every milestone |
| `milestones.md` | When a milestone starts (`In progress`) and in the pull request that releases it (`Released`) |
| `traceability.md` | Generated on every change |
| SBOM | Generated by CI on every build |
| `docs/validation/` reports | Generated for every milestone with algorithms, and regenerated from the released code at each release (§3, activity 7); the stored subset report whenever the software it states changes (§4) |

## 10. Definition of done

A component (a software item, or the part of it that a milestone delivers) is done when:

1. It builds and passes CI: lint and format, type checks or static analysis, all tests, and the traceability checks.
2. Its requirements are in [`srs.md`](srs.md), and each has verifying tests, written by someone other than the implementer, that pass. They are listed in [`traceability.md`](traceability.md).
3. Its relevant hazards and risk controls are in [`risk-analysis.md`](risk-analysis.md). For interfaces and stored data, its threats and security controls are also in [`cybersecurity.md`](cybersecurity.md).
4. Its runtime dependencies are in [`soup.md`](soup.md).
5. Its design is described in [`architecture.md`](architecture.md), with the ADRs behind it.
6. Its folder has a README with instructions to build, test and run it.
7. It contains no diagnostic claims and no alarms, and the repository contains no personal data: datasets are downloaded, never committed.
