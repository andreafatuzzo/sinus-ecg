# Software architecture: Milestone 3 design

_Part of the software architecture of Sinus. [`architecture.md`](architecture.md) holds the general architecture (§1 to §7 and §9 to §12) and the version, status and revision history of every part. Section numbers are those of the whole architecture: a reference such as §6.2 points to `architecture.md`, §8 to [`architecture-m1.md`](architecture-m1.md), §13 and §14 to [`architecture-m2.md`](architecture-m2.md)._

This file holds three sections, written in this order:
- **§15, Milestone 3 architecture of the desktop application** (v0.5): structure, threading, data flow, the stream frame format, the outline of each function, build, CI, tests, the feasibility of SRS-044 and the implementation plan;
- **§16, display low-pass and mains tolerance** (v0.6): the detailed design of SRS-044 in `dsp` and `libs/sinus-dsp` and of SRS-054 in `dsp`;
- **§17, detailed design of the desktop application** (next version): SRS-039 to SRS-043 and SRS-045 to SRS-053, module by module, on the structure fixed here.

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

## 16. Milestone 3 display low-pass and mains tolerance (SRS-044, SRS-054)

This section is the detailed design (IEC 62304 §5.4) of SRS-044 in `dsp` and `libs/sinus-dsp`, with its effects on the golden vectors (SRS-015, SRS-033), the equivalence (SRS-034 to SRS-037) and the memory of the chain (SRS-032), and of SRS-054 in `dsp`. It builds on §15.7 and §15.17 (filter family and feasibility, approved on 2026-10-11). What holds unchanged: §7.1 (a causal reference; shared design formulas, stage order and initial state), §8.2 (module rules, errors, requirement citations, determinism), every rule of §13 and §14 not named below, ADR 0006, ADR 0007 and ADR 0008. The detection rules, the heart rate and the signal quality index do not change: the display stage reads the conditioned signal and feeds nothing.

### 16.1 Decisions of this section

| Topic | Decision | Section |
|---|---|---|
| Filter | Hamming-windowed sinc FIR, cut-off 50 Hz at every accepted sampling frequency, M = ⌊30·fs/1000 + 0.5⌋, N = 2M + 1 taps normalised to a sum of 1; constant delay of M samples | §16.2 |
| Arithmetic | binary64 in both implementations, one written order of operations (taps in index order; no library convolution); the library rounds the output once to binary32 (the rule of ADR 0008 for conditioning, applied to this stage) | §16.2, §16.6 |
| Input of the stage | The binary64 output of the mains stage, never its rounded value | §16.3, §16.6 |
| Start | History filled with the first input of the stage (exactly 0.0 in the chain): the steady state of a constant input, as for every stage (§7.1) | §16.2 |
| Delay compensation | The display value given with sample k belongs to index k − M; the first M values belong to no sample; the last M samples of a stream get no display value | §16.4 |
| On and off | Reference `run_pipeline(..., display=True)`; library `Config::display_lowpass` (default `true`); off: the stage is not run | §16.3, §16.6 |
| Golden vectors | Format version 3: header key `display_delay_samples`, section `[display_coefficients]`, column `display_mv`; readers accept version 3 only; ESP32-S3 pack version 2 | §16.5, §16.7 |
| Equivalence | `display_mv` compared at every sample within 2e-5 mV, the conditioning tolerance (SRS-044); bound 1.05e-5 mV on the golden set | §16.7 |
| Memory | About 1 000 bytes more per chain; about 52 600 bytes, limit 65 536 | §16.6 |
| SRS-054 | System test on the reference, 40 runs; all pass on the prototype; reported in the Milestone 3 verification report | §16.9 |
| Landing | D1 (reference and format) and D2 (library, reader and pack) merged into `develop` together | §16.11 |

### 16.2 Display low-pass: design (SRS-044)

**Coefficients**, computed at configuration in binary64 by the same expressions in both implementations, each operation in the order written (left to right):

1. M = ⌊30 · fs / 1000 + 0.5⌋: the expression of `round_samples_ms(30, fs_hz)` (§8.2) and of §14.3, "Times in samples" (`std::floor(30.0 * fs_hz / 1000.0 + 0.5)`). N = 2M + 1.
2. For k = 0 … N − 1, with j = k − M (an integer, converted exactly to binary64), fc = 50.0 Hz and `pi` the binary64 value nearest to π (Python `math.pi`; C++ `3.141592653589793`):
   - ideal = `2.0 * fc / fs` for j = 0, otherwise `sin(2.0 * pi * fc * j / fs) / (pi * j)`;
   - window = `0.54 - 0.46 * cos(2.0 * pi * k / (N - 1))`;
   - raw[k] = window · ideal.
3. total = raw[0] + raw[1] + … + raw[N − 1], added one at a time in index order (a plain loop; not `numpy.sum`, which adds pairwise, and not `math.fsum`).
4. h[k] = raw[k] / total (a division, not a multiplication by the reciprocal).

The taps are symmetric (h[k] = h[N − 1 − k], up to the last bit of `sin` and `cos`): the phase is linear and the group delay is M samples at every frequency.

