#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/conditioner.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/display_lowpass.hpp"
#include "sinus/dsp/heart_rate.hpp"
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

TEST(Chain, HeartRateAndWindowsComeFromTheDetectionsOfTheSameSample) {
  const double fs = 360.0;
  const std::vector<float> x =
      sinus_test::synthetic_beats(fs, 45.0, sinus_test::regular_beats(0.4, 0.8, 44.5));
  Chain chain;
  ASSERT_EQ(chain.configure(Config{fs, 50}), Status::kOk);
  sinus::dsp::HeartRateTracker tracker;
  ASSERT_EQ(tracker.configure(fs), Status::kOk);
  const sinus::dsp::QualitySamples p = sinus::dsp::quality_samples(fs);
  SampleOutput out;
  std::size_t events = 0;
  std::size_t valid = 0;
  std::vector<std::uint64_t> report_samples;
  for (std::size_t n = 0; n < x.size(); ++n) {
    ASSERT_EQ(chain.process(x[n], out), Status::kOk);
    std::vector<sinus::dsp::ReportedDetection> reported;
    for (std::size_t i = 0; i < out.detection_count; ++i) {
      reported.push_back({out.detections[i].index, out.detections[i].mark});
    }
    sinus::dsp::HeartRateStep want;
    ASSERT_EQ(tracker.step(reported.data(), reported.size(), want), Status::kOk);
    ASSERT_EQ(out.heart_rate_count, want.count) << n;
    for (std::size_t i = 0; i < want.count; ++i) {
      EXPECT_EQ(out.heart_rates[i].sample, n);
      EXPECT_EQ(out.heart_rates[i].status, want.events[i].status);
      EXPECT_EQ(out.heart_rates[i].beat_index, want.events[i].beat_index);
      if (out.heart_rates[i].status == sinus::dsp::HeartRateStatus::kValid) {
        ++valid;
        EXPECT_NEAR(out.heart_rates[i].bpm, 75.0F, 2.0F);
      }
    }
    events += out.heart_rate_count;
    if (out.has_window) {
      report_samples.push_back(out.window.reported_at);
      EXPECT_EQ(out.window.reported_at, n);
      EXPECT_EQ(out.window.last_sample + p.report_delay, n);
      EXPECT_EQ(out.window.usable, out.window.index >= sinus::dsp::kUsableThreshold);
    }
  }
  EXPECT_GT(events, 40U);
  EXPECT_GT(valid, 30U);
  ASSERT_EQ(report_samples.size(), ((x.size() - p.report_delay - p.window) / p.block) + 1U);
}

TEST(Chain, ResetRestartsHeartRateAndWindows) {
  const double fs = 250.0;
  const std::vector<float> x =
      sinus_test::synthetic_beats(fs, 30.0, sinus_test::regular_beats(0.4, 0.9, 29.5));
  Chain used;
  ASSERT_EQ(used.configure(Config{fs, 60}), Status::kOk);
  Chain fresh;
  ASSERT_EQ(fresh.configure(Config{fs, 60}), Status::kOk);
  SampleOutput out;
  for (std::size_t n = 0; n < 5000; ++n) {
    ASSERT_EQ(used.process(x[n], out), Status::kOk);
  }
  used.reset();
  SampleOutput want;
  for (const float v : x) {
    ASSERT_EQ(used.process(v, out), Status::kOk);
    ASSERT_EQ(fresh.process(v, want), Status::kOk);
    ASSERT_EQ(out.heart_rate_count, want.heart_rate_count);
    for (std::size_t i = 0; i < want.heart_rate_count; ++i) {
      ASSERT_EQ(out.heart_rates[i].sample, want.heart_rates[i].sample);
      ASSERT_EQ(out.heart_rates[i].status, want.heart_rates[i].status);
    }
    ASSERT_EQ(out.has_window, want.has_window);
    if (want.has_window) {
      ASSERT_EQ(out.window.first_sample, want.window.first_sample);
      ASSERT_EQ(out.window.index, want.window.index);
    }
  }
}

}  // namespace

// --- display stage (architecture-m3.md 16.6) ---------------------------------------------------

