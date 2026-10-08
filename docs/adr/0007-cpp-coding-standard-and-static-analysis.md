# ADR 0007: C++ coding standard and static analysis

- **Status:** Accepted
- **Date:** 2026-10-08
- **Deciders:** project owner (decision); tech lead (proposal)
- **Related:** OP-043; [ADR 0002](0002-portable-cpp-dsp-library.md); [`architecture.md`](../regulatory/architecture.md) §5.1, §14.2, §14.3; [`sdp.md`](../regulatory/sdp.md) §5

## Context

The portable library (Milestone 2), then the desktop application (Milestone 3) and the firmware (Milestone 4), are written in C++17. OP-043 asks for the coding standard, the formatting and the static analysis tools. The library has hard constraints already (`architecture.md` §5.1): no heap, no exceptions or RTTI, binary32 in the real-time path except where §14.3 states binary64, determinism, bounded work. The tools must run the same locally (Windows, LLVM-MinGW recommended) and in CI (Linux, GCC 14 and Clang 18), and must earn their cost.

## Options considered

1. **MISRA C++:2023.** Recognised in safety-related industries. Its text is sold, and free tools check only part of it; a claim of conformance would need a qualified checker. Sinus claims no compliance with any standard.
2. **AUTOSAR C++14 guidelines.** Superseded by MISRA C++:2023, and written for C++14.
3. **A written subset of the C++ Core Guidelines plus project rules, enforced by compiler warnings, clang-tidy and clang-format (chosen).** Free, checkable in CI, and the clang-tidy checks map to the guidelines.
4. **Add cppcheck** to option 3. A second analyser overlaps with clang-tidy and the compiler warnings; its findings would need their own triage.

## Decision

Option 3, without cppcheck.

**Language and build.** ISO C++17 (`-std=c++17`, no GNU extensions in the library), the compiler options of `architecture.md` §14.2 (warnings as errors, `-fno-exceptions -fno-rtti -ffp-contract=off`, never fast-math), on every compiler.

**Project rules** (every C++ item; the library also keeps §5.1):
- no dynamic memory in the library: no `new`, `delete`, `malloc`, and no allocating standard containers or `std::function`; capacities are compile-time constants;
- no exceptions, no RTTI, no recursion, no global or static mutable state, no `goto`;
- fixed-width integer types: sample indices `std::uint64_t`, counts `std::uint32_t`, array indices `std::size_t`;
- every conversion between numeric types explicit (`static_cast`); `double` only where the design states it;
- every function of the library `noexcept`; functions that return a `Status` or a value that must be used are `[[nodiscard]]`; `enum class` for enumerations; `constexpr` for constants; no macros except where a tool needs one; headers use `#pragma once`;
- names: types `PascalCase`, functions and variables `snake_case` (as in the Python reference, so that both read alike), constants `kPascalCase`, private members with a trailing `_`, namespaces in lower case; identifiers carry their unit when the type does not (`_hz`, `_mv`, `_samples`, `_ms`, `_s`, `_bpm`; architecture, Conventions);
- each public function cites the requirement IDs it implements in a comment, and only those (`architecture.md` §8.2).

**Formatting.** clang-format 22.1.8 (pinned in the tools project of `architecture.md` §14.2) with `libs/sinus-dsp/.clang-format`: `BasedOnStyle: Google`, `ColumnLimit: 100` (the line length of the Python code). CI fails on any difference (`--dry-run --Werror`).

**Static analysis.** clang-tidy 22.1.8 with `libs/sinus-dsp/.clang-tidy`, on the library, `verification/` and `harness/` (not on tests), every finding an error (`WarningsAsErrors: '*'`). Checks: `bugprone-*`, `cert-*`, `clang-analyzer-*`, `cppcoreguidelines-*`, `misc-*`, `modernize-*`, `performance-*`, `portability-*`, `readability-*`, minus `cppcoreguidelines-avoid-magic-numbers` and `readability-magic-numbers` (the design constants are named where they are defined, and coefficients are literals of formulas), `modernize-use-trailing-return-type`, `readability-identifier-length`, `cppcoreguidelines-pro-bounds-constant-array-index` (fixed rings are indexed by computed indices, checked by the sanitizers and unit tests), `misc-non-private-member-variables-in-classes` (plain structures of results), `llvm-header-guard`; `readability-identifier-naming` configured with the names above. A check is disabled only by a change of this file with its reason in a comment; a finding is suppressed in code only with `NOLINTNEXTLINE(<check>)` and a reason.

**Dynamic checks.** AddressSanitizer and UndefinedBehaviorSanitizer on the computer in CI (preset `asan-ubsan`); coverage reported, without a threshold.

## Consequences

- **Positive:** the rules are checked on every push; the same tool versions run locally and in CI; the names match the Python reference, which eases the comparison that equivalence depends on.
- **Negative and risks:** clang-tidy lengthens the CI job (about a minute for the library) and may flag patterns that the rings need (handled by the listed exclusions). The desktop application will use Qt, which allocates and has its own idioms: its `core` keeps these rules, and its Qt layers get their adaptations in their detailed design (Milestone 3), as the firmware's ESP-IDF adapters will (Milestone 4).
- **Follow-up:** `.clang-format`, `.clang-tidy` and the tools project in group C1; `sdp.md` §5.1 rows when they land; OP-043 closed when this ADR is accepted and C1 is merged.