**Filtering**, one output per input sample, causal, with x the input of the stage and x[i] = x[0] for i < 0:

  y[n] = (…((h[0]·x[n] + h[1]·x[n−1]) + h[2]·x[n−2]) + …) + h[N−1]·x[n−N+1]

Each product and each sum is one binary64 operation, in the order of k, with no fused multiply-add.

**Initial state.** The history holds x[0] at every earlier position: the steady state of a constant input equal to the first input (§7.1). In the chain the first input is the output of the mains stage at the first sample, which is exactly 0.0 (§14.3), so the history starts at zero and the first display value is 0.0. A constant input c that is a binary32 value gives exactly c after the rounding to binary32 (the taps sum to 1 within a few units of the last place of binary64; checked by the prototype on 2 000 values from −30 mV to 30 mV at five rates).

**Parameters** (pure computation of the formula; method of §15.17):

| fs | M | N | Delay | Gain 1–30 Hz | Gain at 40 Hz, 50 Hz | Attenuation from 80 Hz to Nyquist | Noise 40 Hz to Nyquist | Σ\|h\| |
|---|---|---|---|---|---|---|---|---|
| 125 Hz | 4 | 9 | 32.0 ms | −0.26 to +0.09 dB | −1.8 dB, −5.9 dB | no such band (Nyquist 62.5 Hz, where the gain is −11.6 dB) | −5.6 dB | 1.343 |
| 250 Hz | 8 | 17 | 32.0 ms | −0.26 to +0.04 dB | −1.8 dB, −6.0 dB | ≥ 50.4 dB | −11.6 dB | 1.350 |
| 360 Hz | 11 | 23 | 30.556 ms (11/360 s) | −0.33 to 0.00 dB | −2.0 dB, −6.0 dB | ≥ 53.6 dB | −13.9 dB | 1.324 |
| 500 Hz | 15 | 31 | 30.0 ms | −0.36 to 0.00 dB | −2.0 dB, −6.1 dB | ≥ 51.4 dB | −15.6 dB | 1.294 |
| 1000 Hz | 30 | 61 | 30.0 ms | −0.36 to 0.00 dB | −2.0 dB, −6.1 dB | ≥ 51.0 dB | −19.0 dB | 1.303 |

- Over every sampling frequency from 125 Hz to 1000 Hz in steps of 0.5 Hz, Σ|h| is at most 1.40 (largest 1.395) and N at most 61 (M = 30 at 1000 Hz). The delay M/fs lies within 0.5/fs of 30 ms.
- **Delay documented for SRS-044:** 11 samples (30.556 ms) at 360 Hz and 8 samples (32.0 ms) at 250 Hz, constant at every frequency.
- **Cut-off at low sampling frequencies.** The cut-off stays 50 Hz at every accepted sampling frequency, including 125 Hz, where it is 0.8 of the Nyquist frequency: the formula needs no special case, and the gain from 1 Hz to 30 Hz stays between −0.57 dB and +0.09 dB at every rate (computed every 2.5 Hz of sampling frequency; the lowest at 147.5 Hz, where M = 4 is shortest relative to the rate). At 125 Hz the Nyquist frequency is below 80 Hz, so the attenuation criterion of SRS-044 has no band to apply to; the stage attenuates the Nyquist frequency by 11.6 dB and white noise from 40 Hz to the Nyquist frequency by 5.6 dB. SRS-044 states its criteria at 360 Hz and 250 Hz; the figures at other rates describe the replay of other records (§15.6) and are not requirements. A lower cut-off at low rates was rejected: it would move the gain at 30 Hz toward the ±1 dB limit for a few dB of noise at rates the device does not use.

### 16.3 Reference (`dsp`)

**Module** `dsp/sinus_dsp/display.py` (new; imports `_types`, `_units`, `errors`, `input_checks` only):

```python
DISPLAY_CUTOFF_HZ: Final = 50.0           # Hz
DISPLAY_HALF_LENGTH_MS: Final = 30        # ms: M = round_samples_ms(30, fs)
DISPLAY_MAX_DELAY_SAMPLES: Final = 30     # M at 1000 Hz

def display_delay_samples(fs_hz: float) -> int: ...                                      # SRS-044
def display_lowpass_taps(fs_hz: float) -> FloatArray: ...                                # SRS-044
def apply_display_lowpass(taps: FloatArray, conditioned_mv: FloatArray) -> FloatArray: ...  # SRS-044
def display_lowpass(conditioned_mv: npt.ArrayLike, fs_hz: float) -> FloatArray: ...      # SRS-044
```

