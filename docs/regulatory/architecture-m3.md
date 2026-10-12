# Software architecture: Milestone 3 design

_Part of the software architecture of Sinus. [`architecture.md`](architecture.md) holds the general architecture (§1 to §7 and §9 to §12) and the version, status and revision history of every part. Section numbers are those of the whole architecture: a reference such as §6.2 points to `architecture.md`, §8 to [`architecture-m1.md`](architecture-m1.md), §13 and §14 to [`architecture-m2.md`](architecture-m2.md)._

This file holds three sections, written in this order:
- **§15, Milestone 3 architecture of the desktop application** (v0.5): structure, threading, data flow, the stream frame format, the outline of each function, build, CI, tests, the feasibility of SRS-044 and the implementation plan;
- **§16, display low-pass and mains tolerance** (v0.6): the detailed design of SRS-044 in `dsp` and `libs/sinus-dsp` and of SRS-054 in `dsp`;
- **§17, detailed design of the desktop application**: SRS-039 to SRS-043 and SRS-045 to SRS-053, module by module, on the structure fixed here. Part 1 (v0.7) holds the WFDB reader and writer and the sources and processing of `core` (groups D4 and D5); part 2 (next version) holds the display model, the status texts, the test input, the recorder and the user interface (groups D6 to D8).

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
| Windows toolchain: Qt's LLVM-MinGW build if Qt 6.12 ships one, otherwise Qt's MinGW 15.1 build with its toolchain. Qt 6.12 ships one (`win64_llvm_mingw`, toolchain LLVM-MinGW 22.1.7), found by group D3, so it is used | Project owner, 2026-10-11 | §15.14 |
| Qt installed in CI by aqtinstall, its archives checked against a committed list of SHA-256 digests | Project owner, 2026-10-11 | §15.14 |
| aqtinstall pinned to a fixed upstream commit that installs Qt 6.11 and later on Windows (release 3.3.0 cannot), until a release includes the fix | Project owner, 2026-10-11 | §15.14 |
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
- **Tools.** `libs/sinus-dsp/tools` was moved to `tools/cpp/` by group D3 (same pins, plus `aqtinstall`, §15.14), with one lock for the library, the desktop and later the firmware's host tests. The move changed no file of `libs/sinus-dsp/include` or `src`, so the library's digest and results did not change; the `libs` and `libs-esp32s3` jobs run the tools with `--project ../../tools/cpp` from `libs/sinus-dsp`. The root `.clang-format` keeps the content of the library's file; the library's `.clang-tidy` keeps every check it has today, split into the root base and its own additions.
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
- **Reference records.** A record of the MIT-BIH Arrhythmia or Noise Stress Test databases is replayed from the local copy that `dsp` downloaded and verified (§6.2, IF-1). The replay checks the record's files against the checksum list `SHA256SUMS.txt` of that copy, itself checked against the digest pinned for the database version (§8.3), before it starts; a verified record gets the mains frequency of 60 Hz and its database name in the banner (SRS-050, SRS-041). Another WFDB record (neither a reference record nor a recorded session) uses the mains setting of the user, shown in the banner (OP-083, decided; SRS-050 v0.9.2).
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
- **Gain.** For a replayed record or session: its own gain and baseline, so that the round trip is exact. For the test input: 1000 adu/mV (1 µV resolution, ±32.767 mV); a test-input sample beyond that range cannot be stored in format 16 at that resolution, and is a failure of the recording (below), as the owner decided for OP-082 (option (a), 2026-10-11).
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
- **Linux.** GCC 14 and Clang 18 of the `ubuntu-24.04` runner, with Qt's `linux_gcc_64` build for Qt 6.12 (built by Qt on RHEL 9.6 with GCC, as its archive names state; it needs only the C and C++ runtimes of that older system, which the GCC 14 standard library of the runner provides).
- **Windows.** C++ code linked with Qt must use the C++ runtime of the Qt build. Qt 6.12 ships a Windows build for LLVM-MinGW (aqtinstall architecture `win64_llvm_mingw`, built with LLVM-MinGW 22.1.7), found by group D3 in the archive list, so by the owner's decision the desktop application uses **that build with Qt's LLVM-MinGW 22.1.7 toolchain**, installed by aqtinstall as a Qt tool (`tools_llvm_mingw2217`), with the run-time libraries (libc++, libunwind) that Qt places next to its own; the MinGW 15.1 fallback is not used. The library code is the same either way; it keeps building with the local LLVM-MinGW toolchain for its own tests (§14.2). The desktop executable links the C++ runtime dynamically, like Qt (the library's `-static` link option is set in the library's folder only and does not reach the desktop).
- **Qt pinning.** `desktop/qt/version.txt` holds the exact Qt version (6.12.0 for Milestone 3, then updated once per milestone). `desktop/qt/<version>-<host>-<arch>.sha256` lists the SHA-256 of every archive that aqtinstall downloads for the modules used, and on Windows also the archives of the toolchain and of its run-time libraries; the install script installs with aqtinstall from `tools/cpp` (which checks the archives against the checksums of the Qt repository) and then checks the downloaded archives against the committed list, so that a changed archive fails the job. The Qt installation is cached with the hash of the list as key.
- **aqtinstall pin.** Release 3.3.0 of aqtinstall cannot install Qt 6.11 or later on Windows (the Qt repository moved each Windows build into a folder of its own). The fix is on the upstream main branch but not released, so `tools/cpp/pyproject.toml` takes aqtinstall from a fixed upstream commit (`[tool.uv.sources]`, a git revision locked in `uv.lock`), with a comment naming the reason; it returns to a PyPI release pinned with `==` once one includes the fix (owner's decision, 2026-10-11). The commit is reviewed like any tool update (`cybersecurity.md` §7.4), and the committed archive digests still decide what is installed.
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

- **Framework.** GoogleTest 1.18.0 (§14.2) for every C++ test, including widget tests. Executables: `sinus_desktop_core_unit_tests` (links `core` only, no Qt: it also proves that `core` needs no Qt), `sinus_desktop_unit_tests`, `sinus_desktop_requirement_tests`, `sinus_desktop_system_tests` (Qt, with the test `main` of `tests/support/` that creates a `QApplication` on the `offscreen` platform). That `main` is an object library (`sinus_desktop_test_main`) added to each Qt test executable, so that an executable with no test of its own still builds and runs. A ctest entry (`sinus_desktop_version`) runs `sinus-desktop --version` and checks that its output states the version of `desktop/VERSION`. `QTest` event functions and `QSignalSpy` are used as helpers inside GoogleTest tests; Qt Test's own test runner is not used, so the `// Verifies: SRS-nnn` tags work as in ADR 0004 and the traceability script needs no change.
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

## 17. Milestone 3 detailed design of the desktop application

This section is the detailed design (IEC 62304 §5.4) of the desktop application on the structure of §15. **Part 1** (v0.7, §17.1 to §17.16) covers groups D4 and D5 of §15.18: the WFDB reader and writer of `core` (OP-050) and the sources and processing of `core`, with SRS-039, SRS-040, the source rules of SRS-041 and the processing part of SRS-050. **Part 2** (v0.8, §17.17 to §17.29) covers D6 (display model, marks, signal status, heart-rate display, quality mark: SRS-043, SRS-045, SRS-046, SRS-048), D7 (UDP test input, recorder: SRS-042, SRS-051, SRS-052 in recordings) and the design of the system test of SRS-047. **Part 3** (v0.9, §17.30 to §17.44) covers D8 (user interface: the main window and its top bar, the waveform widget, the panels, the controls, the About box and accessibility: the display part of SRS-041, the widget part of SRS-043, the texts shown of SRS-045, SRS-046 and SRS-048, SRS-049, the setting of SRS-050, the About box of SRS-052, SRS-053) and what remains for D9. What holds unchanged: §15 and §16.4, ADR 0007, ADR 0009, and the library interface of §14.4 with §16.6.

### 17.1 Conventions of `core`

- **Namespace and files.** `sinus::desktop::core`; one header and one source per module under `desktop/src/core/` (§17.2); the names below are those the developer and QA use.
- **No exceptions** (§15.15). An operation that can fail returns a status, with a message for the user where the user sees it (§17.5). Standard-library calls that can throw are used only in their non-throwing forms (`std::filesystem` with `std::error_code`, streams with their state checked). An allocation failure ends the program (`-fno-exceptions`), as for any C++ program built so.
- **Allocation.** At the opening of a record, the creation of a writer, a source selection, a segment start or a configuration; never per sample in the processing path (§15.5). The frame path (`Frame`, `FrameQueue`, `StreamProcessor::handle`) does not allocate.
- **Files.** Paths are `std::filesystem::path` (the `io` and `ui` layers convert with `QFileInfo::filesystemFilePath()`); files are read and written in binary mode, so a header written on Windows has LF line ends.
- **Time.** `TimePoint` is `std::chrono::steady_clock::time_point` and `Duration` is `std::chrono::nanoseconds` (§17.10). Every function that needs the time takes it as an argument; only the thread classes read a clock.
- **Units** in names (`_mv`, `_hz`, `_millihertz`, `_adu`, `_samples`, `_ms`), as everywhere.
- **Requirement citations.** D4 cites no requirement ID: it lands before any verifying test of a desktop requirement, and a citation without a test fails the traceability check (ADR 0004). D5 adds the citations named in §17.16; the writer cites SRS-051 and SRS-052 only in D7, with QA's tests.

### 17.2 Modules of `core` (part 1)

| Module (`desktop/src/core/`) | Group | Content |
|---|---|---|
| `sha256` | D4 | SHA-256 (FIPS 180-4), digest of a file, lowercase hex (§17.7) |
| `wfdb_status` | D4 | `WfdbStatus`, `WfdbResult` (§17.5) |
| `wfdb_header` | D4 | number grammar, `WfdbHeader`, `parse_wfdb_header` (§17.3) |
| `wfdb_reader` | D4 | `WfdbRecord`, `read_wfdb_record` (§17.4) |
| `recording_metadata` | D4 | `RecordingMetadata`, `RecordingEvent`, comment lines (§17.6) |
| `wfdb_writer` | D4 | `WfdbRecordingWriter` (§17.6) |
| `reference_databases` | D4 | pinned checksum lists, checksum-list parser, record verification (§17.7) |
| `mains` | D4 | `MainsFrequency` (used by the recording metadata, §17.6, and the processor, §17.12) |
| `frame`, `frame_codec` | D5 | `Frame`, `StreamItem`, `encode_frame`, `decode_frame`, `crc32` (§17.9) |
| `clock`, `frame_queue`, `command_queue` | D5 | `Clock`, `SteadyClock`, `FakeClock`, `Wakeup`, `FrameSink`, `FrameQueue`, `CommandQueue` (§17.10, §17.13) |
| `replay_record`, `replay_source` | D5 | `open_replay_record`, `ReplaySource`, `release_offset` (§17.11) |
| `stream_processor` | D5 | `SourceSelection`, `Command`, `SegmentInfo`, `StreamCounters`, `ProcessorState`, `ResultSink`, `StreamProcessor` (§17.12) |
| `snapshot`, `workers` | D5 | `Snapshot`, `SnapshotExchange`, `ProcessingWorker`, `ReplayThread` (§17.13) |
| `headless_replay` | D5 | `run_headless_replay` (§17.14) |

No annotation reader or writer is needed in Milestone 3: the replay takes no reference annotation (the marks come from the library), a reference record is recognised by its checksum list (§17.7), and the events of a recording are header comment lines (§15.11). The annotation format part of OP-050 is therefore not implemented.

### 17.3 WFDB header: the subset read (D4)

`parse_wfdb_header(text, record_name, out)` reads the text of `<record>.hea`; `read_wfdb_record` calls it. The subset is the one of the MIT-BIH Arrhythmia and Noise Stress Test databases (all 63 headers checked on 2026-10-11) and of the recordings of §17.6. Anything outside it is rejected with the status of §17.5; nothing is guessed.

**Text.** At most 1 MiB, else `kMalformedHeader`. A NUL byte is malformed; other bytes are accepted (units are kept as written, so that an error names `µV` as such, §8.4). Lines end at LF; one CR before it is removed. Fields are separated by runs of spaces and tabs. A line whose first non-blank character is `#` is a comment, anywhere in the file: its text after `#` and the blanks that follow is kept, in order, in `comments`. Blank lines are skipped.

**Numbers.** An integer is `[+-]?[0-9]+` within the range of its field (else malformed). A decimal (sampling frequency, gain) is `[0-9]+(\.[0-9]+)?`, no sign, no exponent, at most 15 digits in all after leading zeros are removed, at most 15 after the point; its value is `double(m) / double(10^F)` for the integer m of all its digits and F digits after the point. Both operands are exact in binary64, so the quotient is the correctly rounded value of the text, the same double as Python's `float(text)` that the offline loader uses.

**Record line** (the first line that is not a comment): `name nsig fs nsamp [basetime [basedate]]`.

| Field | Accepted | Rejected |
|---|---|---|
| `name` | equal to the record name given (the stem of the file name) | a different name, `kUnsupportedRecord`; `name/n` (multi-segment), `kUnsupportedRecord` |
| `nsig` | integer 1 to 64 | 0 or more than 64, `kMalformedHeader` |
| `fs` | decimal, 125 to 1000 Hz (SRS-003), a whole number of mHz: `fs_millihertz` = m·10^(3−F), or m/10^(F−3) when that is exact | absent, `kMalformedHeader`; `fs/counter`, outside the range or not a whole number of mHz, `kUnsupportedRecord` |
| `nsamp` | integer ≥ 1, at most 86 400 · fs (24 h) | absent, `kMalformedHeader`; 0, `kEmptyRecord`; longer than 24 h, `kTooLong` |
| `basetime`, `basedate` | kept as text, not interpreted | a further field, `kMalformedHeader` |

`fs_hz` is `fs_millihertz / 1000.0`, the same double as the decimal (both correctly rounded).

**Signal lines.** Exactly `nsig` lines follow (comments may come between them): `file format [gain[(baseline)][/units] [adcres [adczero [initval [checksum [blocksize [description]]]]]]]`.

| Field | Accepted | Rejected |
|---|---|---|
| `file` | `[A-Za-z0-9_][A-Za-z0-9._+-]*`, in the folder of the header; every signal names the same file | another form (a path, `-`), `kMalformedHeader`; signals in several files, `kUnsupportedRecord` |
| `format` | `16` or `212`, the same for every signal | another number, `kUnsupportedFormat`; a modifier `x`, `:` or `+` (samples per frame, skew, byte offset), `kUnsupportedRecord` |
| `gain` | decimal ≥ 0; **0 or absent means 200 adu/mV**, the WFDB default (the noise records `bw`, `em`, `ma` state 0) | malformed text, `kMalformedHeader` |
| `baseline` | integer in parentheses; absent means `adczero` | malformed, `kMalformedHeader` |
| `units` | after `/`, kept as written; absent means `mV` | for signal 0: anything but exactly `mV`, `kUnsupportedUnits` naming the units |
| `adcres` | integer, not used | malformed, `kMalformedHeader` |
| `adczero` | integer, default 0 | malformed, `kMalformedHeader` |
| `initval`, `checksum` | integers; for signal 0 they are checked against the samples (§17.4) | malformed, `kMalformedHeader` |
| `blocksize` | 0 | another value, `kUnsupportedRecord` |
| `description` | the rest of the line, may be empty (e.g. `MLII`) | — |

```cpp
enum class WfdbFormat : std::uint8_t { kFormat16, kFormat212 };
struct WfdbSignal {
  std::string file_name;
  WfdbFormat format = WfdbFormat::kFormat16;
  double gain_adu_per_mv = 200.0;        // 200 when the header gives 0 or nothing
  std::string gain_text;                 // as written, or "200" when the header gives 0 or nothing
  std::int32_t baseline_adu = 0;         // adczero when not given
  std::int32_t adc_zero_adu = 0;
  std::string units;                     // as written; "mV" when not given
  std::optional<std::int32_t> initial_value_adu;
  std::optional<std::int32_t> checksum;
  std::string description;
};
struct WfdbHeader {
  std::string record_name;
  std::uint32_t fs_millihertz = 0;
  double fs_hz = 0.0;
  std::uint64_t sample_count = 0;        // per signal
  std::string base_time, base_date;      // as written, may be empty
  std::vector<WfdbSignal> signals;       // nsig entries
  std::vector<std::string> comments;     // in file order
};
[[nodiscard]] bool parse_wfdb_decimal(std::string_view text, double& value) noexcept;
[[nodiscard]] WfdbResult parse_wfdb_header(std::string_view text, std::string_view record_name,
                                           WfdbHeader& out);
```

### 17.4 Signal formats 16 and 212, and physical values (D4)

```cpp
struct WfdbRecord {
  WfdbHeader header;
  std::vector<std::int16_t> signal0_adu;   // the first stored signal, header.sample_count values
  [[nodiscard]] double physical_mv(std::size_t i) const noexcept;   // (d − baseline) / gain, binary64
  [[nodiscard]] float sample_mv(std::size_t i) const noexcept;      // physical_mv(i) rounded once to binary32
};
// record_path: the record without extension, e.g. data/mitdb/100 (as the offline loader of §8.4).
[[nodiscard]] WfdbResult read_wfdb_record(const std::filesystem::path& record_path, WfdbRecord& out);
```

- **Reading.** `read_wfdb_record` reads `<record_path>.hea`, parses it with the stem of `record_path` as the record name, then reads the signal file. With T = nsig · nsamp values stored interleaved (value j = t · nsig + s for sample t of signal s), the file must have at least 2T bytes (format 16) or ⌈3T/2⌉ bytes (format 212), else `kTruncatedSignal` naming both sizes; further bytes are ignored, as `wfdb` does. Only signal 0 is decoded and kept.
- **Format 16.** Value j is the little-endian two's-complement 16-bit integer at byte 2j.
- **Format 212.** Values are packed in pairs in 3 bytes: for the pair q = ⌊j/2⌋ at bytes b0 b1 b2 from byte 3q, the even value is `b0 | (b1 & 0x0F) << 8` and the odd value `b2 | (b1 & 0xF0) << 4`, each a 12-bit two's-complement number (subtract 4096 from values ≥ 2048). When T is odd the last value uses b0 and b1 only, and the file ends there: `wfdb` 4.3.1 writes 5 bytes for 3 values (`01 08 05 ff 07` for −2047, 5, 2047; checked on 2026-10-11).
- **Checks of signal 0**, in this order, with the index of the first failing sample: the WFDB invalid-sample code (−32768 in format 16, −2048 in format 212), `kInvalidSampleValue` (the offline loader would return a NaN, which no frame can carry); `initval` when given equals the first value, and `checksum` when given equals the sum of all values modulo 2¹⁶ as a signed 16-bit number, else `kChecksumMismatch`; every `sample_mv(i)` at most 1000 mV in magnitude (`std::fabs(x) > 1000.0F` fails, the test of the library, SRS-018), else `kSampleOutOfRange`. All 63 reference records pass these checks (checked on 2026-10-11: no invalid code in signal 0, every checksum and initial value equal, largest magnitude 30.6 mV in `118e_6`).
- **Physical value.** `physical_mv(i) = (static_cast<double>(d) − static_cast<double>(baseline)) / gain_adu_per_mv`: an exact subtraction and one correctly rounded division, the operations of `wfdb.rdrecord(..., physical=True, return_res=64)`, so the value equals the offline loader's (SRS-002, §8.4) bit for bit. The stream carries `sample_mv(i) = static_cast<float>(physical_mv(i))` (§15.9).
- **Memory.** Signal 0 only, as 16-bit values: 2 bytes per sample (3.7 MB for a 30 min record at 360 Hz plus the file buffer; at most 173 MB for 24 h at 1000 Hz). The values are converted when a frame is built.

### 17.5 Status and messages of the reader and writer (D4)

```cpp
enum class WfdbStatus : std::uint8_t {
  kOk, kCannotRead, kMalformedHeader, kUnsupportedRecord, kUnsupportedFormat, kUnsupportedUnits,
  kEmptyRecord, kTooLong, kTruncatedSignal, kChecksumMismatch, kInvalidSampleValue, kSampleOutOfRange,
  kMalformedRecording, kReferenceMismatch, kStartBeyondEnd,                        // reading, replay
  kInvalidName, kInvalidMetadata, kAlreadyExists, kWriteFailed, kSampleOutOfFormat,
  kTooManyEvents, kEmptyRecording, kWriterFailed,                                  // writing
};
struct WfdbResult {
  WfdbStatus status = WfdbStatus::kOk;
  std::string message;   // empty for kOk; otherwise one sentence for the user, as below
  [[nodiscard]] bool ok() const noexcept { return status == WfdbStatus::kOk; }
};
```

A failed read leaves `out` unspecified and is never used: no replay is created from it, so no stream is produced (SRS-039). The message starts with the record name and names the cause; `<r>` is the record name, `<f>` a file name, `<k>` a line number:

| Status | Message |
|---|---|
| `kCannotRead` | `<r>: cannot read <f>` |
| `kMalformedHeader` | `<r>: header line <k> is not valid WFDB: <what>` |
| `kUnsupportedRecord` | `<r>: <feature> is not supported` (e.g. `multi-segment records`, `sampling frequency 100 Hz (125 Hz to 1000 Hz only)`, `record name 'x' in the header`) |
| `kUnsupportedFormat` | `<r>: signal format <n> is not supported (formats 16 and 212 only)` |
| `kUnsupportedUnits` | `<r>: signal units '<u>' are not mV` |
| `kEmptyRecord` | `<r>: the record has 0 samples` |
| `kTooLong` | `<r>: the record is longer than 24 h` |
| `kTruncatedSignal` | `<r>: the signal file <f> has <b> bytes, <n> are needed` |
| `kChecksumMismatch` | `<r>: the samples do not match the checksum (or the initial value) in the header` |
| `kInvalidSampleValue` | `<r>: sample <i> holds the WFDB invalid-sample code` |
| `kSampleOutOfRange` | `<r>: sample <i> is <x> mV, beyond 1000 mV` |
| `kMalformedRecording` | `<r>: header line <k> is not a valid Sinus recording line: <what>` |
| `kReferenceMismatch` | `<r>: <f> does not match the verified checksum list of the <database title>` (or `is missing from …`) |
| `kStartBeyondEnd` | `<r>: the start position (sample <s>) is not before the end of the record (<n> samples)` |
| writer statuses | `Recording <r>: <cause>` (§17.6) |

QA and the developer test the status; the message is checked for the record name and, where the table names a value (format, units, sizes, index), for that value.

### 17.6 Recording writer and the recording header (D4; content of SRS-051 and SRS-052 in D7)

**Header of a recording** (a WFDB record with one signal in format 16, §15.11). With `<n>` the record name, `<fs>` the sampling frequency written from `fs_millihertz` with its integer part and up to three decimals, trailing zeros and point removed (`360`, `128.5`), `<N>` the sample count, `<g>` the gain text, `<b>` the baseline, `<i0>` the first sample and `<c>` the checksum (both in adu):

```
<n> 1 <fs> <N>
<n>.dat 16 <g>(<b>)/mV 16 0 <i0> <c> 0 ECG
# sinus_recording=1
# start_utc=2026-10-11T10:20:30.123Z
# source=test
# source_name=127.0.0.1:45000
# mains_hz=50
# desktop_version=0.3.0.dev0
# desktop_source_sha256=<64 hex>
# library_version=0.3.0.dev0
# library_source_sha256=<64 hex>
# event=gap at_sample=3600 missing_samples=1080
# event=interruption at_sample=5400 missing_samples=0 duration_ms=1500
```

- Lines end with LF. Comment lines are `# ` then `key=value` pairs separated by one space; keys `[a-z0-9_]+`, values printable ASCII without space or `=`. The metadata lines come in the order above, each once; event lines follow in increasing `at_sample`. The sampling frequency and the scale are those of the header lines (no duplicate in the comments).
- `source` is `test` or `replayed` (a recording of a replay of a recorded session is again `replayed`, SRS-051); `source_name` is the record or session name for a replay, `127.0.0.1:<port>` for the test input (D7); `start_utc` is ISO 8601 UTC with milliseconds; `mains_hz` is 50 or 60.
- **Events.** `at_sample` is the position in the recorded samples of the first sample after the event, 1 to N − 1. `missing_samples` is the number of session indices skipped before that sample (§17.12: the jump of the stream counter, 0 when there is none). `duration_ms` (interruptions only) is the time without samples on the application clock, rounded down.
- The offline loader reads such a record without conversion: `load_record(path, annotator=None)` (a recording has no annotation file); `wfdb` returns the comment lines without the `# ` (checked on 2026-10-11 with `wfdb` 4.3.1).

```cpp
enum class RecordingSource : std::uint8_t { kTest, kReplayed };
struct RecordingMetadata {
  std::string start_utc;
  RecordingSource source = RecordingSource::kTest;
  std::string source_name;
  MainsFrequency mains = MainsFrequency::k50Hz;
  std::string desktop_version, desktop_source_sha256, library_version, library_source_sha256;
};
enum class RecordingEventKind : std::uint8_t { kGap, kInterruption };
struct RecordingEvent {
  RecordingEventKind kind = RecordingEventKind::kGap;
  std::uint64_t at_sample = 0;
  std::uint64_t missing_samples = 0;
  std::uint64_t duration_ms = 0;     // kInterruption only
};
inline constexpr std::size_t kMaxRecordingEvents = 10000;
inline constexpr std::uint64_t kMaxMissingSamples = 86400000;   // 24 h at 1000 Hz
// The comment lines (without "# ") of the metadata and events, in the order above.
[[nodiscard]] std::vector<std::string> recording_comment_lines(const RecordingMetadata& metadata,
                                                              const std::vector<RecordingEvent>& events);
// Reads the comments of a header. Returns kOk with has_recording false when no comment is
// "sinus_recording=..."; otherwise every rule above must hold (kMalformedRecording).
[[nodiscard]] WfdbResult parse_recording_comments(const WfdbHeader& header, bool& has_recording,
                                                  RecordingMetadata& metadata,
                                                  std::vector<RecordingEvent>& events);
```

`parse_recording_comments` rejects with `kMalformedRecording` (naming the line): a version other than `1`; a missing, repeated or unknown key; a value outside its rule (`mains_hz` other than 50 or 60, `source` other than `test` or `replayed`, a digest that is not 64 lowercase hex digits); an event out of order, at a position outside 1 to N − 1, with `missing_samples` above `kMaxMissingSamples`, or beyond `kMaxRecordingEvents`. Comments that do not start with a Sinus key before the `sinus_recording` line are allowed (none are written).

**Writer.**

```cpp
struct RecordingFormat {
  std::uint32_t fs_millihertz = 0;
  std::string gain_text;               // "1000" for the test input; the source record's gain_text for a replay
  double gain_adu_per_mv = 0.0;        // the value of gain_text (parse_wfdb_decimal)
  std::int32_t baseline_adu = 0;       // 0 for the test input; the source record's baseline for a replay
};
class WfdbRecordingWriter {
 public:
  WfdbRecordingWriter() noexcept;
  ~WfdbRecordingWriter();              // abandon() if not finished
  [[nodiscard]] WfdbResult open(const std::filesystem::path& folder, std::string_view record_name,
                                const RecordingFormat& format, const RecordingMetadata& metadata);
  [[nodiscard]] WfdbResult append(const float* samples_mv, std::size_t count);
  [[nodiscard]] WfdbResult add_event(RecordingEventKind kind, std::uint64_t missing_samples,
                                     std::uint64_t duration_ms);   // at the current sample count
  [[nodiscard]] WfdbResult finish();   // header, flush, rename: the record is complete
  void abandon() noexcept;             // closes; leaves only the .partial files
  [[nodiscard]] std::uint64_t sample_count() const noexcept;
};
```

- `open`: `record_name` matches `[A-Za-z0-9_]{1,64}` (`kInvalidName`); the format and metadata satisfy the rules above, with the gain above 0 and `fs_millihertz` from 125 000 to 1 000 000 (`kInvalidMetadata`); none of `<n>.hea`, `<n>.dat`, `<n>.hea.partial`, `<n>.dat.partial` exists in `folder` (`kAlreadyExists`: nothing is ever overwritten); then `<n>.dat.partial` is created (`kWriteFailed` if it cannot be).
- `append`: each sample becomes `d = std::round(static_cast<double>(x) * gain) + baseline` (half away from zero); a sample that is not finite, and d outside −32767 to 32767, is `kSampleOutOfFormat` (the finiteness is checked first: a NaN fails every comparison) (−32768 is the invalid-sample code; OP-082 (a): a failure, never a clipped value). For gain 1000 the product of a binary32 value and 1000 is exact in binary64, so the stored value is within half an adu of the source (SRS-051); for a replay, written with the source's gain and baseline, `d` is the source's own value (the binary32 rounding moves (d − b)/g by at most 2⁻²⁴ relative, far below half an adu for |d − b| < 65 536), so the round trip is exact. Values go to a 64 KiB buffer written to the stream when full; the stream state is checked after each write (`kWriteFailed`, which covers a full disk). The first value and the running sum (for the checksum) are kept.
- `add_event`: stamps `at_sample` = the current sample count; an event at sample count 0 is not stored (the recording starts with a segment anyway); a second event at the same position replaces nothing and is not stored; the 10 001st event is `kTooManyEvents`.
- `finish`: 0 samples is `kEmptyRecording`; otherwise it flushes and closes `<n>.dat.partial`, writes `<n>.hea.partial` (record line, signal line, comment lines), closes it, checks both, renames `<n>.dat.partial` to `<n>.dat`, then `<n>.hea.partial` to `<n>.hea` (`std::filesystem::rename` with an error code). Any failure is `kWriteFailed`; the files are left as they are, and without `<n>.hea` nothing loads as a record (RC-020).
- **After a failure** every later call returns `kWriterFailed` and writes nothing; the `.partial` files stay (SRS-051: "a file that names itself incomplete"). The writer never deletes a file.

### 17.7 SHA-256 and reference records (D4)

```cpp
using Sha256Digest = std::array<std::uint8_t, 32>;
class Sha256 {
 public:
  Sha256() noexcept;
  void update(const std::uint8_t* data, std::size_t size) noexcept;
  [[nodiscard]] Sha256Digest finish() noexcept;     // then the object is spent
};
[[nodiscard]] std::string to_hex(const Sha256Digest& digest);   // 64 lowercase hex digits
[[nodiscard]] bool sha256_file(const std::filesystem::path& path, Sha256Digest& out);   // false: cannot read

struct ReferenceDatabase {
  std::string_view slug, version, title;
  std::string_view checksum_list_sha256;   // pinned, as MITDB and NSTDB of §8.3
  MainsFrequency mains;                    // 60 Hz for both (SRS-007, SRS-050)
};
extern const std::array<ReferenceDatabase, 2> kReferenceDatabases;   // mitdb 1.0.0, nstdb 1.0.0
enum class ReferenceCheck : std::uint8_t { kNotReference, kVerified };
// Looks for SHA256SUMS.txt in the folder of the record. kNotReference when it is absent or its
// digest is none of the databases'; otherwise every listed file of the record must match.
[[nodiscard]] WfdbResult check_reference_record(const std::filesystem::path& record_path,
                                                const ReferenceDatabase* databases, std::size_t count,
                                                ReferenceCheck& check, const ReferenceDatabase*& database);
```

- **SHA-256**: our own implementation of FIPS 180-4 in `core` (about 150 lines), so that the rule stays in `core` without Qt and its tests run in the Qt-free executable; files are read in blocks of 1 MiB. Rejected: Qt's `QCryptographicHash`, which would put Qt into `core` or need an injected interface for one primitive.
- **Pinned lists**: the two digests and titles of §8.3, the same constants as `sinus_dsp.data.physionet`; a Python cross-check compares them (§17.8).
- **Check**: if `<folder>/SHA256SUMS.txt` is absent, or its SHA-256 is none of the pinned digests, the result is `kNotReference`. Otherwise the list is parsed by the rules of §8.3 (`^([0-9a-fA-F]{64}) [ *]?(\S+)$` per non-empty line, safe relative paths, no duplicate; a list that breaks them is `kReferenceMismatch`), and the files of the record are selected by the rule of §8.3: every top-level path that starts with `<record>.` and continues with at least one character. No such file: `kNotReference` (a record placed in the folder that the database does not publish). Otherwise every selected file must exist and have its listed digest: `kVerified`, with the database; else `kReferenceMismatch` naming the first file in code-point order that is missing or differs. A damaged reference record is rejected rather than replayed with the setting, so that a record of the reference databases is never filtered with the wrong mains frequency (HAZ-002).
- A copy of a reference record outside a verified folder is an "other record" and uses the setting (OP-083, SRS-050); the banner shows which (§17 part 2).

### 17.8 Fixtures and cross-checks with the Python reference (D4)

**Fixture script** `desktop/tests/fixtures/make_wfdb_fixtures.py`, run from `dsp/` with `uv run python ../desktop/tests/fixtures/make_wfdb_fixtures.py`; it exposes `write_fixtures(folder: Path) -> list[Path]` and writes, with `wfdb.wrsamp` of the locked `wfdb` and `sinus_dsp.synthetic.synthetic_ecg`, into `desktop/tests/fixtures/wfdb/` (committed):

| Record | Content | Use |
|---|---|---|
| `f16_one` | format 16, 1 signal, 360 Hz, 37 samples, gain 200, baseline −12; values include −32767, −1, 0, 1, 32767 | reader |
| `f16_two` | format 16, 2 signals, 250 Hz, 25 samples; signal 0 gain 1000 baseline 5, signal 1 gain 100 | reader (signal 0 only) |
| `f212_even` | format 212, 2 signals, 360 Hz, 40 samples, gain 200, baseline 1024; values include −2047, −1, 0, 2047 | reader |
| `f212_odd` | format 212, 1 signal, 360 Hz, 7 samples (odd count: last value in 2 bytes), gain written `200.0` | reader |
| `f212_odd3` | format 212, 3 signals, 5 samples (15 values, odd) | reader |
| `no_units`, `gain_zero`, `fs_frac` | header without units; gain `0` (read as 200); fs `128.5` | reader |
| `replay16` | format 16, 1 signal, 360 Hz, 61 s: `synthetic_ecg(360, 75, "clean")` three times end to end, cut to 61 s, at gain 200 | SRS-039, SRS-041, SRS-050 |
| `replay212` | format 212, 2 signals (the second negated), 250 Hz, 61 s, from `synthetic_ecg(250, 75, "bw-mains50")`, gain 200, baseline 1024 | SRS-039 |
| `session_gap` | a recorded session (§17.6): 360 Hz, 20 s of `replay16`, gain 1000, `source=test`, `mains_hz=60`, a gap event at sample 3600 (`missing_samples=1080`) and an interruption at 5400 (`missing_samples=0`, `duration_ms=1500`) | SRS-039, SRS-050 |
| `refdb/ref1` (a copy of `f16_one` under that name) with `refdb/SHA256SUMS.txt`; `refdb_bad/` the same with one byte of `ref1.dat` changed | a verified folder for an injected `ReferenceDatabase` (its digest computed by the test with `Sha256`) | §17.7, SRS-050 |
| rejection records | `bad_format` (format 80), `bad_units` (`µV`), `truncated` (one byte short), `empty` (0 samples), `multiseg`, `skew` (`16:1`), `offset` (`16+512`), `two_files`, `fs_low` (100 Hz), `no_fs`, `bad_checksum`, `bad_initval`, `invalid_code` (−32768), `name_mismatch`, `too_big` (gain 1, a value of 20 000 mV), `session_bad_mains` (`mains_hz=55`) | §17.5, SRS-039 |

Headers that `wfdb` cannot write (rejections, `gain_zero`) are written as text by the script. The analogue values are converted to adu with `numpy.round` and clipped to the format's range. For each readable record the script writes `<record>.expected`:

```
record=<name>
fs_millihertz=<n>
sample_count=<n>
sha256_binary32=<64 hex>   # SHA-256 of the binary32 samples (little-endian, in order) of the offline loader, rounded once
rows=<k>                   # sample_count for the small reader records; 0 for replay16, replay212, session_gap
<adu> <binary64 bits, 16 hex> <binary32 bits, 8 hex>     # k rows: the loader's value and its rounding
```

and `rejections.txt`, one line `<record> <WfdbStatus name>` per rejection record. Bit patterns in hex avoid any decimal parsing (and the locale that Qt sets, §17.1).

**Python cross-checks** (pytest, `desktop/tests/python/`, collected by the `dsp` configuration through `testpaths`; no requirement marker: developer tests of OP-050):
1. `test_wfdb_fixtures.py::test_fixture_files_are_reproduced` — `write_fixtures(tmp_path)` gives, file for file, the committed bytes (the script is loaded with `importlib.util.spec_from_file_location`).
2. `test_wfdb_fixtures.py::test_expected_values_are_those_of_the_offline_loader` — for every readable fixture, `load_record(path, annotator=None)` gives the fs, the count, the rows and `sha256_binary32` of its `.expected` file. Nothing is required of the loader on the rejection records: the reader is stricter (name, checksum, initial value, range).
3. `test_wfdb_fixtures.py::test_reference_digests_equal_those_of_dsp` — the digests and titles in `desktop/src/core/reference_databases.cpp` equal `MITDB` and `NSTDB`.
4. `test_wfdb_writer.py::test_cpp_recordings_load_in_offline_loader` — reads the folder `SINUS_DESKTOP_WFDB_DIR` (skipped with its reason when unset): for each record written there by the C++ test `WfdbRecordingWriterCrossCheck.WritesRecords` (`xc_test`: gain 1000, values including ±32.767 mV and events; `xc_replay`: the samples of `f212_even` with its gain and baseline) and its `<name>.source` (the binary32 source values in hex), `load_record(path, annotator=None)` loads, the count and fs are equal, every value is within 0.5/gain · (1 + 1e-9) mV of the source (the factor covers the rounding of the loader's division), `xc_replay` equals the loader's values of `f212_even` exactly, and `wfdb.rdheader(...).comments` are the lines of §17.6.
5. `test_wfdb_reference.py::test_cpp_reader_equals_wfdb_on_reference_records` (`needs_data`; also skipped when `SINUS_DESKTOP_WFDB_DUMP` is unset) — runs the test tool `sinus_desktop_wfdb_dump <record_path>` (built with the tests from `desktop/tests/tools/wfdb_dump.cpp`; prints `fs_millihertz=`, `sample_count=`, `sha256_binary64=`, `sha256_binary32=`, or `error=<status>` with exit status 1) on the 48 records of the MIT-BIH Arrhythmia Database and the 15 of the Noise Stress Test Database, and compares with `load_record`.

The C++ unit tests (developer) compare `read_wfdb_record` with each `.expected` file exactly and each rejection with `rejections.txt`. In the `desktop` job, `SINUS_DESKTOP_WFDB_DIR` points to a folder of the runner, the C++ tests run first, then `uv run --project dsp pytest ../desktop/tests/python` (the `dsp` job collects the same tests; check 4 skips there).

### 17.9 Frames and codec (D5)

```cpp
enum class SourceTag : std::uint8_t { kNone = 0, kDevice = 1, kTestInput = 2, kReplay = 3 };
inline constexpr std::size_t kMinFrameSamples = 1, kMaxFrameSamples = 64;
inline constexpr std::size_t kFrameOverheadBytes = 40, kMaxFrameBytes = 296;
inline constexpr std::uint32_t kMinFsMillihertz = 125000, kMaxFsMillihertz = 1000000;
struct Frame {
  // the fields of §15.4
  SourceTag source = SourceTag::kNone;
  std::uint16_t sample_count = 0;
  std::uint32_t stream_id = 0;
  std::uint64_t first_sample = 0;
  std::uint32_t sequence = 0;
  std::uint32_t fs_millihertz = 0;
  std::uint32_t flags = 0;
  std::array<float, kMaxFrameSamples> samples_mv{};
  // in memory only, set by the source
  TimePoint received_at{};          // receipt on the application clock (scheduled release for a replay)
  std::uint32_t source_session = 0; // the selection it belongs to (§17.12)
  bool starts_segment = false;      // replay of a recorded event (§17.11); false from the codec
  RecordingEvent replayed_event{};  // with starts_segment: the recorded event it reproduces (§17.25)
};
enum class StreamItemKind : std::uint8_t { kFrame, kReplayPaused, kReplayResumed, kReplayEnded };
struct StreamItem {
  StreamItemKind kind = StreamItemKind::kFrame;
  Frame frame;   // for a notice: source, source_session and received_at (the time of the event) only
};
enum class FrameRejection : std::uint8_t {
  kAccepted, kTooShort, kBadMagic, kBadVersion, kBadType, kBadSampleCount, kBadLength, kBadCrc,
  kBadSource, kBadReserved, kBadSamplingFrequency, kBadFlags, kBadSample,
};
inline constexpr std::size_t kFrameRejectionKinds = 13;   // including kAccepted
[[nodiscard]] std::uint32_t crc32(const std::uint8_t* data, std::size_t size) noexcept;
// Writes the wire fields of frame (version 1, type 1, reserved 0, CRC); checks only sample_count.
// Returns 40 + 4n, or 0 when sample_count is outside 1..64 or capacity is smaller.
[[nodiscard]] std::size_t encode_frame(const Frame& frame, std::uint8_t* out, std::size_t capacity) noexcept;
void write_frame_crc(std::uint8_t* bytes, std::size_t size) noexcept;   // for tests that alter a field
// Fills the wire fields of out only when it returns kAccepted; the in-memory fields are not touched.
[[nodiscard]] FrameRejection decode_frame(const std::uint8_t* bytes, std::size_t size, Frame& out) noexcept;
[[nodiscard]] std::string_view frame_rejection_name(FrameRejection reason) noexcept;   // e.g. "bad CRC"
```

- **Validation order** of `decode_frame` (the first failing check is the reason): (1) size < 44, `kTooShort`; (2) magic, `kBadMagic`; (3) version ≠ 1, `kBadVersion`; (4) type ≠ 1, `kBadType`; (5) n outside 1 to 64, `kBadSampleCount`; (6) size ≠ 40 + 4n, `kBadLength`; (7) CRC, `kBadCrc`; (8) source not 1 or 2, `kBadSource` (tag 3 is never valid on the wire); (9) a reserved byte not 0, `kBadReserved`; (10) fs outside 125 000 to 1 000 000 mHz, `kBadSamplingFrequency`; (11) flags ≠ 0, `kBadFlags`; (12) a sample not finite or above 1000 mV in magnitude, `kBadSample`. Structure first, then integrity, so that a damaged datagram counts as a CRC error and not as the field the damage happened to hit; then content.
- Fields are assembled from bytes (little-endian, no cast of the buffer); a float is its 32 bits copied with `std::memcpy` (`static_assert(std::numeric_limits<float>::is_iec559)`).
- **Example** (a test vector for both sides): source 2, n = 2, `stream_id` 0x01020304, `first_sample` 0, `sequence` 0, 360 Hz, samples 1.0 and −0.5 mV encode to 48 bytes `534e5346 01 01 02 00 0200 0000 04030201 0000000000000000 00000000 407e0500 00000000 0000803f 000000bf` followed by the CRC 0x2538023C (`3c023825`); `crc32` of `123456789` is 0xCBF43926.
- The codec has no state; the caller counts rejections by reason (the UDP input, D7).

### 17.10 Clock, wake-up and frame queue (D5)

```cpp
using TimePoint = std::chrono::steady_clock::time_point;
using Duration = std::chrono::nanoseconds;
class Clock {
 public:
  virtual ~Clock() = default;
  [[nodiscard]] virtual TimePoint now() const noexcept = 0;
};
class SteadyClock final : public Clock { /* std::chrono::steady_clock::now() */ };
class FakeClock final : public Clock {
 public:
  explicit FakeClock(TimePoint start = TimePoint{} + std::chrono::hours(1)) noexcept;
  [[nodiscard]] TimePoint now() const noexcept override;
  void advance(Duration step) noexcept;        // step >= 0; a negative step is ignored
  void advance_to(TimePoint time) noexcept;    // no effect when time <= now()
};
class Wakeup {          // one waiting thread
 public:
  void notify() noexcept;                         // any thread
  void wait_until(TimePoint deadline) noexcept;   // returns at the deadline (steady clock) or after notify
};
class FrameSink {
 public:
  virtual ~FrameSink() = default;
  [[nodiscard]] virtual bool offer(const StreamItem& item) noexcept = 0;   // false: not taken
};
class FrameQueue final : public FrameSink {
 public:
  static constexpr std::size_t kCapacity = 256;
  explicit FrameQueue(Wakeup* consumer = nullptr);   // allocates the ring once
  [[nodiscard]] bool offer(const StreamItem& item) noexcept override;   // false when full; nothing counted
  void offer_or_drop(const StreamItem& item) noexcept;   // a full queue drops the item and counts it
  [[nodiscard]] bool try_pop(StreamItem& item) noexcept; // consumer
  [[nodiscard]] std::uint64_t dropped_count() const noexcept;
};
```

- `Clock` gives the time only (a refinement of §15.5: waiting is `Wakeup`'s, on the steady clock). The thread classes (§17.13) run on the steady clock; tests that use `FakeClock` call `ReplaySource::poll` and `StreamProcessor::handle`/`tick` directly, with the times of the fake clock, and need no thread.
- `FrameQueue` is a single-producer single-consumer ring of 256 items (acquire/release indices); a successful offer notifies the consumer's `Wakeup`. One producer at a time: the application stops (joins) the previous source before it starts the next (§17.12), which makes the change of producer safe. **Overflow policy:** external sources (test input, device) use `offer_or_drop`: the new item is dropped and counted, and the next accepted frame is a gap (§15.4); the replay uses `offer` and keeps a refused item until it is taken (back-pressure), so a replay never loses a sample.

### 17.11 Replay source (D5; SRS-039, SRS-050)

**Opening.**

```cpp
enum class ReplayRecordKind : std::uint8_t { kReferenceRecord, kRecordedSession, kOtherRecord };
struct ReplayRecord {
  WfdbRecord wfdb;
  ReplayRecordKind kind = ReplayRecordKind::kOtherRecord;
  std::string name;                             // the record name
  std::string database_title;                   // kReferenceRecord: e.g. "MIT-BIH Arrhythmia Database"
  std::optional<MainsFrequency> fixed_mains;    // 60 Hz (reference), the stored value (session); empty: the setting
  std::optional<RecordingMetadata> recording;   // kRecordedSession
  std::vector<RecordingEvent> events;           // kRecordedSession
};
[[nodiscard]] WfdbResult open_replay_record(const std::filesystem::path& record_path, ReplayRecord& out);
// The same, with the list of reference databases given (tests).
[[nodiscard]] WfdbResult open_replay_record(const std::filesystem::path& record_path,
                                            const ReferenceDatabase* databases, std::size_t count,
                                            ReplayRecord& out);
```

`open_replay_record` reads the record (§17.4); then, in this order: if `parse_recording_comments` finds a recording, it is a `kRecordedSession` whose mains frequency is `mains_hz` (a malformed recording is rejected); otherwise `check_reference_record` decides between `kReferenceRecord` (the database's mains frequency, 60 Hz, and title) and `kOtherRecord` (no fixed mains: the setting, OP-083), or rejects a mismatch. Every error is a `WfdbResult` of §17.5, and nothing is replayed.

**Source.**

```cpp
enum class ReplaySpeed : std::uint8_t { kX1 = 1, kX2 = 2, kX5 = 5, kX10 = 10 };
struct ReplaySettings {
  std::uint64_t start_sample = 0;    // position in the record; the UI converts seconds: ⌊ms · fs_millihertz / 10⁶⌋
  ReplaySpeed speed = ReplaySpeed::kX1;
};
enum class ReplayState : std::uint8_t { kReady, kPlaying, kPaused, kEnded, kStopped };
struct ReplayPoll { bool finished = false; TimePoint next_due{}; };
[[nodiscard]] WfdbResult check_replay_settings(const ReplayRecord& record, const ReplaySettings& settings);   // kStartBeyondEnd
// The time from the start at which the stream position `count − 1` is released (floor, in ns).
[[nodiscard]] Duration release_offset(std::uint64_t count, std::uint32_t fs_millihertz, ReplaySpeed speed) noexcept;
[[nodiscard]] std::uint16_t nominal_frame_samples(std::uint32_t fs_millihertz) noexcept;   // ⌊(fs_mHz + 10 000) / 20 000⌋
class ReplaySource {       // thread-safe: one mutex guards the state
 public:
  // Precondition: check_replay_settings(record, settings) is kOk.
  ReplaySource(ReplayRecord record, const ReplaySettings& settings, std::uint32_t source_session);
  void start(TimePoint now) noexcept;     // kReady -> kPlaying; t0 = now
  bool pause(TimePoint now) noexcept;     // kPlaying -> kPaused; false in any other state
  bool resume(TimePoint now) noexcept;    // kPaused -> kPlaying; false in any other state
  void stop() noexcept;                   // -> kStopped; no further item
  [[nodiscard]] ReplayPoll poll(TimePoint now, FrameSink& sink) noexcept;
  [[nodiscard]] ReplayState state() const noexcept;
  [[nodiscard]] TimePoint start_time() const noexcept;      // t0 as given to start
  [[nodiscard]] const ReplayRecord& record() const noexcept;
};
```

- **Frames.** Starting at record position `start_sample`, each frame holds `nominal_frame_samples(fs)` samples (18 at 360 Hz, 13 at 250 Hz; 6 to 50 over 125 to 1000 Hz), fewer only for the last frame of the record or before a recorded event; samples are `wfdb.sample_mv(p)`. Wire fields: `source` 3, `stream_id` 1, `sequence` 0, 1, 2, …, `fs_millihertz` of the header, `flags` 0; `first_sample` is the stream position: 0 for the first sample, increased by the frame's count, and by `missing_samples` at each recorded event. In memory: `source_session` as constructed, `received_at` = the scheduled release time, `starts_segment` true on the first frame after a recorded event at a position after `start_sample` (events at or before it are skipped), with `replayed_event` a copy of that event (v0.8: a recording of the replay copies it, §17.25).
- **Pacing** (SRS-039). The frame whose last sample has stream position L is due at t0 + `release_offset(L + 1, fs, speed)`, where `release_offset` computes, in integers, q = (count · 1000) / (fs_mHz · speed), r = the remainder, and q · 10⁹ + ⌊r · 10⁹ / (fs_mHz · speed)⌋ ns (no overflow for 24 h plus the largest gaps). Every due time is computed from t0, never accumulated, so no drift builds up: the frame holding the sample 60·fs − 1 of the replay is due exactly 60/speed s after t0, and a scheduling delay of the thread does not carry over to later frames (on Windows the timer granularity is about 16 ms, below the 1 % of 6 s at 10 times).
- **`poll(now, sink)`**: when playing, offers in order every frame due at or before `now`; a refused offer stops the poll and the frame is offered again at the next poll (`next_due` = now + 5 ms). After the last frame it offers the notice `kReplayEnded` (time: the last frame's due time) and enters `kEnded`; `finished` is true from then on and in `kStopped`. A pending pause or resume notice is offered first (below). Otherwise `next_due` is the next frame's due time; while paused it is now + 1 s (the thread is woken by `resume`).
- **Pause and resume** (SRS-039 v0.9.1). `pause(now)` stops the releases and queues the notice `kReplayPaused` at `now`; `resume(now)` adds `now − pause time` to t0, queues `kReplayResumed` at `now`, and the releases continue with the next sample, in the same stream and segment. The speed and the start position cannot change on a source: a change is `stop()` and a new `ReplaySource` with a new session, which starts a new segment (SRS-039, SRS-031).
- **Recorded sessions.** A session is replayed with its segments: at each event the stream position jumps by `missing_samples` and the frame starts a segment. The pacing counts the missing samples, so a recorded gap of 3 s is replayed as 3 s without samples (divided by the speed), and the processor sees an interruption when that lasts 1 s or more (§17.12); a recorded interruption without a counter jump is replayed as a segment start without a pause (the duration is kept in the recording, not replayed).

### 17.12 Stream processor (D5; SRS-041 source rules, SRS-050 processing, SRS-039 states)

```cpp
enum class MainsFrequency : std::uint8_t { k50Hz = 50, k60Hz = 60 };   // module mains (D4); no other value exists (SRS-050)
enum class MainsRule : std::uint8_t { kSetting, kFixed };
struct SourceDescription {            // banner data (SRS-041; texts in §17 part 2)
  std::string name;                   // record or session name (replay); empty otherwise
  ReplaySpeed speed = ReplaySpeed::kX1;
  ReplayRecordKind record_kind = ReplayRecordKind::kOtherRecord;
  std::string database_title;
  std::string address;                // test input (D7)
  std::uint16_t port = 0;
};
struct SourceSelection {
  SourceTag tag = SourceTag::kNone;   // kNone: no source
  std::uint32_t session = 0;          // different for every selection (the caller counts)
  MainsRule mains_rule = MainsRule::kSetting;
  MainsFrequency fixed_mains = MainsFrequency::k60Hz;   // with kFixed
  SourceDescription description;
};
[[nodiscard]] SourceSelection replay_selection(const ReplayRecord& record, const ReplaySettings& settings,
                                               std::uint32_t session);
[[nodiscard]] MainsFrequency mains_in_use(const SourceSelection& selection, MainsFrequency setting) noexcept;
enum class CommandKind : std::uint8_t { kSelectSource, kSetMains };
struct Command {
  CommandKind kind = CommandKind::kSelectSource;
  SourceSelection selection;           // kSelectSource
  MainsFrequency mains = MainsFrequency::k50Hz;   // kSetMains
};
enum class SegmentReason : std::uint8_t {
  kSourceStart, kRateChange, kInterruption, kNewStream, kGap, kMainsChange, kRecordedBreak, kLibraryError,
};
struct SegmentInfo {
  std::uint64_t number = 0;            // 1, 2, … since the application started
  SegmentReason reason = SegmentReason::kSourceStart;
  std::uint32_t timeline = 0;          // §below
  std::uint64_t session_start = 0;     // session index of library index 0
  std::uint64_t missing_samples = 0;   // session indices skipped just before it
  TimePoint started_at{};              // received_at of its first frame
  std::uint32_t fs_millihertz = 0;
  MainsFrequency mains = MainsFrequency::k50Hz;
};
struct StreamCounters {                // since the application started
  std::uint64_t frames_accepted = 0, samples_processed = 0;
  std::uint64_t dropped_other_source = 0;   // SRS-041 (another tag or session, or no source)
  std::uint64_t dropped_out_of_order = 0;   // §15.4: an earlier or repeated frame
  std::uint64_t segments = 0, gaps = 0, interruptions = 0, library_rejections = 0;
};
enum class SourceRunState : std::uint8_t { kNoSource, kWaiting, kRunning, kPaused, kEnded };
struct ProcessorState {
  SourceSelection selection;
  SourceRunState run_state = SourceRunState::kNoSource;
  MainsFrequency mains_setting = MainsFrequency::k50Hz;   // 50 Hz at every start (SRS-050)
  MainsFrequency mains_in_use = MainsFrequency::k50Hz;
  bool mains_change_pending = false;
  bool in_segment = false;
  SegmentInfo segment;                 // the current one when in_segment
  std::uint64_t library_index = 0;     // samples of the current segment so far
  std::uint32_t display_delay_samples = 0;   // M of the configured chain (§16.4); 0 before
  bool interrupted = false;            // 1 s without samples (§15.8)
  StreamCounters counters;
};
class ResultSink {
 public:
  virtual ~ResultSink() = default;
  virtual void on_source_selected(const SourceSelection& selection) noexcept { (void)selection; }
  virtual void on_segment_start(const SegmentInfo& segment) noexcept = 0;
  virtual void on_sample(const SegmentInfo& segment, std::uint64_t library_index, float input_mv,
                         const sinus::dsp::SampleOutput& output) noexcept = 0;
};
class StreamProcessor {
 public:
  StreamProcessor() noexcept;                      // no source, setting 50 Hz, chain not configured;
                                                   // holds the chain (about 52.6 KB): create it with std::make_unique
  void apply(const Command& command, TimePoint now) noexcept;
  void handle(const StreamItem& item) noexcept;
  void tick(TimePoint now) noexcept;               // time rules (§15.8)
  void set_result_sink(ResultSink* sink) noexcept; // nullptr: none
  [[nodiscard]] const ProcessorState& state() const noexcept;
};
// §16.4: the display value given with library sample k belongs to library index k − M; none for k < M.
[[nodiscard]] constexpr bool display_library_index(std::uint64_t k, std::uint32_t m,
                                                   std::uint64_t& library_index) noexcept;
[[nodiscard]] constexpr std::uint64_t session_index(const SegmentInfo& segment,
                                                    std::uint64_t library_index) noexcept;   // start + index
```

**Source selection** (SRS-041). `apply(kSelectSource)` makes the selection current, ends the current segment (the next accepted frame starts one, `kSourceStart`), sets `run_state` to `kWaiting` (`kNoSource` for `kNone`), clears `interrupted` and the pending mains change, starts a new timeline at the next frame, and calls `on_source_selected` (D6 clears the heart rate and the marks there). The application changes a source in this order: stop the old source and join its thread; push `kSelectSource` with a new session; start the new source. **A frame or notice whose `(source, source_session)` is not that of the selection is dropped and counted in `dropped_other_source` before anything else**, so it reaches neither the continuity rules nor the library (SRS-041, §15.4); with no source, every item is dropped so. The old source's frames still in the queue are dropped this way.

**Handling a frame**, in this order:
1. Source check (above). In `kEnded`, a frame is dropped (`dropped_other_source`; none is expected).
2. Continuity with the last accepted frame (same `stream_id` and `fs_millihertz`): with `ds = sequence − (last sequence + 1)` modulo 2³² and the expected `first_sample` = last `first_sample` + last count: `ds ≥ 2³¹` (earlier or repeated) or `first_sample` below the expected one: dropped, `dropped_out_of_order`, no other change; `ds ≠ 0` or `first_sample` above the expected one: a gap.
3. Segment start, if any applies, with the first applicable reason of: `kSourceStart` (first frame after a selection), `kRateChange` (another `fs_millihertz`), `kInterruption` (`interrupted`, or `received_at` at least 1 s after the last activity while running: the `received_at` of the last accepted frame, or a later resume notice), `kNewStream` (another `stream_id`), `kGap` (step 2), `kMainsChange` (a pending change), `kRecordedBreak` (`starts_segment`), `kLibraryError` (§below). The chain is configured (`configure` with the frame's fs as `fs_millihertz / 1000.0`, `mains_in_use`, display stage on) at `kSourceStart`, `kRateChange` and whenever the mains frequency in use differs from the chain's, otherwise reset (`reset`, SRS-031). `counters.segments` +1; `gaps` +1 for `kGap`; `on_segment_start` is called.
4. Samples: for each sample, `Chain::process`; with `kOk`, `samples_processed` +1 and `on_sample(segment, library_index, x, output)`, then `library_index` +1. Any other status (impossible for samples checked by the codec or the reader; reachable only by a frame built by hand) counts `library_rejections`, and the next sample, also within the frame, starts a segment `kLibraryError`.
5. The frame becomes the last accepted one; `run_state` becomes `kRunning` (unless paused or ended); `frames_accepted` +1; `interrupted` cleared.

**Session time base** (§15.6). A **timeline** is a run of the session at one sampling frequency: it starts at session index 0 at `kSourceStart` and `kRateChange` (the display of D6 starts afresh, since indices at another rate are not comparable). Within a timeline, the samples of one stream have the session index `stream_base + (first_sample − stream_origin) + k` for the k-th sample of the frame, with `stream_origin` the `first_sample` of the stream's first accepted frame and `stream_base` its session index: a gap therefore leaves exactly its lost samples unused, and an interruption without a counter jump leaves none. A new stream continues at the last session index + 1. `missing_samples` of a segment is `session_start − (last session index + 1)`, 0 for `kSourceStart` and `kRateChange`. The library's indices (detections `index` and `reported_at`, heart-rate `sample` and `beat_index`, windows `first_sample`, `last_sample`, `reported_at`) are segment-relative and map with `session_index(segment, i)`; nothing is joined across segments (RC-014). The display value given with library sample k maps to `session_index(segment, k − M)` for k ≥ M (`display_library_index`, §16.4); the last M samples of a segment have no display value (D6).

**Mains** (SRS-050). `mains_in_use` is `fixed_mains` for `kFixed` and the setting otherwise; `replay_selection` gives `kFixed` with the record's `fixed_mains` for a reference record or a recorded session, `kSetting` for another record (OP-083); the test input (D7) and the device (M4) use `kSetting`. `apply(kSetMains, f)`: a value equal to the setting is ignored; otherwise the setting becomes f, and when the selection follows the setting and a segment runs, `mains_change_pending` is set, so the next sample starts a `kMainsChange` segment with the chain configured at f: the outputs after the change are those of a newly configured library given the samples after it. With `kFixed` the setting is stored and nothing else changes (no segment, no reset). `state().mains_in_use` is updated at once (for the banner), and the chain at the next sample.

**Replay states.** The notices of the current replay set `run_state`: `kReplayPaused` → `kPaused`; `kReplayResumed` → `kRunning`, and the notice time becomes the last activity, so that a pause is never taken for an interruption; `kReplayEnded` → `kEnded`. `tick(now)`: when a segment runs, `run_state` is `kRunning` and `now` is at least 1 s after the last activity, `interrupted` is set and `interruptions` +1 (once per interruption). The rule does not run while paused or ended (§15.8). D6 adds its timers to `tick`.

### 17.13 Commands, snapshot and threads (D5)

```cpp
class CommandQueue {                      // mutex; any number of producers
 public:
  explicit CommandQueue(Wakeup* consumer = nullptr);
  void push(const Command& command);      // notifies the consumer
  [[nodiscard]] bool try_pop(Command& out);
};
struct Snapshot {
  std::uint64_t generation = 0;
  TimePoint taken_at{};
  ProcessorState processor;
  LiveViewData view;   // D6: display model, marks, status, heart rate, quality mark (§17.23)
};
class SnapshotExchange {
 public:
  void publish(const Snapshot& snapshot);   // copies under a mutex; generation + 1
  [[nodiscard]] bool copy_if_newer(Snapshot& out, std::uint64_t& seen_generation) const;
};
class ProcessingWorker {
 public:
  ProcessingWorker(StreamProcessor& processor, FrameQueue& frames, CommandQueue& commands,
                   SnapshotExchange& snapshots, const Clock& clock, Wakeup& wakeup) noexcept;
  ~ProcessingWorker();                    // stop()
  void start();                           // the thread
  void stop() noexcept;                   // request, notify, join
};
class ReplayThread {
 public:
  ReplayThread(ReplaySource& source, FrameSink& sink, const Clock& clock) noexcept;
  ~ReplayThread();
  void start();                           // source.start(clock.now()), then the loop
  bool pause();  bool resume();           // source.pause/resume(clock.now()) and wake the loop
  void stop() noexcept;                   // source.stop(), wake, join
};
```

- **Worker loop.** Pop at most 64 items; **before handling each item, apply every pending command** (with `clock.now()`), so that a command pushed before a source produced an item always takes effect before that item (§15.5: a command takes effect at a defined sample); after the batch, apply pending commands again; call `tick(now)` when 50 ms have passed since the last tick; publish a snapshot after a batch or a tick; if fewer than 64 items were handled, wait on `Wakeup` until the next tick. `FrameQueue` and `CommandQueue` share the worker's `Wakeup`.
- **Replay loop.** `poll(clock.now(), sink)`; stop when `finished`; otherwise wait on its own `Wakeup` until `next_due`.
- Tests of the threads use `SteadyClock`; the timing criterion of SRS-039 is measured through `ReplayThread` (§17.15).

### 17.14 Headless replay (D5; SRS-040)

```cpp
struct HeadlessReplayOptions {
  ReplaySpeed speed = ReplaySpeed::kX1;
  std::uint64_t start_sample = 0;
  MainsFrequency mains_setting = MainsFrequency::k50Hz;
  Duration step = std::chrono::milliseconds(50);   // the worker's tick period
};
[[nodiscard]] WfdbResult run_headless_replay(const std::filesystem::path& record_path,
                                             const HeadlessReplayOptions& options, ResultSink& sink);
// The same, with the list of reference databases given (tests).
[[nodiscard]] WfdbResult run_headless_replay(const std::filesystem::path& record_path,
                                             const ReferenceDatabase* databases, std::size_t count,
                                             const HeadlessReplayOptions& options, ResultSink& sink);
```

It opens the record (§17.11), checks the settings, applies `kSetMains` then `kSelectSource(replay_selection(record, settings, 1))` to a `StreamProcessor` with `sink` attached, starts a `ReplaySource` at a `FakeClock` time, and then repeats: advance the fake clock by `step`; `poll` into a sink that hands each item to `handle` at once; `tick`; until `finished`. The display, `io` and `ui` are not involved. The same code runs at every speed; only the number of frames per step changes (1 at 1 times, 10 at 10 times at 360 Hz), which is what SRS-040 shows does not change a result. A reference record (verified folder) gets 60 Hz, as SRS-040 asks through SRS-007 and SRS-050.

### 17.15 Verification by requirement (D5)

QA's tests are in `desktop/tests/requirements/` (`sinus_desktop_requirement_tests`), the test engineer's in `desktop/tests/system/`, tagged `// Verifies: SRS-nnn`. They use the fixtures of §17.8 (the test executables get their folder as the compile definition `SINUS_DESKTOP_FIXTURE_DIR`), `FakeClock`, and the interfaces above. Reference records come from the folder named by `SINUS_DESKTOP_DATA_DIR` (the `data/` folder of the `dsp` download, with `mitdb/` and `nstdb/`); a test that needs it calls `GTEST_SKIP()` with its reason when the variable is unset or the record is absent. The `desktop` job downloads the six records of SRS-016 with the `dsp` script and its cache (§15.14) and sets the variable.

**SRS-039** (QA):
- *Samples.* For `replay16`, `replay212` and `session_gap`, at each `ReplaySpeed`, a `ReplaySource` polled every 50 ms of a `FakeClock` into a collecting `FrameSink` delivers frames whose samples, in order, equal `read_wfdb_record(...).sample_mv(i)` for every i, and whose binary32 values have the SHA-256 `sha256_binary32` of the `.expected` file (which the Python check ties to the offline loader, §17.8); every frame has `source` kReplay, `fs_millihertz` of the header, `sample_count` = `nominal_frame_samples` except the last (and, for `session_gap`, before each event), consecutive `sequence`, and `first_sample` increasing by the count (plus `missing_samples` at events, where `starts_segment` is true).
- *Timing* (real clock, ctest label `slow`, about 110 s in all): with a `ReplayThread` on `SteadyClock` and a sink that records `SteadyClock::now()` at each offer, the time from `start_time()` to the offer of the frame that holds stream position 60·fs − 1 differs from 60/speed s by less than 1 % at each speed (`replay16`).
- *Pause and resume* (`FakeClock`): `pause` at a time t; no frame is offered at any poll during the following 10 s; the notice `kReplayPaused` is offered; after `resume`, the next frame starts at the next sample (its `first_sample` = previous `first_sample` + previous count, `starts_segment` false), due 10 s later than without the pause; fed to a `StreamProcessor`, `counters.segments` does not change and `run_state` is `kPaused` then `kRunning`.
- *Stop*: after `stop()`, `poll` returns `finished` and offers nothing.
- *Start position*: `start_sample` = 30 · 360 = 10 800 on `replay16`: the first frame holds `sample_mv(10800)` onwards, with `first_sample` 0; `check_replay_settings` with `start_sample` = `sample_count` gives `kStartBeyondEnd`.
- *End*: after the last sample the notice `kReplayEnded` is offered, `state()` is `kEnded`, `poll` is `finished` and no later frame exists; a processor fed with it has `run_state` `kEnded` (the text "Replay ended" is checked with D6/D8).
- *Rejections*: `open_replay_record` on `truncated`, `bad_format` and `empty` returns `kTruncatedSignal`, `kUnsupportedFormat` and `kEmptyRecord`, each with a message that holds the record name (and the format number 80, for `bad_format`); no `ReplaySource` can be built without a record, so no stream is produced.

**SRS-041, source rules** (QA; the banner and the word in the waveform area come with part 2):
- During a replay of `replay16` (selection with session s), a frame with `source` kTestInput, and another with `source` kReplay and session s + 1, handed to `handle` between two replay frames, increase `dropped_other_source` by 2, cause no `on_segment_start` or `on_sample`, and the results of the whole run (every `on_sample` output) equal those of a run without them.
- After `apply(kSelectSource)` of another source (session s + 1): `on_source_selected` is called; frames of the old session still handed in are dropped and counted; the first frame of the new source starts a segment `kSourceStart` at session index 0; every output after the change equals that of a newly configured `sinus::dsp::Chain` given the new source's samples.
- With the selection `kNone`, every frame is dropped and counted.

**SRS-050, processing** (QA; the setting control and its display come with part 2):
- A new `StreamProcessor` has `mains_setting` and `mains_in_use` 50 Hz.
- With a `kSetting` selection of the test input (frames built in memory from `replay16`): `apply(kSetMains, k60Hz)` sets `mains_in_use` at once; the next sample starts a segment `kMainsChange` with `segment.mains` 60 Hz, and every output from it equals that of a new `Chain` configured at 60 Hz given the samples from that sample on. Setting 60 Hz again changes nothing.
- A reference record: `open_replay_record` on `refdb/ref1` with an injected `ReferenceDatabase` (the digest of `refdb/SHA256SUMS.txt`, 60 Hz) gives `kReferenceRecord` and 60 Hz; `refdb_bad/ref1` gives `kReferenceMismatch`. With `SINUS_DESKTOP_DATA_DIR`: `mitdb/100` gives `kReferenceRecord`, the title "MIT-BIH Arrhythmia Database" and 60 Hz; `run_headless_replay` of 100 with `mains_setting` 50 Hz and then 60 Hz gives, both times, the outputs of a `Chain` at 360 Hz and 60 Hz given the same samples; in a replay of 100 driven by hand (`ReplaySource` polled with a `FakeClock`), `apply(kSetMains)` starts no segment and leaves `mains_in_use` at 60 Hz.
- `replay16` (another record) follows the setting: 50 Hz, then 60 Hz after `kSetMains` with a `kMainsChange` segment. `session_gap` (a recorded session) uses its stored 60 Hz whatever the setting.
- No other value: `MainsFrequency` has two values only; the control is part 2.

**SRS-040** (test engineer): for each record, `run_headless_replay` at each speed with a sink that runs a `sinus::dsp::Chain` (fs of the record, 60 Hz) on the same `input_mv` and compares per sample, with the tolerances of SRS-034 (the same code on the same inputs is expected to give equal values). One segment is expected per record (a reference record has no gap). The comparison names the record, the speed, the sample and the output that differ; the failure cases of SRS-040 (one detection removed, one heart rate changed beyond its tolerance) are made by altering the copy that the comparison receives. The subset of SRS-016 runs in CI; all records with `SINUS_DESKTOP_DATA_DIR` set (the milestone verification report, D9).

**Developer's unit tests** (no tag): the number grammar (exactness against values computed by `strtod` in the C locale for decimals of 1 to 15 digits); every acceptance and rejection of §17.3 and §17.4; the `.expected` and `rejections.txt` comparisons; SHA-256 on the FIPS 180-4 examples (`abc`, the 448-bit and 896-bit messages, one million `a`) and on a file; the writer (names, existing files, out-of-format sample with the `.partial` files left, a write failure simulated with a folder that is removed after `open`, events, the exact header text, `finish` with 0 samples); `parse_recording_comments` rules; codec round trip, each rejection reason in the order of §17.9 and the example frame; `FrameQueue` full, wrap-around and `offer_or_drop`; `release_offset` at 125, 250, 360 and 1000 Hz and every speed, including 24 h; frame planning at the record end and at events; processor continuity (each case of step 2), precedence of reasons, session indices across gaps, new streams and rate changes, the library-error path with a hand-made NaN sample, the 1 s rule with `FakeClock`; the worker's command-before-item order with a real thread.

### 17.16 Implementation order of D4 and D5, and part 2

| Step | Group | Task | Cites | Design |
|---|---|---|---|---|
| 1 | D4 | `sha256` | — | §17.7 |
| 2 | D4 | `wfdb_status`, `wfdb_header` (number grammar, header) | — | §17.3, §17.5 |
| 3 | D4 | `wfdb_reader` (formats 16 and 212, checks, physical values) | — | §17.4 |
| 4 | D4 | `mains`, `recording_metadata`, `wfdb_writer` | — (SRS-051, SRS-052 in D7) | §17.6 |
| 5 | D4 | `reference_databases` | — | §17.7 |
| 6 | D4 | fixture script and fixtures, `.expected`, `rejections.txt`, Python cross-checks, `sinus_desktop_wfdb_dump`, the `desktop` job steps (`SINUS_DESKTOP_WFDB_DIR`, pytest after ctest) | — | §17.8 |
| 7 | D5 | `frame`, `frame_codec` | — | §17.9 |
| 8 | D5 | `clock`, `frame_queue`, `command_queue` | — | §17.10, §17.13 |
| 9 | D5 | `replay_record`, `replay_source`; `wfdb_reader` gains its citation | SRS-039, SRS-050 | §17.11 |
| 10 | D5 | `stream_processor` | SRS-039, SRS-041, SRS-050 | §17.12 |
| 11 | D5 | `snapshot`, `workers` | — | §17.13 |
| 12 | D5 | `headless_replay`; the `desktop` job downloads the SRS-016 subset (if group D3 did not add it) and sets `SINUS_DESKTOP_DATA_DIR` | SRS-040 | §17.14 |

D4 is verified by the developer's tests and the cross-checks alone (OP-050 closes when it is merged). D5 lands with QA's tests of SRS-039, SRS-041 (source rules) and SRS-050 (processing) and the test engineer's subset test of SRS-040, on the same branch, because its code cites them (ADR 0004).

**Part 2** (v0.8, §17.17 onwards) designs D6, D7 and the test of SRS-047; D8 follows in part 3. As planned in v0.7, part 2 was to design D6 (display model and drawing input, marks, signal status, heart-rate display, quality mark: SRS-043, SRS-045, SRS-046, SRS-048, on `ResultSink`-like hooks of the processor and its `tick`), D7 (UDP test input with its rejection counters, the recorder thread on `WfdbRecordingWriter` with the events of §17.12: SRS-042, SRS-051, SRS-052 in recordings) and D8 (main window, banner texts, the word "REPLAY" in the waveform area, mains control, replay controls, record command, About box, accessibility: the display part of SRS-041, SRS-049, the setting of SRS-050, SRS-052, SRS-053), and the test engineer's SRS-047 (D9).

### 17.17 Part 2: scope and modules (D6, D7)

Part 2 (v0.8) designs group D6 (the display model and the drawing input, the marks, the signal status, the heart-rate display and the quality mark, in `core`: SRS-043, SRS-045, SRS-046, SRS-048), group D7 (the UDP test input in `core` and `io`, the recorder in `core`: SRS-042, SRS-051, SRS-052 in recordings) and the system test of SRS-047 (D9). The conventions of §17.1 hold; `io` follows them too, except that it uses Qt types inside its classes.

| Module | Group | Content |
|---|---|---|
| `core/display_texts` | D6 | every text that `core` gives the user interface: status, reasons, heart rate, quality mark, test input (§17.18) |
| `core/display_model` | D6 | `DisplayModel` (values, frame timings, marks, drawn edge), `make_drawing_input` (§17.19) |
| `core/signal_status` | D6 | `StreamActivity`, `SignalStatus`, `evaluate_signal_status` (§17.20) |
| `core/heart_rate_display` | D6 | `HeartRateDisplay`, `RestartHold`, `evaluate_heart_rate_display` (§17.21) |
| `core/live_view` | D6 | `QualityMark`, `LiveViewData`, `LiveView` (§17.22, §17.23) |
| `core/test_input` | D7 | `TestInputReceiver`, counters, selection of the test input (§17.24) |
| `io/udp_test_input` | D7 | `UdpTestInput` (socket and thread) (§17.24) |
| `core/recorder` | D7 | `RecordingRequest`, `RecordingChannel`, `RecorderThread`, recorder status and texts (§17.25) |

`stream_processor` and `snapshot` (D5) are extended as §17.23 and §17.25 state.

### 17.18 Display texts (D6, D7; SRS-041, SRS-042, SRS-045, SRS-046, SRS-048)

All texts are ASCII and are given by `core` (`display_texts.hpp`); the user interface shows them as they are (D8). QA's tests compare with these constants, and the user interface's tests with the text shown.

```cpp
enum class StatusReason : std::uint8_t {
  kNone, kNoData, kDataInterrupted, kReplayPaused, kReplayEnded, kCheckingSignalQuality, kLowSignalQuality,
};
enum class HeartRateReason : std::uint8_t {
  kNone, kNoData, kNotEnoughBeats, kNoRecentBeat, kOutOfRange, kSignalNotUsable, kDataInterrupted,
  kReplayPaused, kReplayEnded,
};
enum class QualityMark : std::uint8_t { kNone, kUsable, kNotUsable };
[[nodiscard]] std::string_view status_text(const SignalStatus& status) noexcept;
[[nodiscard]] std::string_view status_reason_text(StatusReason reason) noexcept;
[[nodiscard]] std::string heart_rate_text(const HeartRateDisplay& heart_rate);   // the value or "--"
[[nodiscard]] std::string_view heart_rate_reason_text(HeartRateReason reason) noexcept;
[[nodiscard]] std::string_view quality_mark_text(QualityMark mark) noexcept;
inline constexpr std::string_view kTestInputLabel = "TEST INPUT";
inline constexpr std::string_view kTestInputWarning = "The test input is never to be used with a worn device.";
```

| Function | Value | Text |
|---|---|---|
| `status_text` | usable / not usable | `usable` / `not usable` |
| `status_reason_text` | `kNone` | (empty: the status is usable) |
| | `kNoData` | `no data` |
| | `kDataInterrupted` | `data interrupted` |
| | `kReplayPaused` | `replay paused` |
| | `kReplayEnded` | `replay ended` |
| | `kCheckingSignalQuality` | `checking signal quality` |
| | `kLowSignalQuality` | `low signal quality` |
| `heart_rate_text` | a value v | `<v> bpm`, v in decimal without sign or leading zero (`std::to_string`, which does not depend on the locale): `72 bpm` |
| | withheld | `--` (two hyphen-minus characters) |
| `heart_rate_reason_text` | `kNone` | (empty: a value is shown) |
| | `kNoData` | `no data` |
| | `kNotEnoughBeats` | `not enough beats` |
| | `kNoRecentBeat` | `no recent beat` |
| | `kOutOfRange` | `out of range` |
| | `kSignalNotUsable` | `signal not usable` |
| | `kDataInterrupted` | `data interrupted` |
| | `kReplayPaused` | `replay paused` |
| | `kReplayEnded` | `replay ended` |
| `quality_mark_text` | `kNone` | (empty: no window in the current segment yet) |
| | `kUsable` | `Signal usable` |
| | `kNotUsable` | `Signal not usable: low quality` |

The words of SRS-045, SRS-046 and SRS-048 are used as written. Two texts are not in those lists and are reported for the requirements (§17.29): `no data`, the status and heart-rate reason before the first sample of a source and with no source; and the heart-rate reason `signal not usable` while the status reason is `checking signal quality`. The labels that name each text ("Signal status", "Heart rate", …), the banner and the record command's texts are part 3 (D8).

### 17.19 Display model and drawing input (D6; SRS-043)

**Parameters.**

```cpp
inline constexpr Duration kDisplayDelay = std::chrono::milliseconds(500);   // SRS-043
inline constexpr Duration kMarkLookahead = std::chrono::milliseconds(100);  // below
// Samples of the 10 s window: 10 · fs rounded half up, from fs in mHz (3600 at 360 Hz, 2500 at 250 Hz, 1285 at 128.5 Hz).
[[nodiscard]] constexpr std::uint64_t window_samples(std::uint32_t fs_millihertz) noexcept {
  return (static_cast<std::uint64_t>(fs_millihertz) + 50U) / 100U;
}
```

**Model.** One `DisplayModel` per timeline (§17.12): values in session indices, the timing of the frames, and the marks.

```cpp
enum class MarkShape : std::uint8_t { kFilled, kHollow };          // reliable, start-up (SRS-022)
enum class MarkState : std::uint8_t { kPending, kShown, kSuppressed };
struct BeatMark { std::uint64_t index = 0; MarkShape shape = MarkShape::kFilled; MarkState state = MarkState::kPending; };
struct FrameTiming { std::uint64_t first_index = 0; std::uint16_t count = 0; TimePoint received_at{}; };
class DisplayModel {   // a value type: copied into each snapshot (copy assignment reuses the capacity)
 public:
  static constexpr std::size_t kFrameTimingCapacity = 1024;
  static constexpr std::size_t kMarkCapacity = 256;
  void clear() noexcept;                                                  // no timeline
  void start_timeline(std::uint32_t fs_millihertz, std::uint32_t release_speed);   // allocates; all "no data"
  void add_frame(std::uint64_t first_index, std::uint16_t count, TimePoint received_at) noexcept;
  void set_value(std::uint64_t index, float display_mv) noexcept;
  void add_mark(std::uint64_t index, MarkShape shape) noexcept;
  void decide_marks(TimePoint now, bool status_usable) noexcept;
  [[nodiscard]] bool has_timeline() const noexcept;
  [[nodiscard]] std::uint32_t fs_millihertz() const noexcept;
  [[nodiscard]] std::uint64_t window_samples() const noexcept;
  [[nodiscard]] float value(std::uint64_t index) const noexcept;          // quiet NaN: no data
  [[nodiscard]] std::optional<std::uint64_t> drawn_edge(TimePoint now) const noexcept;
  [[nodiscard]] const std::vector<BeatMark>& marks() const noexcept;      // increasing index
};
```

- **Values.** A ring of C = 2·W floats (W = `window_samples`), a quiet NaN meaning "no data" (the build has no `-ffast-math`, §15.15). It holds the session indices from `newest − C + 1` to `newest`, where `newest` is the last index of the latest frame given to `add_frame`. When `add_frame` moves `newest` forward, every entry of the new indices is set to "no data" first: the samples lost in a gap, the M samples at the end of every segment that never get a display value (§16.4), and the samples not yet filtered stay "no data". `set_value` stores a value whose index lies in the ring and ignores any other; `value` returns "no data" outside the ring. The latest index given a value is kept (`latest_value_index`). C = 2·W keeps 10 s ahead of the drawn window, more than the 0.5 s of the delay at 10 times speed (5 s of samples).
- **Frame timings.** A ring of 1024 `FrameTiming`, the newest last. The time of acquisition of sample i of frame f, with `last = first_index + count − 1` and r = fs · speed (`release_speed` is the replay speed, 1 for every other source), is `received_at − (last − i) / r` (§15.7; v0.8: for a replay the samples of a frame are spread at the release rate, so the times grow from frame to frame at every speed). 1024 frames cover at least 1.02 s at 1000 frames per second, more than the delay plus the look-ahead.
- **Drawn edge** at time t: the largest index i with a value (i ≤ `latest_value_index`) whose time of acquisition is at most t − 0.5 s. Computed in integers: the frames are taken from the newest; for frame f, d = `received_at` − (t − 0.5 s) in ns; d ≤ 0 gives `last`; d ≥ 1 s gives none (no frame spans 1 s: at most 64 samples at 125 Hz, 0.512 s); otherwise k = ⌈d · fs_mHz · speed / 10¹²⌉ (below 10¹⁶, no overflow), which gives `last − k` when k < count and none otherwise. The first frame, from the newest, that gives an index gives the edge (older frames hold smaller indices), then `min(edge, latest_value_index)`. No index: no edge (`std::nullopt`), unless frame timings were dropped from the ring, in which case the edge is the oldest kept frame's `first_index − 1` (only a sender far faster than real time reaches this). When data stop, the edge stops at the last sample with a value (§15.7, §16.4); during a pause of a replay it stops 0.5 s after the pause and starts again 0.5 s after the resume.
- **Marks.** `add_mark` inserts in increasing index (a mark at an index already present is ignored), in state `kPending`, and drops the oldest when 256 marks are held or when the index left the ring. `decide_marks(now, usable)` decides every pending mark whose index is at most `drawn_edge(now + kMarkLookahead)`: `kShown` when the status is usable, `kSuppressed` otherwise. A decision is never changed: a mark shown stays shown and a suppressed mark is never drawn (SRS-043, §15.7). The look-ahead of 100 ms decides a mark before the trace reaches it, so that it appears with its R peak although the processor decides at most every 50 ms (§17.23); a mark reported within 0.35 s (SRS-021) in frames of at most about 0.1 s (18 samples at 360 Hz: 47 ms) is known at most 0.40 s after its acquisition and decided between 0.40 s and 0.45 s, before the trace reaches it at 0.5 s. A mark reported later (search-back, or frames longer than 0.1 s) has its index behind the edge and is decided at its report: it is added onto the trace already drawn, at its index. The status used is that of the decision, up to 100 ms before the trace reaches the mark.
- `start_timeline` reuses the vectors' capacity when the window has the same size; `clear` keeps it.

**Drawing input.** What the waveform widget paints (D8); computed in `core` so that SRS-043 is tested without Qt.

```cpp
struct TraceColumn {
  std::int32_t x_px = 0;
  float first_mv = 0.0F, last_mv = 0.0F, min_mv = 0.0F, max_mv = 0.0F;   // of the samples of the column, in index order
  bool joins_previous = false;   // the previous column holds the sample just before this column's first
};
struct DrawnMark { std::uint64_t index = 0; std::int32_t x_px = 0; MarkShape shape = MarkShape::kFilled; };
struct DrawingInput {
  bool has_edge = false;
  std::uint64_t first_index = 0, edge_index = 0;   // the window drawn: first_index .. edge_index
  std::int32_t cursor_x_px = 0;                    // sweep_x_px(edge_index + 1)
  std::vector<TraceColumn> columns;                // increasing index
  std::vector<DrawnMark> marks;                    // shown marks of the window, increasing index
};
// floor((index mod W) · width_px / W): the fixed position of an index in the sweep (§15.7).
[[nodiscard]] std::int32_t sweep_x_px(std::uint64_t index, std::uint64_t window_samples, std::int32_t width_px) noexcept;
void make_drawing_input(const DisplayModel& model, TimePoint now, std::int32_t width_px, DrawingInput& out);
```

- No timeline, no edge, or `width_px < 1`: `has_edge` false and both vectors empty. Otherwise E = `drawn_edge(now)`, `first_index` = E − W + 1 (0 when E < W − 1): the window spans 10 s once the timeline has 10 s (SRS-043).
- The indices from `first_index` to E are taken in order. A **run** is a maximal stretch of consecutive indices with values that does not cross the left border (an index with `index mod W == 0` starts a new run): a gap, the M samples of a segment end and the border of the sweep therefore break the trace, and nothing is ever drawn across them (HAZ-012). Within a run, consecutive samples with the same `x_px` form one column (minimum, maximum, first and last value: no sample is skipped when there are more samples than pixels); `joins_previous` is true for every column of a run but its first. The widget draws, for each column, a vertical line from `min_mv` to `max_mv` and, when `joins_previous`, a line from the previous column's `last_mv` to its `first_mv`. When there are fewer samples than pixels, each column holds one sample and the lines join them.
- `marks`: the marks in state `kShown` with an index from `first_index` to E, at `sweep_x_px(index)`. Pending marks are not drawn, even when the look-ahead has passed them.
- The vertical scale (mV to pixels) and the shape of the marks (filled or hollow triangle above the trace, §15.7) are part 3; `out`'s vectors keep their capacity from one call to the next.
- The waveform widget repaints at about 60 Hz (D8): the drawing input is exact at each paint, and the repaint period (16.7 ms) keeps the drawn edge within 20 ms of the 0.5 s on the screen (SRS-043).

### 17.20 Signal status (D6; SRS-045)

```cpp
enum class StreamActivity : std::uint8_t { kNoData, kPlaying, kPaused, kEnded };
struct SignalStatus { bool usable = false; StatusReason reason = StatusReason::kNoData; };
struct SignalStatusInputs {
  StreamActivity activity = StreamActivity::kNoData;
  bool interrupted = false;      // 1 s without samples while playing (§17.12)
  bool has_window = false;       // a window was reported in the current segment
  bool window_usable = false;    // the latest one is marked usable (SRS-027)
};
[[nodiscard]] SignalStatus evaluate_signal_status(const SignalStatusInputs& in) noexcept;
```

The processor maps its `run_state` (§17.12): `kNoSource` and `kWaiting` to `kNoData`, `kRunning` to `kPlaying`, `kPaused` and `kEnded` to themselves. The status is not usable with the first reason that applies, in this order, and usable otherwise:

1. `kNoData`: no source, or no sample yet since the source was selected.
2. `kDataInterrupted`: playing and `interrupted`. While paused or ended the 1 s rule does not run (SRS-045 v0.9.1), so a replay that stalled and was then paused reads "replay paused".
3. `kReplayPaused`, `kReplayEnded`: the replay is paused, or has ended (SRS-039).
4. `kCheckingSignalQuality`: no window yet in the current segment, that is since the start of the stream or the last reset (SRS-031): a gap, an interruption, a change of the mains setting and a new stream all start one (§17.12), and the status reads "checking signal quality" until the first window of the new segment, about 10.5 s.
5. `kLowSignalQuality`: the latest window of the segment is not usable.

**Timing** (on the application clock; verified with `FakeClock`, §17.27): an interruption is set by `tick` at most 50 ms after the 1 s has passed, so "data interrupted" is in the snapshot at most 1.05 s after the last frame and on the screen 1.07 s after it (the snapshot is copied at the next paint), within 2 s. A pause and the end are in-band notices handled at once. A window is applied at the sample at which the library reports it, in the batch of its frame; with SRS-027 and SRS-028 a signal that turns constant gives a window not usable at most 5 s + 0.5 s + 1 s after the start of the stretch, and the frame of that sample is handled on arrival, so the status changes within 6.6 s, within 7 s. The 1 s rule counts from the last activity (§17.12): the sample's frame, or a resume. The boundary is "at least 1 s" (§17.12): at exactly 1 s the data are interrupted (SRS-047 says "for 1 s"; SRS-045 says "no more than 1 s" for usable; the overlap of one instant is resolved this way).

### 17.21 Heart-rate display (D6; SRS-046)

```cpp
struct HeartRateDisplay { bool has_value = false; std::int32_t bpm = 0; HeartRateReason reason = HeartRateReason::kNoData; };
class RestartHold {   // SRS-046: withheld until 4 intervals after the status became usable
 public:
  static constexpr std::uint32_t kIntervals = 4;
  void clear() noexcept;                                         // not active
  void arm(std::uint64_t after_index) noexcept;                  // active; counts from 0
  void on_detection(std::uint64_t index, sinus::dsp::Mark mark) noexcept;
  [[nodiscard]] bool active() const noexcept;
  [[nodiscard]] std::uint64_t after_index() const noexcept;
  [[nodiscard]] std::uint32_t intervals() const noexcept;
};
struct HeartRateDisplayInputs {
  SignalStatus status;
  bool hold_active = false;
  bool has_event = false;                       // a library event in the current segment
  sinus::dsp::HeartRateStatus event_status = sinus::dsp::HeartRateStatus::kNotEnoughBeats;
  float event_bpm = 0.0F;                       // of the latest event
};
[[nodiscard]] HeartRateDisplay evaluate_heart_rate_display(const HeartRateDisplayInputs& in) noexcept;
```

**Rules**, the first that applies:

1. Status not usable: withheld, reason from the status reason: `kNoData` → `kNoData`, `kDataInterrupted` → `kDataInterrupted`, `kReplayPaused` → `kReplayPaused`, `kReplayEnded` → `kReplayEnded`, `kCheckingSignalQuality` and `kLowSignalQuality` → `kSignalNotUsable`.
2. Restart hold active: withheld, `kNotEnoughBeats` (SRS-046 as written, whatever the library reports during the hold).
3. No library event in the segment: withheld, `kNotEnoughBeats` (the library's state at the start of a stream, SRS-026).
4. Latest event `kNotEnoughBeats`, `kNoRecentBeat`, `kOutOfRange`: withheld with that reason.
5. Latest event `kValid`: v = `std::lround(static_cast<double>(bpm))` (half away from zero); v outside 30 to 200, or `bpm` not finite, is withheld with `kOutOfRange` (the library already reports a value outside 30–200 as out of range, so this only guards the rounding); otherwise the value v.

The value is the latest event's, with no smoothing; a withheld display has no value at all (`has_value` false, `bpm` 0), so the previous value cannot be shown (SRS-046). The latest event is cleared at every segment start and source selection.

**Restart hold.** At every change of the status from not usable to usable, the hold is armed with `after_index` = the session index of the last sample processed when the change happened: the sample at which the library reported the usable window (§17.23), or the last sample before a resume. It also applies to the first usable status after the start of a stream or a reset, which follows "checking signal quality" (a reading of "after the status has become usable again" that makes one rule for every not usable stretch; reported in §17.29). `on_detection` (every detection of the segment, in report order): a detection whose index is not above `after_index` is ignored (**the tie rule: "after the sample" is strictly after**; a detection at that index, or reported with the window at the same sample, does not count, as in the library, §13.5: index greater than `reset_at`); otherwise, when it and the previous counted detection are both reliable, one interval is counted; a start-up detection counts no interval and breaks the chain (SRS-024: intervals between consecutive reliable detections). With 4 intervals the hold ends, at the report of the fifth reliable detection after `after_index`, which is the sample at which the library reports its heart rate. The hold is cleared at each segment start and source selection (the next usable status arms it again). A change to not usable during the hold leaves it to the next arming.

**Refresh.** The display is evaluated after every item and tick (§17.23) and published in the snapshot, so a value is in the snapshot when its frame is handled (0 s behind on the application clock) and is refreshed at least every 50 ms; the GUI copies it at its next paint (SRS-046: at least once per second, at most 1 s behind).

### 17.22 Quality mark (D6; SRS-048)

`QualityMark` is set when the library reports a window (`kUsable` or `kNotUsable` from `QualityWindow::usable`), in the batch of the frame that holds the report sample, so the mark of each window is in the next snapshot (at most 50 ms later) and on the screen at the next paint, within 1 s of the report. It is cleared (`kNone`, empty text) at every segment start and source selection. No index value or other figure of the window leaves `core` for the display: `LiveViewData` holds the mark only.

### 17.23 Live view in the processor (D6)

```cpp
struct LiveViewData {                 // copied into every snapshot (Snapshot::view, §17.13)
  DisplayModel display;
  SignalStatus status;
  HeartRateDisplay heart_rate;
  QualityMark quality = QualityMark::kNone;
  RestartHold hold;                   // for tests and the log; not displayed
};
class LiveView {
 public:
  void on_source_selected() noexcept;                               // everything cleared, no timeline
  void on_segment_start(bool new_timeline, std::uint32_t fs_millihertz, std::uint32_t release_speed);
  void on_frame(std::uint64_t first_session_index, std::uint16_t count, TimePoint received_at) noexcept;
  void on_sample(std::uint64_t segment_session_start, std::uint64_t library_index,
                 std::uint32_t display_delay_samples, const sinus::dsp::SampleOutput& output) noexcept;
  void update(const SignalStatusInputs& inputs, TimePoint now) noexcept;
  [[nodiscard]] const LiveViewData& data() const noexcept;
};
```

`LiveView` keeps the inputs of the status that come from the library (window seen, latest mark), the latest heart-rate event and the last processed session index; `update` takes the rest from the processor.

- `on_source_selected`: `DisplayModel::clear`, status `kNoData`, heart rate withheld (`kNoData`), quality `kNone`, hold cleared, latest event cleared. The marks and the heart rate disappear at a change of source (SRS-041).
- `on_segment_start`: with `new_timeline` (`kSourceStart`, `kRateChange`) `start_timeline(fs, speed)`; in every case the window flags, the latest event, the quality mark and the hold are cleared. The values and marks of the earlier segments of the timeline stay drawn.
- `on_frame`: `add_frame`.
- `on_sample`, in this order for the sample s (session index `start + library_index`): (1) with `library_index ≥ M`, `set_value(start + library_index − M, output.display_mv)` (§16.4; M from `Chain::display_delay_samples()`); (2) each detection: `add_mark(start + index, kHollow` for `Mark::kStartUp`, `kFilled` otherwise`)` and `hold.on_detection(start + index, mark)`; (3) the window, if any: window flags and quality mark; then the status is evaluated with activity `kPlaying` and `interrupted` false (a sample is arriving), and a change to usable arms the hold with s; (4) the latest heart-rate event (the last of `heart_rates`). Detections reported at s have indices at most s, so the order of (2) and (3) does not change which detections count.
- `update(inputs, now)`: status from `inputs`; a change to usable arms the hold with the last processed session index; `decide_marks(now, status.usable)`; heart-rate display. 

**Calls of the processor** (extension of §17.12): `apply(kSelectSource)` calls `on_source_selected`; in "handling a frame", after step 3 `on_segment_start` when a segment starts (also within the frame for `kLibraryError`, with `new_timeline` false), then `on_frame` with the session index of the frame's first sample, and in step 4 `on_sample` after `ResultSink::on_sample`; at the end of `handle` (frames and notices) `update(inputs, item time)`, the item time being `received_at` (the notice time for a notice), so that `handle` needs no clock; `tick(now)` calls `update(inputs, now)` after the 1 s rule. New accessor: `[[nodiscard]] const LiveViewData& StreamProcessor::view() const noexcept;`. The worker publishes `Snapshot{generation, taken_at, processor state, view}` after each batch and tick (§17.13).

### 17.24 Test input (D7; SRS-042)

**Core.**

```cpp
inline constexpr std::uint16_t kDefaultTestInputPort = 45000;
inline constexpr std::uint16_t kMinTestInputPort = 1024;        // to 65535
inline constexpr std::string_view kTestInputAddress = "127.0.0.1";
[[nodiscard]] std::string test_input_address_text(std::uint16_t port);   // "127.0.0.1:45000"
// tag kTestInput, mains kSetting, description.address "127.0.0.1" and port
[[nodiscard]] SourceSelection test_input_selection(std::uint16_t port, std::uint32_t session);
struct TestInputCounters {
  std::uint64_t datagrams = 0;                                 // every datagram read
  std::uint64_t accepted = 0;                                  // decoded and given to the queue
  std::uint64_t rejected_sender = 0;                           // sender not a loopback address
  std::array<std::uint64_t, kFrameRejectionKinds> rejected{};  // by FrameRejection; [kAccepted] stays 0
  std::uint64_t queue_full = 0;                                // accepted, dropped by a full FrameQueue
  [[nodiscard]] std::uint64_t rejected_total() const noexcept; // rejected_sender + sum of rejected
};
enum class DatagramOutcome : std::uint8_t { kAccepted, kRejectedSender, kRejectedFrame, kQueueFull };
class TestInputReceiver {      // one per start of the input; on_datagram from one thread at a time
 public:
  TestInputReceiver(FrameQueue& queue, std::uint32_t source_session) noexcept;
  [[nodiscard]] DatagramOutcome on_datagram(const std::uint8_t* bytes, std::size_t size,
                                            bool sender_is_loopback, TimePoint received_at) noexcept;
  [[nodiscard]] TestInputCounters counters() const noexcept;   // any thread (relaxed atomics)
};
```

`on_datagram`: `datagrams` +1; a sender that is not a loopback address is counted (`rejected_sender`) and nothing is decoded; otherwise `decode_frame` (§17.9): a rejection is counted under its reason and the datagram is dropped; an accepted frame gets `received_at`, `source_session` and `starts_segment` false and is offered to the queue (`offer`; a refusal is counted in `queue_full` and the frame dropped, the policy of `offer_or_drop`, §17.10). A rejected datagram never reaches the queue, so it changes no output (SRS-042). Every check of the content (length, magic, CRC, sampling frequency, finite samples within 1000 mV, …) is the codec's. A frame with the device tag (1) is valid on the wire and is dropped by the processor as another source (SRS-041). A lost frame (a later `sequence` or `first_sample`), a frame out of order and a duplicate are the processor's continuity rules (§17.12 step 2): the later frame starts a segment `kGap` (or `kInterruption` after 1 s without samples), and the earlier frame that arrives after it is dropped and counted (`dropped_out_of_order`), never given to the library: a lost or out-of-order frame gives a gap and a new segment (SRS-042; SRS v0.9 decision).

**io.**

```cpp
namespace sinus::desktop::io {
struct TestInputStart { bool ok = false; std::string message; };
class UdpTestInput {
 public:
  UdpTestInput() noexcept;           // off: no thread, no socket
  ~UdpTestInput();                   // stop()
  [[nodiscard]] TestInputStart start(std::uint16_t port, core::FrameQueue& queue, std::uint32_t source_session,
                                     const core::Clock& clock);
  void stop() noexcept;              // closes the socket, ends and joins the thread
  [[nodiscard]] bool running() const noexcept;
  [[nodiscard]] std::uint16_t port() const noexcept;
  [[nodiscard]] core::TestInputCounters counters() const noexcept;   // of the current or the last run
};
}
```

- `start`: a port below 1024 is refused with `Test input: port <p> is not allowed (1024 to 65535)`. Otherwise a `QThread` starts with a receiver object moved to it; in that thread (a blocking queued call) a `QUdpSocket` is created, its receive buffer set to 1 MiB (`QAbstractSocket::ReceiveBufferSizeSocketOption`, best effort) and bound with `bind(QHostAddress(QHostAddress::LocalHost), port, QAbstractSocket::DontShareAddress)`: only the IPv4 loopback address, and exclusively (on Windows `DontShareAddress` uses `SO_EXCLUSIVEADDRUSE`, so no other program can bind the same port and read the frames; on Linux and macOS exclusive binding is the default). A failed bind ends the thread and returns `Test input: cannot open UDP port <p> on 127.0.0.1: <QAbstractSocket::errorString()>`; the input stays off. A socket bound to the loopback address only is not reachable from another address of the computer, and does not open the port in the firewall.
- **Receiving.** On `readyRead`, while `hasPendingDatagrams()`: `readDatagram(buffer, 297, &sender, nullptr)` into a buffer of `kMaxFrameBytes + 1` bytes (a longer datagram is truncated to 297 bytes, which no valid frame has, so it is rejected as `kBadLength`); the time is `clock.now()`; `on_datagram(buffer, bytes read, sender.isLoopback(), now)`. A datagram that cannot be read (−1) is counted as `kTooShort`.
- **Off at every start.** The application creates `UdpTestInput` off and never stores its state (no setting is persisted in Milestone 3); the user turns it on (part 3).
- **Order of a change of source** (as §17.12): stop the current source and join it; push `kSelectSource(test_input_selection(port, session))` with a new session; `start`; if it fails, push `kSelectSource` of no source and show the message. Turning off: `stop`, then `kSelectSource` of no source; the status becomes "no data".
- **Texts.** While the input is the source, the banner reads `TEST INPUT` and `test_input_address_text(port)`, and the window shows `kTestInputWarning` (§17.18; placement in part 3). The counters are shown in the main window (part 3).

### 17.25 Recording (D7; SRS-051, SRS-052 in recordings)

The writer is §17.6 (D4); D7 adds the path from the processor to it, on its own thread, and the rules that decide when a recording starts and ends and which events it holds.

```cpp
struct RecordingRequest {
  std::filesystem::path folder;
  std::string record_name;           // default_recording_name(...) unless the user names it
  RecordingFormat format;            // gain and baseline from the application; fs_millihertz set by the processor
  RecordingMetadata metadata;        // start_utc and the four identity fields from the application;
                                     // source, source_name and mains set by the processor
};
[[nodiscard]] RecordingFormat test_input_recording_format();                        // "1000", 1000.0, 0
[[nodiscard]] RecordingFormat replay_recording_format(const ReplayRecord& record);  // signal 0: gain_text, gain, baseline
[[nodiscard]] std::string format_utc_millis(std::int64_t unix_ms);      // "2026-10-11T10:20:30.123Z"
[[nodiscard]] std::string default_recording_name(std::int64_t unix_ms); // "sinus_20261011_102030"
enum class RecordingEnd : std::uint8_t { kStopped, kReplayEnded, kSourceChanged, kMainsChanged, kRateChanged, kMaximumLength };
enum class RecorderState : std::uint8_t { kIdle, kRecording, kSaved, kFailed, kNotStarted };
struct RecorderStatus {
  RecorderState state = RecorderState::kIdle;
  std::string record_name;
  std::uint64_t samples = 0;         // written so far
  std::string message;               // table below
  std::uint64_t generation = 0;      // +1 at every change
};
class RecordingChannel {             // producer: the processing thread; consumer: RecorderThread
 public:
  static constexpr std::size_t kCapacity = 1024;      // items (51 s of 18-sample frames)
  explicit RecordingChannel(Wakeup* consumer = nullptr);
  [[nodiscard]] bool post_open(RecordingRequest request);   // the request goes to a slot under a mutex
  [[nodiscard]] bool post_samples(const float* samples_mv, std::size_t count) noexcept;   // count 1..64
  [[nodiscard]] bool post_event(RecordingEventKind kind, std::uint64_t missing_samples,
                                std::uint64_t duration_ms) noexcept;
  [[nodiscard]] bool post_finish(RecordingEnd end) noexcept;
  void post_not_started(std::string_view cause);            // status kNotStarted at once
  void mark_overflow() noexcept;                            // the producer could not post: the recording fails
  [[nodiscard]] bool busy() const noexcept;                 // items queued, or a writer open
  [[nodiscard]] bool failed() const noexcept;               // the current recording failed
  [[nodiscard]] RecorderStatus status() const;              // any thread
};
class RecorderThread {
 public:
  explicit RecorderThread(RecordingChannel& channel);
  ~RecorderThread();                 // stop()
  void start();
  void stop() noexcept;              // handles the items already posted, finishes an open recording (kStopped), joins
};
```

- **Items.** A fixed-size ring of `kCapacity` plain items (kind, up to 64 samples, event fields, end), single producer and single consumer as `FrameQueue`; only `post_open` and `post_not_started` allocate (at a command, never per sample). A post that finds the ring full returns false.
- **Commands** (extension of §17.12): `CommandKind` gains `kStartRecording` (with `Command::recording`, a `RecordingRequest`) and `kStopRecording`; `ProcessorState` gains `RecordingPhase recording` (`kOff`, `kPending`, `kOn`) and `recording_samples`; `StreamProcessor::set_recording_channel(RecordingChannel*)` (none: the commands are ignored).
  - `kStartRecording`: refused (`post_not_started`) with `a recording is already running` when the phase is not `kOff` or the channel is busy, and with `no data source is playing` when the selection is not the test input or a replay, or `run_state` is `kNoSource` or `kEnded`; otherwise the phase becomes `kPending` and the request is kept. The recording starts at the next accepted frame (waiting for data and a paused replay are allowed).
  - `kStopRecording`: `kOn` → `post_finish(kStopped)`; `kPending` → not started, `stopped before any sample arrived`. Phase `kOff`.
  - `kSelectSource`: `kOn` → `post_finish(kSourceChanged)`; `kPending` → not started, `the source changed`.
  - `kSetMains` that changes the setting while the selection follows the setting: `kOn` → `post_finish(kMainsChanged)` before the change (a record holds one mains frequency, §17.6); `kPending` stays pending and takes the new value.
  - Notice `kReplayEnded`: `kOn` → `post_finish(kReplayEnded)`; `kPending` → not started, `the replay ended`. A pause adds nothing: the samples continue after the resume, without an event.
- **At each accepted frame** (after step 3 of §17.12, before step 4), when the phase is not `kOff`:
  1. `kOn` and `channel.failed()`: phase `kOff` (the recorder has reported the failure).
  2. `kOn` and the segment reason is `kRateChange`: `post_finish(kRateChanged)`, phase `kOff` (a record has one sampling frequency).
  3. `kOn` and `recording_samples + count` above 86 400 · fs (`86400 · fs_millihertz / 1000`, the 24 h of the reader, §17.4): `post_finish(kMaximumLength)`, phase `kOff`.
  4. `kOn` and the frame starts a segment: one event, at the current position of the recording: if `frame.starts_segment` (a replayed recorded event), a copy of `frame.replayed_event` (kind, `missing_samples`, `duration_ms`), so that a recording of a replay of a recording holds the same events; else for `kInterruption`, `kInterruption` with the segment's `missing_samples` and `duration_ms` = ⌊(`received_at` − last activity) / 1 ms⌋; for `kGap` and `kNewStream`, `kGap` with the segment's `missing_samples`; for the other reasons none (`kSourceStart`, `kRateChange` and `kMainsChange` cannot occur while recording; `kLibraryError` is no break of the samples). A gap that lasts 1 s or more on the application clock is therefore an `interruption` event with its `missing_samples`, a shorter one a `gap` event.
  5. `kPending`: the request is completed: `format.fs_millihertz` = the frame's; `metadata.source` = `kTest` for the test input, `kReplayed` for a replay (also of a recorded session, SRS-051); `source_name` = `test_input_address_text(port)` or the replayed record's name; `mains` = `mains_in_use`; `post_open`; phase `kOn`, `recording_samples` 0. No event at this frame (the recording starts with it).
  6. `kOn`: `post_samples` with the frame's samples as received (never the display values), `recording_samples` + count.
  Any post that returns false: `mark_overflow`, phase `kOff`.
- **Recorder thread.** Waits on its `Wakeup` and handles the items in order: open → `WfdbRecordingWriter::open` (status `kRecording`, or `kFailed` with the writer's message; no file exists after a failed open, except `.dat.partial` after a `kWriteFailed` at its creation, which the writer leaves); samples → `append`; event → `add_event`; finish → `finish` (`kSaved`, or `kFailed`). Any writer failure: `abandon`, `failed()` true, status `kFailed`, and every later item of that recording is discarded. Before each item it checks the overflow mark: a marked recording is abandoned and fails. `post_open` clears `failed()` and the mark. The files are therefore complete only after `finish` has renamed them (§17.6); otherwise only `.partial` files exist, which the offline loader does not read as a record (SRS-051, RC-020).
- **Status texts** (`RecorderStatus::message`; shown in the main window, part 3; `<n>` the record name, `<N>` the samples written):

| State | Message |
|---|---|
| `kRecording` | `Recording <n>` |
| `kSaved` | `Recording <n> saved (<N> samples)`, followed, for an end other than `kStopped`, by `; ended because ` and: `the replay ended`, `the source changed`, `the mains frequency changed`, `the sampling frequency changed`, `it reached 24 h` |
| `kFailed` | the writer's message (§17.5, `Recording <n>: <cause>`), followed by `; the incomplete files end in .partial` when a `.partial` file exists; after an overflow: `Recording <n>: samples were lost because the recorder could not keep up; the incomplete files end in .partial` |
| `kNotStarted` | `Recording not started: <cause>` with the causes above |

- **Metadata and identity** (SRS-051, SRS-052): the application fills `start_utc` = `format_utc_millis` of `std::chrono::system_clock` at the command (`core` has no wall clock: the conversion uses the days-to-civil algorithm of H. Hinnant, "chrono-Compatible Low-Level Date Algorithms", no `gmtime`), `desktop_version` and `desktop_source_sha256` from `core::desktop_identity()` (the item identity generated by the build, §15.12), `library_version` and `library_source_sha256` from `sinus::dsp::library_identity()`; the format from `test_input_recording_format()` or `replay_recording_format(record)`. The writer's rules check every field (§17.6). The default name is `sinus_` and the UTC date and time of the command, `YYYYMMDD_HHMMSS`; the folder and the name are chosen in part 3.
- **Exactness** (SRS-051, half of the resolution): §17.6. For the test input at 1000 adu/mV a sample beyond ±32.767 mV fails the recording (OP-082 (a)).
- At the end of the application, the GUI pushes `kStopRecording`, stops the sources and the worker, then `RecorderThread::stop()`, so a running recording is saved (v0.9: the exact order, with the commands left in the queue applied after the worker is joined, is §17.33).

### 17.26 Changes to part 1 in this version

- §17.6: a sample that is not finite is `kSampleOutOfFormat` (a NaN would pass the range test).
- §17.9 and §17.11: `Frame::replayed_event`, set by the replay with `starts_segment` (§17.25, step 4).
- §17.12: the calls of `LiveView` (§17.23), the recording commands, phase and channel (§17.25), `StreamProcessor::view()`.
- §17.13: `Snapshot::view`.
- §15.7: the acquisition times of a replay's samples are spread at the release rate (§17.19); the drawn edge is computed from the frame timings, not carried per sample.

### 17.27 Verification by requirement (D6, D7)

QA's tests are in `desktop/tests/requirements/`, tagged `// Verifies: SRS-nnn`, with `FakeClock` and the interfaces above; a test that needs a real socket or thread says so. **Fixtures added for D6** to the fixture script of §17.8 (format 16, gain 1000, one signal; with their `.expected` files):

| Record | Content |
|---|---|
| `d6_ecg75_360`, `d6_ecg180_360`, `d6_ecg75_250`, `d6_ecg180_250` | 60 s of `synthetic_ecg(fs, bpm, "clean")` repeated end to end, as `replay16` |
| `d6_flat_360` | 75 bpm at 360 Hz: 20 s of ECG, 30 s held at the value of the sample at 20 s, 20 s of ECG (70 s) |
| `d6_noise_360` | 20 s of ECG, 20 s of white Gaussian noise of 0.1 mV RMS alone (seed 20261011), 20 s of ECG |
| `d6_small_beat_360` | the event input `small-beat` of §13.9 at 360 Hz (one beat found by search-back, reported 0.62 s after its index) |

The streams are made as in §17.15: frames of `nominal_frame_samples` built from `sample_mv` with `received_at` at the release times (a `ReplaySource` at speed 1 on a `FakeClock`, or frames built by hand with the test input's tag), handed to a `StreamProcessor`, with `tick` every 50 ms of the fake clock; the view is read with `view()` and drawn with `make_drawing_input(view.display, now, width)` at widths 800 and 4000 px.

**SRS-043** (QA): on the four `d6_ecg*` records: once 10 s have been drawn, `edge_index − first_index + 1 = window_samples`; at every step t, the sample `edge_index` was acquired at most 0.5 s before t and the sample `edge_index + 1` (when received) later than that (exact with the fake clock; the 20 ms of SRS-043 are those of the repaint, part 3); every mark in the drawing input lies within 0.020 · fs samples of the largest display value within ±0.1 s of it (the R peak of the drawn waveform); every reliable detection after the status is first usable is shown, and is present in the first drawing input whose edge reaches its index. `d6_small_beat_360`: the search-back detection is reported after the edge passed its index; it is absent from the drawing inputs before its report and present at its index in every later one within the window. `d6_flat_360`: from the step at which the status becomes not usable, no mark changes to shown until it is usable again; the columns of the flat stretch are drawn (values present) and the edge keeps advancing. Runs: a stream with one frame removed has no column joining across the lost samples (`joins_previous` false at the first column after them). At a change of source the drawing input is empty and `marks()` is empty (SRS-041).

**SRS-045** (QA): `evaluate_signal_status` on every combination of its inputs gives the reason of the first rule that applies (§17.20). Through the processor: from the first frame to the first window, `kCheckingSignalQuality`; on `d6_ecg75_360`, usable after the first window; on `d6_flat_360` not usable with `kLowSignalQuality` at most 7 s after 20 s of the stream (first step at which it holds, on the fake clock), and on `d6_noise_360` not usable during the noise (the windows lying in it); frames stopped for 3 s: `kDataInterrupted` at most 1.95 s after the `received_at` of the last frame (2 s less the repaint period) and the next frame starts a segment with `kCheckingSignalQuality`; a replay of `replay16` paused (`kReplayPaused`, at the step of the pause) and resumed (no interruption, no new segment), then played to the end (`kReplayEnded` at the step of the notice); with several causes (paused while the latest window is not usable; interrupted during checking) the first reason of the list; no source and a selected test input before its first frame: `kNoData`. While not usable, the edge advances and the values are present.

**SRS-046** (QA): `evaluate_heart_rate_display` and `RestartHold` with hand-made inputs, and `LiveView` fed with hand-built `SampleOutput`s at 360 Hz: a valid 72.5 gives 73 and `73 bpm`, 72.49 gives 72; each library reason and each status reason gives `--` and its text of §17.18; an out-of-range event gives `--` and `out of range`; in no case is the previous value shown (after any withheld state the display has no value until a new valid event after the hold); after a not usable stretch, with the library reporting valid values at once, the display stays `--` with `not enough beats` until the report of the fifth reliable detection whose index is above the sample at which the status became usable, and a detection at exactly that index does not count (tie rule); a start-up detection in the chain breaks it. Through the processor on `d6_ecg75_360`: the value shown equals the latest library event rounded at every step, and is in the view at the step of the frame that carried it. Inspection of the absence of colour scale and sound: part 3.

**SRS-048** (QA): on `d6_noise_360` and `d6_flat_360`, after each window reported, `view().quality` at the end of that frame's `handle` is the window's mark, and `quality_mark_text` gives `Signal usable` or `Signal not usable: low quality`; `LiveViewData` has no field with the index (checked by the test of part 3 on the main window).

**SRS-042** (QA): *core*: `TestInputReceiver` with a datagram of each rejection of §17.9 (too short, magic, version, type, sample count, length, CRC, source 3, reserved, sampling frequency, flags, a NaN, an infinity, 1000.1 mV) counts it under its reason, offers nothing, and a stream with those datagrams interleaved gives the same outputs (`ResultSink`) as without them; a datagram with `sender_is_loopback` false is counted and offers nothing; frames of `d6_ecg75_360` give detections and a valid heart rate; a stream with one frame removed gives a segment `kGap`, and every output after it equals that of a new `sinus::dsp::Chain` given the samples after the gap; two frames swapped give a `kGap` segment at the later one and the earlier one counted in `dropped_out_of_order`; a duplicate is counted and dropped. *io* (real loopback socket, `SteadyClock`): a new `UdpTestInput` is not running, and a socket of the test can bind 127.0.0.1:port (nothing holds it); after `start`, valid datagrams sent by the test to 127.0.0.1:port reach the queue, and binding the same port again (from the test, with `DontShareAddress`) fails; a datagram sent to another IPv4 address of the computer (the first non-loopback address of `QNetworkInterface::allAddresses()`; `GTEST_SKIP` when none) at the port is not received (`datagrams` unchanged after 500 ms); a port below 1024 and a port already bound are refused with their messages; `kTestInputWarning` and `kTestInputLabel` are the texts of §17.18 (their display: part 3).

**SRS-051** (QA): with a `RecordingChannel`, a `RecorderThread` and a folder of the test (`SINUS_DESKTOP_RECORDING_DIR` when set, a temporary folder otherwise):
- *Replay*: the first 60 s of `replay16` replayed (`FakeClock`) and recorded (`kStopRecording` applied after the frame that holds sample 21 599): `read_wfdb_record` and `parse_recording_comments` give 21 600 samples equal to the source's `sample_mv` (exactly: the source's gain), fs 360, gain `200`, `source=replayed`, `source_name=replay16`, `mains_hz=50`, `start_utc` as given, the identities of SRS-052, no event. `replay212` the same with its gain and baseline.
- *Test input*: 10 s of frames, then 3 s without frames whose counter jumps by 1080 samples, then 10 s, then 10 frames lost (0.5 s) with the next one 0.55 s after the previous: the recording has the samples received (N = sum of the counts), an event `interruption` at the position of the first sample after the 3 s with `missing_samples=1080` and `duration_ms` ≥ 3000, and an event `gap` with `missing_samples=180` at its position; every sample is within 0.5/1000 mV of the frame's value; `source=test`, `source_name=127.0.0.1:<port>`.
- *Replay of a recording*: that recording replayed and recorded again is `source=replayed` with `source_name` the first recording's name and the same events (kind, position, missing samples, duration).
- *Failure*: a folder that does not exist gives `kFailed` with the writer's message and no file; on Linux when not run as root (`geteuid() != 0`), a read-only folder (mode 0555) gives `kFailed` and no file; on Linux, a file size limit (`setrlimit(RLIMIT_FSIZE)` of 100 KiB with `SIGXFSZ` ignored, restored after the test) makes a write fail during a recording of 200 s at 360 Hz (two buffers of 64 KiB), as a full disk does through the same path: `kFailed`, the message ends with `.partial`, `<n>.hea` does not exist. The other cases `GTEST_SKIP` with their reason. Each refusal of §17.25 gives `kNotStarted` and its message.
- *Offline loader*: `dsp/tests/requirements/test_srs051_desktop_recordings.py` (marker `SRS-051`; skipped with its reason when `SINUS_DESKTOP_RECORDING_DIR` is unset, as in the `dsp` job) loads every complete recording of that folder with `load_record(path, annotator=None)`: the count, the fs and the samples (within 0.5/gain · (1 + 1e-9) mV of the `<n>.source` file that the C++ test writes beside each recording, as in §17.8 check 4), and the comment lines; and checks that no `.partial` record loads (the failure cases). The `desktop` job sets the variable and runs it after `ctest`.

**SRS-052, recordings** (QA): the four identity lines of each recording equal the versions in `desktop/VERSION` and `libs/sinus-dsp/VERSION` and the digests that the test computes itself with the methods of §15.12 and §14.15 from the source tree (`SINUS_DESKTOP_SOURCE_ROOT`, a compile definition of the test executable: the repository root), using `core::Sha256` on the bytes. The About box: part 3.

**Developer's unit tests** (no tag): `window_samples` at 125, 128.5, 250, 360 and 1000 Hz; the ring (no data for new indices, gaps larger than C, values outside the ring ignored); `drawn_edge` against a direct computation over all samples, at speeds 1 and 10, with frames of 1, 18 and 64 samples, at the boundary (a sample acquired exactly 0.5 s before is drawn), with the frame-timing ring overflowed; mark insertion order, duplicates, capacity, decisions never changed, look-ahead; `make_drawing_input` runs, columns, joins, border of the sweep, narrow and wide widths, empty cases; `evaluate_signal_status` and `evaluate_heart_rate_display` tables; `RestartHold` chain and tie; texts; `format_utc_millis` (1970-01-01, 2000-02-29, 2026-10-11, the end of 9999) and `default_recording_name`; `TestInputReceiver` counters across threads; the channel ring full, `mark_overflow`, `busy`; the recorder thread with a writer failure in the middle; every recording rule of §17.25 with the processor and a channel without a thread (items read back with a test consumer).

### 17.28 System test of SRS-047 (D9, test engineer)

In `desktop/tests/system/` (`// Verifies: SRS-047`), ctest label `slow`, about 65 s, in the `desktop` and `desktop-windows` jobs. The code that implements SRS-047 (the 1 s rule of §17.12 and the status and heart-rate rules of §17.20 and §17.21) cites SRS-047 only in D9, with this test (ADR 0004).

- **Set-up.** The whole live path on the real clock: `UdpTestInput` (io) → `FrameQueue` → `ProcessingWorker` with `StreamProcessor` on `SteadyClock` → `SnapshotExchange`; a `ResultSink` on the processor that stores every segment and every output; an observer thread that copies the snapshot every 5 ms (`copy_if_newer`) and logs the steady time, `taken_at`, `status_reason_text`, `heart_rate_text` and `heart_rate_reason_text`. The selection is `test_input_selection(port, 1)` with the default 50 Hz.
- **Stream.** The samples of `replay16` (75 bpm, 360 Hz, 21 960 samples), in frames of 18 samples encoded with `encode_frame` (tag 2), sent from a `QUdpSocket` of the test to 127.0.0.1:port, frame j at t0 + (last sample + 1)/360 s on the steady clock, computed from t0. Positions 0 to 7 199 are sent (20 s); then nothing for 3 s; positions 7 200 to 14 399 follow with the sequence and `first_sample` continuing (an interruption without lost samples), sent from t0 + 23 s; then the 10 frames of positions 14 400 to 14 579 are not sent (0.5 s lost: the sequence and `first_sample` jump); then 14 580 to 21 959 at their times. The pauses are measured from the send time of the last frame before them.
- **Criteria.**
  1. *Interruption shown*: the first snapshot with status reason and heart-rate reason `data interrupted` has `taken_at` at most 1.95 s after the send time of the last frame before the 3 s pause (2 s less the repaint period); from that snapshot to the first snapshot after the restart, every snapshot shows `--` with `data interrupted`, and no snapshot after it shows a value until the end of the hold below (the last value is never shown again).
  2. *Restart*: the frame of position 7 200 starts a segment `kInterruption`; the outputs of the sink for that segment equal, sample by sample (exactly: the same code on the same inputs), those of a new `sinus::dsp::Chain` (360 Hz, 50 Hz) given the samples from 7 200 up to the next segment; its detections with an index in the first 2 s of the segment are marked start-up (at least one); the first snapshot with a value comes after the report of the fifth reliable detection of the segment (four intervals; the restart hold of §17.21 is later still, since it counts from the first usable status).
  3. *Gap under 1 s*: the frame of position 14 580 starts a segment `kGap` with `missing_samples` 180; no snapshot from the last frame before the loss to the end shows `data interrupted`; the segment's outputs equal those of a new chain given the samples from 14 580; the heart rate is withheld until its fourth interval, as in 2.
  4. The run is valid only if the sender kept its schedule: every frame sent within 20 ms of its time (else the test fails with the delays found, not with a criterion).
- The log of snapshots is written to the test output when a criterion fails.

### 17.29 Implementation order of D6 and D7; part 3

| Step | Group | Task | Cites | Design |
|---|---|---|---|---|
| 13 | D6 | `display_texts` | SRS-045, SRS-046, SRS-048 | §17.18 |
| 14 | D6 | `display_model` (model, edge, marks, drawing input) | SRS-043 | §17.19 |
| 15 | D6 | `signal_status`, `heart_rate_display` | SRS-045, SRS-046 | §17.20, §17.21 |
| 16 | D6 | `live_view`; the calls of the processor, `view()`, `Snapshot::view` | SRS-043, SRS-045, SRS-046, SRS-048 | §17.22, §17.23 |
| 17 | D6 | the `d6_*` fixtures and their `.expected` files | — | §17.27 |
| 18 | D7 | `test_input` (core), `udp_test_input` (io; Qt Network linked to `io` only) | SRS-042 | §17.24 |
| 19 | D7 | `Frame::replayed_event` and its setting in `ReplaySource` (if D5 has merged without it) | — | §17.26 |
| 20 | D7 | `recorder` (channel, thread, texts, UTC), the recording commands and rules of the processor; `wfdb_writer` and `recording_metadata` gain their citations | SRS-051, SRS-052 | §17.25 |
| 21 | D7 | the `desktop` job sets `SINUS_DESKTOP_RECORDING_DIR` and runs QA's Python check after `ctest` | — | §17.27 |

D6 lands with QA's tests of SRS-043, SRS-045, SRS-046 and SRS-048 (at the level of `core`; the texts on the screen are checked again in part 3), D7 with those of SRS-042, SRS-051 and the recording part of SRS-052, each on the branch of its code (ADR 0004). SRS-047 is cited and tested in D9 (§17.28).

**Readings reported for the requirements** (confirmed by the project owner on 2026-10-12, `srs.md` v0.9.5; the design implements them and changes only a constant or a rule if they are decided otherwise): (1) SRS-045 and SRS-046 have no reason for the time before the first sample of a source and with no source: the design shows `no data` for both. (2) SRS-046 lists no heart-rate reason for "checking signal quality": the design shows `signal not usable`. (3) SRS-046 "after the status has become usable again" is applied to every change from not usable to usable, including the first after the start of a stream or a reset: the first heart rate of a stream comes four intervals after the first usable window (about 10.5 s + 3.2 s at 75 bpm, 18.5 s at 30 bpm). (4) The marks of a stream's first 10.5 s are never drawn, since the status is "checking signal quality" then (SRS-043 with SRS-045): the hollow start-up marks of the first 2 s are therefore not seen; they are seen when detection learns its levels again in a usable signal.

**Part 3** (v0.9, §17.30 to §17.44) designs D8: the main window, the top bar with the intended-use statement and the banner, the waveform widget on `make_drawing_input` (vertical scale, mark shapes, the word "REPLAY"), the status, heart-rate and quality panels with their accessible names, the mains setting, the replay controls, the test-input controls and counters, the record command and its status, the About box, and the accessibility test method (SRS-041 display, SRS-043 widget, SRS-045, SRS-046 and SRS-048 texts shown, SRS-049, SRS-050 setting, SRS-052 About, SRS-053).

### 17.30 Part 3: scope, layers and modules (D8)

Part 3 (v0.9) designs group D8 of §15.18: the main window, the top bar, the waveform widget, the panels, the controls, the About box and accessibility (the display part of SRS-041, the widget part of SRS-043, the texts shown of SRS-045, SRS-046 and SRS-048, SRS-049, the setting of SRS-050, the About part of SRS-052, SRS-053, and the controls of SRS-039, SRS-042 and SRS-051). The rule of §15.2 holds: every rule that decides a text, an enabled state or a position on the screen is a `core` function tested without Qt; `ui` builds the widgets, copies the snapshot and shows what `core` gives; `app` owns the threads and the sources.

| Module | Group | Content |
|---|---|---|
| `core/display_texts` | D8 (extended) | the intended-use statement, the "REPLAY" label, the no-source banner, the accessible names and descriptions (§17.31, §17.37) |
| `core/main_view` | D8 | `MainViewTexts`, `make_main_view_texts`, banner, mains, replay state, record summary and counter texts, `max_start_seconds`, `ControlInputs`, `ControlStates`, `evaluate_control_states` (§17.31, §17.32) |
| `core/about` | D8 | `AboutInfo`, `about_text` (§17.39) |
| `core/waveform_geometry` | D8 | `WaveformGeometry`, `make_waveform_geometry`, `trace_y_px` (§17.36) |
| `ui/session_port` | D8 | `ActionResult`, `SessionPort`: what the window asks of the session (§17.33) |
| `ui/readout_field` | D8 | `ReadoutField` (§17.37) |
| `ui/waveform_view` | D8 | `WaveformView`, `WaveformPanel` (§17.36) |
| `ui/top_bar` | D8 | `TopBar` (§17.34) |
| `ui/main_window` | D8 | `MainWindow` (§17.34, §17.35, §17.38) |
| `ui/about_dialog` | D8 | `AboutDialog` (§17.39) |
| `app/session_controller` | D8 | `SessionController`, the implementation of `SessionPort` that owns the queues, threads and sources (§17.33) |
| `app/about_info`, `app/main.cpp` | D3, D8 | `about_info()`; command line, wiring, shutdown (§17.33, §17.39) |

Dependencies: `ui` uses `core` and Qt Widgets, never `io`; `app` uses `ui`, `io` and `core`. Namespaces `sinus::desktop::ui` and `sinus::desktop::app`. Texts cross from `core` to Qt with `QString::fromStdString` (they are ASCII) and paths with `QFileInfo::filesystemFilePath()` (§17.1). The rules of §15.15 apply (exceptions off, RTTI on, widgets owned by their parent).

Changes to parts 1 and 2 in this version: the shutdown order of §17.25 is made exact in §17.33; `display_texts` (§17.18) gains the constants of §17.31 and §17.37; §15.7's repaint "at about 60 Hz" is the 16 ms timer of §17.35.

### 17.31 Texts of the main window (D8; SRS-039, SRS-041, SRS-042, SRS-049, SRS-050)

```cpp
// display_texts (added in D8)
inline constexpr std::string_view kIntendedUseStatement =
    "Not a medical device, not for diagnosis or health decisions";   // SRS-049, exactly, no final full stop
inline constexpr std::string_view kReplayWaveformLabel = "REPLAY";   // SRS-041, waveform area
inline constexpr std::string_view kNoSourceBanner = "NO SOURCE";

// main_view
struct MainViewTexts {
  std::string source_banner;                 // top bar (SRS-041)
  bool replay_label = false;                 // kReplayWaveformLabel in the waveform area
  bool test_input_warning = false;           // kTestInputWarning in the top bar (SRS-042)
  std::string heart_rate, heart_rate_reason, quality_mark, signal_status, signal_status_reason;   // §17.18
  std::string mains_in_use;                  // SRS-050
  std::string replay_state;                  // SRS-039; empty unless a replay is the source
  std::string stream_counters;               // empty unless the test input is the source
};
[[nodiscard]] std::string source_banner_text(const SourceSelection& selection, MainsFrequency mains_in_use);
[[nodiscard]] std::string mains_in_use_text(const SourceSelection& selection, MainsFrequency mains_in_use);
[[nodiscard]] std::string_view replay_state_text(SourceRunState run_state) noexcept;
[[nodiscard]] std::string format_hz(std::uint32_t fs_millihertz);            // "360", "128.5", "0.125"
[[nodiscard]] std::string record_summary_text(const ReplayRecord& record);
[[nodiscard]] std::string stream_counters_text(const TestInputCounters& input, const StreamCounters& stream);
[[nodiscard]] MainViewTexts make_main_view_texts(const ProcessorState& processor, const LiveViewData& view,
                                                 const TestInputCounters& input);
// The largest start in whole seconds whose sample ⌊s · fs_mHz / 1000⌋ is before the end: ⌈count · 1000 / fs_mHz⌉ − 1.
[[nodiscard]] std::uint64_t max_start_seconds(std::uint64_t sample_count, std::uint32_t fs_millihertz) noexcept;
```

Exact texts (`<name>`, `<title>`: `SourceDescription::name` and `database_title`; `<N>`: 1, 2, 5 or 10; `<F>`: 50 or 60, the frequency in use; the speed is written with the letter `x`, since every text is ASCII, §17.18):

| Function | Case | Text |
|---|---|---|
| `source_banner_text` | no source | `NO SOURCE` |
| | replay of a reference record | `REPLAY: record <name> (<title>), x<N>, mains <F> Hz (fixed by the record)` |
| | replay of a recorded session | `REPLAY: session <name>, x<N>, mains <F> Hz (stored in the session)` |
| | replay of another record | `REPLAY: record <name>, x<N>, mains <F> Hz (setting)` |
| | test input | `TEST INPUT: udp 127.0.0.1:<port>, mains <F> Hz (setting)` |
| | device (not selectable in Milestone 3) | `DEVICE` (completed in Milestone 4) |
| `mains_in_use_text` | the three origins | `<F> Hz (setting)`, `<F> Hz (fixed by the record)`, `<F> Hz (stored in the session)`; with no source `<F> Hz (setting)` |
| `replay_state_text` | `kWaiting`, `kRunning`, `kPaused`, `kEnded` | `Replay starting`, `Replay playing`, `Replay paused`, `Replay ended` (SRS-039); `kNoSource`: empty |
| `record_summary_text` | reference record | `<name>: <fs> Hz, <count> samples (<H>:<MM>:<SS>), <title>, checksum verified` |
| | recorded session | `<name>: <fs> Hz, <count> samples (<H>:<MM>:<SS>), recorded session (<replayed or test>, mains <F> Hz, started <start_utc>)` |
| | other record | `<name>: <fs> Hz, <count> samples (<H>:<MM>:<SS>), WFDB record, mains from the setting` |
| `stream_counters_text` | | `received <datagrams>, accepted <accepted>, rejected <rejected_total()>, queue full <queue_full>, gaps <gaps>, out of order <dropped_out_of_order>` |

- The duration is ⌊count · 1000 / fs_mHz⌋ s written as hours (no leading zero), minutes and seconds. `format_hz` writes fs_mHz / 1000 with up to three decimals and no trailing zeros.
- `make_main_view_texts`: the banner and the mains text from `processor.selection` and `processor.mains_in_use`; `replay_label` and `replay_state` when the selection's tag is `kReplay` (in every run state, so also paused, ended and interrupted); `test_input_warning` and `stream_counters` when it is `kTestInput`; the five readouts from the functions of §17.18 applied to `view`.
- The banner does not depend on the run state: it names the source in every state (SRS-041); the state of a replay is the replay-state text, and the reasons of the status say paused, ended or interrupted.

### 17.32 Enabled states of the controls (D8; SRS-039, SRS-042, SRS-050, SRS-051)

```cpp
struct ControlInputs {
  bool record_open = false;                        // a record is open for the next replay
  SourceTag source = SourceTag::kNone;             // processor.selection.tag
  std::optional<ReplayState> replay;               // the current ReplaySource, if one exists
  bool test_input_running = false;
  MainsRule mains_rule = MainsRule::kSetting;      // processor.selection.mains_rule
  SourceRunState run_state = SourceRunState::kNoSource;
  RecordingPhase recording = RecordingPhase::kOff; // processor.recording (§17.25)
  bool recorder_busy = false;                      // RecordingChannel::busy()
};
struct ControlStates {
  bool open_record = false, start_position = false, speed = false, play = false;
  bool pause = false, resume = false, stop_replay = false;
  bool test_input_port = false, start_test_input = false, stop_test_input = false;
  bool mains = false;                              // both buttons
  bool recording_target = false, start_recording = false, stop_recording = false;
};
[[nodiscard]] ControlStates evaluate_control_states(const ControlInputs& in) noexcept;
```

With `replay_active` = `replay` is `kReady`, `kPlaying` or `kPaused`:

| Control | Enabled when |
|---|---|
| open record, start position, speed | not `replay_active` (a change applies only to the next replay, SRS-039) |
| play | not `replay_active` and `record_open` (while the test input runs, play changes the source, §17.33) |
| pause / resume | `replay` is `kPlaying` / `kPaused` |
| stop | `replay` is `kPlaying`, `kPaused` or `kEnded` |
| port, start test input / stop test input | not `test_input_running` / `test_input_running` |
| mains (both buttons) | `mains_rule` is `kSetting` **and** `recording` is `kOff` (the second condition pending the owner's confirmation, §17.38) |
| recording folder and name | `recording` is `kOff` |
| start recording | `recording` is `kOff`, not `recorder_busy`, `source` is `kTestInput` or `kReplay`, `run_state` is neither `kNoSource` nor `kEnded` |
| stop recording | `recording` is not `kOff` |

The checked mains button is `processor.mains_in_use` (the fixed value for a reference record or a recorded session, the setting otherwise). The states only guide the user: a command that arrives anyway is refused by the rules of §17.25 with its message.

### 17.33 Session port and controller (D8)

```cpp
namespace sinus::desktop::ui {
struct ActionResult { bool ok = true; std::string message; };   // message for the message line when !ok
class SessionPort {   // called from the GUI thread only
 public:
  virtual ~SessionPort() = default;
  [[nodiscard]] virtual bool copy_snapshot_if_newer(core::Snapshot& out, std::uint64_t& seen_generation) = 0;
  [[nodiscard]] virtual ActionResult open_record(const std::filesystem::path& record_path) = 0;   // no extension
  [[nodiscard]] virtual const core::ReplayRecord* open_record_info() const = 0;                   // nullptr: none
  [[nodiscard]] virtual ActionResult start_replay(const core::ReplaySettings& settings) = 0;
  virtual void pause_replay() = 0;
  virtual void resume_replay() = 0;
  virtual void stop_replay() = 0;
  [[nodiscard]] virtual std::optional<core::ReplayState> replay_state() const = 0;
  [[nodiscard]] virtual ActionResult start_test_input(std::uint16_t port) = 0;
  virtual void stop_test_input() = 0;
  [[nodiscard]] virtual bool test_input_running() const = 0;
  [[nodiscard]] virtual core::TestInputCounters test_input_counters() const = 0;
  virtual void set_mains(core::MainsFrequency frequency) = 0;
  virtual void start_recording(const std::filesystem::path& folder, const std::string& record_name) = 0;   // "": default
  virtual void stop_recording() = 0;
  [[nodiscard]] virtual core::RecorderStatus recorder_status() const = 0;
  [[nodiscard]] virtual bool recorder_busy() const = 0;
};
}
namespace sinus::desktop::app {
class SessionController final : public ui::SessionPort {
 public:
  explicit SessionController(const core::Clock& clock);   // processor (make_unique), queues, exchange, channel
  ~SessionController() override;                         // shutdown()
  void start();                                          // processing worker and recorder threads
  void shutdown() noexcept;                              // below; idempotent
  // SessionPort overrides
};
}
```

The controller owns: the `FrameQueue` (256) and `CommandQueue` with the worker's `Wakeup`, the `StreamProcessor` (with `set_recording_channel`), the `SnapshotExchange`, the `ProcessingWorker`, the `RecordingChannel` and `RecorderThread`, at most one `ReplaySource` with its `ReplayThread`, one `UdpTestInput` (off), the open `ReplayRecord` and the session counter (from 1, +1 at every selection).

- **`open_record(path)`**: `open_replay_record`; on success it replaces the open record (a running replay is not touched; play is disabled while one runs, §17.32); on failure the result's message, and the earlier record stays open.
- **`start_replay(settings)`**: `check_replay_settings` (failure: its message); stop the current source (a replay: `ReplayThread::stop()`, which joins, then both objects are destroyed; the test input: `UdpTestInput::stop()`); next session; push `kSelectSource(replay_selection(record, settings, session))`; build a `ReplaySource` from a copy of the open record (2 bytes per sample: tens of milliseconds for 24 h at 360 Hz, at a command only) and a `ReplayThread` writing into the frame queue, and `start()`. This is the order of §17.12: stop, select, start.
- **`pause_replay`, `resume_replay`**: `ReplayThread::pause()`, `resume()` (a false result changes nothing). **`stop_replay`**: stop and destroy the replay, then push `kSelectSource` of no source with the next session: the banner reads `NO SOURCE` and the status `no data`; the record stays open for another play.
- **`start_test_input(port)`, `stop_test_input`**: the order of §17.24 (stop the current source, select with the next session, `start`; on failure select no source and return the message; off: stop, then select no source).
- **`set_mains(f)`**: push `kSetMains(f)`.
- **`start_recording(folder, name)`**: t = `std::chrono::system_clock::now()` in Unix milliseconds; the request of §17.25 with that folder, `name` or `default_recording_name(t)` when empty, `test_input_recording_format()` when the test input is the current source, `replay_recording_format(record of the current ReplaySource)` for a replay, `start_utc = format_utc_millis(t)` and the four identity fields; with no current source the command is pushed anyway and the processor refuses it (`no data source is playing`). **`stop_recording`**: push `kStopRecording`.
- **Shutdown** (refines the last item of §17.25): (1) stop the current source; (2) `ProcessingWorker::stop()` (joins); (3) on the GUI thread, with the worker joined, apply to the processor every command still in the command queue and then `kStopRecording`, so that a running recording is finished as `kStopped` whatever the worker had handled; (4) `RecorderThread::stop()`, which writes the items posted and finishes the record. `main` calls `shutdown()` after `QApplication::exec()` returns; the destructor calls it too.
- The replay thread, the test-input thread, the worker and the recorder are the threads of §15.5; the GUI thread only calls the port, copies snapshots and reads thread-safe states (`ReplaySource::state()`, the counters, `RecordingChannel::status()`).

### 17.34 Main window structure (D8; SRS-041, SRS-049)

`ui::MainWindow` is a top-level `QWidget`, not a `QMainWindow`: it has no menu bar, tool bar, dock widget or status bar, which a user can hide, move or close. Constructor: `MainWindow(SessionPort& session, const core::Clock& clock, QWidget* parent = nullptr)`. Window title `Sinus`. Layout (object names in quotes; QA finds the widgets by them):

```
MainWindow "main_window"  (QVBoxLayout, size constraint QLayout::SetMinimumSize)
├── TopBar "top_bar"  (QFrame, QVBoxLayout)
│   ├── QLabel "intended_use"        kIntendedUseStatement, no word wrap
│   ├── QLabel "source_banner"       MainViewTexts::source_banner, word wrap
│   └── QLabel "test_input_warning"  kTestInputWarning while the test input is the source, else empty
├── QHBoxLayout
│   ├── WaveformPanel "waveform_panel"  (stretch 1)
│   │   ├── QLabel "replay_label"    "REPLAY" while a replay is the source, else empty
│   │   └── WaveformView "waveform"
│   └── QGridLayout (caption QLabel | ReadoutField), top-aligned:
│       Heart rate     | "heart_rate"
│       Reason         | "heart_rate_reason"
│       Signal quality | "quality_mark"
│       Signal status  | "signal_status"
│       Reason         | "signal_status_reason"
│       Mains filter   | "mains_in_use"
├── QLabel "message"   the last refusal or error of a user action
└── QHBoxLayout of QGroupBox
    ├── "Replay": "open_record" (Open record...), "record_summary", "start_position" (QSpinBox), "speed" (QComboBox),
    │             "play", "pause", "resume", "stop_replay" (QPushButton), "replay_state" (QLabel)
    ├── "Test input": "test_input_port" (QSpinBox), "start_test_input", "stop_test_input", "stream_counters" (QLabel)
    ├── "Mains frequency": "mains_50" (QRadioButton "50 Hz"), "mains_60" (QRadioButton "60 Hz")
    ├── "Recording": "recording_folder_button" (Folder...), "recording_folder" (QLabel), "recording_name" (QLineEdit),
    │                "start_recording", "stop_recording", "recorder_status" (QLabel)
    └── "about" (About...)
```

- **Top bar** (SRS-041, SRS-049). It is the first item of the window's layout, so it is at the top in every state, and no widget of the window lies over it. It is not inside a scroll area, dock, tool bar, splitter or stacked widget, and holds no button, so it has no close control. No code hides it or its labels: the replay label and the test-input warning become empty texts, never hidden, so that the layout does not move. The statement is not wrapped, so the window can never be narrower than it; the banner wraps (a long record name makes the bar taller, not cut). The test-input warning sits in the bar so that it is seen with the banner while the test input is the source (SRS-042).
- **Fonts.** `kReadoutFontScale = 1.5`: the three labels of the top bar and the six readout fields use the application font (`QApplication::font()`) with its point size × 1.5; the top bar labels and the heart-rate field are bold. The captions, controls and messages use the application font. The statement is therefore as large as every status text of SRS-045 and SRS-046, the heart rate included (SRS-049). `replay_label` uses the same scaled bold font.
- **Minimum size.** `QLayout::SetMinimumSize` makes the layout's minimum the window's minimum, so the smallest window still shows every element whole. The waveform view has a minimum of 852 × 240 px (a plot of at least 800 px, §17.36); each readout field has the minimum width of its longest text (§17.37). There is no maximum size; QA tests the minimum and 3840 × 2160 px.
- **Palette.** One palette for the whole window (the application's); no style sheet and no colour set from a value or a state (§17.40).
- **Tab order**: the controls from left to right, then the readout fields from top to bottom.

### 17.35 Refresh (D8; SRS-043, SRS-045, SRS-046, SRS-048)

- A `QTimer` with `Qt::PreciseTimer` and an interval of `kRefreshIntervalMs = 16` calls `MainWindow::refresh()`; it starts in the constructor. `void set_refresh_timer_active(bool)` lets a test stop it and call `refresh()` itself.
- **`refresh()`**, in this order:
  1. `session.copy_snapshot_if_newer(snapshot_, seen_)`; when newer, `make_main_view_texts(snapshot_.processor, snapshot_.view, session.test_input_counters())`, and each label and field whose text differs is set (`ReadoutField::set_text`, §17.37); the waveform view keeps a pointer to `snapshot_.view.display`, the window's own copy (copy assignment reuses the capacity, §17.19, so the copy does not allocate).
  2. Every time: the replay-state text, the counters (they change without a snapshot), the recorder status (when its `generation` changed), and `evaluate_control_states` applied with `setEnabled`; the mains button of `processor.mains_in_use` is checked under a `QSignalBlocker`, so that a change made by the program pushes no command.
  3. `waveform->update()`: the view repaints at every refresh, also without a new snapshot, because the drawn edge moves with time.
- **Timing.** A heart rate, status or quality mark is in the snapshot at most 50 ms after the frame that carries it (§17.21, §17.22) and on the screen at the next refresh, 16 ms later at most plus the paint: within the 1 s of SRS-046 and SRS-048, and within the 20 ms that §17.20 counted for this step of the 2 s of SRS-045.

### 17.36 Waveform widget (D8; SRS-043, SRS-041)

**Geometry** (`core/waveform_geometry`):

```cpp
inline constexpr double kMillimetresPerMv = 10.0;        // the usual scale of ECG paper
inline constexpr double kMinimumSpanMv = 5.0;            // the trace area always shows at least ±2.5 mV
inline constexpr std::int32_t kLeftMarginPx = 48;        // the 1 mV bar and its text
inline constexpr std::int32_t kRightMarginPx = 4;
inline constexpr std::int32_t kMinimumPlotWidthPx = 800; // one pixel column is at most 12.5 ms of the 10 s
inline constexpr std::int32_t kMarkBandPx = 14, kMarkWidthPx = 10, kMarkHeightPx = 9;
struct WaveformGeometry {
  std::int32_t plot_left_px = 0, plot_width_px = 0;      // x of index i: plot_left_px + sweep_x_px(i, W, plot_width_px)
  std::int32_t mark_top_px = 0;                          // the band of the marks, above the trace
  std::int32_t trace_top_px = 0, trace_bottom_px = 0, trace_mid_px = 0;
  double px_per_mv = 0.0;
};
[[nodiscard]] WaveformGeometry make_waveform_geometry(std::int32_t width_px, std::int32_t height_px,
                                                      double logical_dpi_y) noexcept;
[[nodiscard]] std::int32_t trace_y_px(const WaveformGeometry& geometry, float mv) noexcept;
```

- `plot_left_px` = 48; `plot_width_px` = max(1, width − 52); `mark_top_px` = 2; `trace_top_px` = 2 + 14 + 2 = 18; `trace_bottom_px` = height − 3; `trace_mid_px` = (top + bottom) / 2 (integer division).
- `px_per_mv` = min(10 mm/mV at `logical_dpi_y` (`10 · dpi / 25.4`), (bottom − top) / 5 mV). The scale is fixed (no automatic gain), so the same amplitude always has the same height and a change of the signal is not hidden by a change of scale.
- `trace_y_px` = mid − lround(mv · px_per_mv), clamped to the trace area: a value beyond it is drawn on the border, so the trace stays continuous and a saturated stretch shows as flat.

**View.**

```cpp
class WaveformView final : public QWidget {
 public:
  explicit WaveformView(const core::Clock& clock, QWidget* parent = nullptr);   // minimum 852 × 240 px
  void set_model(const core::DisplayModel* model) noexcept;                   // nullptr: nothing drawn
  [[nodiscard]] const core::DrawingInput& last_drawing_input() const noexcept; // of the last paint (tests)
  [[nodiscard]] const core::WaveformGeometry& last_geometry() const noexcept;
 protected:
  void paintEvent(QPaintEvent* event) override;
};
```

`paintEvent`, in this order: the geometry from `width()`, `height()` and `logicalDpiY()`; `make_drawing_input(*model, clock.now(), plot_width_px, input)` with the time **of the paint**; fill with the palette's `Base` colour; the 1 mV bar (a vertical line of `px_per_mv` px in the left margin, from `trace_mid_px` up, and the text `1 mV` beside it); when `has_edge`:

- **Trace.** For each column at x = `plot_left_px + x_px`: a vertical line from `trace_y_px(max_mv)` to `trace_y_px(min_mv)` (a point when equal) and, when `joins_previous`, a line from the previous column's (x, `trace_y_px(last_mv)`) to (x, `trace_y_px(first_mv)`). The lines are collected in a vector kept by the view and drawn with one `drawLines`. A column that does not join is never connected to the previous one: gaps, segment ends and the sweep border stay open (HAZ-012, §17.19).
- **Marks.** For each `DrawnMark`, a triangle pointing down with its tip at (x, `trace_top_px − 2`) and its base of 10 px at `mark_top_px`: `kFilled` filled with the trace colour, `kHollow` outline only (`Qt::NoBrush`, pen 1 px). Start-up and reliable detections differ by shape, not by colour (SRS-022, §15.7).
- **Cursor.** A vertical line of 2 px at `plot_left_px + cursor_x_px` from `mark_top_px` to `trace_bottom_px`. The cursor stands at the oldest column, so the newest sample is just left of it and the oldest just right.
- One colour (the palette's `Text`) for the trace, the marks, the cursor and the bar; pen width 1 px except the cursor; antialiasing off, so that the pixels are exact for the tests.

**Alignment on the screen** (SRS-043). A mark and the trace column of the sample at its index have the same x (`sweep_x_px`, the same width), so a mark within 20 ms of the R peak in the data (§17.27) is drawn over the column of the R peak; with at least 800 px for 10 s, one column holds at most 12.5 ms. Each paint draws the edge for the time of that paint, and the screen keeps it until the next refresh, 16 ms later: the drawn edge is between 0.5 s and 0.5 s + 16 ms behind the acquisition (the presentation by the window system is outside the application). The exactness on the data is §17.27; the repaint interval measured on the real clock is reported in D9 (§17.43).

**Panel and "REPLAY".** `WaveformPanel` stacks `replay_label` (empty or `REPLAY`, a fixed height of one line of its font) above the view: the word is in the waveform area while a replay is the source (SRS-041) and never covers the trace or a mark.

**Accessibility.** The view has the accessible name `ECG waveform` and the accessible description `The last 10 s of the ECG, drawn 0.5 s after acquisition. Filled triangles mark detected beats; hollow triangles mark beats found while detection was starting up. The vertical line is the current position.` (constants `kWaveformAccessibleName`, `kWaveformAccessibleDescription` in `display_texts`); it takes no focus.

### 17.37 Readout fields and accessibility (D8; SRS-053, SRS-045, SRS-046, SRS-048, SRS-050)

**Why not a label.** Qt exposes the text of a label as its accessible name (the Qt documentation of `QAccessibleTextInterface`: labels "return their text as name"), so a `QLabel` cannot carry a fixed name and a changing text. A read-only `QLineEdit` exposes its `accessibleName` as the name and its text as the value and through the text interface (Qt's line-edit accessible interface, mapped to the UI Automation value and text patterns on Windows and to AT-SPI text on Linux), and a keyboard user can reach it with Tab.

```cpp
class ReadoutField final : public QLineEdit {
 public:
  ReadoutField(std::string_view accessible_name, QStringList longest_texts, QWidget* parent = nullptr);
  void set_text(const QString& text);   // nothing when equal; otherwise setText, then the notification
};
```

- **Construction**: `setReadOnly(true)`, `setFrame(false)`, `setFocusPolicy(Qt::TabFocus)`, `setAccessibleName(name)`; the minimum width is the largest `horizontalAdvance` of `longest_texts` in the field's font plus the text margins and 8 px, so no text of the field is ever scrolled or cut. The copy entry of the context menu stays.
- **`set_text`**: when the text differs, `setText(text)`, `setCursorPosition(0)`, then `QAccessibleValueChangeEvent event(this, text); QAccessible::updateAccessibility(&event);` so that a screen reader is told of the change (besides any text event that Qt's line edit sends itself). Qt delivers it to the platform only while an assistive tool is active (`QAccessible::isActive()`), at a negligible cost otherwise.

| Object name | Accessible name | Text (shown and exposed) | Longest texts | Requirement |
|---|---|---|---|---|
| `heart_rate` | `Heart rate` | `heart_rate_text` | `200 bpm`, `--` | SRS-053, SRS-046 |
| `heart_rate_reason` | `Heart rate reason` | `heart_rate_reason_text` | `signal not usable`, `not enough beats` | SRS-053, SRS-046 |
| `quality_mark` | `Signal quality` | `quality_mark_text` | `Signal not usable: low quality` | SRS-048 |
| `signal_status` | `Signal status` | `status_text` | `not usable` | SRS-053, SRS-045 |
| `signal_status_reason` | `Signal status reason` | `status_reason_text` | `checking signal quality` | SRS-053, SRS-045 |
| `mains_in_use` | `Mains frequency in use` | `mains_in_use_text` | `60 Hz (stored in the session)` | SRS-050 |

The names are constants of `display_texts` (`kHeartRateName`, …). The labels keep Qt's rule (their text is their name) and get an accessible description: `intended_use` `Intended-use statement`, `source_banner` `Data source`, `test_input_warning` `Test input warning`, `replay_label` `Replay indication`, `replay_state` `Replay state`, `recorder_status` `Recording status`, `message` `Message`, `stream_counters` `Test input counters`, `record_summary` `Open record`. Each caption label is the buddy (`QLabel::setBuddy`) of its field.

**Test method** (QA, `offscreen` platform):
1. *Exposure.* From `QAccessible::queryAccessibleInterface(&window)`, the tree is walked with `childCount()` and `child(i)`; each name of the table is found on exactly one interface, whose `object()` is the field.
2. *Text.* On that interface, `text(QAccessible::Value)` and `textInterface()->text(0, textInterface()->characterCount())` equal the field's `text()` and the expected literal of the state; `role()` is `QAccessible::EditableText` and `state().readOnly` is set.
3. *Change.* A test helper `AccessibilityRecorder` (`tests/support`, RAII) installs an update handler with `QAccessible::installUpdateHandler`, activates accessibility, records the events and restores both at the end. After a snapshot that changes the text and `refresh()`, a `QAccessible::ValueChanged` event whose object is the field and whose value is the new text has been recorded; a `refresh()` without a change records none for that field. Activation: `QAccessible::setActive(true)` where the pinned Qt declares it, as Qt's own accessibility tests do (the default platform accessibility object of the `offscreen` platform holds the flag); otherwise through the platform integration's `QPlatformAccessibility::setActive`, with the private Qt GUI headers in the test executables only. The developer settles which at step 24 with the first unit test of the helper; criteria 1 and 2 do not depend on it.

### 17.38 Controls (D8; SRS-039, SRS-042, SRS-050, SRS-051)

- **Replay.** `Open record...`: `QFileDialog::getOpenFileName` with the filter `WFDB header (*.hea)`; the path without its extension goes to `open_record`; on success `record_summary` shows `record_summary_text` and `start_position` gets the range 0 to `max_start_seconds` with the value 0; a failure goes to the message line. `start_position`: `QSpinBox`, suffix ` s`, step 1; `speed`: `QComboBox`, not editable, items `x1`, `x2`, `x5`, `x10` (default `x1`). `Play`: `start_replay({start_sample = s · fs_mHz / 1000 (integer division, §17.11), speed})`. `Pause`, `Resume`, `Stop`: the port. `replay_state` shows `MainViewTexts::replay_state`: `Replay ended` at the end (SRS-039), while the status reason reads `replay ended`.
- **Test input.** `test_input_port`: `QSpinBox` 1024 to 65535, `kDefaultTestInputPort` at every start; `Start`, `Stop`: the port; `stream_counters` shows the counters while the test input is the source. The controller creates the input off and nothing turns it on but the user's `Start`; no setting is stored (SRS-042, §17.24).
- **Mains** (SRS-050). Two `QRadioButton` `50 Hz` and `60 Hz` in an exclusive `QButtonGroup` (ids 50 and 60): no other value exists. The checked button is the frequency in use (50 Hz at start, the processor's default). A user click (`QButtonGroup::idClicked`, emitted for user actions and not for `setChecked`) on the other value calls `set_mains`. For a reference record or a recorded session the buttons show the fixed value and are disabled; the setting is kept and shown again when the source changes. **While a recording is pending or running the buttons are disabled** (recommended; pending the owner's confirmation): a change would end the recording, a step the user may not expect. The rule of §17.25 that ends a recording at a change of the mains setting stays as a safety net. The frequency in use with its origin is the `mains_in_use` field, and the banner states it for every source. Radio buttons do not react to the mouse wheel, so the setting cannot change by accident while scrolling.
- **Recording** (SRS-051). `Folder...`: `QFileDialog::getExistingDirectory`; `recording_folder` shows the folder, by default `QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation)`. `recording_name`: `QLineEdit` with the placeholder `default: sinus_<UTC date>_<UTC time>`; empty means the default name (§17.25). `Start recording`, `Stop recording`: the port. `recorder_status` shows `RecorderStatus::message`: `Recording <n>` while recording (the visible indicator of `usability.md` §1.4), then the saved, failed or not-started message.
- **Messages.** The `message` label shows the message of the last failed user action (open, play, test input) and is cleared by the next successful one; no dialog box is used for messages (§17.40).
- **Closing** the window ends `exec()`; `main` then calls `SessionController::shutdown()` (§17.33), so a running recording is saved.

### 17.39 About box and `--version` (D8; SRS-052, SRS-049)

```cpp
struct AboutInfo {
  std::string desktop_version, desktop_source_sha256;   // core::desktop_identity()
  std::string library_version, library_source_sha256;   // sinus::dsp::library_identity()
  std::string qt_build_version, qt_runtime_version;     // QT_VERSION_STR and qVersion(), set by app
  std::string compiler, build_type;                     // the build values that D3 prints
  bool other_qt_allowed = false;                        // SINUS_DESKTOP_ALLOW_OTHER_QT
};
[[nodiscard]] std::string about_text(const AboutInfo& info);   // lines ended by "\n"
// app/about_info: the only place that fills AboutInfo, used by the About box and by --version.
[[nodiscard]] core::AboutInfo about_info();
```

`about_text` gives exactly these lines (`<…>` the fields):

```
Sinus desktop application
Not a medical device, not for diagnosis or health decisions
Version: <desktop_version>
Source identifier (SHA-256): <desktop_source_sha256>
Real-time library sinus-dsp version: <library_version>
Real-time library source identifier (SHA-256): <library_source_sha256>
Qt: built with <qt_build_version>, running with <qt_runtime_version>
Compiler: <compiler>
Build type: <build_type>
Other Qt version allowed: <yes or no>
Licence: Apache-2.0; Qt is used under the LGPL-3.0
```

- **`sinus-desktop --version`** writes `about_text(about_info())` to standard output and exits with 0, before any `QApplication` is created (`qVersion()` needs none); the ctest `sinus_desktop_version` of D3 keeps passing, since the version is on the third line. Any other argument than `--version` is answered with `usage: sinus-desktop [--version]` on standard error and exit code 2. If D3 printed another form, this one replaces it.
- **About box** (`AboutDialog`, title `About Sinus`, modal, opened only by the user's `About...`): one `QLabel` "about_text" in plain-text format with the text of `about_text`, selectable by mouse and keyboard so that the identifiers can be copied, and a `QDialogButtonBox` with `Close`. The statement is its second line (SRS-049); the version and the source identifier are its third and fourth (SRS-052).

### 17.40 No sound, notification, alarm, colour scale or judging label (D8; SRS-046, SRS-048, SRS-049)

- The desktop application links Qt Core, Qt GUI, Qt Widgets and Qt Network only (ADR 0009): no Qt Multimedia, no Qt TextToSpeech.
- These are not used in `desktop/src`: `QApplication::beep`, `QApplication::alert`, `QSystemTrayIcon`, `QMessageBox`, `QSoundEffect`, `QMediaPlayer`, `QTextToSpeech`, `QToolTip::showText`, `setStyleSheet`, `setPalette`, `QProgressBar`, `QSlider`, `QDial`, `QLCDNumber`; and the window never raises or activates itself (`raise`, `activateWindow`, `setWindowState`). A message is a text in the window (§17.38).
- No colour carries meaning: one palette, no colour set from a value or a state; sources and states are words, marks are shapes (SRS-041, SRS-046). The quality is a mark in words with no number, bar or scale (SRS-048). No text shown next to the heart rate states a range, a limit or a judgement (no "normal", "abnormal", "high", "tachycardia", "bradycardia").
- Verified by a source scan, a check of the shown texts and inspection (§17.41).

### 17.41 Verification by requirement (D8)

QA's tests are in `desktop/tests/requirements/`, in `sinus_desktop_requirement_tests` (offscreen `main` of `tests/support`), as GoogleTest tests with `QTest` event functions and `QSignalSpy` as helpers (§15.16), tagged `// Verifies: SRS-nnn`. Two set-ups:

- **(a) Window with a fake session.** `tests/support/fake_session_port.hpp` (developer, §17.42): a `SessionPort` whose snapshot, replay state, counters and recorder status are set by the test and which records every call with its arguments. Snapshots are made by a real `StreamProcessor` (D5, D6) fed with the fixtures of §17.27 as in §17.27, with `tick` every 50 ms of a `FakeClock`, and copied as `{state(), view()}`; the waveform view uses the same `FakeClock`; the refresh timer is stopped and the test calls `refresh()`. The expected texts are written in the tests as literals, not taken from the `core` functions.
- **(b) Window with the real `SessionController`** on `SteadyClock`, for the paths through the threads; waits use `QTest::qWaitFor` with a limit of 5 s.

The **states of SRS-041** used below: no source; replay playing at ×1, ×2, ×5 and ×10; replay paused; replay ended; replay interrupted (no frame for 1.2 s, then `tick`); test input receiving.

**SRS-041** (display). (a) In each state, `source_banner` has the exact text of §17.31 and the same top-left position in the window; `replay_label` reads `REPLAY` in the replay states and is empty otherwise; the banner's palette is the window's and no style sheet is set. A replay of a hand-built reference record (`kReferenceRecord`, title `MIT-BIH Arrhythmia Database`, name `100`) shows `REPLAY: record 100 (MIT-BIH Arrhythmia Database), x1, mains 60 Hz (fixed by the record)`; a recorded session `REPLAY: session <name>, x1, mains 50 Hz (stored in the session)`. After a change of source, `last_drawing_input().marks` is empty and `heart_rate` shows `--`. (b) The fixture `replay16` opened and played at ×10: the banner reads `REPLAY: record replay16, x10, mains 50 Hz (setting)`; then the test input started on a free port: `TEST INPUT: udp 127.0.0.1:<port>, mains 50 Hz (setting)`, `replay_label` empty, no replay remains (`replay_state()` empty).

**SRS-043** (widget). (a) With the `d6_ecg75_360` stream, at several fake times: after `grab()`, `last_drawing_input()` equals `make_drawing_input(model, fake now, last_geometry().plot_width_px)` (the view draws the input of the time of the paint); in the image, the cursor's column has the trace colour over the trace area; each drawn mark is at the x of its sample's column; with a hand-made model holding one shown mark of each shape, a filled mark has the trace colour at its centroid and a hollow mark the background colour at its centroid and the trace colour on its outline; with one frame removed, no trace pixel lies in the columns strictly between the two runs; with `d6_flat_360`, the trace keeps being drawn while the status is not usable and no mark is added from then on. Signals with peaks of 1 mV and 3 mV give the same `px_per_mv`. At the minimum window size `plot_width_px` is at least 800. The refresh timer is active, `Qt::PreciseTimer`, with an interval of 16 ms.

**SRS-045, SRS-046, SRS-048** (texts shown). (a) For each case of §17.27 (statuses and reasons, every heart-rate reason, the value cases 72.5 → `73 bpm` and 72.49 → `72 bpm`, each quality mark), after `refresh()` each field has the expected literal; after a withheld state the previous value is never in `heart_rate`; a new value is shown at the first `refresh()` after its snapshot; at the minimum window size each field shows its longest text whole (`horizontalAdvance` not above the field's text width). SRS-048: `quality_mark` is the readout directly below `heart_rate_reason` in the same column, its text is always one of the empty text, `Signal usable` and `Signal not usable: low quality`, and the window holds no `QProgressBar`, `QSlider`, `QDial` or `QLCDNumber`. SRS-046: in every state and for the heart rates 31, 72 and 199 bpm, every readout has the window's palette and no style sheet, and no text of the window contains the words of §17.40.

**SRS-049.** (a) In each state of SRS-041, at the minimum size and at 3840 × 2160 px: `intended_use` has the exact text, is visible, its `visibleRegion()` is its whole rectangle and its text is not cut (`horizontalAdvance` not above its width); no visible widget outside the top bar's subtree (other than its ancestors) intersects the top bar's rectangle; the top bar's only ancestor is the window; the top bar has no `QAbstractButton` descendant; the window has no `QMenuBar`, `QToolBar`, `QDockWidget`, `QStatusBar` or `QScrollArea`; `QFontInfo` of the statement has a pixel size not below that of each readout field. The About box's text contains the statement line. The source scan: a test reads every file under `<SINUS_DESKTOP_SOURCE_ROOT>/desktop/src` and finds none of the names of §17.40, and finds in `desktop/CMakeLists.txt` no Qt module other than Core, Gui, Widgets and Network (tagged SRS-049 and SRS-046). Inspection by QA, recorded in its report: no sound or notification in a session of each source.

**SRS-050** (setting). (a) At construction `mains_50` is checked and `mains_in_use` reads `50 Hz (setting)`; the group holds exactly two radio buttons, `50 Hz` and `60 Hz`, exclusive; `QTest::mouseClick` on `60 Hz` makes exactly one `set_mains(60)` call, a click on the checked button none; a reference-record snapshot checks `60 Hz`, disables both and shows `60 Hz (fixed by the record)`; a recorded session at 50 Hz shows `50 Hz (stored in the session)` and disables both; another record keeps them enabled with `(setting)`; with the recording phase `kPending` or `kOn` both are disabled (this check is dropped if the owner does not confirm §17.38). (b) A click on `60 Hz` makes the snapshot's `processor.mains_setting` 60 within 1 s and the field read `60 Hz (setting)` (the effects on the processing are D5's tests).

**SRS-052** (About). The About box's text equals `about_text(app::about_info())`, and its version and source-identifier lines equal the values that the test computes itself as in §17.27 (`desktop/VERSION`, the digest of `desktop/src` by the method of §15.12 with `core::Sha256`, and the same for the library). A `QProcess` runs `sinus-desktop --version` (path from the compile definition `SINUS_DESKTOP_EXECUTABLE`; the test executable depends on the program) and its output has the same lines.

**SRS-053.** The method of §17.37 for `heart_rate`, `heart_rate_reason`, `signal_status` and `signal_status_reason`, in each state of SRS-045 and each case of SRS-046 of the list above: exposure, text equal to the shown text, and the change notification.

**Controls, added to the tests of SRS-039, SRS-042 and SRS-051.** SRS-039 (a): `Play` passes `start_sample` = s · fs_mHz / 1000 and the speed of the combo box; `Pause`, `Resume`, `Stop` call the port; the enabled states follow §17.32 in each replay state; `replay_state` reads `Replay paused` and `Replay ended`; (b) the format-16 fixture played at ×10 to its end shows `Replay ended` and the status reason `replay ended`. SRS-042 (b): in a new window the test input is not running, `start_test_input` is enabled and the port is 45000; after `Start` the top bar shows `The test input is never to be used with a worn device.` and after `Stop` the warning is empty and the banner `NO SOURCE`; a malformed datagram sent by the test raises the rejected count in `stream_counters`. SRS-051 (a): `Start recording` calls the port with the folder and the name typed (the empty name passed as empty); `recorder_status` shows the status message; (b) `replay16` at ×10 recorded for 2 s and stopped: `Recording <n> saved (<N> samples)` and the record exists (its content is D7's tests).

### 17.42 Developer's unit tests (D8)

No requirement tag, in `desktop/tests/unit/` (`core` functions in `sinus_desktop_core_unit_tests`): every row of the text tables of §17.31 (banner for each source kind and speed, both mains frequencies; `format_hz` at 125, 128.5, 360, 1000 Hz and 0.125 Hz; durations at 0 s, 59 s, 1 h; `max_start_seconds` at counts that are and are not whole seconds); `evaluate_control_states` over every combination of its inputs against the table of §17.32; `about_text` line by line; `make_waveform_geometry` and `trace_y_px` (scale at 96 and 192 dpi, small heights, clamping, rounding); `ReadoutField` (`set_text` sends one event per change and none without a change, minimum width) and the `AccessibilityRecorder` helper on the `offscreen` platform (step 24 settles the activation, §17.37); `WaveformView` painting of a hand-made `DrawingInput` (no edge, one column, joins, marks at both borders); the fake session port; `SessionController` (order of a change of source: the old source stopped before the select, a new session per selection; a failed test-input start selects no source; shutdown saves a running recording and is idempotent; a second `open_record` failure keeps the first record); `MainWindow` wiring (each control calls its port function; the mains buttons push no command when set by `refresh()`).

### 17.43 Implementation order of D8; what remains for D9

| Step | Group | Task | Cites | Design |
|---|---|---|---|---|
| 22 | D8 | `display_texts` additions, `main_view` (texts, control states) | SRS-039, SRS-041, SRS-042, SRS-049, SRS-050 | §17.31, §17.32 |
| 23 | D8 | `waveform_geometry` | SRS-043 | §17.36 |
| 24 | D8 | `tests/support`: `AccessibilityRecorder` (with its activation settled first), `fake_session_port.hpp`; `ui/readout_field` | SRS-053 | §17.37, §17.41 |
| 25 | D8 | `ui/waveform_view` (`WaveformView`, `WaveformPanel`) | SRS-043, SRS-041 | §17.36 |
| 26 | D8 | `ui/top_bar`, `ui/session_port`, `ui/main_window` (layout, refresh, controls, messages) | SRS-041, SRS-045, SRS-046, SRS-048, SRS-049, SRS-050, SRS-053 | §17.33 to §17.38 |
| 27 | D8 | `core/about`, `app/about_info`, `ui/about_dialog`, `--version` with `about_text` | SRS-052, SRS-049 | §17.39 |
| 28 | D8 | `app/session_controller`, `main.cpp` wiring and shutdown | SRS-039, SRS-042, SRS-051 | §17.33 |
| 29 | D8 | compile definitions of the requirement tests: `SINUS_DESKTOP_EXECUTABLE` (and `SINUS_DESKTOP_SOURCE_ROOT`, from D7) | — | §17.41 |

D8 lands with QA's tests of §17.41 on the branch of its code (ADR 0004). The code of SRS-047 still cites it only in D9 (§17.28).

**What remains for D9** (test engineer): SRS-040 on all the 48 MIT-BIH records and the five noise stress records with the local databases (`needs_data`), the subset staying in CI (§15.16); the system test of SRS-047 (§17.28); the Milestone 3 verification report, with the results of every M3 requirement, the inspections of SRS-046 and SRS-049 recorded by QA, the refresh intervals measured over 60 s on the real clock on both CI hosts (median and 99th percentile, informative for the 20 ms of SRS-043), and the check of the readouts with a screen reader (OP-084, §17.44).

### 17.44 Readings reported for the requirements (part 3)

Confirmed by the project owner on 2026-10-12 and stated in `srs.md` v0.9.5.

1. **SRS-049 "overlaid".** The windows that the user opens (the file and folder choosers, the About box) are separate windows and may lie over the main window while they are open; no element of the main window ever lies over the top bar. The About box holds the statement itself.
2. **SRS-049 "status text".** All the readouts, the heart rate included, use the size of the top bar (§17.34): the statement is as large as each of them; the heart rate is distinguished by weight only.
3. **SRS-041 texts.** With no source the banner reads `NO SOURCE` (SRS-041 lists the texts of a replay and of the test input only); the banner states the mains frequency for every source with its origin; the speed is written `x10`.
4. **SRS-039 "Replay ended"** is the replay-state text in the replay controls, with the status reason `replay ended`; after the end the replay stays the source until `Stop` or another source, and `Stop` leaves no source.
5. **SRS-053 "accessible names" and "text".** The name is the fixed name of the element (`Heart rate`, …) and the text is the value of a read-only field that a keyboard user reaches with Tab; the method of verification is Qt's accessibility interface, not a screen reader; a check with a screen reader is OP-084.
6. **SRS-042.** The statement that the test input is never to be used with a worn device is in the top bar, below the banner, while the test input is the source.
