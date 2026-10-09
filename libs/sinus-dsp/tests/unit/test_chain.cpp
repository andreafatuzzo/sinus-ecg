#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "synthetic_beats.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;

constexpr float kNan = std::numeric_limits<float>::quiet_NaN();
constexpr float kInf = std::numeric_limits<float>::infinity();

std::vector<float> test_input(std::size_t n) {
  std::vector<float> x(n);
  for (std::size_t i = 0; i < n; ++i) {
    x[i] = 0.3F * static_cast<float>(i % 23) - 2.0F;
  }
  return x;
}

void expect_empty(const SampleOutput& out) {
  EXPECT_EQ(out.baseline_mv, 0.0F);
  EXPECT_EQ(out.conditioned_mv, 0.0F);
  EXPECT_EQ(out.detection_count, 0U);
}

TEST(Chain, StartsNotConfigured) {
  Chain chain;
  EXPECT_FALSE(chain.configured());
  SampleOutput out{1.0F, 1.0F};
  EXPECT_EQ(chain.process(0.1F, out), Status::kNotConfigured);
  expect_empty(out);
  chain.reset();  // harmless
  EXPECT_FALSE(chain.configured());
}

TEST(Chain, ConfigureReportsTheStatusOfTheCheck) {
  Chain chain;
  EXPECT_EQ(chain.configure(Config{124.9, 50}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(chain.configure(Config{360.0, 61}), Status::kInvalidMainsFrequency);
  EXPECT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  EXPECT_TRUE(chain.configured());
  EXPECT_EQ(chain.config().sampling_frequency_hz, 360.0);
  EXPECT_EQ(chain.config().mains_frequency_hz, 50);
}

TEST(Chain, RejectedConfigurationLeavesAConfiguredChainNotConfigured) {
  Chain chain;
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  SampleOutput out{};
  ASSERT_EQ(chain.process(0.5F, out), Status::kOk);
  const double bad[] = {1000.1, kNan, kInf, -kInf};
  for (const double fs : bad) {
    ASSERT_EQ(chain.configure(Config{fs, 50}), Status::kInvalidSamplingFrequency);
    EXPECT_FALSE(chain.configured());
    out = SampleOutput{1.0F, 1.0F};
    EXPECT_EQ(chain.process(0.5F, out), Status::kNotConfigured);
    expect_empty(out);
    ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);  // and recovers
  }
}

TEST(Chain, ASampleAtTheLimitIsProcessedAndTheNextBinary32ValueIsNot) {
  const float above = std::nextafter(sinus::dsp::kMaxAbsSampleMv, 2000.0F);
  EXPECT_GT(above, sinus::dsp::kMaxAbsSampleMv);
  for (const float ok : {1000.0F, -1000.0F}) {
    Chain chain;
    ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
    SampleOutput out{};
    EXPECT_EQ(chain.process(ok, out), Status::kOk) << ok;
  }
  for (const float bad : {above, -above, kNan, kInf, -kInf}) {
    Chain chain;
    ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
    SampleOutput out{1.0F, 1.0F};
    EXPECT_EQ(chain.process(bad, out), Status::kInvalidSample) << bad;
    expect_empty(out);
  }
}

TEST(Chain, StopsAtAnInvalidSampleUntilReset) {
  Chain chain;
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  SampleOutput out{};
  for (int i = 0; i < 10; ++i) {
    ASSERT_EQ(chain.process(0.2F * static_cast<float>(i), out), Status::kOk);
  }
  ASSERT_EQ(chain.process(kNan, out), Status::kInvalidSample);
  for (const float x : {0.1F, 0.2F, kNan, 5000.0F}) {
    out = SampleOutput{1.0F, 1.0F};
    EXPECT_EQ(chain.process(x, out), Status::kStopped);
    expect_empty(out);
  }
  EXPECT_TRUE(chain.configured());
}

TEST(Chain, ResetGivesTheOutputsOfANewlyConfiguredChain) {
  const std::vector<float> input = test_input(500);
  Chain fresh;
  ASSERT_EQ(fresh.configure(Config{250.0, 60}), Status::kOk);
  std::vector<SampleOutput> want(input.size());
  for (std::size_t i = 0; i < input.size(); ++i) {
    ASSERT_EQ(fresh.process(input[i], want[i]), Status::kOk);
  }

  Chain used;
  ASSERT_EQ(used.configure(Config{250.0, 60}), Status::kOk);
  SampleOutput out{};
  for (const float x : test_input(211)) {
    ASSERT_EQ(used.process(x, out), Status::kOk);
  }
  ASSERT_EQ(used.process(kInf, out), Status::kInvalidSample);  // stopped, then reset
  used.reset();
  for (std::size_t i = 0; i < input.size(); ++i) {
    ASSERT_EQ(used.process(input[i], out), Status::kOk);
    ASSERT_EQ(out.baseline_mv, want[i].baseline_mv) << i;
    ASSERT_EQ(out.conditioned_mv, want[i].conditioned_mv) << i;
  }
}

TEST(Chain, InvalidSampleChangesNoStateOfTheStream) {
  // Reset after the stop restarts at the first sample; the rejected sample is not part of it.
  Chain chain;
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  SampleOutput out{};
  ASSERT_EQ(chain.process(0.7F, out), Status::kOk);
  ASSERT_EQ(chain.process(2000.0F, out), Status::kInvalidSample);
  chain.reset();
  ASSERT_EQ(chain.process(0.4F, out), Status::kOk);
  EXPECT_EQ(out.baseline_mv, 0.0F);  // the first sample of a new stream
  EXPECT_EQ(out.conditioned_mv, 0.0F);
}

TEST(Chain, ReconfigurationStartsANewStream) {
  Chain chain;
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  SampleOutput out{};
  ASSERT_EQ(chain.process(0.7F, out), Status::kOk);
  ASSERT_EQ(chain.process(kNan, out), Status::kInvalidSample);
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);  // clears the stop too
  ASSERT_EQ(chain.process(0.4F, out), Status::kOk);
  EXPECT_EQ(out.baseline_mv, 0.0F);
}

