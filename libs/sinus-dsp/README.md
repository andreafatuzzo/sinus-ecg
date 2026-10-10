# sinus-dsp: portable real-time signal-processing library

C++17 library, planned for Milestone 2. It is the single real-time implementation of the Sinus signal processing, used by both the firmware (ESP32-S3) and the desktop application.

## Planned content

- Second-order-section (biquad) filters: baseline wander high-pass, 50 Hz or 60 Hz mains notch, low-pass.
- Decimation for the device's oversampled ADC.
- LMS adaptive filter for mains and motion interference (with an accelerometer reference, if the device has one).
- Streaming Pan–Tompkins QRS detection, one sample at a time, with a bounded, documented delay.
- Kalman filter for the heart rate from RR intervals.
- Per-window signal quality index.

## Constraints

- **Dependencies:** C++17 and its standard library only. No dependency on ESP-IDF, FreeRTOS, Qt or the operating system.
- **Memory:** no dynamic memory; fixed-size state sized at compile time.
- **Errors:** no exceptions and no RTTI; errors are returned as values.
- **Arithmetic:** `float` (binary32) in the real-time path, because the ESP32-S3 floating-point unit is single precision.
- **Behaviour:** deterministic (no global state, clocks, random numbers or I/O), with bounded work per sample.
- **Build:** CMake, for the host and for the ESP32-S3, from the same sources.

## Build and test

The development tools (CMake, Ninja, clang-format, clang-tidy, gcovr) are pinned in `tools/`. With a C++17 compiler selected by `CXX` (GCC 14, Clang 18, or LLVM-MinGW on Windows), from this folder:

```sh
uv sync --locked --project tools
uv run --project tools cmake --preset debug      # also: release, asan-ubsan, coverage, tidy
uv run --project tools cmake --build --preset debug
uv run --project tools ctest --preset debug
```

GoogleTest 1.18.0 is fetched by URL and checked by SHA-256; a computer without network access sets `FETCHCONTENT_SOURCE_DIR_GOOGLETEST` to a copy. The version is in `VERSION`; the library states it with the SHA-256 of its own code (`sinus::dsp::library_identity()`).

## Verification

- **Tests:** GoogleTest on the host, in `tests/{unit,requirements,system}/`, with requirement tags as in [ADR 0004](../../docs/adr/0004-test-tagging-and-traceability-gates.md).
- **Equivalence:** the library is checked against the golden vectors exported by the Python reference in [`dsp/`](../../dsp/), within defined tolerances (OP-005), on the host and on the ESP32-S3 (OP-051).

Design: [`architecture.md`](../../docs/regulatory/architecture.md) §5 and §7, and [ADR 0002](../../docs/adr/0002-portable-cpp-dsp-library.md).

Sinus is not a medical device; this library is not intended for diagnosis or monitoring.

_Build instructions will be added with the first code (Milestone 2)._
