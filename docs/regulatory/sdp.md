# Software development plan

_Inspired by IEC 62304 §5.1. Version 0.1, 2026-09-28. Status: draft (Milestone 0)._

> Sinus is not a medical device and claims no compliance with IEC 62304. This plan borrows the standard's structure so that the project is developed the way medical device software is.

## 1. Purpose and scope

This plan defines how the Sinus software is specified, built, verified, released and maintained. It covers every software item in the repository:

| Software item | Location | Language | Status |
|---|---|---|---|
| DSP reference implementation and validation pipeline | `dsp/` | Python | Milestone 1 |
| Firmware | `firmware/` | C | Milestone 2 |
| App | `app/` | TBD (OP-006) | Milestone 3 |
| Backend | `backend/` | Python (FastAPI) | Milestone 4 |

Hardware design (`hardware/`) is out of scope for this plan, except where it creates software requirements or risk controls.

## 2. Software safety classification

Assumed **Class B**. The rationale and its limits are in [`safety-class.md`](safety-class.md). The activities below are those IEC 62304 requires for Class B. Detailed design and unit-level acceptance criteria (§5.4) are applied only where a software item implements a risk control.

## 3. Lifecycle model

Development is **incremental**: one milestone per increment (see the roadmap in `README.md`). Each increment runs the same activities. Each activity has an owner role (§3.1):

1. **Functional analysis and requirements** (project manager): update [`functional-analysis.md`](functional-analysis.md), then new or changed `SRS-xxx` entries in [`srs.md`](srs.md) in the format defined there. The project owner confirms the requirements.
2. **Risk analysis** (project manager, with the tech lead for technical causes): update [`risk-analysis.md`](risk-analysis.md). New risk controls become requirements.
3. **Architecture and detailed design** (tech lead): update [`architecture.md`](architecture.md), including a design section per requirement. The project owner approves architectural changes.
4. **Implementation and unit testing** (developer): the code cites the requirement IDs it implements, and unit tests go in `dsp/tests/unit/`.
5. **Requirement verification** (QA): functional tests in `dsp/tests/requirements/`, derived from the SRS and marked with `@pytest.mark.requirement(...)`. Defects go back to step 4.
6. **System verification** (test engineer), when a macro feature is complete: end-to-end and performance tests in `dsp/tests/system/`, the EC57 validation, and the milestone verification report in `docs/validation/`.
7. **Increment review**:
   - the traceability matrix has no gaps for the increment's requirements;
   - no open point still targets the milestone;
   - `regulatory-reviewer` reports no blocking findings;
   - the project owner merges the milestone into `main` and tags it.

### 3.1 Roles

Roles hand work to each other through the documents above. Every decision reserved to the project owner stays with the project owner.

| Role | Owns | Must not |
|---|---|---|
| Project manager | Functional analysis, SRS, open points, user-level hazards | Design software, write code or tests |
| Tech lead | Architecture, detailed design, SOUP and technology choices, code conventions | Change what the product must do; implement features |
| Developer | Production code, unit tests (`dsp/tests/unit/`) | Write requirement or system tests; change requirements or interfaces |
| QA | Requirement verification tests (`dsp/tests/requirements/`), defect reports | Edit production code or unit tests; weaken tests |
| Test engineer | System tests (`dsp/tests/system/`), validation pipeline, verification reports | Edit production code; tune algorithms on the evaluation data |
| Reviewer | Process compliance review before merging into `main` | Edit anything |

**Independence of verification.** The implementer never verifies their own code functionally. CI enforces this with the traceability check: `@pytest.mark.requirement` is only accepted in `dsp/tests/requirements/` and `dsp/tests/system/`.

## 4. Configuration management

- **Version control**: Git, hosted at `github.com/andreafatuzzo/sinus-ecg`.
- **Branches**:
  - `main` holds reviewed, releasable states;
  - `develop` is the integration branch;
  - work happens on `feature/*` branches off `develop`.
- **Protection of `main`** (GitHub ruleset): changes arrive only through pull requests, the CI job `dsp` must pass on an up-to-date branch, and force pushes and deletion are blocked.
- **Releases**: each completed milestone is tagged on `main` as `m<N>` (e.g. `m1`). The tag identifies the exact code, documents and validation results of that increment.
- **Dependencies**: `dsp/uv.lock` pins every Python dependency to an exact version, and CI installs with `uv sync --locked`. Runtime dependencies are SOUP and are listed in [`soup.md`](soup.md) (§7).
- **Data**: reference databases are downloaded by script, verified by checksum and never committed.

## 5. Development standards and tools

| Concern | Standard / tool |
|---|---|
| Python style and lint | ruff (format + lint), configured in `dsp/pyproject.toml` |
| Python types | mypy `--strict` on `sinus_dsp` |
| Tests | pytest with `--strict-markers` |
| Environment | uv, Python 3.11 pinned in `dsp/.python-version` |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |
| C (firmware) | To be defined at Milestone 2 (OP-003) |

Development is assisted by Claude Code (an AI coding assistant). All AI-generated changes go through the same pull-request, CI and review gates as any other change. The project owner reviews and approves every merge into `main`.

## 6. Verification strategy

| Level | Method | Evidence |
|---|---|---|
| Unit (developer) | Unit tests of internal behavior in `dsp/tests/unit/`; they do not count as requirement verification | CI log |
| Requirement (QA) | Tests in `dsp/tests/requirements/`, tagged with the requirement ID and checking its pass criterion, for SRS entries with Verification level `Requirement` | CI log; [`traceability.md`](traceability.md) |
| System (test engineer) | Tests in `dsp/tests/system/` for SRS entries with Verification level `System`, including ANSI/AAMI EC57 beat-by-beat evaluation on the MIT-BIH Arrhythmia Database | Milestone verification report in `docs/validation/`, regenerated by a single script |
| Integration (later milestones) | Recorded real signals replayed through firmware → app → backend | To be defined at Milestone 3 (OP-007) |
| Process | `traceability.py --check` in CI; `regulatory-reviewer` before merging into `main` | CI log; pull request |

A requirement counts as verified only when at least one test checks its pass criterion and that test passes in CI. Tests that need the reference database (not available in CI) run locally, and their output is captured in the validation report of the milestone.

## 7. SOUP management

Every third-party runtime component is recorded in [`soup.md`](soup.md) in the same change that introduces it. Each entry records its purpose and version, and the review of its known anomalies. Development-only tools are not SOUP.

## 8. Problem resolution

- Defects and anomalies are tracked as GitHub Issues labelled `bug`.
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
| `open-points.md` | Whenever something is deferred or decided; reviewed at every milestone |
| `traceability.md` | Generated on every change |
| `docs/validation/` reports | Generated for every milestone with algorithms |
