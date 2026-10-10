// SRS-019: baseline wander stage, then mains stage, in binary64 (architecture-m2.md 14.3, 14.6).
#include "sinus/dsp/conditioner.hpp"

#include "sinus/dsp/biquad.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

Status Conditioner::configure(const Config& config) noexcept {
  configured_ = false;
  started_ = false;
  const Status status = validate(config);
  if (status != Status::kOk) {
    return status;
  }
  baseline_.set(baseline_coefficients(config.sampling_frequency_hz));
  mains_.set(mains_coefficients(config.sampling_frequency_hz, config.mains_frequency_hz));
  configured_ = true;
  return Status::kOk;
}

void Conditioner::reset() noexcept {
  // The coefficients are kept; the first sample of the new stream sets the states (start).
  started_ = false;
}

Status Conditioner::process(float sample_mv, ConditionedSample& out) noexcept {
  if (!configured_) {
    out = ConditionedSample{0.0F, 0.0F};
    return Status::kNotConfigured;
  }
  const auto x = static_cast<double>(sample_mv);
  if (!started_) {
    baseline_.start(x);  // steady state of a constant input equal to the first sample
  }
  const double baseline = baseline_.step(x);
  if (!started_) {
    mains_.start(baseline);  // the baseline output of the first sample, exactly 0.0
    started_ = true;
  }
  const double conditioned = mains_.step(baseline);  // the binary64 value, never its rounding
  out = ConditionedSample{static_cast<float>(baseline), static_cast<float>(conditioned)};
  return Status::kOk;
}

}  // namespace sinus::dsp
