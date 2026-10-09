#pragma once

// Distance in units in the last place between two finite numbers of the same type.

#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace sinus::dsp::testing {

namespace detail {

// Maps the bit pattern to an integer that grows with the value (-0.0 and +0.0 are both 0).
inline std::int64_t ordered(double v) {
  std::int64_t bits = 0;
  std::memcpy(&bits, &v, sizeof bits);
  return bits < 0 ? std::int64_t{INT64_MIN} - bits : bits;
}

inline std::int32_t ordered(float v) {
  std::int32_t bits = 0;
  std::memcpy(&bits, &v, sizeof bits);
  return bits < 0 ? std::int32_t{INT32_MIN} - bits : bits;
}

}  // namespace detail

inline std::int64_t ulp_distance(double a, double b) {
  return std::llabs(detail::ordered(a) - detail::ordered(b));
}

inline std::int64_t ulp_distance(float a, float b) {
  return std::llabs(static_cast<long long>(detail::ordered(a)) -
                    static_cast<long long>(detail::ordered(b)));
}

}  // namespace sinus::dsp::testing