namespace {

std::vector<float> display_test_signal(double fs) {
  std::vector<float> x =
      sinus_test::synthetic_beats(fs, 30.0, sinus_test::regular_beats(0.4, 0.8, 29.5));
  for (std::size_t k = 0; k < x.size(); ++k) {
    const double t = static_cast<double>(k) / fs;
    x[k] += 0.8F + static_cast<float>(0.3 * std::sin(2.0 * 3.141592653589793 * 0.3 * t) +
                                      0.1 * std::sin(2.0 * 3.141592653589793 * 50.0 * t));
  }
  return x;
}

void expect_same_except_display(const SampleOutput& a, const SampleOutput& b, std::size_t n) {
  ASSERT_EQ(a.baseline_mv, b.baseline_mv) << n;
  ASSERT_EQ(a.conditioned_mv, b.conditioned_mv) << n;
  ASSERT_EQ(a.detection_count, b.detection_count) << n;
  for (std::size_t i = 0; i < a.detection_count; ++i) {
    ASSERT_EQ(a.detections[i].index, b.detections[i].index) << n;
    ASSERT_EQ(a.detections[i].reported_at, b.detections[i].reported_at) << n;
    ASSERT_EQ(a.detections[i].mark, b.detections[i].mark) << n;
    ASSERT_EQ(a.detections[i].path, b.detections[i].path) << n;
  }
  ASSERT_EQ(a.heart_rate_count, b.heart_rate_count) << n;
  for (std::size_t i = 0; i < a.heart_rate_count; ++i) {
    ASSERT_EQ(a.heart_rates[i].sample, b.heart_rates[i].sample) << n;
    ASSERT_EQ(a.heart_rates[i].beat_index, b.heart_rates[i].beat_index) << n;
    ASSERT_EQ(a.heart_rates[i].has_beat, b.heart_rates[i].has_beat) << n;
    ASSERT_EQ(a.heart_rates[i].status, b.heart_rates[i].status) << n;
    ASSERT_EQ(std::isnan(a.heart_rates[i].bpm), std::isnan(b.heart_rates[i].bpm)) << n;
    if (!std::isnan(a.heart_rates[i].bpm)) {
      ASSERT_EQ(a.heart_rates[i].bpm, b.heart_rates[i].bpm) << n;
    }
  }
  ASSERT_EQ(a.has_window, b.has_window) << n;
  if (a.has_window) {
    ASSERT_EQ(a.window.first_sample, b.window.first_sample) << n;
    ASSERT_EQ(a.window.last_sample, b.window.last_sample) << n;
    ASSERT_EQ(a.window.reported_at, b.window.reported_at) << n;
    ASSERT_EQ(a.window.index, b.window.index) << n;
    ASSERT_EQ(a.window.usable, b.window.usable) << n;
  }
}

}  // namespace

TEST(ChainDisplay, TheStageIsOnByDefault) {
  EXPECT_TRUE(Config{}.display_lowpass);
  EXPECT_TRUE((Config{360.0, 50}).display_lowpass);
}

