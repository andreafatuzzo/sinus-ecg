// SRS-017, SRS-018, SRS-031: configuration, input checks, stop and restart of the chain
// (architecture-m2.md 14.5, 14.10).
#include "sinus/dsp/chain.hpp"

#include <cmath>

#include "sinus/dsp/conditioner.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/limits.hpp"
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
  config_ = config;
  configured_ = true;
  return Status::kOk;
}

void Chain::reset() noexcept {
  if (!configured_) {
    return;
  }
  conditioner_.reset();
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
  out.baseline_mv = conditioned.baseline_mv;
  out.conditioned_mv = conditioned.conditioned_mv;
  return Status::kOk;
}

}  // namespace sinus::dsp
