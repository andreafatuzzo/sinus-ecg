# Firmware

Firmware for the ESP32-S3, in C++17 on ESP-IDF with FreeRTOS. It is planned for Milestone 4, and will provide:

- **Acquisition** at a fixed 360 Hz from the AD8232 front end, through the ADC:
  - the ADC is calibrated;
  - it samples at a higher rate, hardware-timed, and the firmware decimates to 360 Hz.
- **Tasks with explicit priorities** for acquisition, processing and Bluetooth LE transmission, connected by fixed-size ring buffers. Nothing is allocated from the heap after start-up.
- **Processing** with the portable library [`libs/sinus-dsp`](../libs/sinus-dsp/README.md), the same code as in the desktop application.
- **Bluetooth LE GATT streaming** with packet sequence numbers and a sample counter, so that the receiver detects every lost sample.
- **Supervision:** watchdog, explicit device state (normal, low battery, error) and low-battery handling.
- **Host testing:** the logic that does not depend on the hardware (packetizer, state machine) is built and tested on a computer, in `tests/{unit,requirements,system}/` ([ADR 0004](../docs/adr/0004-test-tagging-and-traceability-gates.md)).

Later, after Milestone 6: an ADS1293 front end with a register-level SPI driver (OP-042).

Design: [`architecture.md`](../docs/regulatory/architecture.md) §6.1, [ADR 0001](../docs/adr/0001-mcu-and-firmware-framework.md) and [ADR 0005](../docs/adr/0005-device-sampling-rate-360-hz.md).

⚡ The device must run only on battery power while electrodes are attached to a person. Never connect it to USB, a charger, or mains-powered equipment while it is worn, including for flashing, debugging or a serial console.

_Build and flash instructions will be added with the first code (Milestone 4)._
