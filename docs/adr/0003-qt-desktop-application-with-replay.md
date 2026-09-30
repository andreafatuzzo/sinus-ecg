# ADR 0003: Qt 6 desktop application with replay

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** project owner (a Qt 6 desktop application with replay, no web or mobile application; closes OP-006); tech lead (structure, licensing constraint, criteria for OP-033)
- **Related:** HAZ-006, HAZ-007, HAZ-013; RC-005, RC-007, RC-008, RC-015; OP-007, OP-015, OP-033, OP-037, OP-038, OP-040, OP-050; [`architecture.md`](../regulatory/architecture.md) §3.1, §6.2; [`usability.md`](../regulatory/usability.md) §1.4

## Context

The receiving application must:
- show the live waveform with beat marks, the heart rate, the signal quality, the signal status, the device state, the data source and the intended-use statement (FB-11);
- record sessions in WFDB format (FB-03);
- replay reference records and recorded sessions as if they came from the device (FB-15);
- accept a serial or network test input (F3.11);
- connect to the device over Bluetooth LE (Milestone 4).

It must run the same real-time signal processing as the device ([ADR 0002](0002-portable-cpp-dsp-library.md)), on the common desktop operating systems. The first user-interface milestone (Milestone 3) has no hardware, so replay must work on its own.

## Options considered

1. **Web application** (browser, Web Bluetooth, Web Serial). Easy to distribute. However:
   - linking the C++ library would need WebAssembly;
   - Bluetooth and serial access in browsers varies by browser and operating system.
2. **Mobile application.** Good Bluetooth LE support. However:
   - one platform per operating system;
   - no simple serial or network test input;
   - a larger testing effort.
3. **Python desktop application** (e.g. Qt for Python). Quick to build, but it would either:
   - need bindings to the C++ library; or
   - run the Python reference in real time, which is not the real-time implementation.
4. **C++17 desktop application with Qt 6.**
   - It links the C++ library directly.
   - It runs on Windows, macOS and Linux.
   - Its modules cover Bluetooth LE (central role), serial ports and networking.
   - Qt 6 itself requires C++17.
5. **C++ with a lighter toolkit** (e.g. an immediate-mode user interface). Smaller, but without integrated Bluetooth LE, serial and networking modules.

## Decision

Option 4: a C++17 desktop application with Qt 6, in `desktop/`, with the following rules.

- **Replay** is part of the application. A replayed record or session enters as a stream with the content and timing of the device stream, and follows exactly the live processing path (`architecture.md` §3.1, §4.3). The data source is always shown, and recordings of replayed or test data are marked (RC-015, OP-037).
- **Logic is separated from the user interface** (`architecture.md` §6.2):
  - a Qt-free `core`, tested on the host;
  - Qt-dependent `io` adapters;
  - a `ui` layer that only renders snapshots of the core state.
- **Licensing.** Only Qt modules available under the LGPL-3.0 are used, linked dynamically. Modules offered only under GPL or commercial terms are not used, so the waveform is drawn by the application.
- **Test input.** The serial and UDP test input is off by default. UDP listens on the local host only unless the user changes it. The application states that the test input is never used with a worn device (OP-038).
- **Not decided yet: the user-interface technology** (Qt Widgets or Qt Quick/QML), OP-033, decided before the user-interface requirements of Milestone 3. The criteria:
  - rendering cost and smoothness of a continuously scrolling 360 Hz waveform;
  - testability of the view logic;
  - clear, always-visible safety-related elements (usability.md §1.4);
  - accessibility;
  - build and deployment effort on the three operating systems.

## Consequences

**Positive**
- The desktop application and the device run the same signal-processing code.
- The whole chain can be demonstrated and verified without hardware (FB-15, US-9), and replay verifies the live path (OP-007).
- One code base for Windows, macOS and Linux.

**Negative and risks, with mitigations**
- **Qt is a large SOUP item.** Its known anomalies must be reviewed, and the LGPL obligations met: dynamic linking, licence notices, the possibility for the user to relink. Mitigations: an entry in [`soup.md`](../regulatory/soup.md) when Qt is introduced, with the modules used, and a check of each module's licence.
- **Bluetooth LE behaves differently** on each operating system (pairing, permissions, background behaviour). Mitigation: integration tests with the device on each supported operating system (Milestone 4).
- **Replay can be taken for live data** (HAZ-013). Mitigations: the data-source indication (RC-015) and the formative usability evaluation (OP-040).
- **CI cost.** Installing Qt in CI adds build time. Mitigation: a pinned Qt version with caching.
- **WFDB in C++.** The application needs a WFDB reader and writer in C++ (OP-050).
