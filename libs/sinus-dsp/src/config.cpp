// SRS-017: the configuration check (architecture-m2.md 14.5).
#include "sinus/dsp/config.hpp"

#include <cmath>

#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

Status validate(const Config& config) noexcept {
  const double fs = config.sampling_frequency_hz;
  if (!std::isfinite(fs) || fs < kMinSamplingFrequencyHz || fs > kMaxSamplingFrequencyHz) {
    return Status::kInvalidSamplingFrequency;
  }
  if (config.mains_frequency_hz != 50 && config.mains_frequency_hz != 60) {
    return Status::kInvalidMainsFrequency;
  }
  return Status::kOk;
}

}  // namespace sinus::dsp
