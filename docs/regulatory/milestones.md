# Milestones

_Release register, inspired by IEC 62304 §5.8. Read by `dsp/scripts/traceability.py`. Status: living document._

## Conventions

- One row per milestone of the roadmap in `README.md`; the title is the roadmap heading.
- **Status** is one of:
  - `Planned`: work on the milestone has not started;
  - `In progress`: work on the milestone has started on `develop`;
  - `Released`: set in the pull request that merges the milestone into `main`. After the merge, the project owner tags `main` as `m<N>` (`sdp.md` §4).
- Each requirement names its milestone in `srs.md` (`**Milestone:** Mn`).
- **Release gate.** On a pull request into `main`, CI fails unless every requirement of every milestone that is `In progress` or `Released` has at least one verifying test, no open point in [`open-points.md`](open-points.md) still targets such a milestone, the package version is a release version (not `.dev`), and every report in `docs/validation/` states the software being released (`dsp/scripts/traceability.py --check --release-gate` and `dsp/scripts/software_check.py`; [`architecture.md`](architecture.md) §8.14, §8.16). A milestone therefore reaches `main` only with all its requirements verified, and later changes cannot remove that verification. Rules and rationale: [ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md).
- The traceability matrix ([`traceability.md`](traceability.md)) shows, for each milestone, its requirements, how many have a verifying test and the result of the release gate for that milestone, and the overall outcome of the release gate with the items that make it fail.

## Register

| Milestone | Title | Status |
|---|---|---|
| M0 | Foundations | Released |
| M1 | Python reference | In progress |
| M2 | Portable C++ DSP library | Planned |
| M3 | Qt desktop application with replay | Planned |
| M4 | Hardware, firmware and integration | Planned |
| M5 | Backend and interoperability | Planned |
| M6 | Classification, HRV and final report | Planned |
