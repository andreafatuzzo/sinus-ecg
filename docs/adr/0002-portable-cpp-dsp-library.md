# ADR 0002: One portable C++17 signal-processing library, verified against the Python reference with golden vectors

- **Status:** Accepted; precision rule amended by [ADR 0008](0008-arithmetic-of-the-real-time-library.md)
- **Date:** 2026-09-29
- **Deciders:** project owner (a single C++17 library shared by the firmware and the desktop application, with the Python code as reference); tech lead (constraints, causal reference, golden-vector format)
- **Related:** SRS-004, SRS-005, SRS-006, SRS-015; RC-012; HAZ-001, HAZ-002; OP-005, OP-043, OP-049, OP-051; [`architecture.md`](../regulatory/architecture.md) §5, §7

## Context

Signal conditioning, beat detection, heart-rate tracking and the signal quality index are needed in real time:
- in the desktop application (Milestone 3: replay; Milestone 4: device);
- on the device (Milestone 4).

The offline Python implementation in `dsp/` (Milestone 1) is validated on the reference databases (SRS-007, SRS-014), so it is the reference. A real-time implementation that behaves differently from that reference is a cause of missed and false beats (HAZ-001, HAZ-002), and RC-012 controls it by comparing the real-time outputs with the reference on golden vectors (SRS-015).

## Options considered

1. **Port the reference to C in the firmware, and implement the processing separately in the desktop application.** Two real-time implementations must be kept equivalent to the reference and to each other.
2. **One portable C++17 library, used by both the firmware and the desktop application, and verified against the Python reference on golden vectors.**
3. **Run the Python reference in the desktop application (embedded interpreter) and a C port on the device.** Two languages at runtime, and the reference is not written for sample-by-sample processing.
4. **A vendor-optimised signal-processing library on the device.** Faster, but tied to one target and not usable in the desktop application, so it brings back two implementations.

## Decision

Option 2: `libs/sinus-dsp`, a C++17 library built with CMake for the host and for the ESP32-S3.

- **Constraints** (`architecture.md` §5.1):
  - C++17 and its standard library only;
  - no dependency on ESP-IDF, FreeRTOS, Qt or the operating system;
  - no dynamic memory;
  - no exceptions and no RTTI;
  - deterministic;
  - binary32 in the real-time path, `double` only at configuration time;
  - bounded work and delay per sample;
  - the same source code on every target.
- **The Python reference is causal** (`architecture.md` §7.1). It applies its filters forward only (no zero-phase filtering) and detects beats from current and past samples with a bounded look-back, like the streaming library. Both sides share:
  - the filter design formulas;
  - the stage order;
  - the initial-state rule.

  Their outputs are therefore compared sample by sample, with no delay allowance.
- **Golden vectors** exported by the reference (SRS-015) use the text format of `architecture.md` §7.3:
  - values are written so that reading them back gives exactly the computed values;
  - the files are deterministic and contain no timestamps;
  - they are regenerated in CI from the same commit and are not stored in the repository.
- **Where the equivalence runs.** The library passes the equivalence checks on the host in CI on every change, and on the ESP32-S3 in Espressif's QEMU emulator in CI (OP-051, decided by the project owner on 2026-09-29). The tolerances are defined in OP-005.

## Consequences

**Positive**
- One real-time implementation: the device and the desktop application cannot diverge from each other.
- The validation results of the reference (SRS-007, SRS-014) transfer to the real-time implementation, within the equivalence tolerance. This is because the reference computes the same causal algorithm.
- The library is testable on a computer, with GoogleTest (tagging per [ADR 0004](0004-test-tagging-and-traceability-gates.md)), sanitizers and coverage, without hardware.
- A change to the reference that the library does not follow makes CI fail at once.

**Negative and risks, with mitigations**
- **Phase distortion.** The reference cannot use zero-phase filtering, so the causal baseline filter distorts the phase of the lowest ECG components (ST segment, T wave). Accepted: Sinus makes no claim on morphology or ST-segment measurements, and SRS-004 and SRS-005 constrain amplitude only.
- **Two code bases.** Every algorithm exists in Python and in C++, and both change together. Mitigation: the equivalence tests in CI, on vectors regenerated at every build.
- **Rounding differences.** binary32 on the device against binary64 in the reference. Mitigation: tolerances derived from the numerical analysis of each stage (OP-005). Coefficients are designed in `double` and rounded once, and the stage order keeps signal magnitudes small.
- **Development constraints.** The library cannot use exceptions, the heap or the standard containers that allocate, which costs convenience. Mitigations: the interface style of `architecture.md` §5.2 and the coding standard (OP-043).
- **Real-time budget.** The library must meet its budget on the ESP32-S3 (OP-049). A target-specific optimisation would need its own equivalence tests.

**Follow-up**
- The Milestone 2 requirements specify the real-time functions, their delay bounds and the equivalence tolerances (OP-005, OP-049).
- Record the toolchain and its C++ standard library in [`soup.md`](../regulatory/soup.md) when the library is introduced.
