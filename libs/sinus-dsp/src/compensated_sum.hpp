#pragma once

// The compensated (Neumaier) sum in binary32, for every sum that the reference computes with
// math.fsum (architecture-m2.md 14.3). The arithmetic is in compensated_sum.cpp, compiled without
// contraction and without reassociation (OP-057).

namespace sinus::dsp {

class CompensatedSum {
 public:
  void add(float v) noexcept;
  [[nodiscard]] float value() const noexcept;

 private:
  float sum_ = 0.0F;
  float compensation_ = 0.0F;
};

}  // namespace sinus::dsp