TEST(ChainDisplay, DelayIsZeroUntilConfiguredAndMOnOrOff) {
  Chain chain;
  EXPECT_EQ(chain.display_delay_samples(), 0U);
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  EXPECT_EQ(chain.display_delay_samples(), 11U);
  ASSERT_EQ(chain.configure(Config{250.0, 60, false}), Status::kOk);
  EXPECT_EQ(chain.display_delay_samples(), 8U);
  EXPECT_FALSE(chain.config().display_lowpass);
  EXPECT_EQ(chain.configure(Config{360.0, 55}), Status::kInvalidMainsFrequency);
  EXPECT_EQ(chain.display_delay_samples(), 0U);
  ASSERT_EQ(chain.configure(Config{1000.0, 50}), Status::kOk);
  EXPECT_EQ(chain.display_delay_samples(), 30U);
  EXPECT_EQ(chain.configure(Config{50.0, 50}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(chain.display_delay_samples(), 0U);
}

TEST(ChainDisplay, IsTheDisplayLowpassOfTheBinary64ConditionedValue) {
  for (const double fs : {250.0, 360.0}) {
    const std::vector<float> x = display_test_signal(fs);
    Chain chain;
    ASSERT_EQ(chain.configure(Config{fs, 50}), Status::kOk);
    sinus::dsp::Conditioner conditioner;
    ASSERT_EQ(conditioner.configure(Config{fs, 50}), Status::kOk);
    sinus::dsp::DisplayLowpass display;
    ASSERT_EQ(display.configure(fs), Status::kOk);
    SampleOutput out;
    for (std::size_t n = 0; n < x.size(); ++n) {
      ASSERT_EQ(chain.process(x[n], out), Status::kOk);
      sinus::dsp::ConditionedSample c{};
      ASSERT_EQ(conditioner.process(x[n], c), Status::kOk);
      float want = 0.0F;
      ASSERT_EQ(display.process(c.conditioned_f64_mv, want), Status::kOk);
      ASSERT_EQ(out.display_mv, want) << fs << " sample " << n;
    }
  }
}

TEST(ChainDisplay, TheFirstDisplayValueIsZero) {
  Chain chain;
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  SampleOutput out;
  ASSERT_EQ(chain.process(3.25F, out), Status::kOk);
  EXPECT_EQ(out.display_mv, 0.0F);
}

TEST(ChainDisplay, OffGivesNanAndTheSameOtherOutputs) {
  for (const double fs : {250.0, 360.0}) {
    for (const int mains : {50, 60}) {
      const std::vector<float> x = display_test_signal(fs);
      Chain on;
      ASSERT_EQ(on.configure(Config{fs, mains, true}), Status::kOk);
      Chain off;
      ASSERT_EQ(off.configure(Config{fs, mains, false}), Status::kOk);
      SampleOutput a;
      SampleOutput b;
      std::size_t detections = 0;
      for (std::size_t n = 0; n < x.size(); ++n) {
        ASSERT_EQ(on.process(x[n], a), Status::kOk);
        ASSERT_EQ(off.process(x[n], b), Status::kOk);
        ASSERT_TRUE(std::isnan(b.display_mv)) << n;
        ASSERT_FALSE(std::isnan(a.display_mv)) << n;
        expect_same_except_display(a, b, n);
        detections += a.detection_count;
      }
      EXPECT_GT(detections, 30U);
    }
  }
}

TEST(ChainDisplay, NoDisplayValueWithAStatusOtherThanOk) {
  Chain chain;
  SampleOutput out;
  out.display_mv = 1.0F;
  EXPECT_EQ(chain.process(0.1F, out), Status::kNotConfigured);
  EXPECT_EQ(out.display_mv, 0.0F);
  for (const bool display : {true, false}) {
    ASSERT_EQ(chain.configure(Config{360.0, 50, display}), Status::kOk);
    ASSERT_EQ(chain.process(0.1F, out), Status::kOk);
    out.display_mv = 1.0F;
    EXPECT_EQ(chain.process(kNan, out), Status::kInvalidSample);
    EXPECT_EQ(out.display_mv, 0.0F);
    out.display_mv = 1.0F;
    EXPECT_EQ(chain.process(0.1F, out), Status::kStopped);
    EXPECT_EQ(out.display_mv, 0.0F);
  }
}

TEST(ChainDisplay, ResetRestartsTheDisplayStage) {
  const double fs = 360.0;
  const std::vector<float> x = display_test_signal(fs);
  Chain fresh;
  ASSERT_EQ(fresh.configure(Config{fs, 50}), Status::kOk);
  Chain used;
  ASSERT_EQ(used.configure(Config{fs, 50}), Status::kOk);
  SampleOutput out;
  for (std::size_t n = 100; n < 1500; ++n) {
    ASSERT_EQ(used.process(x[n], out), Status::kOk);
  }
  used.reset();
  SampleOutput want;
  for (std::size_t n = 0; n < x.size(); ++n) {
    ASSERT_EQ(used.process(x[n], out), Status::kOk);
    ASSERT_EQ(fresh.process(x[n], want), Status::kOk);
    ASSERT_EQ(out.display_mv, want.display_mv) << n;
    expect_same_except_display(out, want, n);
  }
}