- `display_delay_samples(fs_hz)`: M of §16.2, after `validate_fs(fs_hz)` (§13.2): `InvalidInputError` for a value that is not a real number, is not finite, or lies outside 125 Hz to 1000 Hz.
- `display_lowpass_taps(fs_hz)`: a new float64 array of the N taps of §16.2, fs checked as above; computed with `math.sin` and `math.cos` on Python floats, in a loop, in the order of §16.2.
- `apply_display_lowpass(taps, conditioned_mv)`: the filtering of §16.2, vectorised over the samples and looped over the taps:

  ```python
  n_taps = taps.size
  padded = numpy.concatenate((numpy.full(n_taps - 1, x[0]), x))
  y = taps[0] * padded[n_taps - 1 :]
  for k in range(1, n_taps):
      y = y + taps[k] * padded[n_taps - 1 - k : padded.size - k]
  ```

  Each NumPy operation is one correctly rounded binary64 operation per element, so the result depends neither on the machine nor on a BLAS library (unlike `numpy.convolve` and `scipy.signal.lfilter`, §14.11) and equals, bit for bit, the library's binary64 value for the same input. Checks, `InvalidInputError` otherwise: `taps` one-dimensional, of odd length, finite; `conditioned_mv` one-dimensional, of at least one sample, finite. The arguments are not modified; the output is a new array as long as the input.
- `display_lowpass(conditioned_mv, fs_hz)`: converts the signal with `numpy.asarray(..., dtype=numpy.float64)`, checks it as above and returns `apply_display_lowpass(display_lowpass_taps(fs_hz), x)`. It does not apply the 10 s minimum and the 1000 mV bound of `validate_input`, which concern the raw input of the pipeline.

**Pipeline** (`pipeline.py`):

```python
def run_pipeline(signal_mv: npt.ArrayLike, fs_hz: float, mains_hz: int, *, display: bool = True) -> PipelineResult: ...

@dataclass(frozen=True)
class PipelineResult:
    ...                                   # the fields of §13.1, unchanged, then:
    display_delay_samples: int            # M (§16.2)
    display_taps: FloatArray              # the N taps
    display_mv: FloatArray | None         # the display output, as long as the input; None with display=False
```

- `display` must be a `bool` (`InvalidInputError` otherwise, raised with the other argument checks, before any computation).
- Order inside `run_pipeline`: the checks and `_condition` (unchanged); then, if `display`, `display_mv = apply_display_lowpass(taps, conditioned.mains_mv)` on the binary64 output of the mains stage; then the trace, the heart rate and the quality windows exactly as in §13.1. Nothing after the display stage reads its output. `display_delay_samples` and `display_taps` are filled whether `display` is on or off: they are part of the configuration.
- `detect_beats` and `detect_marked` do not compute the display output (they stop after the trace, §13.3).
- `STAGES` stays `("baseline", "mains")`: the display stage is a branch, not a stage in series before detection, and the golden vectors give it items of its own (§16.5).

**Citations.** The public functions of `display.py` and `run_pipeline` cite SRS-044; `golden.golden_vector` and `render_golden_vector` cite SRS-044 for the export of the display output (with SRS-015 and SRS-033); `filters.mains_sos` cites SRS-054 (§16.9).

### 16.4 Delay compensation, start and end of a stream (contract with the desktop, §15.7)

- The display value given with the k-th sample of a stream (`SampleOutput::display_mv` after the sample k, or `display_mv[k]` of the reference) is the filtered value of **index k − M** of that stream. The desktop stores it at the session index segment start + k − M (§15.6, §15.7). The compensation is exact: a whole number of samples, the same at every frequency.
- For k < M the value belongs to no sample (it comes from the history of §16.2) and is discarded. Indices 0 to M − 1 get their values with the samples M to 2M − 1.
- The last M samples of a stream get no display value: a stream ends at a reset (gap, interruption, change of source or of the mains setting, start of a replay; §15.6) or when the samples stop. These samples are "no data" for the display (§15.7): 30.6 ms at 360 Hz, 32 ms at 250 Hz. The drawn edge of §15.7 is therefore at most the latest index that has a display value; the delay of 0.5 s is far longer than M samples, so this moves the edge only when data stops. The detail is §17.
- Detections keep their indices (§13.3). The filter is symmetric, so the R peak of the compensated display trace lies at the same index as in the conditioned signal (prototype: no shift on the synthetic ECGs at 30, 75 and 200 bpm at either rate), and the marks of SRS-043 align with the drawn peaks.
- The desktop takes M from `Chain::display_delay_samples()` (§16.6), never from a formula of its own.

### 16.5 Golden-vector format, version 3 (SRS-015, SRS-033, SRS-044)

Version 3 keeps every rule of §7.3 and §13.8 and adds the display stage. The writer writes version 3 only; the Python and C++ readers accept version 3 only (`format_version` is `3`), so a version 2 file is rejected for its version, at line 2, as version 1 files are since Milestone 2. The files are never stored (§7.5): CI exports them from the commit under test, and a local folder written before this change is written again with `export_golden.py`.

**Header.** The keys of §13.8 in their order, with `format_version=3`, then one more key at the end: `display_delay_samples`, M of §16.2.

