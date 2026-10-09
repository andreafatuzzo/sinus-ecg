#include <gtest/gtest.h>

#include <cstddef>
#include <vector>

#include "reference_values.hpp"
#include "sinus/dsp/conditioner.hpp"
#include "ulp.hpp"

namespace {

using sinus::dsp::ConditionedSample;
using sinus::dsp::Conditioner;
using sinus::dsp::Config;
using sinus::dsp::Status;
using sinus::dsp::testing::ulp_distance;

std::vector<ConditionedSample> run(Conditioner& c, const std::vector<float>& input) {
  std::vector<ConditionedSample> out;
  for (const float x : input) {
    ConditionedSample s{};
    EXPECT_EQ(c.process(x, s), Status::kOk);
    out.push_back(s);
  }
  return out;
}

std::vector<float> test_input(std::size_t n) {
  std::vector<float> x(n);
  for (std::size_t i = 0; i < n; ++i) {
    x[i] = 0.2F * static_cast<float>(i % 17) - 1.3F + 0.01F * static_cast<float>(i % 5);
  }
  return x;
}

TEST(Conditioner, FollowsTheReferenceOnTwelveSamples) {
  for (const auto& r : sinus::dsp::reference::kRuns) {
    Conditioner c;
    ASSERT_EQ(c.configure(Config{r.fs_hz, r.mains_hz}), Status::kOk);
    for (std::size_t n = 0; n < r.input.size(); ++n) {
      ConditionedSample s{};
      ASSERT_EQ(c.process(r.input[n], s), Status::kOk);
      EXPECT_LE(ulp_distance(s.baseline_mv, r.baseline[n]), 1) << r.fs_hz << " baseline " << n;
      EXPECT_LE(ulp_distance(s.conditioned_mv, r.conditioned[n]), 1)
          << r.fs_hz << " conditioned " << n;
    }
  }
}

TEST(Conditioner, FirstSampleGivesExactlyZeroForAnyOffset) {
  for (const double fs : {125.0, 360.0, 1000.0}) {
    for (const float level : {0.37F, -2.5F, 999.0F, 0.0F}) {
      Conditioner c;
      ASSERT_EQ(c.configure(Config{fs, 50}), Status::kOk);
      ConditionedSample s{1.0F, 1.0F};
      ASSERT_EQ(c.process(level, s), Status::kOk);
      EXPECT_EQ(s.baseline_mv, 0.0F) << fs << " " << level;
      EXPECT_EQ(s.conditioned_mv, 0.0F) << fs << " " << level;
    }
  }
}

TEST(Conditioner, NotConfiguredGivesNoOutput) {
  Conditioner c;
  ConditionedSample s{1.0F, 1.0F};
  EXPECT_EQ(c.process(0.5F, s), Status::kNotConfigured);
  EXPECT_EQ(s.baseline_mv, 0.0F);
  EXPECT_EQ(s.conditioned_mv, 0.0F);
}

TEST(Conditioner, FailedConfigureLeavesItNotConfigured) {
  Conditioner c;
  ASSERT_EQ(c.configure(Config{360.0, 50}), Status::kOk);
  EXPECT_EQ(c.configure(Config{360.0, 55}), Status::kInvalidMainsFrequency);
  ConditionedSample s{};
  EXPECT_EQ(c.process(0.5F, s), Status::kNotConfigured);
  EXPECT_EQ(c.configure(Config{50.0, 50}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(c.process(0.5F, s), Status::kNotConfigured);
}

TEST(Conditioner, ResetGivesTheOutputsOfANewConfiguration) {
  const std::vector<float> input = test_input(400);
  Conditioner fresh;
  ASSERT_EQ(fresh.configure(Config{360.0, 60}), Status::kOk);
  const auto want = run(fresh, input);

  Conditioner used;
  ASSERT_EQ(used.configure(Config{360.0, 60}), Status::kOk);
  (void)run(used, test_input(137));  // any earlier stream, any length
  used.reset();
  const auto got = run(used, input);
  ASSERT_EQ(got.size(), want.size());
  for (std::size_t i = 0; i < got.size(); ++i) {
    EXPECT_EQ(got[i].baseline_mv, want[i].baseline_mv) << i;
    EXPECT_EQ(got[i].conditioned_mv, want[i].conditioned_mv) << i;
  }
}

TEST(Conditioner, ReconfigureChangesTheFilters) {
  const std::vector<float> input = test_input(100);
  Conditioner a;
  ASSERT_EQ(a.configure(Config{360.0, 50}), Status::kOk);
  const auto at_50 = run(a, input);
  ASSERT_EQ(a.configure(Config{360.0, 60}), Status::kOk);
  const auto at_60 = run(a, input);
  EXPECT_NE(at_50.back().conditioned_mv, at_60.back().conditioned_mv);
  EXPECT_EQ(at_50.back().baseline_mv, at_60.back().baseline_mv);  // same first stage
}

TEST(Conditioner, MainsStageReceivesTheUnroundedBaselineOutput) {
  // Reference run: the mains stage input is the binary64 baseline output. With a rounded
  // input the 125 Hz stream below would differ from the binary64 chain in the last binary32 digits.
  Conditioner c;
  ASSERT_EQ(c.configure(Config{125.0, 50}), Status::kOk);
  sinus::dsp::BiquadF64 base;
  sinus::dsp::BiquadF64 mains;
  base.set(sinus::dsp::baseline_coefficients(125.0));
  mains.set(sinus::dsp::mains_coefficients(125.0, 50));
  const std::vector<float> input = test_input(300);
  for (std::size_t i = 0; i < input.size(); ++i) {
    const double x = static_cast<double>(input[i]);
    if (i == 0) {
      base.start(x);
    }
    const double b = base.step(x);
    if (i == 0) {
      mains.start(b);
    }
    const double y = mains.step(b);
    ConditionedSample s{};
    ASSERT_EQ(c.process(input[i], s), Status::kOk);
    ASSERT_EQ(s.baseline_mv, static_cast<float>(b)) << i;
    ASSERT_EQ(s.conditioned_mv, static_cast<float>(y)) << i;
  }
}

}  // namespace
