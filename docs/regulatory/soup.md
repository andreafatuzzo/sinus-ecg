# SOUP list (Software Of Unknown Provenance)

_Inspired by IEC 62304 §8.1.2. Every new runtime dependency must be added here in the same change that introduces it._

| Name | Component | Version constraint | Purpose | Known anomalies reviewed |
|---|---|---|---|---|
| NumPy | dsp | `>=1.26` | Array math for signal processing | TBD |
| SciPy | dsp | `>=1.11` | Filter design and application | TBD |
| wfdb | dsp | `>=4.1` | Reading PhysioNet WFDB records and annotations | TBD |

The review of known anomalies (the "TBD" entries) is tracked as OP-009 in [`open-points.md`](open-points.md). Vulnerabilities found in SOUP are handled as described in [`cybersecurity.md`](cybersecurity.md) §7.

This table lists the **direct** runtime dependencies. The exact resolved versions are in `dsp/uv.lock`. The SBOM generated in CI lists every runtime component, including transitive dependencies (e.g. those of wfdb), with versions and licences ([`cybersecurity.md`](cybersecurity.md) §6).

## Planned SOUP (recorded when introduced)

The components below are chosen in [`architecture.md`](architecture.md) §9 and in the ADRs. Each becomes a row of the table above, with its exact version, in the change that introduces it.

| Name | Component | Milestone | Purpose |
|---|---|---|---|
| ESP-IDF | firmware | M4 (library build checks from M2) | Espressif SDK for the ESP32-S3. Used: ADC continuous-mode driver and ADC calibration, GPIO, NimBLE Bluetooth LE host, task watchdog, and the C and C++ runtime libraries of its toolchain ([ADR 0001](../adr/0001-mcu-and-firmware-framework.md)) |
| FreeRTOS | firmware | M4 | Real-time kernel as shipped and configured by ESP-IDF: tasks, priorities, task notifications |
| Qt 6 | desktop | M3 | Application framework: Core, GUI, Widgets or Quick (OP-033), Bluetooth, Serial Port, Network. LGPL-3.0 modules only, linked dynamically ([ADR 0003](../adr/0003-qt-desktop-application-with-replay.md)) |
| FastAPI | backend | M5 | Web API framework, with its runtime dependencies (e.g. Starlette, Pydantic) and an ASGI server; database and FHIR libraries are chosen at Milestone 5 |

- `libs/sinus-dsp` uses only the C++ standard library of each toolchain. It is recorded with the toolchain when the library is introduced (Milestone 2).
- The WFDB implementation of the desktop application is decided in OP-050. A third-party library would be added here.

## Development tools (not SOUP)

Development-only tools are not part of any software item and are not listed as SOUP (`sdp.md` §7):
- Python: pytest, ruff, mypy, and `cyclonedx-bom`, which generates the SBOM;
- C++ (planned): CMake, the compilers, GoogleTest, clang-format, clang-tidy or cppcheck.

The Python tools are pinned in `dsp/uv.lock` in the `dev` group.
