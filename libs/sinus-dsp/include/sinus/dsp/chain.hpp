#pragma once

// SRS-017, SRS-018, SRS-031, SRS-032: the processing chain, its input checks and its restart
// (architecture-m2.md 14.4, 14.5, 14.10): signal conditioning, detection, heart rate and signal
// quality, in this order within a sample.

#include <array>
#include <cstddef>

#include "sinus/dsp/conditioner.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/heart_rate.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/signal_quality.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

struct SampleOutput {
  float baseline_mv = 0.0F;
  float conditioned_mv = 0.0F;
  std::size_t detection_count = 0;  // detections reported at this sample (architecture-m2.md 14.7)
  std::array<Detection, kMaxDetectionsPerSample> detections{};
  std::size_t heart_rate_count = 0;  // heart-rate events at this sample (14.8)
  std::array<HeartRateEvent, kMaxHeartRateEventsPerSample> heart_rates{};
  bool has_window = false;  // a quality window is reported at this sample (14.9)
  QualityWindow window{};
};

class Chain {
 public:
  Chain() noexcept = default;  // not configured
  // SRS-017: a configuration that validate() rejects leaves the chain not configured, whatever it
  // was before. On success a new stream starts, as after reset().
  [[nodiscard]] Status configure(const Config& config) noexcept;
  // SRS-031: a new stream with the same configuration; clears the stop of SRS-018.
  void reset() noexcept;
  // SRS-017, SRS-018: kNotConfigured, kStopped, kInvalidSample (the chain is stopped) or kOk.
  // With any status but kOk, out holds no result (all zero).
  [[nodiscard]] Status process(float sample_mv, SampleOutput& out) noexcept;
  [[nodiscard]] bool configured() const noexcept { return configured_; }
  [[nodiscard]] const Config& config() const noexcept { return config_; }

 private:
  Config config_{};
  Conditioner conditioner_;
  QrsDetector detector_;
  HeartRateTracker heart_rate_;
  SignalQuality quality_;
  bool configured_ = false;
  bool stopped_ = false;
};

static_assert(sizeof(Chain) <= kChainMemoryLimitBytes);  // SRS-032

}  // namespace sinus::dsp
