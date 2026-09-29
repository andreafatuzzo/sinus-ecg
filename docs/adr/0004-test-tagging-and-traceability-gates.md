# ADR 0004: Test tagging and traceability gates

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** project owner (the rules: implemented ⇒ tested, release gate, verification-level check, SBOM); tech lead (conventions and implementation)

## Context

Requirements are `SRS-nnn` entries in [`srs.md`](../regulatory/srs.md). `dsp/scripts/traceability.py` generates the traceability matrix ([`traceability.md`](../regulatory/traceability.md)) from the requirement IDs cited in code and in tests, and CI runs it with `--check`. Until this decision, the check failed only when the matrix was stale, when an ID was unknown, when an open point cited an undefined ID, or when a pytest requirement marker sat outside `dsp/tests/requirements/` and `dsp/tests/system/` (independence of verification, `sdp.md` §3.1). That left five gaps:

1. A requirement cited in production code, and so claimed as implemented, could have no verifying test. The matrix showed **none**, but CI stayed green.
2. Nothing stopped a milestone from reaching `main` with requirements that no test verifies. The increment review of `sdp.md` §3 relied on reading the matrix.
3. Each requirement has a Verification level (`Requirement`: QA; `System`: test engineer), but a test could verify it from the folder of the other level, which hides who verified it and how.
4. From Milestone 2 the code is C++17 (`libs/sinus-dsp`, `desktop/`, `firmware/`) tested with GoogleTest. The script understood only pytest, and only scanned `firmware/` for `.c` and `.h` files.
5. The README announces a software bill of materials (SBOM), but none was generated.

Constraints:
- the checks must be static (CI must not need to build or run C++ to trace it) and deterministic;
- the rules must be the same for Python and C++;
- Milestone 0, which contains only documents while the requirements of Milestone 1 are still untested, must be mergeable into `main`.

## Decision

### 1. Sources scanned

| What | Where | How |
|---|---|---|
| Requirements | `docs/regulatory/srs.md` | headings `### SRS-nnn: Title`, each with a `**Milestone:** Mn` line and a `**Verification level:**` line starting with `Requirement` or `System` |
| Milestones | `docs/regulatory/milestones.md` | table rows `\| Mn \| Title \| Status \|`, Status `Planned`, `In progress` or `Released` |
| Production code (implementation) | `dsp/sinus_dsp/**/*.py`, `dsp/scripts/**/*.py`; `libs/**`, `firmware/**`, `desktop/**` for `*.c, *.cc, *.cpp, *.h, *.hpp` | any `SRS-nnn` in the file (by convention in a comment or docstring) |
| Python tests | test files (`test_*.py`, `*_test.py`) under `dsp/tests/` | pytest marker, §3 |
| C++ tests | C and C++ files under `libs/`, `firmware/`, `desktop/` | tag comment, §4 |

Folders named `tests`, `test` (ESP-IDF component tests) or `test_apps` are never scanned as production code. Build output and third-party code are never scanned: folders named `build`, `_deps`, `managed_components`, `third_party`, `external` or `vendor`, and folders whose names start with `.`, `build-` or `cmake-build-`.

### 2. Test folders and independence

Every component keeps its tests in three folders:

```
dsp/tests/{unit,requirements,system}/
libs/<library>/tests/{unit,requirements,system}/
desktop/tests/{unit,requirements,system}/
firmware/tests/{unit,requirements,system}/
```

- `unit/`: the developer's unit tests. They carry no requirement tags.
- `requirements/`: QA's tests of requirements whose Verification level is `Requirement`.
- `system/`: the test engineer's tests of requirements whose Verification level is `System`.

A requirement tag (a pytest marker or a C++ tag comment) is accepted only in a `tests/requirements/` or `tests/system/` folder. Anywhere else, `--check` fails and the tag is not counted. The implementer therefore cannot verify their own code functionally.

### 3. pytest convention (unchanged)

