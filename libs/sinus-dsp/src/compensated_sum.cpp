// The compensated sum of architecture-m2.md 14.3, in its order of operations.
#include "compensated_sum.hpp"

#include <cmath>

namespace sinus::dsp {

void CompensatedSum::add(float v) noexcept {
  const float t = sum_ + v;
  compensation_ += (std::fabs(sum_) >= std::fabs(v)) ? ((sum_ - t) + v) : ((v - t) + sum_);
  sum_ = t;
}

float CompensatedSum::value() const noexcept { return sum_ + compensation_; }

}  // namespace sinus::dsp