**Sections**, always in this order: `[coefficients]`, `[display_coefficients]`, `[signals]`, `[beats]`, `[reference_beats]`, `[heart_rates]`, `[quality_windows]`, `[end]`.
- `[display_coefficients]`: columns `tap,h`; 2M + 1 rows, one per tap k = 0 … 2M in order: k, then h[k].
- `[signals]`: columns `input_mv`, `<stage>_mv` for each stage of `stages`, then `display_mv` (version 3: `input_mv,baseline_mv,mains_mv,display_mv`). The `display_mv` of row k is the value given with sample k, **not shifted** by M (§16.4), so that the library's output is compared at the same sample.
- The other sections as in §13.8.

```
…
n_quality_windows=7
display_delay_samples=11
[coefficients]
stage,section,b0,b1,b2,a1,a2
baseline,0,…
mains,0,…
[display_coefficients]
tap,h
0,…
…
22,…
[signals]
input_mv,baseline_mv,mains_mv,display_mv
…
```

**Reader rules added** (each named at the line where the text breaks it, §7.3):
- `display_delay_samples`: an integer of the syntax of §7.3, from 1 to 30 (`DISPLAY_MAX_DELAY_SAMPLES`, `kDisplayMaxDelaySamples`), named at its header line;
- `[display_coefficients]`: the column line exactly `tap,h`; rows of two fields; `tap` equal to the row number counted from 0; `h` a float of §7.3; 2M + 1 rows, a different count named as the row counts of §7.3 (at the line found where the next row, or the next section, is expected);
- `[signals]`: the column line of the stages followed by `,display_mv`; each row has one field more than in version 2.

The readers do not check that M or the taps fit the sampling frequency: the equivalence check compares M with the library's (§16.7), the library's unit tests compare the taps, and QA's tests of SRS-015 compare both with the reference functions.

**Interface changes** (`sinus_dsp.golden`):

```python
FORMAT_VERSION: Final = 3

@dataclass(frozen=True)
class GoldenVector:
    ...                                   # the fields of §13.8, unchanged, then:
    display_delay_samples: int            # M
    display_taps: FloatArray              # the 2M + 1 taps
    display_mv: FloatArray                # as long as input_mv, not shifted
```

`golden_vector` takes the new fields from `run_pipeline(..., display=True)`. `render_golden_vector` rejects with `InvalidInputError` a vector whose M is outside 1 to 30, whose taps are not 2M + 1, whose `display_mv` is not as long as the input, or that holds a value that is not finite (the export then fails naming the input, §7.3). Every text it returns is accepted by `parse_golden_vector`, which gives back an equal vector. `export_golden_vectors`, the script `export_golden.py`, its options and the set of inputs do not change.

**Size.** One more float per row: about 8 MB more for the 32 files; the set is about 30 MB (§13.8: about 22 MB), still not stored.

**Verification notes.**
- QA (SRS-015 and SRS-033 in version 3; the export part of SRS-044): the tests of §13.8 with `format_version=3`; each file holds `display_delay_samples`, `[display_coefficients]` and the column `display_mv`; the values read back equal, bit for bit, `display_delay_samples(fs)`, `display_lowpass_taps(fs)` and `display_lowpass(mains_mv, fs)` called directly on the `mains_mv` of `run_pipeline` for the same input.
- Developer's unit tests: one rejected text per new reader rule, with its line (M of 0, of 31, not an integer; a wrong column line of `[display_coefficients]` and of `[signals]`; a missing and an extra tap row; a tap number out of order; a `[signals]` row of three fields); the round trip render → parse; a version 2 file rejected for its version.

### 16.6 Real-time library (`libs/sinus-dsp`)

**Module** `display_lowpass` (new public header `include/sinus/dsp/display_lowpass.hpp`, source `src/display_lowpass.cpp`), citing SRS-044:

```cpp
// limits.hpp
inline constexpr std::uint32_t kDisplayMaxDelaySamples = 30;                        // M at 1000 Hz
inline constexpr std::size_t kDisplayTapCapacity = 2 * kDisplayMaxDelaySamples + 1;  // 61

// display_lowpass.hpp (SRS-044)
inline constexpr double kDisplayCutoffHz = 50.0;
inline constexpr double kDisplayHalfLengthMs = 30.0;
using DisplayTaps = std::array<double, kDisplayTapCapacity>;
// Preconditions: a sampling frequency that validate accepts.
[[nodiscard]] std::uint32_t display_delay_samples(double fs_hz) noexcept;        // M (§16.2)
// Writes the 2M + 1 taps of §16.2 to taps[0 .. 2M] and 0.0 to the rest; returns 2M + 1.
std::size_t display_lowpass_taps(double fs_hz, DisplayTaps& taps) noexcept;

class DisplayLowpass {
 public:
  [[nodiscard]] Status configure(double fs_hz) noexcept;   // kInvalidSamplingFrequency as in §14.5
  void reset() noexcept;                                    // the next sample starts a new stream
  // Precondition: a finite value (the Chain gives the binary64 conditioned value).
  [[nodiscard]] Status process(double conditioned_mv, float& display_mv) noexcept;  // kNotConfigured before configure
  [[nodiscard]] std::uint32_t delay_samples() const noexcept;   // M; 0 when not configured
  [[nodiscard]] std::size_t tap_count() const noexcept;         // N; 0 when not configured
  [[nodiscard]] const DisplayTaps& taps() const noexcept;
};
```

