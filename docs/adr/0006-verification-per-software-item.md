# ADR 0006: Verification per software item

- **Status:** Accepted
- **Date:** 2026-10-08
- **Deciders:** project owner (the rule: one verifying test per software item that implements a requirement, decided on 2026-10-07); tech lead (how the items and the tests are determined, the checks, the matrix)
- **Related:** amends [ADR 0004](0004-test-tagging-and-traceability-gates.md) §1, §5, §6, §7 and §8; SRS-022, SRS-024 to SRS-028, SRS-035, SRS-036, SRS-038; OP-066; [`architecture.md`](../regulatory/architecture.md) §13.12 (design of the checks), §14.17; [`sdp.md`](../regulatory/sdp.md) §3.1, §6

## Context

ADR 0004 counts a requirement as verified when at least one correctly placed test carries its tag. From Milestone 2 some requirements are implemented by two software items:
- SRS-022 and SRS-024 to SRS-028 name `dsp and libs/sinus-dsp`: the Python reference and the C++ library must both meet them;
- SRS-035 and SRS-038 name `dsp (scripts)` and `libs/sinus-dsp`.

Under ADR 0004, the Python requirement test alone would show these requirements verified, and the release gate would pass, while the C++ library had no test of them. The milestone review could catch it, but nothing in CI would.

Two further facts shape the rule:
- each requirement already names its software items in `srs.md` (`**Software item:** …`), and the eight distinct lines of `srs.md` v0.8.1 use a small grammar (items separated by `;` or ` and `, an optional qualifier in parentheses, and `CI workflow`, which is not a software item);
- some verifications of a C++ item need Python: the inspection of its CI job (SRS-036) and its detections scored on the reference databases with the evaluation of `dsp` (SRS-038).

## Options considered

1. **Keep ADR 0004 and rely on the review.** No change; a gap stays invisible to CI.
2. **Implementing items from the code citations only.** An item that cites a requirement needs a test in that item. Catches a C++ implementation without a C++ test, but a requirement whose C++ part is not written yet would pass the release gate.
3. **Implementing items from the `Software item` line, tests attributed to the item whose folder holds them (chosen).** The gate requires a test in every named item; the per-push check requires a test in every item that cites the requirement; a test of a C++ item may be written in Python, in that item's test folders.
4. **Tests declare the item they verify** (for example a keyword of the pytest marker or of the C++ tag). More syntax, and a test could claim an item it does not exercise.

## Decision

Option 3.

1. **Software items of a requirement**: those named on its `**Software item:**` line, read with the grammar above. `CI workflow` names the build configuration and is verified through the tests of the items listed with it. A requirement (not deleted) without that line, with an unknown name or with no item other than `CI workflow` fails `--check`.
2. **Item of a file**: the first folder of its path (`dsp`, `libs/<name>`, `desktop`, `firmware`, `backend`).
3. **A test verifies a requirement for an item** when it carries the requirement's tag, lies in the folder of its Verification level (ADR 0004 §5) and belongs to that item. Python test files are read under `dsp/tests` and under the `tests` folder of each C++ item; C++ tests as in ADR 0004 §4.
4. **Implemented ⇒ tested, per item** (every push): an item whose production code cites a requirement has a verifying test of it in that item.
5. **Release gate, per item** (pull requests into `main`): every requirement of a milestone in progress or released has a verifying test in each of its software items.
6. **Consistency** (every push): code of an item that a requirement does not name may not cite it, and a test in such an item does not count and fails `--check`.
7. **Matrix**: a column `Software items`; each item without a verifying test shown as `**none in <item>**`; milestone counts and gaps per item.

The exact messages, the order of the rules and the unit tests are in `architecture.md` §13.12, with the disabled-test rule decided in §8.16 item 5 (OP-066) and the version of the C++ items (§14.15), which land in the same change.

## Consequences

- **Positive:** a requirement of two items cannot reach `main` with one of them unverified; the `Software item` lines become checked data instead of prose; Python and C++ tests of one item share one rule.
- **Negative and risks:** a requirement whose second item lands later shows `**none in <item>**` and fails the gate until that item's test exists, which is the purpose. Python tests under `libs/sinus-dsp/tests` run in the `dsp` environment (pytest `testpaths`), so that environment also serves the C++ item's Python tests; `ruff` checks them with the configuration of `dsp`. A wrong `Software item` line now fails CI: the PM keeps the lines accurate, and the consistency rule shows a citation in an unnamed item.
- **Follow-up:** `dsp/scripts/traceability.py`, its unit tests and the regenerated matrix (group C1 of `architecture.md` §14.18); the conventions of `srs.md` (the `Software item` line is read by the script) and of `milestones.md` (the gate is per item), owned by the PM; `sdp.md` §3.1 and §6; at acceptance, the status line of ADR 0004 becomes "Accepted; amended by ADR 0006".