```python
@pytest.mark.requirement("SRS-nnn", "SRS-nnn")
def test_rejects_non_finite_input() -> None: ...
```

The marker is placed on a test function or a test class, or listed in `pytestmark` at module or class level. The script reads it with Python's `ast` module and does not import the test. The matrix names the test `path::Class::test_name`.

### 4. GoogleTest convention

One or more comment lines of the form `// Verifies: ` followed by comma-separated requirement IDs, **directly above** the line that opens a GoogleTest `TEST`, `TEST_F`, `TEST_P`, `TYPED_TEST` or `TYPED_TEST_P`. No blank line or other line may come between them:

```cpp
// Verifies: SRS-nnn
// Verifies: SRS-nnn, SRS-nnn
TEST_F(QrsDetectorTest, OneDetectionPerBeatAt360Hz) {
  ...
}
```

- The matrix names the test `path::Suite.Name`, the GoogleTest full name (`--gtest_filter` syntax).
- For `TEST_P` and typed tests, the tag covers every instantiation.
- `Verifies:` is reserved, so a mistake fails instead of silently dropping a test from the matrix. `--check` fails when:
  - `Verifies:` appears in any other form (a block comment, after code on the same line, prose);
  - a tag contains anything other than comma-separated `SRS-nnn` IDs;
  - a tag is not directly followed by one of the five test macros.

Alternatives considered:
- **`RecordProperty("requirement", ...)` inside the test body.** It reaches the JUnit XML report, but it is only recorded when the test runs. Linking it statically to its test would require parsing C++ bodies.
- **Requirement IDs in test names** (e.g. `TEST(Srs0nn, ...)`). A name cannot carry several IDs, and it mixes traceability into test naming.
- **A project macro wrapping `TEST`.** It hides GoogleTest from IDEs and tools.

The comment mirrors the pytest marker: it sits on the test itself, can be read in review, and a line-based scan parses it.

On-target firmware tests (ESP-IDF Unity `TEST_CASE`, or tests driven from the host) are not covered yet. Their convention is decided with the firmware (Milestone 4). Until then, a tag above anything other than a GoogleTest macro fails the check.

### 5. Verification-level check (every push)

A test that verifies a requirement must be in the folder of that requirement's Verification level:
- `Requirement` → a `tests/requirements/` folder;
- `System` → a `tests/system/` folder.

A tag in the folder of the other level fails `--check`. The level states who verifies the requirement and how; the folder is how CI and readers see it.

### 6. Implemented ⇒ tested (every push)

Citing a requirement ID in production code claims that the requirement is implemented. `--check` fails when such a requirement has no verifying test, i.e. no correctly placed test with its tag. The matrix lists these requirements under "Implemented requirements without tests".

### 7. Release gate (pull requests into `main`)

**Sources of truth:**
- the `**Milestone:** Mn` line of each requirement in `srs.md`;
- the milestone register [`milestones.md`](../regulatory/milestones.md):
  - a milestone becomes `In progress` when its work starts on `develop`;
  - the pull request that merges it into `main` sets it to `Released`.

**Gate:** `traceability.py --release-gate` fails unless both hold:
- every requirement (not deleted) of every milestone that is `In progress` or `Released` has at least one verifying test;
- every requirement (not deleted) names a milestone listed in the register.

CI runs the gate in a separate workflow (`.github/workflows/release-gate.yml`, job `release-gate`) that is triggered only by pull requests into `main`. A push never produces the `release-gate` check, so a push-event run cannot satisfy it, and the ruleset on `main` requires both `dsp` and `release-gate`.

- **Why `In progress` is gated too.** `main` receives `develop` only at the end of a milestone. If the milestone is not verified, the pull request must fail even if its status was not yet changed to `Released`, so a forgotten status change does not open the gate.
- **Why a register file.** It is a table parsed with one pattern, and it changes in the pull request diff like any reviewed document. It also serves as the release record (IEC 62304 §5.8). Rejected alternatives:
  - **README roadmap checkboxes:** written for presentation, and a ticked box does not define a release.
  - **The `m<N>` git tags:** created only after the merge, so a pull request's CI cannot see them.
  - **A single "current milestone" value:** it cannot state several released milestones.
