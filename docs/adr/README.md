# Architecture decision records

An architecture decision record (ADR) documents one significant technical decision: its context, the options considered, the decision and its consequences. ADRs complement [`architecture.md`](../regulatory/architecture.md) (IEC 62304 §5.3):
- the architecture document describes the current design and cites the ADRs behind it;
- the ADRs keep the reasons, including the options that were rejected.

## When to write one

Write an ADR for a decision that meets any of these conditions:
- it is costly to reverse;
- it affects more than one software item;
- it selects a technology or a SOUP item;
- it sets a rule that the whole project must follow.

An open point in [`open-points.md`](../regulatory/open-points.md) that asks for such a decision is closed by the ADR, and its resolution cites it.

## How ADRs work

- **Numbers.** Files are named `NNNN-short-title.md` with a four-digit number. Numbers are never reused.
- **Template.** Start from [`0000-template.md`](0000-template.md).
- **Proposal and acceptance.** The tech lead proposes an ADR with status `Proposed`. The project owner accepts it (`Accepted`) or rejects it (`Deprecated`), in the pull request that adds it.
- **Changes.** An accepted ADR is not rewritten; only its status line and cross-references may change. To change a decision, write a new ADR and set the old one to `Superseded by ADR NNNN`.
- **Follow-up.** An ADR names the documents, requirements, risk controls and open points it affects. They are updated in the same pull request, or tracked as open points.

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-mcu-and-firmware-framework.md) | MCU and firmware framework: ESP32-S3, ESP-IDF with FreeRTOS, C++17 | Accepted | 2026-09-29 |
| [0002](0002-portable-cpp-dsp-library.md) | One portable C++17 signal-processing library, verified against the Python reference with golden vectors | Accepted | 2026-09-29 |
| [0003](0003-qt-desktop-application-with-replay.md) | Qt 6 desktop application with replay | Accepted | 2026-09-29 |
| [0004](0004-test-tagging-and-traceability-gates.md) | Test tagging and traceability gates | Accepted | 2026-09-29 |
| [0005](0005-device-sampling-rate-360-hz.md) | Device sampling rate: 360 Hz | Accepted | 2026-09-29 |
| [0006](0006-verification-per-software-item.md) | Verification per software item | Proposed | 2026-10-08 |
| [0007](0007-cpp-coding-standard-and-static-analysis.md) | C++ coding standard and static analysis | Proposed | 2026-10-08 |
| [0008](0008-arithmetic-of-the-real-time-library.md) | Arithmetic of the real-time library | Proposed | 2026-10-08 |
