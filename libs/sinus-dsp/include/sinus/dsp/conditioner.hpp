#pragma once

// SRS-019: removal of baseline wander and then mains interference, one sample at a time and
// without delay (architecture-m2.md 14.6).

#include "sinus/dsp/biquad.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

struct ConditionedSample {
  float baseline_mv;
  float conditioned_mv;
};

class Conditioner {
 public:
  // SRS-017: kInvalidSamplingFrequency or kInvalidMainsFrequency, as validate(); a failure leaves
  // the object not configured.
  [[nodiscard]] Status configure(const Config& config) noexcept;
  // The state that follows configure with the same configuration (SRS-031).
  void reset() noexcept;
  // SRS-019: the stage outputs of this sample, in the same call. Precondition: a finite sample
  // within kMaxAbsSampleMv (Chain checks it). Returns kNotConfigured, with both values 0, before
  // a successful configure.
  [[nodiscard]] Status process(float sample_mv, ConditionedSample& out) noexcept;

 private:
  BiquadF64 baseline_;
  BiquadF64 mains_;
  bool configured_ = false;
  bool started_ = false;  // the first sample of the stream has been given
};

}  // namespace sinus::dsp
