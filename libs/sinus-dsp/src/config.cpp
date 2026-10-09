// SRS-017: the configuration check (architecture-m2.md 14.5). The parameters in samples are those
// of the reference (_units.py, qrs.py, quality.py), in binary64 (architecture-m2.md 14.3, "Times in
// samples").
#include "sinus/dsp/config.hpp"

#include <cmath>
#include <cstdint>

#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

namespace {

// floor(t_ms * fs / 1000 + 0.5), as round_samples_ms.
std::uint32_t round_samples_ms(double t_ms, double fs_hz) noexcept {
  return static_cast<std::uint32_t>(std::floor(((t_ms * fs_hz) / 1000.0) + 0.5));
}

// floor(t_ms * fs / 1000), as floor_samples_ms.
std::uint32_t floor_samples_ms(double t_ms, double fs_hz) noexcept {
  return static_cast<std::uint32_t>(std::floor((t_ms * fs_hz) / 1000.0));
}

// ceil(t_ms * fs / 1000), as ceil_samples_ms.
std::uint32_t ceil_samples_ms(double t_ms, double fs_hz) noexcept {
  return static_cast<std::uint32_t>(std::ceil((t_ms * fs_hz) / 1000.0));
}

// floor(t_s * fs + 0.5), as round_samples.
std::uint32_t round_samples(double t_s, double fs_hz) noexcept {
  return static_cast<std::uint32_t>(std::floor((t_s * fs_hz) + 0.5));
}

}  // namespace

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

DetectorSamples detector_samples(double fs_hz) noexcept {
  return DetectorSamples{
      round_samples_ms(36.0, fs_hz),   // band delay D
      round_samples_ms(150.0, fs_hz),  // integration window N
      round_samples_ms(95.0, fs_hz),   // peak timeout P
      ceil_samples_ms(200.0, fs_hz),   // refractory R, rounded up
      round_samples_ms(360.0, fs_hz),  // T-wave window TW
      round_samples(2.0, fs_hz),       // learning L
      round_samples(8.0, fs_hz),       // re-learning G
  };
}

QualitySamples quality_samples(double fs_hz) noexcept {
  const std::uint32_t block = round_samples_ms(1000.0, fs_hz);
  return QualitySamples{
      block,
      10U * block,                     // window W
      5U * block,                      // held stretch
      floor_samples_ms(500.0, fs_hz),  // report delay
      round_samples_ms(150.0, fs_hz),  // zone: the detector's N
  };
}

}  // namespace sinus::dsp
