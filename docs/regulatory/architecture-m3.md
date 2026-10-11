# Software architecture: Milestone 3 design

_Part of the software architecture of Sinus. [`architecture.md`](architecture.md) holds the general architecture (§1 to §7 and §9 to §12) and the version, status and revision history of every part. Section numbers are those of the whole architecture: a reference such as §6.2 points to `architecture.md`, §8 to [`architecture-m1.md`](architecture-m1.md), §13 and §14 to [`architecture-m2.md`](architecture-m2.md)._

This file holds three sections, written in this order:
- **§15, Milestone 3 architecture of the desktop application** (this version): structure, threading, data flow, the stream frame format, the outline of each function, build, CI, tests, the feasibility of SRS-044 and the implementation plan;
- **§16, display low-pass and mains tolerance** (next version): the detailed design of SRS-044 in `dsp` and `libs/sinus-dsp` and of SRS-054 in `dsp`;
- **§17, detailed design of the desktop application** (the version after): SRS-039 to SRS-043 and SRS-045 to SRS-053, module by module, on the structure fixed here.

## 15. Milestone 3 architecture of the desktop application

This section refines §6.2 for `srs.md` v0.9 (SRS-039 to SRS-054) and the decisions of the project owner of 2026-10-11, including [ADR 0009](../adr/0009-qt-widgets-with-own-waveform-drawing.md) (Qt Widgets with a waveform drawn by the application; OP-033 closed). It fixes what the detailed design of §16 and §17 builds on. The interfaces below are named, with their responsibilities; their exact signatures, parameters and edge cases are §17.

What holds unchanged: §3.1 (the desktop application is the only item that produces real-time results for the user, with the library chain); §4.2 (units, time base, continuous segments, data source with every frame); §5 (the library is linked, never copied); ADR 0003, ADR 0004, ADR 0006, ADR 0007.

### 15.1 Decisions of this section

