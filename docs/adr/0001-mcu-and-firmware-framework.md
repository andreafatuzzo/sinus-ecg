# ADR 0001: MCU and firmware framework: ESP32-S3, ESP-IDF with FreeRTOS, C++17

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** project owner (decision; closes OP-002 and OP-003); tech lead (rationale, consequences, mitigations)
- **Related:** OP-014, OP-023, OP-035, OP-036, OP-038, OP-042, OP-043, OP-047; HAZ-005, HAZ-011, HAZ-012; [ADR 0002](0002-portable-cpp-dsp-library.md), [ADR 0005](0005-device-sampling-rate-360-hz.md); [`architecture.md`](../regulatory/architecture.md) §3.1, §6.1

## Context

The worn device (Milestone 4) must:
- acquire a single-lead ECG at a fixed rate of 360 Hz ([ADR 0005](0005-device-sampling-rate-360-hz.md)), on battery only;
- supervise its own state (battery, faults, watchdog);
- stream the samples to the desktop application over Bluetooth LE with packet sequence numbers;
- run the portable real-time library in its processing task ([ADR 0002](0002-portable-cpp-dsp-library.md), `architecture.md` §3.1).

The first front end, the AD8232, has an analog output, so the microcontroller's ADC is in the signal path. A later front end, the ADS1293, is read over SPI (OP-042).

The firmware logic that does not touch hardware (packetizer, state machine) must be testable on a computer.

## Options considered

1. **nRF52840 with Zephyr** (C or C++).
   - Advantages:
     - very low power in Bluetooth LE;
     - a good ADC for its class (12-bit, with hardware oversampling);
     - Zephyr's device model and host simulation.
   - Drawbacks: a single Cortex-M4F core at 64 MHz with 256 KB of RAM, which leaves less headroom for running the real-time chain next to acquisition and the radio.
2. **ESP32-S3 with ESP-IDF and FreeRTOS, in C++17.**
   - Advantages:
     - two Xtensa LX7 cores at up to 240 MHz with a single-precision floating-point unit, 512 KB of SRAM and Bluetooth LE 5;
     - ESP-IDF is open source (Apache-2.0) and maintained by the vendor. It provides the drivers used here: ADC continuous mode with DMA, ADC calibration, the NimBLE Bluetooth LE host, and the task watchdog;
     - FreeRTOS provides tasks with explicit priorities, queues, stream buffers and task notifications;
     - official container images make firmware builds in CI reproducible;
     - low-cost boards with a LiPo charger are widely available.
   - Drawbacks: a noisier, less linear ADC, and a higher current draw than option 1.
3. **ESP32-S3 with Zephyr.** The same chip, with fewer vendor-maintained drivers for its ADC and radio.

## Decision

Option 2.
- **Hardware and SDK.** ESP32-S3, with ESP-IDF and its FreeRTOS. The ESP-IDF version is pinned, and CI builds with its official container image.
- **Language.** The firmware is written in **C++17**, not C, so that it links the portable library directly and shares its types (ADR 0002).
- **C++ settings.** Exceptions and RTTI are disabled, and nothing is allocated from the heap after start-up.
- **Structure** (`architecture.md` §6.1):
  - hardware adapters that depend on ESP-IDF;
  - a core that does not, built and unit-tested on the host;
  - acquisition, processing, transmission and supervision tasks with explicit priorities, connected by fixed-size ring buffers.
- **Bluetooth.** The Bluetooth LE host is NimBLE, the ESP-IDF component for Bluetooth LE only.
- **ADC.** The AD8232 output is read by ADC unit 1 in continuous mode.

## Consequences

**Positive**
- Enough processing headroom to run the full real-time chain on the device next to acquisition and the radio. Device and desktop use one implementation, and the device build is checked on real signals (`architecture.md` §3.1).
- Hardware-timed sampling through DMA, which keeps sampling jitter low (OP-014).
- Reproducible firmware builds in CI; firmware logic tested on the host.

**Negative and risks, with mitigations**
- **ADC linearity and noise.** The ADC is the weakest part of the first prototype's signal path:
  - its reference voltage varies from chip to chip (1000–1200 mV around a design value of 1100 mV);
  - its response is not perfectly linear, especially towards the ends of each attenuation range;
  - its readings are noisy, and radio activity can add noise.

  Mitigations:
  1. Per-chip calibration with the ESP-IDF ADC calibration driver (factory calibration data), to convert raw codes to mV.
  2. A front-end design that keeps the AD8232 output in the central, most linear part of the chosen attenuation range, and a bypass capacitor at the ADC input (hardware design, Milestone 4).
  3. Hardware-timed sampling at an integer multiple of 360 Hz, decimated with an anti-aliasing filter. Averaging reduces the ADC noise ([ADR 0005](0005-device-sampling-rate-360-hz.md)).
  4. Digital conditioning (baseline, mains, low-pass), and a signal quality index that marks unusable windows so that no heart rate is shown from them (RC-007).
  5. Bench measurement of the noise floor and of linearity with an ECG simulator, with the radio active, reported in the Milestone 4 verification report.
  6. The second front end (ADS1293, a 24-bit converter read over SPI) removes the microcontroller's ADC from the signal path (OP-042).
- **Power.** The ESP32-S3 draws more current than the nRF52840 while streaming, so a session on a given battery is shorter. Mitigations: CPU frequency scaling and light sleep between DMA frames, and a battery sized for the target session duration (OP-023); low-battery handling (OP-035, HAZ-011).
- **Two cores.** Two cores make data races possible. Mitigations: single-producer single-consumer ring buffers, tasks pinned to cores, and host tests of the core logic.
- **Dependence on ESP-IDF interfaces.** Mitigations: the ESP-IDF calls are confined to the adapters; the core and the portable library have no ESP-IDF dependency.
- **C++ on a microcontroller.** Code size and the discipline needed without exceptions or heap. Mitigations: the constraints of `architecture.md` §5.1 and §6.1; coding standard and static analysis (OP-043).
- **USB port and debug interfaces.** The ESP32-S3 has a USB port and debug interfaces. Battery-only operation while worn is a hardware property (HAZ-005, RC-006): the charging concept and wired links are decided in OP-024 and OP-038, and debug interfaces in release builds in OP-047.

**Follow-up**
- Add ESP-IDF, FreeRTOS and the toolchain's runtime libraries to [`soup.md`](../regulatory/soup.md) when the firmware is introduced (Milestone 4).
- The firmware requirements (Milestone 4) cover watchdog, device state and low battery (OP-035, OP-036).
