/* SRS-038: C interface of the shared library sinus_dsp_harness (computer only), called from the
   Python evaluation with ctypes (architecture-m2.md 14.14). It is not part of the library: it is
   not linked into the firmware and not covered by the source digest. */
#ifndef SINUS_DSP_HARNESS_H
#define SINUS_DSP_HARNESS_H

#include <stdint.h>

#ifdef _WIN32
#define SINUS_DSP_HARNESS_API __declspec(dllexport)
#else
#define SINUS_DSP_HARNESS_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Runs a newly configured Chain on n samples; writes up to `capacity` detections (index, mark,
   report sample) and returns their total number, or -1 - (int)Status on a configuration error or
   an invalid sample. `startup[i]` is 1 for a start-up mark and 0 for a reliable one. The arrays
   may be null when `capacity` is 0, and `samples_mv` when n is 0; a null array otherwise gives
   -1 - (int)kInvalidArgument. */
SINUS_DSP_HARNESS_API int64_t sinus_dsp_harness_detect(double fs_hz, int32_t mains_hz,
                                                       const float* samples_mv, uint64_t n,
                                                       uint64_t* indices, uint8_t* startup,
                                                       uint64_t* reported_at, uint64_t capacity);

/* "<version>;<source SHA-256>" of the library; valid for the life of the process. */
SINUS_DSP_HARNESS_API const char* sinus_dsp_harness_identity(void);

#ifdef __cplusplus
}
#endif

#endif /* SINUS_DSP_HARNESS_H */