- `display_delay_samples` and `display_lowpass_taps`: the formulas of §16.2 with `std::floor`, `std::sin`, `std::cos` and `constexpr double kPi = 3.141592653589793` in the `.cpp` (C++17 has no `std::numbers`); the total added in index order; each tap divided by the total.
- `process`: on the first sample after `configure` or `reset`, first fills the history with that value (§16.2); stores the value in a ring of N binary64 values indexed by the sample counter modulo N (one private helper, as in §14.4); then `acc = taps[0] * x`, `acc = acc + taps[k] * x[n − k]` for k = 1 … N − 1, and `display_mv = static_cast<float>(acc)`. All floating-point code is in the `.cpp` (§14.3, `-ffp-contract=off`).
- `ConditionedSample` gains `double conditioned_f64_mv`: the binary64 output of the mains stage, of which `conditioned_mv` is the rounding. `Conditioner::process` sets it; nothing else in the conditioner changes.

**Chain** (`config.hpp`, `chain.hpp`, which also cite SRS-044):

```cpp
struct Config {
  double sampling_frequency_hz = 0.0;
  int mains_frequency_hz = 0;      // 50 or 60
  bool display_lowpass = true;     // SRS-044: the display stage on (true) or off
};
struct SampleOutput {
  float baseline_mv = 0.0F;
  float conditioned_mv = 0.0F;
  float display_mv = 0.0F;         // SRS-044: the display value of index (this sample − M), §16.4
  …                                // the other fields of §14.4, unchanged
};
class Chain {
 public:
  …                                // the members of §14.4, unchanged, then:
  [[nodiscard]] std::uint32_t display_delay_samples() const noexcept;   // M; 0 when not configured
};
```

- `configure` (§14.5): the checks and their order do not change (`display_lowpass` has no invalid value). On success the chain also configures its `DisplayLowpass`, whether the stage is on or off, so that `display_delay_samples()` gives M in both cases.
- `process`: within one sample the order is conditioning; **display** (only if `display_lowpass`: `DisplayLowpass::process(conditioned.conditioned_f64_mv, out.display_mv)`); detection; heart rate; signal quality (§14.4, "Behaviour of `Chain::process`"). Detection and the rest take `conditioned_mv` (binary32) as before; nothing reads the display value.
- With the stage off, it is not run, and `display_mv` is a quiet NaN at every processed sample (§14.4: a value that does not exist is a quiet NaN; `config().display_lowpass` says whether it exists). With any status other than `kOk`, `display_mv` is 0.0f like the other values (SRS-017, SRS-018: no output of any kind).
- `reset` (§14.10, SRS-031) also restarts the display stage: after a reset the outputs, the display value included, are those of a newly configured chain given the same samples.
- The C interface of SRS-038 (§14.14) does not change; its chain has the default configuration (stage on).

**Arithmetic (ADR 0008).** The stage computes like the conditioning stages: binary64 from the binary64 conditioned value, one rounding to binary32 at the output. Filtering the rounded `conditioned_mv` instead would add the rounding of every conditioned value, up to Σ|h| · u · |x|, to the difference from the reference. ADR 0008 is not changed: it names the two stages of Milestone 2, and this section applies its rule to the third.

**Memory (SRS-032, §14.10).** A new row of the table of §14.10: display stage, taps 61 × 8 bytes and history 61 × 8 bytes, M, N, the counter and the start flag: about 1 000 bytes. Total about 52 600 bytes, 80 % of the limit of 65 536 bytes; the `static_assert` of §14.10 is unchanged. No allocation in `configure`, `process` or `reset`; the `no_heap_symbols` check covers the new source, and QA's test of SRS-032 runs its configurations with the stage on (the default). `SampleOutput` grows by 4 bytes and stays outside the chain.

**Cost on the ESP32-S3.** N software binary64 multiplications and N − 1 additions per sample: 45 operations at 360 Hz, about twice the two conditioning stages, still of the order of 1 % of one core (OP-014, measured with the firmware). A firmware that displays nothing can configure the stage off (Milestone 4).