| Decision | Decided by | Where |
|---|---|---|
| Qt Widgets, waveform drawn by the application with `QPainter`; no chart module, no third-party plotting library (OP-033 closed) | Project owner, 2026-10-11 (ADR 0009) | §15.7 |
| Qt 6.12, one exact patch version pinned, updated once per milestone; modules Core, GUI, Widgets, Network in M3 (Serial Port and Bluetooth in M4); Qt Test for tests only | Project owner, 2026-10-11 | §15.14 |
| No binary distribution in M3 (source only); licence notices, deployment and the offer of the Qt source come with the first binary release | Project owner, 2026-10-11 | §15.14 |
| Windows and Linux built and tested; macOS not built (OP-080) | Project owner, 2026-10-11 | §15.14 |
| Windows toolchain: Qt's LLVM-MinGW build if Qt 6.12 ships one, otherwise Qt's MinGW 15.1 build with its toolchain | Project owner, 2026-10-11 | §15.14 |
| Qt installed in CI by aqtinstall, its archives checked against a committed list of SHA-256 digests | Project owner, 2026-10-11 | §15.14 |
| Own minimal WFDB reader and writer, verified against the Python reference reader (OP-050) | Project owner, 2026-10-11 | §15.9, §15.11 |
| `desktop/VERSION` and a source digest, shown in the About box, `--version`, recordings and the log (OP-076, desktop part) | Project owner, 2026-10-11 | §15.12 |
| CycloneDX SBOM from the build; the known anomalies of Qt reviewed by hand from its security advisories (OP-075, desktop part) | Project owner, 2026-10-11 | §15.12 |
| Development tools moved from `libs/sinus-dsp/tools` to a repository-level `tools/cpp/`; one `.clang-format` and a base `.clang-tidy` at the repository root | Tech lead (part of this version's approval) | §15.2 |
| Sweep display; start-up detections drawn as hollow marks | Tech lead (SRS-043 leaves sweep or scroll to the design; the display of start-up marks is a design choice) | §15.7 |
| Frame format version 1 of the sample stream (IF-5 now, the sample frames of IF-4 in M4) | Tech lead (cited by SRS-042) | §15.4 |
| Display low-pass: linear-phase FIR, Hamming-windowed sinc, cut-off 50 Hz, half-length 30 ms | Tech lead (feasibility of SRS-044) | §15.17, detailed in §16 |

### 15.2 Layout of `desktop/` and the shared tools

```
.clang-format              # one copy for every C++ item (moved from libs/sinus-dsp/, unchanged content)
.clang-tidy                # base configuration of ADR 0007 (moved from libs/sinus-dsp/)
tools/cpp/                 # uv project pinning the C++ development tools (moved from libs/sinus-dsp/tools/), plus aqtinstall
libs/sinus-dsp/
  .clang-tidy              # InheritParentConfig: true, the library's own additions only
  cmake/SourceDigest.cmake # generalised: item root and folder list as arguments (§15.12)
desktop/
  CMakeLists.txt  CMakePresets.json  README.md
  VERSION                  # one line, the version of the milestone register (§15.12)
  .clang-tidy              # InheritParentConfig: true, the desktop adaptations (§15.15)
  cmake/                   # Flags.cmake, QtPin.cmake (version check), Sbom.cmake, sbom.cdx.json.in
  qt/                      # version.txt (the exact Qt version), <version>-<host>-<arch>.sha256 (archive digests), install script
  src/
    core/                  # C++17 and libs/sinus-dsp only; no Qt header, no Qt link
    io/                    # Qt Core and Qt Network: UDP test input, worker threads, settings
    ui/                    # Qt Widgets: main window, bars, waveform widget, panels, About box
    app/                   # main.cpp: wiring, command line (--version)
  tests/
    support/               # GoogleTest main with a QApplication on the offscreen platform; fixture and fake-clock helpers
    fixtures/              # small WFDB records generated by a committed script with Python wfdb (§15.16)
    unit/                  # developer
    requirements/          # QA
    system/                # test engineer
```

- **Core without Qt.** `sinus_desktop_core` is a static library that links only `sinus::dsp` and the C++ standard library; it is built without Qt include folders, so a Qt include in `core` fails to compile. Every rule that decides a result, a status, a text or a position on the screen is in `core` (§6.2); `io` and `ui` adapt it to Qt.
- **Tools.** `libs/sinus-dsp/tools` moves to `tools/cpp/` (same pins, plus `aqtinstall`), with one lock for the library, the desktop and later the firmware's host tests. The move changes no file of `libs/sinus-dsp/include` or `src`, so the library's digest and results do not change; the `libs` and `libs-esp32s3` jobs change their `--project` path. The root `.clang-format` keeps the content of the library's file; the library's `.clang-tidy` keeps every check it has today, split into the root base and its own additions.
- **Identity inputs.** The source digest of the desktop application covers `desktop/src` (§15.12); tests, CMake files and tools are outside it, as for the library.

### 15.3 Building against the library

- `desktop/CMakeLists.txt` (CMake ≥ 3.25, run by the pinned CMake of `tools/cpp`) adds the library with `add_subdirectory(../libs/sinus-dsp sinus-dsp EXCLUDE_FROM_ALL)` and links `sinus::dsp`. The library is then not the top-level project, so its tests are off, and `EXCLUDE_FROM_ALL` builds only what the desktop links: the verification code and the harness are not built. The library target keeps its own flags (`-ffp-contract=off`, no exceptions, no RTTI, its warnings), whatever the desktop sets (§14.2). No library source is copied (§5.3).
- The desktop application uses the library's public headers only (`include/sinus/dsp/`), through `Chain` (§14.4), with the display output added by §16.
- `find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network)`, `qt_standard_project_setup()`, AUTOMOC on the `io` and `ui` targets only. Qt Test is found only when the tests are built.
- Targets: `sinus_desktop_core` (static, no Qt), `sinus_desktop_io`, `sinus_desktop_ui` (static, Qt), the executable `sinus-desktop`, and the test executables of §15.16.
- **Qt version check.** `cmake/QtPin.cmake` compares `Qt6_VERSION` with `desktop/qt/version.txt` and stops the configuration on a difference, unless `SINUS_DESKTOP_ALLOW_OTHER_QT=ON` (local exploration only, stated in the identity of the build, §15.12; CI never sets it).

### 15.4 Stream frame format, version 1 (IF-5; sample frames of IF-4)

The test input (SRS-042) receives one frame per UDP datagram. The same layout carries the samples of the device stream in Milestone 4 (IF-4), where further frame types (device state, device-side results, §3.1) are added with new type codes; the replay (§15.9) produces the same frames in memory, without encoding them.

All fields are little-endian; there is no padding; a decoder copies each field out of the byte buffer (no casts of the buffer).

| Offset | Size | Field | Rule (version 1) |
|---|---|---|---|
| 0 | 4 | `magic` | ASCII `SNSF` (0x53 0x4E 0x53 0x46) |
| 4 | 1 | `version` | 1 |
| 5 | 1 | `type` | 1 = sample frame (the only type of Milestone 3) |
| 6 | 1 | `source` | data source tag: 1 = device, 2 = test input. 0 and 3 to 255 are invalid on the wire; the replay's frames carry tag 3 in memory only |
| 7 | 1 | `reserved0` | 0 |
| 8 | 2 | `sample_count` n | 1 to 64 |
| 10 | 2 | `reserved1` | 0 |
| 12 | 4 | `stream_id` | chosen by the sender when it starts a stream; any value. A new value is a new stream |
| 16 | 8 | `first_sample` | sample counter of the first sample of the frame, in the time base of the stream (§4.2), starting at 0 |
| 24 | 4 | `sequence` | frame number in the stream: 0 for the first frame, +1 per frame, modulo 2³² |
| 28 | 4 | `fs_millihertz` | sampling frequency in mHz, 125 000 to 1 000 000 (SRS-003) |
| 32 | 4 | `flags` | 0 in Milestone 3; electrode contact in Milestone 4 (OP-078) |
| 36 | 4·n | `samples_mv` | n samples, IEEE 754 binary32, in mV, each finite and at most 1000 mV in magnitude |
| 36 + 4·n | 4 | `crc32` | CRC-32 of bytes 0 to 35 + 4·n: the CRC of IEEE 802.3 and zlib (reflected polynomial 0xEDB88320, initial value and final XOR 0xFFFFFFFF; check value 0xCBF43926 for the ASCII string `123456789`) |

- **Size.** A frame has 40 + 4·n bytes, 44 to 296. Senders use n = ⌊fs / 20 + 0.5⌋ samples (50 ms; 18 at 360 Hz, 13 at 250 Hz) unless a test needs another size; receivers accept any n from 1 to 64.
- **Malformed datagram** (SRS-042): a length other than 40 + 4·n for the n it states, or shorter than 44; any field outside its rule; a wrong CRC; a sample that is not finite or exceeds 1000 mV in magnitude. It is rejected whole, counted under its reason, and given to nothing; it does not change the expected sequence number, so a malformed datagram sent in addition to a valid stream starts no segment.
- **Continuity.** A frame continues the current segment when it has the `stream_id`, `source` and `fs_millihertz` of the previous accepted frame, `sequence` = previous + 1 (mod 2³²) and `first_sample` = previous `first_sample` + previous n. Otherwise:
  - a later `sequence` or a jump of `first_sample` in the same stream is a gap of lost frames: a new continuous segment starts with this frame (SRS-031, SRS-042, SRS-047; RC-014);
  - an earlier or repeated `sequence` in the same stream (out of order, duplicate) is dropped and counted; the frames after it were already handled as a gap when the missing one did not arrive in order;
  - a new `stream_id` or sampling frequency starts a new segment (with the chain configured again for a new frequency).
- **Source tag.** A frame whose tag is not that of the current source is dropped and counted before it reaches continuity or the library (SRS-041).
- **Byte order and floats.** Both the device (Xtensa, little-endian) and the computers used are little-endian; the codec still assembles values from bytes, so it does not depend on the host. Encoding and decoding are pure functions of `core` (`encode_frame`, `decode_frame` returning a result with the reason of a rejection), tested without a socket.

### 15.5 Threading and data flow

```
 Source threads                     Processing thread (core)                         GUI thread (ui)
 ReplaySource (core, paced by Clock) ─┐                                               QTimer, about 30 Hz
 UdpTestInput (io, own QThread)    ───┼─▶ FrameQueue ─▶ StreamProcessor ─▶ SnapshotExchange ─▶ views paint the latest snapshot
 DeviceSource (io, M4)             ───┘   (bounded,       │  source tag check, continuity, segments       (copy under a mutex)
                                           SPSC, drops    │  Chain per segment (+ display output, §16)
                                           and counts)    │  display model, marks, signal status,
                                                          │  heart-rate display, quality mark, counters
                                                          └─▶ RecordingQueue ─▶ recorder thread (WFDB writer, §15.11)
 GUI commands (start, stop, pause, resume, source, mains, record) ─▶ CommandQueue ─▶ StreamProcessor (between frames)
```

- **One source interface** in `core`: start with a frame sink, stop; the replay adds pause and resume (SRS-039). Every source emits the same `Frame` (§15.4 content, plus the time of receipt on the application clock, which is not on the wire). Only one source is active (SRS-041): changing the source stops the first and resets the processing.
- **`FrameQueue`**: a bounded single-producer single-consumer ring of frames in `core`, allocated when the source starts (capacity 256 frames, about 12 s at 360 Hz). A full queue drops the new frame and counts it; the next accepted frame is then a gap (§15.4), as on the device (§6.1). Overload is therefore a tested rule of `core`, never a growing queue.
- **`StreamProcessor`** (core) is single-threaded and deterministic: it takes frames, commands and clock ticks, and keeps all the state of §15.6 to §15.8. A thin `ProcessingWorker` runs it on its own thread, waking on a frame or every 50 ms (time-based rules, §15.8). Tests drive `StreamProcessor` directly, without threads.
- **`Clock`** (core): `now()` on a monotonic time base, and `wait_until()`. The application uses `std::chrono::steady_clock`; tests use a `FakeClock` that advances only when told, so that a 30 min record is replayed in milliseconds through the same code (SRS-039 pacing, SRS-045 and SRS-047 timing).
- **Snapshots.** After each batch of frames, and at each tick, the processor publishes a `Snapshot` (display window, marks, heart-rate text and reason, status and reason, quality mark, source banner data, counters, the mapping from samples to times of acquisition) into `SnapshotExchange` (latest value, copied under a mutex). The GUI copies it at its refresh and does no processing; the position of the drawn edge is computed at paint time from the clock (§15.7).
- **Commands** from the GUI go through a `CommandQueue` (mutex) and are applied between two frames, so that a command takes effect at a defined sample (SRS-041, SRS-050: reset at the change).
- **Results tap.** `StreamProcessor` gives every per-sample output of the chain to an optional `ResultSink`. The system test of SRS-040 uses it to compare the application's results with the library run directly; nothing else in Milestone 3 uses it (later: the upload of derived data, M5).
- **Memory.** `core` allocates when a source starts or a segment starts, never per sample; the library chain has its own fixed memory (SRS-032).

### 15.6 Processing per continuous segment

- One `sinus::dsp::Chain` per application, configured with the sampling frequency of the stream and the mains frequency in use (SRS-050); `reset()` at the start of each continuous segment (SRS-031), `configure()` again when the frequency changes. A reset happens: at a gap (§15.4), after an interruption (SRS-047), at a source change (SRS-041), at a change of the mains setting (SRS-050), and at every start of a replay (SRS-039).
- **Session time base.** The library counts samples from 0 in each segment. The processor maps them to the session time base (sample index of the session, §4.2): segment start + library index. Detections, heart-rate events and windows are kept in session indices; never compared or joined across a segment boundary (RC-014).
- **Mains frequency in use.** The setting (50 Hz at every start, SRS-050) for the test input; 60 Hz for a replay of a record of the MIT-BIH Arrhythmia or Noise Stress Test databases, recognised as such by the verified local copy (§15.9); the stored value for a replay of a recorded session (SRS-051).

### 15.7 Display pipeline (SRS-043, SRS-044)

- **Display values** come from the library's display output (§16): the conditioned signal through the display low-pass, a separate output that feeds nothing else (SRS-044). Its constant delay of M samples (M = 11 at 360 Hz, 8 at 250 Hz, §15.17) is compensated exactly: the display value produced at sample k belongs to index k − M.
- **Display model** (core): a ring of the last 10 s plus margin in session indices, each entry a display value or "no data". Samples lost in a gap and the stretch of an interruption are "no data" and are drawn as nothing: a trace is never joined across a gap (HAZ-012).
- **Delay of 0.5 s.** At each paint, the right end of the drawn data is the latest index whose time of acquisition is at most `now − 0.5 s`. The time of acquisition of a sample is the time of receipt of its frame (the release time for a replay), minus the time of the samples after it in the frame at the stream rate; the snapshot carries this mapping per frame. The drawn edge stops at the last received sample when data stops. The 0.5 s is on the application clock, also at replay speeds above 1.
- **Sweep.** The window shows the last 10 s of the session time base at fixed positions: the horizontal position of index i is (i mod W) for a window of W = 10·fs samples; a vertical cursor at the drawn edge moves left to right and overwrites the oldest data. The trace stands still, so a mark added later appears at a fixed place on the trace, and only the cursor moves. When there are more samples than pixel columns, each column draws the minimum and maximum of its samples (no sample is skipped).
- **Marks.** Each detection of the library is a mark at its index. A mark is drawn when its index lies within the drawn window, up to the drawn edge. Reported within 0.35 s (SRS-021), it is already known when the trace reaches its index and appears with its R peak; reported later (search-back, up to the maximum delay of SRS-021), it is added onto the trace already drawn, at its index. A mark that would be drawn for the first time while the signal status is not usable is never drawn; a mark already drawn stays (SRS-043). Marks are cleared at a change of source (SRS-041).
- **Start-up detections** (SRS-022) are drawn as hollow triangles and reliable detections as filled triangles above the trace: the distinction is by shape, not by colour. Start-up detections are not used by the heart rate (SRS-024), and the hollow mark says so without hiding what the detector found.
- **The text "REPLAY"** is drawn in the waveform area while a replay is the source (SRS-041).
- The **waveform widget** (ui) only paints the snapshot: it computes nothing but pixel positions from the window, the edge and the marks given by `core`. The drawing input (positions of trace columns and marks, the edge) is a `core` function, so SRS-043 is verified "on the data given to the drawing" without Qt.

### 15.8 Signal status, heart rate and quality mark (outline of SRS-045 to SRS-048)

Pure state machines in `core`, stepped by the processor with each sample's outputs and with clock ticks; the GUI shows their texts.

- **Signal status** (SRS-045): usable only when the latest quality window is marked usable, a sample arrived within the last 1 s on the application clock, and the source is playing. Otherwise not usable, with the first applicable reason of the list of SRS-045; "checking signal quality" from the start of a stream or a reset until the first window. **Reading of "samples arrive" for a replay:** the 1 s rule applies while the source is playing; while the replay is paused or ended the reason is "replay paused" or "replay ended", and the 1 s rule does not run (the pause is not an interruption, and resume continues the segment, SRS-039).
- **Heart-rate display** (SRS-046): the latest library event, rounded to a whole bpm; "--" with the reason in words otherwise; withheld while the status is not usable, and afterwards until 4 intervals between reliable detections whose index lies after the sample at which the status became usable. The previous value is never kept for display once withheld.
- **Interruption** (SRS-047): no sample for 1 s → "data interrupted"; the next sample starts a new segment; a gap under 1 s starts a new segment without the indication.
- **Quality mark** (SRS-048): the text of the latest window, refreshed within 1 s of its report.
- All times are measured on the `Clock`; the bounds "within 2 s", "within 7 s", "within 1 s" are met by the 50 ms tick of the processor and the GUI refresh, and are verified with the fake clock.

### 15.9 Replay (SRS-039, SRS-040)

- **Reader.** Own minimal WFDB reader in `core` (OP-050): header (single segment), signal formats 16 and 212, the first stored signal; physical values in mV with the gain and baseline of the header, by the same formula as the offline loader of SRS-002 (§8.4), in binary64, then rounded once to binary32 for the stream. A strict reader: anything outside this subset, a truncated signal file and a record of 0 samples are rejected with a message naming the cause (SRS-039). The comment lines of a recorded session give its metadata and events (§15.11).
- **Reference records.** A record of the MIT-BIH Arrhythmia or Noise Stress Test databases is replayed from the local copy that `dsp` downloaded and verified (§6.2, IF-1). The replay checks the record's files against the checksum list `SHA256SUMS.txt` of that copy, itself checked against the digest pinned for the database version (§8.3), before it starts; a verified record gets the mains frequency of 60 Hz and its database name in the banner (SRS-050, SRS-041). How another WFDB record (neither a reference record nor a recorded session) gets its mains frequency is OP-083.
- **Pacing.** `ReplaySource` (core) releases frames of n = ⌊fs / 20 + 0.5⌋ samples. Frame j, whose last sample has index L within the replay, is released at t₀ + (L + 1) / (fs · speed) on the `Clock`, computed from the start and never accumulated, so no drift builds up (SRS-039: 60 s within 1 %). A pause stops the releases and moves t₀ by the paused time; resume continues with the next sample, in the same segment. Speed and start position are set before the start; a change is a stop and a new replay (a new segment).
- **Content.** The replay's frames carry tag 3 (replay), the record or session name and the speed for the banner; a recorded session with gap events is replayed with the same gaps (a jump of the sample counter at each gap event), so that a replay of a recording starts the same segments as the session.
- **End.** After the last sample the replay stops and the status becomes "replay ended" (SRS-039, SRS-045).
- **Headless replay** (SRS-040): the same `ReplaySource` and `StreamProcessor` with a `FakeClock` and a `ResultSink`, without `io` or `ui`; the test engineer's test compares its results with those of a `Chain` given the same samples directly (§15.16).

### 15.10 Test input (SRS-042)

- `UdpTestInput` (io) owns a `QUdpSocket` in its own thread, bound to the IPv4 loopback address only (`127.0.0.1`), on a port shown in the banner (default and range: §17). The socket is not created until the user turns the input on; it is off at every start of the application.
- Every datagram is checked for a loopback sender address before decoding; any other sender is counted and dropped. Binding to the loopback address keeps the port unreachable from other addresses of the computer.
- Decoding and every check of §15.4 are `core` functions; `io` only moves bytes.
- While the input is on, the banner reads "TEST INPUT" with the address and port, and the window states that the test input is never to be used with a worn device (SRS-042, OP-038).

### 15.11 Recording (SRS-051, SRS-052)

- **What is recorded.** The samples as given by the source (never the display values), the D7 metadata and the events (gaps with the number of missing samples when the stream counter gives it, interruptions with their duration on the application clock), each at its position in the recorded samples. No sample is invented or left out: the record holds the received samples in order, and a gap is an event, not filler. Detected beats are not saved.
- **Format.** WFDB, one signal, format 16; the metadata and events as header comment lines in a documented `key=value` form (start date and time UTC, sampling frequency, gain, software version and source digest of the desktop application and the library, mains frequency in use, data source, record or session name, mark "replayed" or "test"). A header comment needs no annotation writer and is ignored by the offline loader of SRS-002, which reads the record without conversion.
- **Gain.** For a replayed record or session: its own gain and baseline, so that the round trip is exact. For the test input: 1000 adu/mV (1 µV resolution, ±32.767 mV); a test-input sample beyond that range cannot be stored in format 16 at that resolution, and is a failure of the recording (below) until OP-082 is decided.
- **Writing.** The processor gives the source frames to a `RecordingQueue`; a recorder thread writes them through a buffered writer. The files are written under names that mark them incomplete (`<name>.dat.partial`, `<name>.hea.partial`); at the end the header is written with the sample count, both files are flushed, and they are renamed, the header last. Any write error, a full disk or a full queue stops the recording, reports the failure in the main window, and leaves only the `.partial` files, which the offline loader does not read as a record (RC-020).
- **Identity** in each recording: the comment lines of §15.12 (SRS-052).

### 15.12 Identity and SBOM (SRS-052; OP-075, OP-076)

- **Version.** `desktop/VERSION`, one line, equal to the version of the milestone register (`0.3.0.dev0` while M3 is in progress, `0.3.0` at its release, §8.14). The version rule of `traceability.py` applies to it from the first `desktop/CMakeLists.txt` (§13.12), so both land together.
- **Source digest.** The method of §14.15 over every regular file under `desktop/src` whose path has no component starting with `.`, named by its path relative to the folder that contains the item (here the repository root: `desktop/src/core/frame.cpp`), sorted, CR LF replaced by LF; one line `<sha256>  <name>` per file, then the SHA-256 of the manifest. The library's `SourceDigest.cmake` is generalised (item root and folders as arguments) and run by both items; it is not copied. The same digest from a shell at the repository root:

  ```sh
  find desktop/src -type f -not -path '*/.*' -print0 | LC_ALL=C sort -z \
    | xargs -0 sha256sum --text | sha256sum --text
  ```

- **Where it is stated.** The About box (version and digest of the desktop application and of the library from `library_identity()`, the Qt version used to build and the one loaded at run time (`qVersion()`; the LGPL lets the user replace the Qt libraries), compiler, build type, and whether `SINUS_DESKTOP_ALLOW_OTHER_QT` was set); `sinus-desktop --version` (the same text); the header comments of every recording; the first lines of the application log.
- **SBOM.** `cmake/Sbom.cmake` writes `sbom-desktop.cdx.json`, CycloneDX 1.6, deterministic (no timestamp, no serial number), like the library's (§14.16): metadata component `sinus-desktop` (type `application`, licence `Apache-2.0`, version, digest and build-target properties); components `sinus-dsp` (its version and digest), each linked Qt module (version, `LGPL-3.0-only`, CPE `cpe:2.3:a:qt:qt:<version>:*:*:*:*:*:*:*`) and the C++ runtime of the toolchain. The `desktop` job uploads it. Qt has no package ecosystem in the vulnerability databases that OSV-Scanner reads, so the known anomalies of Qt are reviewed by hand from the Qt security advisories for the pinned version, in `soup.md`.

### 15.13 Fixed elements and accessibility (SRS-041, SRS-049, SRS-053)

- **Top bar.** A non-scrolling area at the top of the main window, outside any scroll area or dock, holds the intended-use statement and the source banner; it has no close control and the window's minimum size keeps it whole. Its font is not smaller than that of the status texts. "REPLAY" and "TEST INPUT" are words, not colours.
- **Texts.** The heart rate, its reason, the signal status and its reason, and the quality mark are text labels whose content comes from `core`. Each has a fixed accessible name ("Heart rate", "Heart rate reason", "Signal status", …); the visible text is exposed through the accessibility interface, and a change of text sends the accessibility notification (`QAccessible::updateAccessibility`), so that a screen reader reads the change (SRS-053). The waveform widget has an accessible name and a description that says what the marks are.
- **No sound, notification or alarm** anywhere in the application (SRS-049); no colour scale, range or judging label (SRS-046).
- The exact names, texts and the accessibility test method are §17.

### 15.14 Build, toolchains, Qt and CI

- **Presets** (`desktop/CMakePresets.json`, Ninja, `build/<preset>`): `debug`, `release`, `asan-ubsan` (Linux), `coverage` (GCC), `tidy`; as for the library (§14.2).
- **Linux.** GCC 14 and Clang 18 of the `ubuntu-24.04` runner, with Qt's `linux_gcc_64` build for Qt 6.12 (built by Qt on Ubuntu 24.04 with GCC 13; the GCC 14 standard library is compatible with it).
- **Windows.** C++ code linked with Qt must use the C++ runtime of the Qt build. The supported Windows compilers listed by the Qt 6.12 documentation are MSVC 2022 and MinGW-w64 15.1; an LLVM-MinGW build is not listed. By the owner's decision the desktop application therefore uses **Qt's MinGW 15.1 build with Qt's MinGW 15.1 toolchain** (installed by aqtinstall as a Qt tool), unless the archive list of Qt 6.12 shows an LLVM-MinGW build when group D3 installs it, in which case that build and its toolchain are used. The library code is the same either way; it keeps building with the local LLVM-MinGW toolchain for its own tests (§14.2). The desktop executable links the C++ runtime dynamically, like Qt (the library's `-static` link option is set in the library's folder only and does not reach the desktop).
- **Qt pinning.** `desktop/qt/version.txt` holds the exact Qt version (6.12.x, the latest patch release when group D3 starts, then updated once per milestone). `desktop/qt/<version>-<host>-<arch>.sha256` lists the SHA-256 of every archive that aqtinstall downloads for the modules used; the install script installs with aqtinstall from `tools/cpp` (which checks the archives against the checksums of the Qt repository) and then checks the downloaded archives against the committed list, so that a changed archive fails the job. The Qt installation is cached with the hash of the list as key.
- **CI jobs** (`.github/workflows/ci.yml`):
  - `desktop` (ubuntu-24.04): tools; Qt install and check; clang-format; GCC 14 `release` build and all tests on the `offscreen` platform; GCC 14 `asan-ubsan` (LeakSanitizer with a committed suppression file for leaks inside Qt and fontconfig, each entry with its reason); Clang 18 `release`; `tidy`; `coverage` summary (gcovr, no threshold); SBOM; the Python cross-checks of the WFDB writer (§15.16); the SRS-040 subset run, with the six records of SRS-016 obtained by the `dsp` download script and its cache (§8.11).
  - `desktop-windows` (windows runner): tools; Qt install and check; the Windows toolchain above; `release` build and all tests on the `offscreen` platform.
  - The project owner adds both to the ruleset of `main` once they are green on `develop`.
  - No executable with Qt libraries is uploaded as an artifact in Milestone 3 (no binary distribution).
- **LGPL.** Qt is linked dynamically and unmodified. The licence texts, the notices of Qt and its third-party parts, the deployment step and the offer of the Qt source are added with the first binary release (owner's decision, 2026-10-11).

### 15.15 Coding rules on the desktop (ADR 0007)

- `core`: every rule of ADR 0007, including no exceptions and no RTTI use; the library's rule "no dynamic memory" becomes "no allocation per sample" (§15.5). Same warnings as the library, `-Werror`, `-ffp-contract=off`.
- `io`, `ui`, `app`: the same formatting, warnings and `-Werror`; Qt headers are included as system headers; exceptions off; **RTTI on** (Qt is built with it, and UBSan's `vptr` check then works). Adaptations, each with its reason in `desktop/.clang-tidy` or in a folder's `.clang-tidy` with `InheritParentConfig`: `cppcoreguidelines-owning-memory` off in `io` and `ui` (Qt objects are owned by their parent and created with `new`); Qt's virtual function names (`paintEvent`) accepted; files generated by `moc` excluded from clang-tidy and built with the relaxed test warnings.
- Units in names (`_mv`, `_hz`, `_s`, `_ms`, `_bpm`, `_samples`), as everywhere (§4.2 conventions).

### 15.16 Tests and traceability

- **Framework.** GoogleTest 1.18.0 (§14.2) for every C++ test, including widget tests. Executables: `sinus_desktop_core_unit_tests` (links `core` only, no Qt: it also proves that `core` needs no Qt), `sinus_desktop_unit_tests`, `sinus_desktop_requirement_tests`, `sinus_desktop_system_tests` (Qt, with the test `main` of `tests/support/` that creates a `QApplication` on the `offscreen` platform). `QTest` event functions and `QSignalSpy` are used as helpers inside GoogleTest tests; Qt Test's own test runner is not used, so the `// Verifies: SRS-nnn` tags work as in ADR 0004 and the traceability script needs no change.
- **Folders** (ADR 0004, ADR 0006): `desktop/tests/unit/` (developer, no tag), `requirements/` (QA), `system/` (test engineer). A requirement whose Software item is `desktop` alone needs its verifying test under `desktop/tests`; SRS-044 needs one in `dsp` and one in `libs/sinus-dsp` (ADR 0006).
- **Fake clock and injected sources.** Requirement and system tests drive `StreamProcessor`, `ReplaySource` and the codec with a `FakeClock` and in-memory frames; the timing criteria of SRS-039 at the real rate (60 s at each speed) are the only tests that use the steady clock.
- **WFDB cross-checks with the Python reference reader** (`wfdb` of `dsp`), as pytest tests under `desktop/tests`, collected by the `dsp` test configuration (`testpaths` gains `../desktop/tests`, as for the library):
  1. read direction: small fixture records (formats 16 and 212, odd sample counts for 212, negative values, gain and baseline) generated by a committed script with Python `wfdb`; a Python test checks that the committed bytes are still those that `wfdb` writes, and the C++ tests compare their reading with the committed expected values exactly;
  2. write direction: a C++ test writes records into the folder named by `SINUS_DESKTOP_WFDB_DIR`; a Python test reads them with the offline loader of SRS-002 and compares exactly. The `desktop` job sets the variable; without it the Python test is skipped with its reason (the precondition rule of §13.12);
  3. reference databases (needs the local databases): the C++ reader on all 48 MIT-BIH records equals the samples of `wfdb`.
- **System tests** (test engineer): SRS-040 (the subset in CI; all the records with the local databases, `needs_data`, and in the milestone verification report), SRS-047 (through the test input), SRS-054 (in `dsp`).

### 15.17 Feasibility of SRS-044

**Criteria** (at 360 Hz and 250 Hz): gain within ±1 dB from 1 to 30 Hz; attenuation ≥ 20 dB from 80 Hz to the Nyquist frequency; group delay varying by at most 20 ms from 1 to 30 Hz, constant and documented; R-wave peak of the synthetic ECG of SRS-006 kept to ≥ 90 %; noise RMS reduced by ≥ 6 dB for white noise in the band from 40 Hz to the Nyquist frequency.

**Filter family: linear-phase FIR.** A symmetric FIR filter of N = 2M + 1 taps has a group delay of exactly M samples at every frequency, so the delay criterion holds with no variation at all, the delay is constant and is compensated exactly on the display (§15.7). Its coefficients are given by a closed formula of the sampling frequency, computed at configuration time in binary64, like the coefficients of the conditioning stages (§14.4).

- **Design:** Hamming-windowed sinc, cut-off f_c = 50 Hz, half-length M = ⌊0.030·fs + 0.5⌋ samples:
  h[k] = w[k] · sin(2π f_c (k − M) / fs) / (π (k − M)) (and 2 f_c / fs at k = M), w[k] = 0.54 − 0.46 cos(2π k / (N − 1)), k = 0 … N − 1, then scaled so that the taps sum to 1 (gain 1 at 0 Hz).
- **Computed response** (pure computation of the formula; gain on a 0.25 Hz grid; noise as the mean of |H|² over the band, the expected ratio for band-limited white noise; R wave as the peak of the Q, R and S waves of §7.2 sampled with the R centre on a sample, before and after the filter):

| fs | N | Group delay | Gain 1–30 Hz | Attenuation from 80 Hz | Noise 40 Hz–Nyquist | R-wave peak kept |
|---|---|---|---|---|---|---|
| 360 Hz | 23 | 11 samples = 30.6 ms, constant | −0.33 dB to 0.00 dB | ≥ 53.6 dB | −13.9 dB | 99.1 % |
| 250 Hz | 17 | 8 samples = 32.0 ms, constant | −0.26 dB to +0.04 dB | ≥ 50.4 dB | −11.6 dB | 99.4 % |
| Criterion | | variation ≤ 20 ms | ±1 dB | ≥ 20 dB | ≤ −6 dB | ≥ 90 % |

- **Result: every figure of SRS-044 is feasible, with margin**; the smallest margin is the noise reduction at 250 Hz (5.6 dB beyond the criterion), where the band from 40 Hz to the Nyquist frequency is narrower and the transition band from 40 to 80 Hz weighs more. The R-wave figure is the same at 30, 75 and 200 bpm, because the widths of the Q, R and S waves do not depend on the rate (§7.2). The same formula meets the gain and attenuation criteria at 200, 500 and 1000 Hz (checked at those rates: gain ≥ −0.37 dB, attenuation ≥ 51 dB); at 125 Hz the Nyquist frequency is below 80 Hz and only the gain criterion applies (§16 states the cut-off there).
- **Alternatives rejected.** An IIR low-pass (e.g. Butterworth) meets the attenuation with fewer operations, but its group delay varies with frequency, so the alignment of the marks would depend on the QRS content and the delay would not be constant. A moving average fails the gain criterion (−1.55 dB at 30 Hz for 4 samples at 360 Hz) and has side lobes at −13 dB. An equiripple design would be shorter, but needs an iterative design algorithm or a table of coefficients per sampling frequency instead of a formula.
- **Cost and equivalence.** In the library the stage runs in binary64 on the binary64 conditioned value, inside the conditioning stages of ADR 0008, and its output is rounded once to binary32; the sum of the absolute taps is at most 1.35 (1.32 at 360 Hz, 1.35 at 250 Hz), so the conditioning difference of 0.0018 µV (ADR 0008) grows to at most about 0.0025 µV, far below the tolerance of 2e-5 mV of SRS-034. Memory: N binary64 values, at most 61 at 1000 Hz (488 bytes), within the limit of SRS-032 (§14.10). Time: 23 binary64 multiply-adds per sample at 360 Hz, a small fraction of the processing budget on the ESP32-S3 (measured with the firmware, OP-014). §16 gives the bound, the exact operation order and the golden-vector format change.

### 15.18 Implementation plan and verification by role

The groups land in this order; a later group may start when the groups it depends on are merged into `develop`. Each group lands with the tests of its requirements in the item that implements it (§13.12). D1 and D3 do not depend on each other and may run in parallel.

| # | Group | Requirements | Design | Depends on | Verified by |
|---|---|---|---|---|---|
| D1 | `dsp`: display low-pass reference (`display` output of the pipeline), golden-vector export of the display output; mains deviation runs for SRS-054 | SRS-044 (reference), SRS-015 and SRS-033 (format change), SRS-054 | §16 | — | QA (SRS-044 reference tests); test engineer (SRS-054 system test) |
| D2 | `libs/sinus-dsp`: display stage in `Chain`, display output in the equivalence check and on the ESP32-S3 | SRS-044 (library), SRS-034, SRS-035, SRS-036 (extended to the display output), SRS-032 | §16 | D1 | QA (SRS-044, SRS-034, SRS-035 requirement tests); test engineer (SRS-036 emulator run) |
| D3 | Foundation of `desktop/`: tools moved to `tools/cpp/` with aqtinstall, root `.clang-format` and `.clang-tidy`, CMake, presets, flags, Qt pin and install with the hash list, `VERSION` and the generalised digest, `--version`, empty test executables with the offscreen `main`, jobs `desktop` and `desktop-windows`, SBOM, `testpaths`; Qt rows of `soup.md` | — (OP-075, OP-076 desktop parts; ADR 0009) | §15.2, §15.3, §15.12, §15.14 to §15.16 | — | Developer (unit tests); CI green; no requirement cited |
| D4 | `core`: WFDB reader and writer, fixture script and Python cross-checks | — (OP-050) | §15.9, §15.11, §15.16, §17 | D3 | Developer (unit tests and Python cross-checks) |
| D5 | `core`: frame, codec, `FrameQueue`, `Clock`/`FakeClock`, `StreamProcessor` with segments and the chain, `ReplaySource` with pacing, source exclusivity, mains in use, `ResultSink`, `CommandQueue`, `ProcessingWorker` | SRS-039, SRS-040, SRS-041 (source rules), SRS-050 (processing) | §15.4 to §15.6, §15.9, §17 | D2 (display output), D4 | QA (SRS-039, SRS-041, SRS-050); test engineer (SRS-040 system test) |
| D6 | `core`: display model and drawing input, marks, signal status, heart-rate display, quality mark | SRS-043, SRS-045, SRS-046, SRS-048 | §15.7, §15.8, §17 | D5 | QA |
| D7 | `io` and `core`: UDP test input; recorder thread and writer with events, metadata and identity | SRS-042, SRS-051, SRS-052 (recordings) | §15.10 to §15.12, §17 | D5 | QA |
| D8 | `ui` and `app`: main window, top bar, banner, waveform widget, panels, mains setting, replay controls, record command, About box, accessibility | SRS-041 (display), SRS-043 (widget), SRS-045, SRS-046, SRS-048 (texts shown), SRS-049, SRS-050 (setting), SRS-052 (About), SRS-053 | §15.7, §15.13, §17 | D6, D7 | QA |
| D9 | System verification: SRS-040 on the whole databases, SRS-047 through the test input, the Milestone 3 verification report | SRS-040, SRS-047 | §15.16, §17 | D7, D8 | Test engineer |

Requirements tagged by QA (Verification level Requirement): SRS-039, SRS-041 to SRS-046, SRS-048 to SRS-053. By the test engineer (System): SRS-040, SRS-047, SRS-054. The implementer of a group never verifies it functionally (`sdp.md` §3.1, §6).