- **Milestone 0.** M0 has no requirements, so the gate on M0 passes. SRS-001 to SRS-016 belong to M1, which is `Planned` and so not gated. When M1 starts, its status becomes `In progress` on `develop`. From then on, a pull request from `develop` into `main` fails until every M1 requirement has a verifying test.

The gate does not check the following:
- **That tests pass.** pytest checks that in the same job.
- **That tests needing the reference database ran.** They are skipped in CI, and their results are in the milestone validation report (`sdp.md` §6).
- **That no open point still targets the milestone.** The process review checks that (`sdp.md` §3).

### 8. Requirement and register fields (every push)

`--check` also fails when:
- a requirement (not deleted) has no `**Milestone:**` line, names a milestone that is not in the register, or has no Verification level starting with `Requirement` or `System`;
- a requirement ID is defined twice in `srs.md`;
- a register row has an unknown status or repeats a milestone.

A requirement whose entry contains `_Deleted_` is exempt from the milestone and level fields and from the release gate.

### 9. SBOM

CI generates a CycloneDX (1.6, JSON) SBOM of the `dsp` runtime environment and uploads it as the workflow artifact `sbom-dsp`:

1. `uv sync --locked --no-dev --no-install-project`, with `UV_PROJECT_ENVIRONMENT` set to a folder in the runner's temporary directory, builds an environment with the locked runtime dependencies only;
2. `cyclonedx-py environment` describes it, with `sinus-dsp` from `pyproject.toml` as the root component, and `--output-reproducible` so that the same lock file gives the same SBOM.

- `cyclonedx-py` comes from the `cyclonedx-bom` package (7.4.0), pinned in `uv.lock` in the `dev` group.
- Development tools (pytest, ruff, mypy, cyclonedx-bom) are not part of the software item, are not SOUP (`sdp.md` §7) and are not in the SBOM.
- The SBOM also lists transitive dependencies (e.g. those of wfdb), whereas [`soup.md`](../regulatory/soup.md) lists the direct runtime dependencies.
- The SBOM is not committed: it is regenerated for every build.
- **Why not `uv export --format cyclonedx1.5`.** That export is a uv preview feature that may change between uv releases, and CI installs the latest uv. `cyclonedx-py` is pinned by the lock file, and reads package metadata such as licenses from the installed environment.
- **C++ components.** The C++ library (M2), the desktop application (M3) and the firmware (M4) add their SBOM parts when they land, from their own dependency manifests. Their generator and content are tracked as OP-046.

## Consequences

- **CI failures instead of matrix gaps.** A matrix gap that matters now fails CI when it appears: at the push that cites a requirement without a test, and at the pull request that would release an unverified milestone.
- **Branches stay red until verified.** A feature branch stays red from the developer's first citation until QA's (or the test engineer's) tagged test is on the same branch. Pull requests into `develop` are opened only when both are present.
- **Release pull requests update the register.** The pull request that releases a milestone sets it to `Released` in `milestones.md`, and the next milestone is set to `In progress` when its work starts. The process review checks the register against the roadmap.
- **New requirements need a Milestone line**, or CI fails.
- **Python and C++ tests share one matrix and one set of rules**, and a mistyped tag fails loudly.
- **The checks are static.** A tag records what a test claims to verify. Whether the test really checks the pass criterion is reviewed by QA and in the process review.
- **Every successful build publishes an SBOM** of the Python reference. The dev group gains `cyclonedx-bom` and its dependencies.
- **Where the rules are written:** the Conventions of `srs.md`, `milestones.md`, `CONTRIBUTING.md`, and the docstring of `traceability.py`. The script reads all paths through one layout object, so it can be tested on a fixture tree.
