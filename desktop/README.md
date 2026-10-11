# Desktop application

Qt 6 desktop application in C++17. It is planned for Milestone 3 (replay and test input) and extended in Milestone 4 (connection to the device over Bluetooth LE).

> **Not a medical device, not for diagnosis or health decisions.** The application shows this statement at all times.

Current state (Milestone 3 in progress): the build, the identity (`sinus-desktop --version`) and an empty main window. The application does not process or show any signal yet.

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
- **User-interface technology:** Qt Widgets, with the waveform drawn by the application ([ADR 0009](../docs/adr/0009-qt-widgets-with-own-waveform-drawing.md)).
- **Licensing:** only Qt modules available under the LGPL-3.0 are used.
- **Tests:** in `tests/{unit,requirements,system}/` ([ADR 0004](../docs/adr/0004-test-tagging-and-traceability-gates.md)).

| Folder | Content |
|---|---|
| `src/core` | C++17 and the library only: no Qt header, no Qt link |
| `src/io` | Qt Core and Qt Network |
| `src/ui` | Qt Widgets |
| `src/app` | `main.cpp`: wiring and command line |
| `tests/unit` | developer's unit tests (GoogleTest) |
| `tests/requirements`, `tests/system` | requirement and system tests |
| `qt/` | the pinned Qt version, the SHA-256 lists of its archives, the install script |
| `cmake/` | flags, Qt version check, identity, SBOM |

Design: [`architecture.md`](../docs/regulatory/architecture.md) §6.2, [`architecture-m3.md`](../docs/regulatory/architecture-m3.md) §15 and [ADR 0003](../docs/adr/0003-qt-desktop-application-with-replay.md).

⚡ A worn device is connected to this application only over Bluetooth LE. Never connect a worn device to the computer with a cable. The test input is only for sources that are not worn.

## Qt

`qt/version.txt` holds the exact Qt version. Install it with the pinned aqtinstall of `tools/cpp`, from the repository root, into a folder outside the repository:

```sh
uv run --project tools/cpp python desktop/qt/install_qt.py --dest <folder>
```

The script keeps the archives that aqtinstall downloads and checks them against `qt/<version>-<host>-<arch>.sha256`; a missing, extra or changed archive fails it. It installs `linux_gcc_64` on Linux and, on Windows, Qt's LLVM-MinGW build with the LLVM-MinGW toolchain that Qt names, and prints `qt-prefix=` (and `toolchain-bin=` on Windows).

## Build and test

From `desktop/`, with the tools of `tools/cpp` (`uv run --project ../tools/cpp ...`), Qt's prefix in `CMAKE_PREFIX_PATH` and, on Windows, the toolchain's `bin` folder and Qt's `bin` folder on `PATH`:

```sh
cmake --preset release            # also: debug, asan-ubsan (Linux), coverage (GCC), tidy
cmake --build --preset release
ctest --preset release            # the tests use the offscreen platform
build/release/sinus-desktop --version
```

The configuration stops when the Qt found is not the pinned version; `-DSINUS_DESKTOP_ALLOW_OTHER_QT=ON` accepts another one for local exploration, and the identity then says so.
