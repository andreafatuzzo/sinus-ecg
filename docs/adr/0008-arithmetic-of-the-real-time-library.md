# ADR 0008: Arithmetic of the real-time library

- **Status:** Accepted
- **Date:** 2026-10-08
- **Deciders:** project owner (decision); tech lead (proposal, analysis)
- **Related:** amends the precision rule of [ADR 0002](0002-portable-cpp-dsp-library.md) ("binary32 in the real-time path, `double` only at configuration time"); SRS-019, SRS-032, SRS-034, SRS-036, SRS-038; RC-012; OP-005, OP-014, OP-049, OP-057; [`architecture.md`](../regulatory/architecture.md) §4.2, §5.1, §7.1, §14.3, §14.10, §14.11

## Context

ADR 0002 chose binary32 for the whole real-time path, because the floating-point unit of the ESP32-S3 is single precision, and left the differences from the binary64 reference to tolerances (OP-005). The project owner decided on 2026-10-07 what equivalence means (SRS-034, SRS-036, SRS-038): the same detections with the same marks, the same heart-rate statuses at the same samples, the same usable marks, values within tolerances, the conditioning within a tolerance far below 5 µV (the step of the reference recordings), and the same counts per record on the whole reference databases.

To set the tolerances, the tech lead modelled the planned C++ arithmetic in Python, rounding every operation to binary32 in the order of the design, and compared it with the reference on the golden set (32 files) and on all 63 records of the two reference databases (148 407 detections). Results (`architecture.md` §14.11):

| Arithmetic | Conditioning, largest difference (golden / databases) | Detections | Integrated-peak ties | Report-sample ties | Memory per chain (1000 Hz capacity) |
|---|---|---|---|---|---|
| binary32 throughout | 0.71 µV / **3.5 µV**; 4.3 µV on a 6 mV input at 1000 Hz | identical | 90–103 | 2 | about 52 KB |
| binary64 conditioning, binary32 elsewhere | **0.0018 µV** / **0.0018 µV** | identical | 110 | 1 | about 52 KB |
| binary64 throughout | as above | identical | 0 | 0 | about 95 KB |

The cause of the binary32 conditioning error is the baseline wander stage: its poles lie at radius 0.9939 at 360 Hz (0.9978 at 1000 Hz), so the rounding errors inside its recursion are amplified about 730 times (3 400 times at 1000 Hz). The other stages amplify theirs at most about 110 times, and detection decisions depend on them only in near ties.

## Options considered

1. **Binary32 throughout (ADR 0002 as accepted).** Uses the floating-point unit everywhere; fails "far below 5 µV" on real data (3.5 µV on record 118e_6 of the Noise Stress Test Database).
2. **Binary64 for the two signal-conditioning stages, binary32 for detection, heart rate and signal quality (chosen).** The conditioning difference becomes the rounding of the input and output (at most 0.0018 µV on all the data). Detection decisions stay identical on all the data; rare ties of the integrated-peak position remain, which change no detection and are absorbed by the tolerance of the signal quality index. Cost: about 20 software binary64 operations per sample on the ESP32-S3, below 1 % of a core at 360 Hz; no change of memory.
3. **Binary64 throughout.** No ties at all and tolerances of the order of 1e-9; about 43 KB more per chain (the store of peaks and the learning windows double), about 1–2 % of a core on the ESP32-S3 (estimate), and the floating-point unit no longer used.
4. **A low-noise realisation of the baseline stage in binary32** (for example a coupled form). About eighty times less noise, but a second set of coefficients, a realisation that differs from the reference's, and still a worst-case bound near the criterion.

## Decision

Option 2. The library takes and gives samples in binary32. Its two signal-conditioning stages compute in binary64, in transposed direct form II with the operation order of the reference, and round their outputs once to binary32. Detection, heart rate and the signal quality index compute in binary32, in the operation order of `architecture.md` §14.3. Every use of `double` in the real-time path is explicit; implicit promotion stays a compile error. No floating-point contraction and no fast-math on any target (OP-057).

## Consequences

- **Positive:** the conditioning tolerance can be 2e-5 mV, 250 times below 5 µV, with a rigorous bound; the memory and the binary32 detection path of ADR 0002 are kept; the same binary64 results on the computer and the ESP32-S3.
- **Negative and risks:** a mixed arithmetic to explain and review (the order of every operation is written in §14.3); software binary64 on the ESP32-S3, measured with the firmware (OP-014); the remaining binary32 ties could make a golden vector fail after a change of the reference (about 1 detection in 100 000 for the report sample, none in 150 109 for the index): the owner's rule for near ties applies (OP-056 (b)).
- **Follow-up:** `architecture.md` §4.2, §5.1, §7.1 (done in v0.4); the rationale of SRS-034 mentions "the binary32 library", which the PM may reword; at acceptance, the status line of ADR 0002 becomes "Accepted; precision rule amended by ADR 0008".
