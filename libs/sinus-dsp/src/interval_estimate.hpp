#pragma once

// SRS-024, SRS-025: the estimator of the heart rate (architecture-m2.md 13.5, steps 1 to 4), on
// integers only. Private to the library; the unit tests call it directly.

#include <cstddef>
#include <cstdint>

namespace sinus::dsp {

inline constexpr std::size_t kEstimateMinIntervals = 4;   // SRS-026
inline constexpr std::size_t kEstimateRobustWindow = 5;   // intervals
inline constexpr std::size_t kEstimateMeanWindow = 6;     // intervals
inline constexpr std::uint64_t kInlierLowPercent = 92;    // 13.5, step 2
inline constexpr std::uint64_t kInlierHighPercent = 116;  // 13.5, step 2

// k intervals whose sum is span: the rate is 60 fs k / span.
struct IntervalEstimate {
  std::uint32_t n_intervals;
  std::uint64_t span_samples;
  bool robust;  // the robust method; false: the mean of all the intervals given
};

// Preconditions (not checked): count from kEstimateMinIntervals to kEstimateMeanWindow, every
// interval positive, oldest first.
[[nodiscard]] IntervalEstimate estimate_intervals(const std::uint64_t* intervals,
                                                  std::size_t count) noexcept;

}  // namespace sinus::dsp
