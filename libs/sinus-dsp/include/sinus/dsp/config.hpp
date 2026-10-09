#pragma once

// SRS-017: the configuration of the real-time library and its check (architecture-m2.md 14.4,
// 14.5).

#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

struct Config {
  double sampling_frequency_hz = 0.0;
  int mains_frequency_hz = 0;  // 50 or 60
};

// SRS-017: kOk, or the first failing check, in this order: kInvalidSamplingFrequency (not finite,
// or outside 125 Hz to 1000 Hz, bounds included), then kInvalidMainsFrequency (not 50 or 60).
[[nodiscard]] Status validate(const Config& config) noexcept;

}  // namespace sinus::dsp