**Verification notes (developer's unit tests).** M and N at every rate from 125 Hz to 1000 Hz in steps of 0.5 Hz equal ⌊30·fs/1000 + 0.5⌋ and 2M + 1, with M ≤ 30; the taps at 125, 250, 360, 500 and 1000 Hz equal the formula, and those at 250 Hz and 360 Hz the `[display_coefficients]` of the golden vectors, within 1e-15 (absolute; `std::sin` and `std::cos` may differ in the last bit between C libraries, §14.3); symmetry within 1e-15; a constant binary32 input gives exactly that value; an impulse after a zero start gives the taps in order, rounded to binary32; `reset` equals a new configuration; `process` before `configure` returns `kNotConfigured`; with `display_lowpass` false, `display_mv` is NaN and every other field of `SampleOutput` equals, bit for bit, that of a chain with the stage on; `display_delay_samples()` is 0 before `configure`.

### 16.7 Equivalence of the display output (SRS-034 to SRS-037, SRS-044)

**Bound.** At each sample the library and the reference compute the same binary64 operations (§16.2) on their binary64 mains outputs, which differ only by the rounding of the input to binary32 carried through the stages (the binary64 recursions add below 1e-12 mV, §14.11). With u = 2⁻²⁴, the difference is therefore at most (G_d + 1) · u · max|x|, as in §14.11, where G_d is the ℓ1 gain from the input to the display output and the 1 is the final rounding to binary32. G_d ≤ 5.59 × 1.40 = 7.83 (both conditioning stages, §14.11, times Σ|h|, §16.2); computed from the impulse responses of the cascade at 125, 200, 250, 333.3, 360, 500 and 1000 Hz with both mains settings, it is at most 2.68. On the golden set (inputs within 20 mV) the bound is 8.83 · u · 20 mV = 1.05e-5 mV, below the tolerance of 2e-5 mV; it stays below it for inputs up to 38 mV in magnitude (50 mV for the conditioning stages, §14.11). A golden input above 38 mV in magnitude added to SRS-015 or SRS-033 needs this bound redone first. The measured difference is expected at the level of the conditioning stages (1.8e-6 mV, §14.11), mostly the final rounding.

**Equivalence check** (`verification/equivalence`, §14.12). One more compared output, after `mains_mv`:

| Output | Compared | Largest difference | Tolerance |
|---|---|---|---|
| `display_mv` | first the delay: the file's `display_delay_samples` against `Chain::display_delay_samples()` (a structural difference, text `delay <library>, file <file>`, `At sample` `—`); then every sample | max \|library − file\|, in binary64; `At sample` the sample number, as for `mains_mv` | 2e-5 mV |

The chain is configured with the stage on (the default). The taps are not compared by the check (as the biquad coefficients, §14.4): the developer's unit tests compare them (§16.6). The results (§14.12) state `format version 3` in the row `Golden vectors` and one more row per file; the row `Chain size` gives the new size. SRS-037 needs no change: `display_mv` is one more compared output, with its largest difference, tolerance and outcome. `golden_reader` (C++) reads version 3 with the rules of §16.5; `golden_set` keeps the same 32 identifiers.

**Pack, version 2** (§14.13). The header is unchanged except the pack version, 2; each file starts with the 4 bytes `GVF3`; after the coefficient rows come a `uint32` M and the 2M + 1 taps as `float64`; per sample, the input as `float32` and three `float64` (baseline, mains, display). The target rejects a pack of version 1. Size: 394 340 samples × 28 bytes plus the events, about 11.2 MB, within the partition `golden` (0xE00000 = 14 680 064 bytes), which the job already checks. The emulator run takes a few seconds more.

**CI (SRS-035, SRS-036).** The jobs do not change: `dsp` exports version 3, `libs` checks it with the reader of version 3, `libs-esp32s3` packs it in version 2 and checks it in the emulator. Each reader accepts only its version, so the reference and the library change in the same merge (§16.11).

**Verification notes.**
- QA (SRS-034, C++ requirement test): the mutation test gains a copy with one `display_mv` value changed by more than 2e-5 mV, which fails and names the file, `display_mv` and the sample; and a copy with `display_delay_samples` and its tap rows changed, which fails with the delay difference.
- QA (SRS-035, SRS-037): unchanged tests; the expected results texts gain the row `display_mv` and `format version 3`.
- Test engineer (SRS-036): the system test of the emulator run (§14.13) expects the row `display_mv` for every file and format version 3; the log of a CI run, and of a run on a pack with one display value changed beyond the tolerance, is kept for the Milestone 3 verification report.

### 16.8 Verification of SRS-044

Two requirement tests, one per item (ADR 0006), both by QA: `dsp/tests/requirements/test_srs_044_display_lowpass.py` through `run_pipeline`, and `libs/sinus-dsp/tests/requirements/test_srs_044_display_lowpass.cpp` through `Chain::process`, one sample at a time, each sample the `static_cast<float>` of the binary64 signal. Both compute the same measures with the same criteria, at 360 Hz and 250 Hz, with the mains setting 50 Hz unless stated. "Display" is the display output (`PipelineResult.display_mv`, `SampleOutput::display_mv`), "conditioned" the output of the mains stage (`mains_mv`, `conditioned_mv`), both as binary64 for the measures; n is the number of samples.

| # | Property (SRS-044) | Signal | Measure | Criterion | Expected (prototype on the reference) |
|---|---|---|---|---|---|
| 1 | Gain from 1 to 30 Hz | x[n] = sin(2π f n / fs) mV, f = 1, 5, 10, 20, 30 Hz, 10 s each (the shortest input that the reference accepts) | G = 20·log10(RMS(display[n/2 …]) / RMS(conditioned[n/2 …])), the second half | \|G\| ≤ 1 dB | 360 Hz: −0.33 dB (30 Hz) to 0.00 dB; 250 Hz: −0.26 dB (30 Hz) to +0.03 dB |
| 2 | Attenuation | f = 80, 100, 120 Hz as in 1; at the Nyquist frequency x[n] = cos(π n) = (−1)ⁿ mV (a sine there samples to zero) | G as in 1 | G ≤ −20 dB | 360 Hz: −57.1, −61.1, −61.7 dB, −57.8 dB at 180 Hz; 250 Hz: −70.6, −60.8, −56.1 dB, −50.4 dB at 125 Hz |
| 3 | Gain and attenuation at every frequency | the taps (`PipelineResult.display_taps`; in the library `display_lowpass_taps`, whose taps the chain uses) | \|H(f)\| = \|Σₖ h[k]·e^(−2πi f k / fs)\| on a 0.25 Hz grid from 1 to 30 Hz and from 80 Hz to the Nyquist frequency (included) | within ±1 dB; ≤ −20 dB | as in §16.2 |
| 4 | Group delay | sinusoids of 10 s at f − 0.5 Hz and f + 0.5 Hz, f = 1, 10, 20, 30 Hz | at each frequency g, the phase φ of the display and of the conditioned signal by a least-squares fit of a·sin(2π g n / fs) + b·cos(2π g n / fs) over the second half; Δ = (φ_display − φ_conditioned)(f + 0.5) − (φ_display − φ_conditioned)(f − 0.5), wrapped into (−π, π]; τ(f) = −Δ / (2π · 1 Hz) | max τ − min τ ≤ 20 ms, and each τ within 0.01 ms of M/fs (30.556 ms at 360 Hz, 32.000 ms at 250 Hz): the documented constant delay | τ = M/fs at every f, within 1e-4 ms |
| 5 | R-wave peak | the synthetic ECG of SRS-006 (§7.2 waveform, no interference), 30 s, at 30, 75 and 200 bpm | for each true R centre r with 2·fs ≤ r and r + M + w < n, w = ⌊50·fs/1000⌋: max(display[r+M−w … r+M+w]) / max(conditioned[r−w … r+w]) | every ratio ≥ 0.90 | 360 Hz: 0.990 to 0.991; 250 Hz: 0.993 to 0.994 |
| 6 | Noise | the synthetic ECG at 75 bpm, 60 s (n = 60·fs), and the same plus noise w: Gaussian samples (below), band-limited by removing every DFT component below 40 Hz, scaled to an RMS of 0.1 mV over the 60 s | e_in = conditioned(ECG + w) − conditioned(ECG), e_out = display(ECG + w) − display(ECG); 20·log10(RMS(e_out) / RMS(e_in)) over the samples from 2·fs to the end | ≤ −6 dB | 360 Hz: −14.4 dB; 250 Hz: −12.0 dB |
| 7 | Detection unchanged | (a) the synthetic ECGs of SRS-010: 30, 40, 75, 180, 200 bpm, 30 s, with the baseline wander and the interference at 50 Hz (setting 50) and at 60 Hz (setting 60); (b) the inputs of the golden vectors (below) | reference: `run_pipeline(x, fs, mains)` against `run_pipeline(x, fs, mains, display=False)`; library: two chains, `display_lowpass` true and false, given the same samples | reference: every field of `detections`, `heart_rate` and `quality`, and `baseline_mv`, `mains_mv`, identical (floats bit for bit); library: at every sample every field of `SampleOutput` except `display_mv` identical, bit for bit, and `display_mv` NaN with the stage off | identical by construction |

- **Noise generation.** Python: `numpy.random.default_rng(seed).standard_normal(n)` with a seed fixed in the test, then `numpy.fft.rfft`, the bins whose frequency (`rfftfreq(n, 1 / fs)`) is below 40 Hz set to 0, `irfft(…, n)`, then the scaling. C++: the standard distributions differ between standard libraries, so the test uses its own generator (for example SplitMix64 and the Box–Muller transform, written in `tests/requirements/support`) and removes the components below 40 Hz by a direct DFT of those bins (2 400 bins for 60 s, at both rates), then scales. The noise differs between the two tests; each meets the criterion with a margin of about 6 dB.
- **Inputs of the golden vectors (7 b).** Reference: `synthetic_set()` and `synthetic_event_set()` (26 inputs) in CI, and the six record segments in a separate test marked `needs_data`. Library: the inputs of the vector folder that its SRS-034 test reads, skipped with the reason when the folder is not given, as there.
- **Delay variation and documentation.** Measure 4 checks both: the variation (criterion of SRS-044) and that the delay is the constant documented in §16.2.
- SRS-044 has no desktop part: the desktop only draws the output (§15.7, §17).

### 16.9 SRS-054: mains interference removal under a deviation (test engineer)

- **Test.** `dsp/tests/system/test_srs_054_mains_deviation.py`, `@pytest.mark.requirement("SRS-054")`, synthetic only, so it runs in CI (no `needs_data`).
- **Signals.** The synthetic ECG of SRS-006 at 30, 40, 75, 180 and 200 bpm, 30 s, at 360 Hz and at 250 Hz: the waveform of §7.2, beat k centred on ⌊(0.5 + k·RR)·fs + 0.5⌋ while 0.5 + k·RR ≤ 29.5 s (as the generator of QA's tests of SRS-010; the test engineer writes the same formulas in `tests/system`), plus 1.0 mV · sin(2π · 0.3 Hz · t) and 0.2 mV · sin(2π · f · t), t = n / fs, phase 0, added in this order. f = 49.5 Hz and 50.5 Hz with the mains setting 50 Hz; f = 59.5 Hz and 60.5 Hz with 60 Hz: 2 rates × 5 heart rates × 4 frequencies = 40 runs.
- **Run.** `run_pipeline(x, fs, setting).beats`.
- **Criteria** (those of SRS-006, as SRS-010 applies them): exactly one detection within ⌊0.150·fs⌋ samples of each true R centre and no other detection; indices strictly increasing and at least ⌈0.200·fs⌉ samples apart.
- **Result.** The test fails if any run fails, and its message lists every failing run (fs, rate, frequency, setting) with its violations. The test engineer records the 40 outcomes in the Milestone 3 verification report, with the deviations for which the criterion holds; if a run fails, the design is not changed silently: the result is reported and the project manager opens an open point (SRS-054, rationale).
- **Expected** (prototype on the reference of this branch, 2026-10-11): all 40 runs pass. For the report, not as a criterion: the 0.2 mV interference alone leaves, in the conditioned output from 5 s on, a residue of about 0.103 mV in amplitude at 49.5 and 50.5 Hz and 0.090 mV at 59.5 and 60.5 Hz: the notch (Q = 30, §8.6) attenuates a deviation of 0.5 Hz by about 6 dB only, and detection still meets SRS-006 because its band-pass (5–15 Hz) and thresholds reject the residue. On the display output the residue is reduced further by the display stage (−6.0 dB at 50 Hz, −14.0 dB at 60 Hz at 360 Hz).
- **Citation.** The docstring of `filters.mains_sos` cites SRS-054 (the notch is what SRS-054 checks), so that SRS-054 is implemented in `dsp`; its system test lands on the same branch (ADR 0004, ADR 0006).

### 16.10 Identity, digest and reports

- D1 changes files under `dsp/sinus_dsp/` (`display.py`, `pipeline.py`, `golden.py`, the docstring of `filters.py`): the source digest changes (§8.14), so both validation reports are regenerated in the same change and `software_check.py` passes. Detection does not change, so the regenerated reports differ from the current ones only in the row `Software` (and `Runtime` if the machine's versions differ): any other difference shows a change of detection and stops the merge. The version stays `0.3.0.dev0`.
- D2 changes `libs/sinus-dsp/include` and `src`: the library digest changes (§14.15); no stored file holds it (the equivalence results are CI artifacts).
- The golden vectors carry the new reference digest; CI compares the library only with vectors of the same run (§7.5).

### 16.11 Implementation order and verification by role

D1 and D2 are developed on one branch, D1 first (SRS-044: the reference is written first), and merged into `develop` together, when both groups, QA's tests and the system test of SRS-054 pass: each reader accepts only its format version (§16.5), so D1 alone would fail the job `libs`.

| Step | Group | Task | Requirements | Design |
|---|---|---|---|---|
| 1 | D1 | `display.py`: constants, `display_delay_samples`, `display_lowpass_taps`, `apply_display_lowpass`, `display_lowpass` | SRS-044 | §16.2, §16.3 |
| 2 | D1 | `run_pipeline(..., display=True)` and the three fields of `PipelineResult` | SRS-044 | §16.3 |
| 3 | D1 | Golden format version 3: `GoldenVector`, `golden_vector`, `render_golden_vector`, `parse_golden_vector` | SRS-015, SRS-033, SRS-044 | §16.5 |
| 4 | D1 | `filters.mains_sos` cites SRS-054 | SRS-054 | §16.9 |
| 5 | D1 | Both validation reports regenerated; traceability matrix regenerated | — | §16.10 |
| 6 | D2 | `limits.hpp` capacities; `display_lowpass.hpp` and `.cpp` | SRS-044 | §16.6 |
| 7 | D2 | `ConditionedSample::conditioned_f64_mv`; `Config::display_lowpass`; `SampleOutput::display_mv`; `Chain` (configure, process, reset, `display_delay_samples`) | SRS-044, SRS-031, SRS-032 | §16.6 |
| 8 | D2 | `golden_reader` version 3; `equivalence` (`display_mv`, delay); `equivalence_report`; `golden_pack` version 2 and the target's pack reader | SRS-034 to SRS-037 | §16.7 |

**Verification by role.** QA: SRS-044 in both items (§16.8); SRS-015 and SRS-033 tests moved to version 3 (§16.5); the SRS-034 mutation with `display_mv` and the expected texts of SRS-035 and SRS-037 (§16.7); SRS-032 run again with the new chain. Test engineer: SRS-054 (§16.9); SRS-036 system test with `display_mv` (§16.7). Developer: the unit tests of §16.5 and §16.6. QA's existing tests that check version 2 or its column lines are updated by QA, not by the developer (`sdp.md` §3.1).
