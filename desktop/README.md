# Desktop application

Qt 6 desktop application in C++17. It is planned for Milestone 3 (replay and test input) and extended in Milestone 4 (connection to the device over Bluetooth LE).

> **Not a medical device, not for diagnosis or health decisions.** The application shows this statement at all times.

## Planned functions

- **Live view:**
  - conditioned waveform with detected beats marked;
  - heart rate, signal quality and signal status;
  - device state and data source.

  There are no alarms, sounds or judging labels.
- **Replay mode:** a MIT-BIH record or a recorded session is played as if it came from the device, at its original rate. Records come from the local copy downloaded and verified by `dsp/`. The screen always shows that the data is replayed, and from which record.
- **Recording:** sessions are saved in WFDB format. Recordings of replayed or test data are marked as such.
- **Test input:** a serial or UDP input for tests without hardware, off by default, and never for a device worn by a person.
- **Signal processing:** it uses the portable library [`libs/sinus-dsp`](../libs/sinus-dsp/README.md), so the processing is the same as on the device.

## Structure

- **Logic separated from the user interface.**
  - A Qt-free `core`: stream model, sources, processing, signal status and heart-rate display rules. It is tested on its own with GoogleTest.
  - Qt adapters for Bluetooth LE, serial, UDP and files.
  - A `ui` layer that only renders.
- **User-interface technology:** Qt Widgets or Qt Quick, still to be decided (OP-033).
- **Licensing:** only Qt modules available under the LGPL-3.0 are used.
- **Tests:** in `tests/{unit,requirements,system}/` ([ADR 0004](../docs/adr/0004-test-tagging-and-traceability-gates.md)).

Design: [`architecture.md`](../docs/regulatory/architecture.md) §6.2 and [ADR 0003](../docs/adr/0003-qt-desktop-application-with-replay.md).

⚡ A worn device is connected to this application only over Bluetooth LE. Never connect a worn device to the computer with a cable. The test input is only for sources that are not worn.

_Build and run instructions will be added with the first code (Milestone 3)._
