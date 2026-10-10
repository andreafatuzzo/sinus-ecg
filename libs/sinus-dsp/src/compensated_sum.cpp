// The compensated sum of architecture-m2.md 14.3, in its order of operations.
#include "compensated_sum.hpp"

#include <cmath>

namespace sinus::dsp {

void compensated_add(float& sum, float& compensation, float v) noexcept {
  const float t = sum + v;
  compensation += (std::fabs(sum) >= std::fabs(v)) ? ((sum - t) + v) : ((v - t) + sum);
  sum = t;
}

float compensated_value(float sum, float compensation) noexcept { return sum + compensation; }

void CompensatedSum::add(float v) noexcept { compensated_add(sum_, compensation_, v); }

float CompensatedSum::value() const noexcept { return compensated_value(sum_, compensation_); }

}  // namespace sinus::dsp
