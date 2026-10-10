// SRS-017, SRS-018, SRS-031: configuration, input checks, stop and restart of the chain
// (architecture-m2.md 14.5, 14.10).
#include "sinus/dsp/chain.hpp"

#include <array>
#include <cmath>
#include <cstddef>

#include "sinus/dsp/conditioner.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/heart_rate.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/signal_quality.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

Status Chain::configure(const Config& config) noexcept {
  configured_ = false;
  stopped_ = false;
  config_ = Config{};
  const Status status = validate(config);  // SRS-017
  if (status != Status::kOk) {
    return status;
  }
  const Status conditioner_status = conditioner_.configure(config);
  if (conditioner_status != Status::kOk) {
    return conditioner_status;
  }
  const Status detector_status = detector_.configure(config.sampling_frequency_hz);
  if (detector_status != Status::kOk) {
    return detector_status;
  }
  const Status heart_rate_status = heart_rate_.configure(config.sampling_frequency_hz);
  if (heart_rate_status != Status::kOk) {
    return heart_rate_status;
  }
  const Status quality_status = quality_.configure(config.sampling_frequency_hz);
  if (quality_status != Status::kOk) {
    return quality_status;
  }
  config_ = config;
  configured_ = true;
  return Status::kOk;
}

void Chain::reset() noexcept {
  if (!configured_) {
    return;
  }
  conditioner_.reset();
  detector_.reset();
  heart_rate_.reset();
  quality_.reset();
  stopped_ = false;  // SRS-018, SRS-031
}

Status Chain::process(float sample_mv, SampleOutput& out) noexcept {
  out = SampleOutput{};
  if (!configured_) {
    return Status::kNotConfigured;  // SRS-017
  }
  if (stopped_) {
    return Status::kStopped;  // SRS-018
  }
  if (!std::isfinite(sample_mv) || std::fabs(sample_mv) > kMaxAbsSampleMv) {
    stopped_ = true;  // SRS-018: the sample changes no state of the stream
    return Status::kInvalidSample;
  }
  ConditionedSample conditioned{0.0F, 0.0F};
  const Status status = conditioner_.process(sample_mv, conditioned);  // SRS-019
  if (status != Status::kOk) {
    return status;
  }
  DetectorStep step;
  const Status detector_status = detector_.process(conditioned.conditioned_mv, step);  // SRS-020
  if (detector_status != Status::kOk) {
    return detector_status;
  }
  // SRS-024, SRS-025, SRS-026: the heart rate with the detections reported at this sample.
  std::array<ReportedDetection, kMaxDetectionsPerSample> reported{};
  for (std::size_t i = 0; i < step.count; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-avoid-unchecked-container-access): count bounded.
    reported[i] = ReportedDetection{step.detections[i].index, step.detections[i].mark};
  }
  HeartRateStep heart_rate;
  const Status heart_rate_status = heart_rate_.step(reported.data(), step.count, heart_rate);
  if (heart_rate_status != Status::kOk) {
    return heart_rate_status;
  }
  // SRS-027, SRS-028: the signal quality window, with the same detections.
  bool has_window = false;
  QualityWindow window{};
  const Status quality_status = quality_.step(sample_mv, step, has_window, window);
  if (quality_status != Status::kOk) {
    return quality_status;
  }
  out.baseline_mv = conditioned.baseline_mv;
  out.conditioned_mv = conditioned.conditioned_mv;
  out.detection_count = step.count;
  out.detections = step.detections;
  out.heart_rate_count = heart_rate.count;
  out.heart_rates = heart_rate.events;
  out.has_window = has_window;
  out.window = window;
  return Status::kOk;
}

}  // namespace sinus::dsp
