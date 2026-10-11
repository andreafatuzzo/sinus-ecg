// SRS-024, SRS-025: the estimator of the heart rate (architecture-m2.md 13.5, steps 1 to 4), as
// estimate_intervals of dsp/sinus_dsp/heart_rate.py. Integers only.
#include "interval_estimate.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <utility>

namespace sinus::dsp {

namespace {

// Element k of a fixed array, with k always in range by the callers (at most six intervals).
template <typename Array>
auto& element(Array& array, std::size_t k) noexcept {
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-avoid-unchecked-container-access): k % size.
  return array[k % array.size()];
}

}  // namespace

IntervalEstimate estimate_intervals(const std::uint64_t* intervals, std::size_t count) noexcept {
  // Step 1: w is the last min(5, count) intervals; M the third smallest of w (the upper middle
  // of four).
  const std::size_t window = std::min(count, kEstimateRobustWindow);
  const std::size_t first = count - window;
  std::array<std::uint64_t, kEstimateRobustWindow> w{};
  std::array<std::uint64_t, kEstimateRobustWindow> sorted{};
  for (std::size_t i = 0; i < window; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): count intervals given.
    element(w, i) = element(sorted, i) = intervals[first + i];
  }
  for (std::size_t i = 1; i < window; ++i) {  // insertion sort of at most five values
    for (std::size_t j = i; j > 0 && element(sorted, j) < element(sorted, j - 1); --j) {
      std::swap(element(sorted, j), element(sorted, j - 1));
    }
  }
  const std::uint64_t middle = element(sorted, 2);

  // Step 2: the outliers, with the limits of 92 % and 116 % of M.
  std::array<bool, kEstimateRobustWindow> outlier{};
  std::size_t outliers = 0;
  std::size_t first_outlier = 0;
  std::size_t second_outlier = 0;
  for (std::size_t i = 0; i < window; ++i) {
    const std::uint64_t v = element(w, i);
    const bool is_outlier =
        100U * v < kInlierLowPercent * middle || 100U * v > kInlierHighPercent * middle;
    element(outlier, i) = is_outlier;
    if (is_outlier) {
      if (outliers == 0) {
        first_outlier = i;
      } else if (outliers == 1) {
        second_outlier = i;
      }
      ++outliers;
    }
  }

  // Step 3: the robust estimate with no outlier, one, or two that are adjacent in w.
  if (outliers <= 1 || (outliers == 2 && second_outlier == first_outlier + 1)) {
    std::uint32_t inliers = 0;
    std::uint64_t span = 0;
    for (std::size_t i = 0; i < window; ++i) {
      if (!element(outlier, i)) {
        ++inliers;
        span += element(w, i);
      }
    }
    return IntervalEstimate{inliers, span, true};
  }

  // Step 4: the mean of all the intervals given.
  std::uint64_t span = 0;
  for (std::size_t i = 0; i < count; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): count intervals given.
    span += intervals[i];
  }
  return IntervalEstimate{static_cast<std::uint32_t>(count), span, false};
}

}  // namespace sinus::dsp
