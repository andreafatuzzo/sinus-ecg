# SOUP list (Software Of Unknown Provenance)

_Inspired by IEC 62304 §8.1.2. Every new runtime dependency must be added here in the same change that introduces it. Known anomalies last reviewed on 2026-10-05._

| Name | Component | Version constraint | Version reviewed | Purpose | Known anomalies reviewed |
|---|---|---|---|---|---|
| Python (CPython) | dsp | 3.11 (`dsp/.python-version`; `requires-python = ">=3.11"`) | 3.11.16 and 3.11.17 | Interpreter and standard library: SHA-256 of the data files and of the package source (`hashlib`), download over HTTPS (`urllib.request`), correctly rounded sums and the trigonometric functions of the filter design (`math`); `tomllib` and `ast` in the scripts | 2026-10-05: no anomaly that affects Sinus ([review](#python-cpython-311)) |
| NumPy | dsp | `>=1.26` | 2.4.6 | Array math for signal processing | 2026-10-05: no anomaly that affects Sinus; one machine-dependent behaviour, without effect on any result ([review](#numpy-246)) |
| SciPy | dsp | `>=1.11` | 1.17.1 | Filter application: `scipy.signal.sosfilt` and `scipy.signal.lfilter` (the coefficients are computed by Sinus) | 2026-10-05: no anomaly that affects Sinus ([review](#scipy-1171)) |
| wfdb | dsp | `>=4.1` | 4.3.1 | Reading PhysioNet WFDB records and annotations | 2026-10-05: no anomaly that affects Sinus ([review](#wfdb-431)) |

The first review of known anomalies (OP-009 in [`open-points.md`](open-points.md)) is recorded [below](#known-anomalies-review). Vulnerabilities found in SOUP are handled as described in [`cybersecurity.md`](cybersecurity.md) §7, and a vulnerability whose triage concludes that it affects Sinus is recorded in the last column.

This table lists the **direct** runtime dependencies and the interpreter. The exact resolved versions are in `dsp/uv.lock`. The SBOM generated in CI lists every runtime package, including transitive dependencies (e.g. those of wfdb), with versions and licences ([`cybersecurity.md`](cybersecurity.md) §6); it does not list the interpreter.

## Known anomalies review

**Scope.** The versions that `dsp/uv.lock` selects for Python 3.11, the configuration that CI and the validation reports use (the reports state it in their `Runtime` row, [`architecture.md`](architecture.md) §8.14). For Python 3.12 and later the lock selects NumPy 2.5.3 and SciPy 1.18.1; their release notes were read as part of this review, but that configuration is not the one that is verified.

**Sources, for every item:**
- **Known vulnerabilities:** the OSV database (`osv.dev`), which collects the PyPA advisory database and the GitHub advisory database, queried on 2026-10-05 for each of the 36 packages of the runtime closure in `dsp/uv.lock` at its locked version (the 33 packages that a Python 3.11 environment installs on Windows, 32 on Linux, which does not install `tzdata`; and NumPy 2.5.3, SciPy 1.18.1 and contourpy 1.4.0, selected for later Python versions). **No known vulnerability.** As a control, the same query returned the published advisories for older versions of NumPy, aiohttp and urllib3.
- **Release notes** of the locked version and of every later release: a defect fixed after the locked version is an anomaly of the locked version.
- **Open issues** of the project's issue tracker, searched for the functions that Sinus uses.

Each review below states what Sinus uses, what was reviewed, and the anomalies relevant to that use, with the reason why they do or do not affect Sinus. None needs a change to [`risk-analysis.md`](risk-analysis.md).

### Python (CPython) 3.11

- **Used by Sinus:** `hashlib.sha256` (verification of the data files, §8.3 of [`architecture.md`](architecture.md), and the source digest, §8.14); `urllib.request` (download over HTTPS, redirects followed, §8.3); `math.fsum`, `math.tan`, `math.cos` (§8.2, §8.6); float formatting and `repr` (reports, golden vectors); `os.replace` and `os.walk`; in the scripts, `argparse`, `tomllib` and `ast`.
- **Reviewed:** the release status of the 3.11 series, and the security fixes of 3.11.17 (2026-10-01), the release after 3.11.16. Python 3.11 receives security fixes only, until October 2027 (PEP 664). `dsp/.python-version` names the minor version only, so CI and local environments use the latest 3.11 build that their version of uv provides (3.11.16 on the development machine on 2026-10-05).
- **Relevant anomalies:**
  - The security fixes of 3.11.17 that 3.11.16 lacks concern `tarfile`, `zipfile`, the bundled `libexpat`, server-side and `asyncio` uses of `ssl`, the `idna` codec, credentials of `urllib.request.HTTPPasswordMgr` (CVE-2026-15806), and the formatting of a float with a precision close to the platform's `INT_MAX`. Sinus uses none of these modules or functions; it opens HTTPS connections without credentials to ASCII host names and formats floats with small, fixed precisions. Not affected.
  - In general, a defect in `urllib` or `http.client` cannot make Sinus accept altered data: Sinus requests only fixed `https://physionet.org/` addresses built from validated record names, and a file counts as verified only if its SHA-256 equals the value of the pinned checksum list (SC-5 of [`cybersecurity.md`](cybersecurity.md)). A defect in the transport can stop a download; it cannot make an altered file count as verified. Not affected.
  - `math.tan` and `math.cos` call the platform's mathematical library, whose results may differ in the last place between platforms. Known and handled: the CI environment is the authority for the stored subset report ([`architecture.md`](architecture.md) §8.11).
  - The patch level is not pinned, and the 3.11 series ends in October 2027. NumPy 2.4 and SciPy 1.17 are the last series that support Python 3.11 (see below), so a later defect fix in them would need a newer Python. Not an anomaly of the current versions; the choice of a newer Python is OP-065.

### NumPy 2.4.6

- **Used by Sinus:** creation and conversion of 1-D `float64` and `int64` arrays (`array`, `asarray`, `ascontiguousarray`, `zeros`, `full`, `arange`, `vstack`); `abs`, `max`, `argmax`, `argmin`, `isfinite`, `count_nonzero`; element-wise arithmetic; `exp` and `sin` only in the synthetic test signals of `sinus_dsp.synthetic`. No file input or output, no pickling, no linear algebra, no random numbers, no sums with `numpy.sum` or `numpy.mean` (§8.2).
- **Reviewed:** release notes of 2.4.6 and of the later releases 2.5.0 to 2.5.3. 2.4.6 is the last release of the 2.4 series and of any series that supports Python 3.11 (2.5 requires Python 3.12). Open issues labelled as bugs that concern `argmax`, `argmin`, `max`, `isfinite`, `count_nonzero`, `exp`, `sin` and `vstack`.
- **Relevant anomalies:**
  - Defects fixed after 2.4.6 concern `StringDType`, `datetime64`, random number generation, `f2py`, linear algebra, masked arrays, reference leaks on error paths and iterator internals. Sinus uses none of them. Not affected.
  - Open defects concern object arrays, NaN handling in `argmax` and `argmin`, and the speed of `argmax` on multidimensional arrays. Sinus passes only finite (SRS-003), numeric, 1-D arrays. Not affected.
  - **Machine-dependent results of `exp` and `sin`.** NumPy selects at run time between a baseline implementation of the `float64` `exp` and `sin` and an implementation for AVX2 and FMA3 processors (`numpy.lib.introspect.opt_func_info`, checked on 2026-10-05), so their results may differ in the last bits between machines. Sinus uses them only to build the synthetic inputs of the golden vectors ([`architecture.md`](architecture.md) §7.2), which are regenerated in the CI run that uses them and compared with the C++ library within the tolerances of OP-005 (§7.5). No report value depends on them. No effect on any result.
  - **Machine-dependent results of `convolve`** (added on 2026-10-08). `scipy.signal.lfilter` with FIR coefficients calls `numpy.convolve`, which computes each output as a dot product through the BLAS library bundled with NumPy (OpenBLAS 0.3.31, which selects its kernel for the processor at run time, `numpy.show_config()`); its summation order is not sequential, so the derivative and the integrated signal of the detection ([`architecture.md`](architecture.md) §8.7.1) may differ in the last bits between machines (checked on 2026-10-08: about 1e-15 relative to a sequential sum). A detection decision changes only on a near tie at that level. Known and handled as for `math` above: the CI environment is the authority for the stored subset report ([`architecture.md`](architecture.md) §8.2, §8.11), and the C++ library is compared within tolerances. No effect on any reported result.

### SciPy 1.17.1

- **Used by Sinus:** `scipy.signal.sosfilt` with an initial state (`zi`) and `scipy.signal.lfilter` with FIR coefficients (`a = [1.0]`), on 1-D `float64` arrays. The coefficients are computed in closed form by Sinus ([`architecture.md`](architecture.md) §8.6, §8.7); no SciPy filter-design function and no `lfilter_zi` or `sosfilt_zi` runs.
- **Reviewed:** release notes and issue lists of 1.17.1, 1.18.0 and 1.18.1. 1.17.1 is the last release of any series that supports Python 3.11 (1.18 requires Python 3.12). Open issues that mention `sosfilt` or `lfilter`.
- **Relevant anomalies:**
  - No defect of `sosfilt` or `lfilter` was fixed after 1.17.1. `lfilter_zi` was rewritten in 1.18.0; Sinus does not use it. Not affected.
  - Open issues: requests for enhancements (several channels, complex coefficients, a unified filter interface); scipy/scipy#21771, `lfilter` slow on some machines with about 10 000 coefficients (speed only; Sinus uses at most the 150 ms integration window, 54 coefficients at 360 Hz); scipy/scipy#19321, an interpreter crash in a test with object arrays on a debug build of Python (Sinus uses `float64`). Not affected.
  - Floating-point contraction in the SciPy build may change filter outputs in the last place between builds. Known and handled as for `math` above ([`architecture.md`](architecture.md) §8.11).

### wfdb 4.3.1

- **Used by Sinus:** `wfdb.rdheader(path)`, `wfdb.rdrecord(path, channels=[channel], physical=True, return_res=64)` and `wfdb.rdann(path, annotator)` on local files of the two MIT-BIH databases (signal format 212), with paths built from the data folder and validated record names. No PhysioNet access through wfdb (Sinus downloads with its own code, §8.3), no writing, plotting or processing functions.
- **Reviewed:** release notes of 4.2.0, 4.3.0 and 4.3.1 (the latest release, 2026-02-03); the changes on the development branch after 4.3.1 (documentation and one unused import); all 87 open issues on 2026-10-05.
- **Relevant anomalies:**
  - MIT-LCP/wfdb-python#493 and #522: `rdann` raised `OverflowError` with NumPy 2. Fixed in 4.2.0 (the sample differences are computed in 64-bit integers, as the 4.3.1 source shows), although both issues are still open. Not affected.
  - MIT-LCP/wfdb-python#487: `get_contained_labels` fails with recent pandas. It runs only with `summarize_labels=True`, which Sinus does not set. Not affected.
  - Issues on headers of other databases (#528), on dates and times in headers (#415; the headers used have none), on `sampfrom` and `sampto` in `rdann` (#470; not used) and on the `WFDB` path variable (#545; not used). Not affected.
  - The remaining open issues concern writing (`wrsamp`, `wrann`), plotting, downloads, EDF and FLAC formats, and the processing functions (`xqrs`, `gqrs`, `find_local_peaks`). Sinus uses none of them. Not affected.
  - **Behaviours that Sinus relies on, recorded as known:** a sample equal to the invalid-sample value of its format is returned as NaN by `rdrecord(..., physical=True)`; Sinus rejects a non-finite signal (SRS-003), and the validation runs on all 48 records and the 12 noise stress records raised no such rejection. Headers are read as ASCII and units default to mV ([`architecture.md`](architecture.md) §8.4). Local files are opened through `fsspec`, which interprets URL-like paths; Sinus passes only file-system paths.

### Transitive runtime packages

- **On the code path of Sinus:** importing wfdb and reading a record loads `pandas` 3.0.6, `fsspec` 2026.9.0, `python-dateutil` 2.9.0.post0 and `six` 1.17.0, and no other third-party package besides NumPy (checked on 2026-10-05 by reading records 100, 207 and 118e06 with `sinus_dsp.data.records.load_record`). They serve wfdb only: pandas for its tables of annotation codes and header fields, fsspec to open the files, dateutil (with six) for header dates. wfdb 4.3.1 includes its fix for pandas 3.0 (MIT-LCP/wfdb-python#561), and the requirement tests of SRS-002 and the validation runs read the records through this path. No known vulnerability. Not affected.
- **Installed but not on the code path:** `aiohttp` and `requests` with their dependencies (network access through wfdb, unused), `matplotlib` with its dependencies (plotting), `soundfile` with `cffi` (FLAC formats), `tzdata` (Windows only). No known vulnerability. Their defects cannot change a result of Sinus. Because they are installed, a vulnerability reported in them is still triaged ([`cybersecurity.md`](cybersecurity.md) §7).

**Result.** No known anomaly affects the use that Sinus makes of its SOUP. Each later review records its date, the versions reviewed and its result in this section, when a runtime dependency is added or its locked version changes, and at each milestone release.

## Planned SOUP (recorded when introduced)

The components below are chosen in [`architecture.md`](architecture.md) §9 and in the ADRs. Each becomes a row of the table above, with its exact version and the review of its known anomalies, in the change that introduces it.

| Name | Component | Milestone | Purpose |
|---|---|---|---|
| ESP-IDF | firmware | M4 (library build checks from M2) | Espressif SDK for the ESP32-S3. Used: ADC continuous-mode driver and ADC calibration, GPIO, NimBLE Bluetooth LE host, task watchdog, and the C and C++ runtime libraries of its toolchain ([ADR 0001](../adr/0001-mcu-and-firmware-framework.md)) |
| FreeRTOS | firmware | M4 | Real-time kernel as shipped and configured by ESP-IDF: tasks, priorities, task notifications |
| Qt 6 | desktop | M3 | Application framework: Core, GUI, Widgets or Quick (OP-033), Bluetooth, Serial Port, Network. LGPL-3.0 modules only, linked dynamically ([ADR 0003](../adr/0003-qt-desktop-application-with-replay.md)) |
| FastAPI | backend | M5 | Web API framework, with its runtime dependencies (e.g. Starlette, Pydantic) and an ASGI server; database and FHIR libraries are chosen at Milestone 5 |
| C++ standard library and C library of the computer's toolchain | libs/sinus-dsp | M2 | Linked into the library on the computer (in CI: libstdc++, libgcc and glibc of GCC 14 on Ubuntu 24.04; with Clang 18 the same libstdc++). Used: `<cmath>` (`std::tan`, `std::cos`, `std::sqrt`, `std::floor`, `std::ceil` at configuration; `std::isfinite`, `std::fabs` per sample) and `<array>`; no allocation ([`architecture.md`](architecture.md) §9, §14.3) |
| C++ standard library and newlib of the ESP-IDF toolchain | libs/sinus-dsp (build for the ESP32-S3); firmware | M2 (test build); M4 | The same functions, from libstdc++ and newlib of `xtensa-esp-elf` esp-15.2.0 in ESP-IDF v6.1 ([`architecture.md`](architecture.md) §14.13) |

- `libs/sinus-dsp` uses only the C++ standard library and the C library of each toolchain (the two rows above); they become rows of the table above, with their review, when the library code lands (Milestone 2, group C2 of [`architecture.md`](architecture.md) §14.18).
- The WFDB implementation of the desktop application is decided in OP-050. A third-party library would be added here.

## Development tools (not SOUP)

Development-only tools are not part of any software item and are not listed as SOUP (`sdp.md` §7):
- Python: pytest, ruff, mypy, and `cyclonedx-bom`, which generates the SBOM. They are pinned in `dsp/uv.lock` in the `dev` group;
- vulnerability scanning: OSV-Scanner, which scans the SBOM in CI. Its release is pinned in `.github/workflows/ci.yml` by version and SHA-256 ([`cybersecurity.md`](cybersecurity.md) §7);
- dependency monitoring: Dependabot, a GitHub service (alerts, and version updates of the CI actions configured in `.github/dependabot.yml`);
- C++ (planned for Milestone 2, [`architecture.md`](architecture.md) §14.2, §14.13): the compilers; CMake, Ninja, clang-format, clang-tidy and gcovr, pinned in `libs/sinus-dsp/tools/uv.lock`; GoogleTest 1.18.0, pinned by URL and SHA-256; the ESP-IDF container image with Espressif's QEMU, pinned by tag and digest (ESP-IDF itself becomes SOUP with the firmware).
