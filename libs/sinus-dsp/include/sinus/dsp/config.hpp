#pragma once

// SRS-017: the configuration of the real-time library and its check (architecture-m2.md 14.4,
// 14.5).

#include <cstdint>

#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

struct Config {
  double sampling_frequency_hz = 0.0;
  int mains_frequency_hz = 0;  // 50 or 60
};

// SRS-017: kOk, or the first failing check, in this order: kInvalidSamplingFrequency (not finite,
// or outside 125 Hz to 1000 Hz, bounds included), then kInvalidMainsFrequency (not 50 or 60).
[[nodiscard]] Status validate(const Config& config) noexcept;

// The parameters of detection in samples (architecture-m1.md 8.7, table "Parameters in samples";
// architecture-m2.md 14.3, "Times in samples"): the same integers as the reference.
struct DetectorSamples {
  std::uint32_t band_delay, window, peak_timeout, refractory, t_wave_window, learning,
      relearn_after;
};
// The parameters of the signal quality index in samples (architecture-m2.md 13.6).
struct QualitySamples {
  std::uint32_t block, window, held, report_delay, zone;
};
// Preconditions: a sampling frequency that validate() accepts.
[[nodiscard]] DetectorSamples detector_samples(double fs_hz) noexcept;
[[nodiscard]] QualitySamples quality_samples(double fs_hz) noexcept;

}  // namespace sinus::dsp