TEST(Chain, FitsTheMemoryLimit) { EXPECT_LE(sizeof(Chain), sinus::dsp::kChainMemoryLimitBytes); }

TEST(Chain, ReportsTheDetectionsOfTheDetectorOnTheConditionedSignal) {
  // An ECG with an offset and a slow baseline: the chain detects on its conditioned output.
  const double fs = 250.0;
  std::vector<float> x =
      sinus_test::synthetic_beats(fs, 20.0, sinus_test::regular_beats(0.4, 0.9, 19.5));
  for (std::size_t k = 0; k < x.size(); ++k) {
    x[k] += 1.5F + 0.2F * static_cast<float>(std::sin(0.6 * static_cast<double>(k) / fs));
  }
  Chain chain;
  ASSERT_EQ(chain.configure(Config{fs, 50}), Status::kOk);
  sinus::dsp::QrsDetector detector;
  ASSERT_EQ(detector.configure(fs), Status::kOk);
  SampleOutput out;
  sinus::dsp::DetectorStep step;
  std::size_t total = 0;
  for (const float v : x) {
    ASSERT_EQ(chain.process(v, out), Status::kOk);
    ASSERT_EQ(detector.process(out.conditioned_mv, step), Status::kOk);
    ASSERT_EQ(out.detection_count, step.count);
    for (std::size_t i = 0; i < step.count; ++i) {
      EXPECT_EQ(out.detections[i].index, step.detections[i].index);
      EXPECT_EQ(out.detections[i].reported_at, step.detections[i].reported_at);
      EXPECT_EQ(out.detections[i].mark, step.detections[i].mark);
      EXPECT_EQ(out.detections[i].path, step.detections[i].path);
    }
    total += out.detection_count;
  }
  EXPECT_EQ(total, 22U);
}

}  // namespace
