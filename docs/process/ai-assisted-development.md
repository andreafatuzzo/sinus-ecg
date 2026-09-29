# Development with AI assistance

_Status: living document. Last updated 2026-09-29._

Sinus is developed with the help of an AI coding assistant, as disclosed in the software development plan ([`sdp.md`](../regulatory/sdp.md) §5.3). This page states:
- what the assistant is used for;
- which decisions stay with people;
- how AI-assisted work is checked.

In short, AI assistance changes who drafts the work, not the gates that the work must pass.

## What the assistant is used for

- Drafting production code and unit tests.
- Drafting verification tests from the requirements.
- Drafting and revising documentation: functional analysis, requirement and risk proposals, architecture, reports.
- Reviews: checking a change against the process (traceability, open points, consistency between documents) before it is merged.
- Routine work: refactoring, fixing lint and type errors, CI configuration.

The assistant is a development tool. It is not part of the product and is not SOUP.

## Decisions that stay with people

The project owner takes these decisions, after reviewing the documents behind them:
- the intended use and the software safety classification;
- the requirements: the owner confirms every version of [`srs.md`](../regulatory/srs.md);
- the risk analysis: hazards, severity and probability estimates, risk acceptability;
- safety-related thresholds and targets, such as the detection performance target, the equivalence tolerances, and the signal quality and abstention thresholds;
- architecture decisions (the owner accepts every [ADR](../adr/README.md)) and every new SOUP item;
- the open points reserved to the owner;
- every merge into `main`, and every milestone release.

A proposal from the assistant on any of these is only a proposal until the owner accepts it. An ambiguous or conflicting requirement is raised as an open point; it is not settled by interpretation.

## The same gates for every change

AI-assisted changes pass exactly the same gates as any other change:
- **Pull requests only.** `main` is protected and changes only by merging a pull request with green CI (`sdp.md` §4).
- **CI:**
  - formatting and lint;
  - strict type checking for Python;
  - static analysis and sanitizers for C++, from Milestone 2;
  - all tests;
  - the traceability checks and, for pull requests into `main`, the release gate ([ADR 0004](../adr/0004-test-tagging-and-traceability-gates.md)).
- **Traceability.** Code cites the requirements it implements, and verifying tests cite the requirements they verify. The traceability matrix is generated, never edited by hand.
- **Independent verification.** The implementer never verifies their own code functionally, and this holds for AI-assisted work too:
  - requirement and system tests are written in a task separate from the implementation, from the requirement text;
  - the implementing task does not write or edit them;
  - CI rejects requirement tags outside the verification test folders;
  - a failing verifying test is resolved by fixing the code or, through the owner, the requirement, never by weakening the test.
- **Process review** before a milestone is merged into `main` (`sdp.md` §3).
- **Library documentation.** The use of a library or API is checked against the documentation of the version in use, not assumed.

## Known limitations and how they are handled

| Limitation | Handling |
|---|---|
| Plausible but wrong code or text | Tests derived from the requirements, independent verification, human review of every pull request |
| Library functions that do not exist, or that changed between versions | Documentation of the pinned version; type checks; CI |
| A requirement silently reinterpreted | Requirements are decided by the owner; ambiguities become open points |
| Changes wider than asked | Small pull requests; every diff reviewed |

## Data

No recordings of real wearers, no credentials and no other personal data are given to the assistant. The reference databases used in development are public.
