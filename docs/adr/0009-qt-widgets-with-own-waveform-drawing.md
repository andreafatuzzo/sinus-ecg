# ADR 0009: Qt Widgets with a waveform drawn by the application

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** project owner (decision, 2026-10-11; closes OP-033); tech lead (proposal, analysis)
- **Related:** completes [ADR 0003](0003-qt-desktop-application-with-replay.md) (the user-interface technology it left open); [ADR 0004](0004-test-tagging-and-traceability-gates.md), [ADR 0007](0007-cpp-coding-standard-and-static-analysis.md); SRS-041, SRS-043, SRS-044, SRS-045, SRS-046, SRS-048, SRS-049, SRS-053; HAZ-001, HAZ-002, HAZ-013; RC-005, RC-015, RC-019; OP-033, OP-080; [`architecture.md`](../regulatory/architecture.md) §6.2, [`architecture-m3.md`](../regulatory/architecture-m3.md) §15; [`usability.md`](../regulatory/usability.md) §1.4

## Context

ADR 0003 chose a Qt 6 desktop application and left one choice open (OP-033): Qt Widgets or Qt Quick/QML, to be decided before the user-interface requirements of Milestone 3, with these criteria: rendering of a continuous 360 Hz waveform, testability of the view logic, clear and always visible safety-related elements, accessibility, and build and deployment effort.

Facts the decision depends on:
- **Load.** The main window shows one waveform of 10 s at up to 1000 Hz (at most 10 000 points, 3 600 at 360 Hz) with beat marks, refreshed a few tens of times per second, plus a few lines of text (SRS-041, SRS-043, SRS-045, SRS-046, SRS-048, SRS-049). Either toolkit draws this without effort on any current computer; speed does not decide.
- **Licences.** The Qt chart modules (Qt Charts and Qt Graphs) are offered under commercial terms or the GPL-3.0 only, according to their Qt 6 documentation, so the rule of ADR 0003 (LGPL-3.0 modules only, linked dynamically) excludes them. Qt Widgets is available under the LGPL-3.0. A third-party plotting library would be one more SOUP item, with its own licence and anomaly review, for a single view.
- **Static checks and traceability.** ADR 0007 gates every C++ file with clang-format, clang-tidy and warnings as errors, and `dsp/scripts/traceability.py` scans C++ sources for requirement IDs and reads `// Verifies:` tags above GoogleTest `TEST` macros (ADR 0004). QML and JavaScript files are covered by neither.
- **Tests without a display.** Qt provides the `offscreen` platform plugin for running widget code without a window system; a widget can be rendered to an image (`QWidget::grab`) and driven with the `QTest` event functions.
- **Accessibility.** Both toolkits expose their elements to the accessibility interfaces of Windows and Linux through `QAccessible`; a widget's accessible name and description are properties of `QWidget` (SRS-053).

## Options considered

1. **Qt Widgets, with the waveform drawn by the application with `QPainter` on a `QWidget`.**
   - One language (C++); every file under the gates of ADR 0007 and scanned by the traceability script without change.
   - Tests are GoogleTest executables on the `offscreen` platform; the drawing input (window, positions of the trace and marks) is computed in code without Qt and tested directly; the widget is checked by rendering it to an image.
   - The deployed program needs Qt Core, Qt GUI, Qt Widgets and the platform plugin only.
   - Plain desktop look, no touch-oriented controls (not needed).
2. **Qt Quick/QML, with the waveform drawn by a C++ scene-graph item.**
   - Modern look and animation; well suited to touch screens.
   - Two languages; QML and JavaScript need their own linters and formatter as extra gates, and requirement logic written in QML would escape clang-tidy and the traceability scan (a script change or a rule "no logic in QML").
   - Adds Qt Qml, Qt Quick, Qt Quick Controls and the JavaScript engine to the deployment: a larger SOUP surface.
   - Tests need Qt Quick Test or C++ tests through a `QQuickWindow`, with a software or GPU scene-graph backend in CI.
3. **Either toolkit with a chart module or a third-party plotting library.** Qt Charts and Qt Graphs are excluded by licence. A third-party library under a permissive or LGPL licence would bring axes, zoom and legends that the display does not need, and a SOUP review for a single view; the beat marks added onto the drawn trace (SRS-043) would still need code of our own.

## Decision

Option 1.

- The user interface of the desktop application uses **Qt Widgets**. Qt Quick, Qt Qml and QML files are not used.
- The **waveform is drawn by the application**: a widget of the `ui` layer paints with `QPainter` from a snapshot of the display data prepared in the Qt-free `core` (the window, the trace values, the positions of the marks). The widget does no signal processing (`architecture.md` §6.2).
- **No chart module and no third-party plotting library.** Only Qt modules available under the LGPL-3.0 are used, linked dynamically (ADR 0003): for Milestone 3, Qt Core, Qt GUI, Qt Widgets and Qt Network; Qt Serial Port and Qt Bluetooth are added in Milestone 4. Qt Test is used by the tests only and is not shipped.
- Every C++ test of the desktop application, including widget tests, is a GoogleTest test, so that `// Verifies:` tags work as in ADR 0004; widget tests run on the `offscreen` platform.

## Consequences

- **Positive:**
  - one language and one set of gates; no change of the traceability rules;
  - the drawing input is tested without Qt, and the widget by rendering, in CI without a display;
  - a smaller deployment and SOUP list;
  - full control of how late marks are added onto the drawn trace and of the elements that must never be hidden (SRS-043, SRS-049).
- **Negative and risks:**
  - about 300 lines of drawing code to write and test instead of a library; mitigated by keeping the drawing input in `core`, where it is unit-tested;
  - a plain look; acceptable for a desktop tool for replay and monitoring, and checked in the formative usability evaluation (OP-040);
  - a later touch or mobile user interface would need a new decision; none is planned.
- **Follow-up:** OP-033 closed by this record; `architecture.md` §2, §6.2, §9 and §11 and `architecture-m3.md` §15 state the decision; the status line of ADR 0003 and the index of `docs/adr/README.md` cite this record; the Qt modules are entered in `soup.md` when the desktop build lands (`architecture-m3.md` §15.18).
