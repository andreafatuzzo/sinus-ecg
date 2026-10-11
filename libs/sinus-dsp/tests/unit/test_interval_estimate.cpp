#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <vector>

#include "interval_estimate.hpp"

namespace {

using sinus::dsp::estimate_intervals;
using sinus::dsp::IntervalEstimate;

IntervalEstimate estimate(const std::vector<std::uint64_t>& intervals) {
  return estimate_intervals(intervals.data(), intervals.size());
}

void expect_estimate(const std::vector<std::uint64_t>& intervals, std::uint32_t k,
                     std::uint64_t span, bool robust) {
  const IntervalEstimate e = estimate(intervals);
  EXPECT_EQ(e.n_intervals, k);
  EXPECT_EQ(e.span_samples, span);
  EXPECT_EQ(e.robust, robust);
}

TEST(IntervalEstimate, RegularRhythmUsesEveryIntervalOfTheWindow) {
  expect_estimate({100, 100, 100, 100}, 4, 400, true);
  expect_estimate({100, 100, 100, 100, 100}, 5, 500, true);
  // Six intervals given: the window is the last five.
  expect_estimate({90, 100, 100, 100, 100, 100}, 5, 500, true);
}

TEST(IntervalEstimate, AMissedDetectionIsLeftOutAtAnyPosition) {
  expect_estimate({100, 100, 200, 100, 100}, 4, 400, true);
  expect_estimate({200, 100, 100, 100, 100}, 4, 400, true);
  expect_estimate({100, 100, 100, 100, 200}, 4, 400, true);
  expect_estimate({100, 100, 100, 100, 100, 200}, 4, 400, true);
}

TEST(IntervalEstimate, AnAddedDetectionIsLeftOutAtAnyPosition) {
  expect_estimate({100, 100, 50, 50, 100}, 3, 300, true);
  expect_estimate({50, 50, 100, 100, 100}, 3, 300, true);
  expect_estimate({100, 100, 100, 50, 50}, 3, 300, true);
}

TEST(IntervalEstimate, AnIsolatedPrematureBeatWithItsPauseIsLeftOut) {
  expect_estimate({100, 100, 60, 140, 100}, 3, 300, true);
}

TEST(IntervalEstimate, TwoOutliersThatAreNotAdjacentGiveTheMeanOfAllTheIntervals) {
  expect_estimate({100, 50, 100, 50, 100}, 5, 400, false);
  expect_estimate({80, 100, 50, 100, 50, 100}, 6, 480, false);
  expect_estimate({50, 100, 100, 100, 50}, 5, 400, false);  // both at the ends
}

TEST(IntervalEstimate, BigeminyGivesTheMeanRate) {
  expect_estimate({150, 300, 150, 300, 150, 300}, 6, 1350, false);
  expect_estimate({300, 150, 300, 150, 300, 150}, 6, 1350, false);
}

TEST(IntervalEstimate, ThreeOutliersGiveTheMean) {
  // M = 100; 40, 200 and 30 are outliers, not two adjacent ones.
  expect_estimate({40, 100, 200, 100, 30}, 5, 470, false);
}

TEST(IntervalEstimate, FourIntervalsTakeTheUpperMiddleAsTheMiddle) {
  expect_estimate({100, 100, 100, 300}, 3, 300, true);   // M = 100
  expect_estimate({100, 300, 300, 100}, 4, 800, false);  // M = 300, two outliers not adjacent
  expect_estimate({100, 100, 300, 300}, 2, 600, true);   // M = 300, adjacent outliers left out
}

TEST(IntervalEstimate, TheLimitsOfTheInliersAre92And116PercentOfTheMiddleIncluded) {
  expect_estimate({100, 100, 100, 92, 116}, 5, 508, true);
  expect_estimate({100, 100, 100, 91, 117}, 3, 300, true);  // both outside, adjacent
  expect_estimate({100, 100, 100, 91, 116}, 4, 416, true);
  expect_estimate({100, 100, 100, 92, 117}, 4, 392, true);
}

TEST(IntervalEstimate, TheMiddleIsAnInlierSoTheEstimateIsNeverEmpty) {
  for (std::uint64_t a = 1; a < 40; ++a) {
    for (std::uint64_t b = 1; b < 40; ++b) {
      const IntervalEstimate e = estimate({a, b, 20, b, a, 20});
      ASSERT_GE(e.n_intervals, 1U);
      ASSERT_GT(e.span_samples, 0U);
    }
  }
}

}  // namespace
