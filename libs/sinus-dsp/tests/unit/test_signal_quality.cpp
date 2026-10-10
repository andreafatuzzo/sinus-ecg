#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "sinus/dsp/config.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/signal_quality.hpp"

namespace {

using sinus::dsp::Detection;
using sinus::dsp::DetectionPath;
using sinus::dsp::DetectorStep;
using sinus::dsp::Mark;
using sinus::dsp::QualityWindow;
using sinus::dsp::SignalQuality;
using sinus::dsp::Status;
using sinus::dsp::ZoneSums;

// Hand-built input for the index: the squared derivative is `in_zone` in the zone of every
// detection and `outside` elsewhere, so that S and B are known.
struct Scenario {
  double fs = 250.0;
  std::uint64_t samples = 0;
  float in_zone = 100.0F;
  float outside = 1.0F;
  struct Det {
    std::uint64_t peak;
    std::uint64_t reported_at;
  };
  std::vector<Det> detections;
  std::vector<float> input;  // empty: alternating values
};

std::uint64_t zone_low(std::uint64_t peak, std::uint64_t zone) {
  return (peak + 1U >= zone) ? (peak + 1U - zone) : 0U;
}

std::vector<QualityWindow> drive(SignalQuality& quality, const Scenario& s) {
  const sinus::dsp::QualitySamples p = sinus::dsp::quality_samples(s.fs);
  std::vector<QualityWindow> windows;
  for (std::uint64_t n = 0; n < s.samples; ++n) {
    DetectorStep step;
    bool in_any_zone = false;
    for (const Scenario::Det& d : s.detections) {
      if (n >= zone_low(d.peak, p.zone) && n <= d.peak) {
        in_any_zone = true;
      }
      if (d.reported_at == n) {
        const std::uint64_t low = zone_low(d.peak, p.zone);
        const std::uint64_t boundary = ((low / p.block) + 1U) * p.block;
        const std::uint64_t first = std::min(d.peak + 1U, boundary) - low;
        const std::uint64_t second = (d.peak >= boundary) ? (d.peak - boundary + 1U) : 0U;
        step.detections[step.count] = Detection{d.peak, n, Mark::kReliable, DetectionPath::kNormal};
        step.zones[step.count] = ZoneSums{d.peak, static_cast<float>(first) * s.in_zone,
                                          static_cast<float>(second) * s.in_zone};
        ++step.count;
      }
    }
    step.squared_derivative = in_any_zone ? s.in_zone : s.outside;
    const float input = s.input.empty() ? ((n % 2U == 0U) ? 0.1F : 0.2F) : s.input[n];
    bool has_window = false;
    QualityWindow window{};
    EXPECT_EQ(quality.step(input, step, has_window, window), Status::kOk);
    if (has_window) {
      windows.push_back(window);
    }
  }
  return windows;
}

std::vector<Scenario::Det> regular(std::uint64_t first, std::uint64_t spacing, std::size_t count) {
  std::vector<Scenario::Det> dets;
  for (std::size_t i = 0; i < count; ++i) {
    const std::uint64_t m = first + (i * spacing);
    dets.push_back(Scenario::Det{m, m});
  }
  return dets;
}

SignalQuality configured(double fs) {
  SignalQuality quality;
  EXPECT_EQ(quality.configure(fs), Status::kOk);
  return quality;
}

TEST(SignalQuality, WindowsAreTenBlocksEveryBlockReportedHalfASecondAfterTheirLastSample) {
  for (const double fs : {125.0, 250.0, 360.0, 360.5, 1000.0}) {
    const sinus::dsp::QualitySamples p = sinus::dsp::quality_samples(fs);
    Scenario s;
    s.fs = fs;
    s.samples = 30U * p.block;
    SignalQuality quality = configured(fs);
    const std::vector<QualityWindow> windows = drive(quality, s);
    const std::uint64_t expected = ((s.samples - p.report_delay - p.window) / p.block) + 1U;
    ASSERT_EQ(windows.size(), expected) << fs;
    for (std::size_t k = 0; k < windows.size(); ++k) {
      EXPECT_EQ(windows[k].first_sample, k * p.block);
      EXPECT_EQ(windows[k].last_sample, (k * p.block) + p.window - 1U);
      EXPECT_EQ(windows[k].reported_at, windows[k].last_sample + p.report_delay);
      EXPECT_EQ(windows[k].index, 0.0F);  // no detection
      EXPECT_FALSE(windows[k].usable);
    }
    EXPECT_LE(p.report_delay, static_cast<std::uint64_t>(std::floor(0.5 * fs)));
  }
}

TEST(SignalQuality, NoWindowBeforeTheFirstReportSample) {
  Scenario s;
  s.samples = 2500U + 125U - 1U;  // the first window is reported at sample 2624
  SignalQuality quality = configured(250.0);
  EXPECT_TRUE(drive(quality, s).empty());
  Scenario t;
  t.samples = 2625U;
  SignalQuality other = configured(250.0);
  EXPECT_EQ(drive(other, t).size(), 1U);
}

TEST(SignalQuality, TheIndexIsSOverSPlusSixteenBOfTheZonesAndTheRest) {
  for (const double fs : {125.0, 250.0, 360.0, 1000.0}) {
    const sinus::dsp::QualitySamples p = sinus::dsp::quality_samples(fs);
    for (const std::uint64_t offset : {p.block / 5U, 10U}) {  // 10: the zone crosses a boundary
      Scenario s;
      s.fs = fs;
      s.samples = 25U * p.block;
      s.detections = regular(p.block + offset, p.block, 24);
      SignalQuality quality = configured(fs);
      const std::vector<QualityWindow> windows = drive(quality, s);
      ASSERT_GE(windows.size(), 14U);
      for (const QualityWindow& w : windows) {
        EXPECT_NEAR(w.index, 100.0F / 116.0F, 1e-5F) << fs << " " << w.first_sample;
        EXPECT_TRUE(w.usable);
      }
    }
  }
}

TEST(SignalQuality, ABackgroundOfOneSixteenthOfTheZonesIsUsableExactlyAtTheThreshold) {
  Scenario s;
  s.in_zone = 1.0F;
  s.outside = 0.0625F;
  s.samples = 4000;
  s.detections = regular(300, 250, 15);
  SignalQuality quality = configured(250.0);
  const std::vector<QualityWindow> windows = drive(quality, s);
  ASSERT_GE(windows.size(), 2U);
  EXPECT_EQ(windows[1].index, sinus::dsp::kUsableThreshold);
  EXPECT_TRUE(windows[1].usable);

  Scenario t = s;
  t.outside = 0.07F;
  SignalQuality other = configured(250.0);
  const std::vector<QualityWindow> noisy = drive(other, t);
  ASSERT_GE(noisy.size(), 2U);
  EXPECT_LT(noisy[1].index, sinus::dsp::kUsableThreshold);
  EXPECT_FALSE(noisy[1].usable);
}

TEST(SignalQuality, TheNumberOfDetectionsMustBeFourToThirtyFour) {
  for (const std::size_t count : {3U, 4U, 34U, 35U}) {
    Scenario s;
    s.samples = 2700;
    s.detections = regular(100, 70, count);  // all inside window 0
    SignalQuality quality = configured(250.0);
    const std::vector<QualityWindow> windows = drive(quality, s);
    ASSERT_FALSE(windows.empty());
    if (count == 3U || count == 35U) {
      EXPECT_EQ(windows[0].index, 0.0F) << count;
      EXPECT_FALSE(windows[0].usable);
    } else {
      EXPECT_GT(windows[0].index, 0.0F) << count;
    }
  }
}

TEST(SignalQuality, AHeldInputOfFiveBlocksInsideTheWindowGivesZero) {
  struct Case {
    std::uint64_t start, length;
    bool held;
  };
  // 250 Hz: H = 250, five blocks = 1250 samples; window 0 is samples 0 to 2499.
  for (const Case& c : {Case{0, 1250, true}, Case{0, 1249, false}, Case{700, 1250, true},
                        Case{700, 1249, false}, Case{1250, 1250, true},  // ends at the last sample
                        Case{1251, 1250, false},                         // one sample too late
                        Case{1, 1250, true}}) {
    Scenario s;
    s.samples = 2700;
    s.detections = regular(300, 250, 9);
    s.input.resize(s.samples);
    for (std::uint64_t n = 0; n < s.samples; ++n) {
      s.input[n] = (n % 2U == 0U) ? 0.1F : 0.2F;
    }
    for (std::uint64_t n = c.start; n < c.start + c.length; ++n) {
      s.input[n] = 0.3F;
    }
    SignalQuality quality = configured(250.0);
    const std::vector<QualityWindow> windows = drive(quality, s);
    ASSERT_FALSE(windows.empty());
    if (c.held) {
      EXPECT_EQ(windows[0].index, 0.0F) << c.start << " " << c.length;
    } else {
      EXPECT_GT(windows[0].index, 0.0F) << c.start << " " << c.length;
    }
  }
}

TEST(SignalQuality, ADetectionReportedAfterTheReportSampleOfAWindowIsLeftOutOfIt) {
  Scenario s;
  s.samples = 3200;
  // Four detections in window 0 and window 1; the first is found late, at sample 2750, which is
  // after the report sample of window 0 (2624) and before that of window 1 (2874).
  s.detections = {{300, 2750}, {550, 550}, {800, 800}, {1000, 1000}};
  SignalQuality quality = configured(250.0);
  const std::vector<QualityWindow> windows = drive(quality, s);
  ASSERT_GE(windows.size(), 2U);
  EXPECT_EQ(windows[0].index, 0.0F);  // three detections
  EXPECT_NEAR(windows[1].index, 100.0F / 116.0F, 1e-5F);
}

TEST(SignalQuality, ALateDetectionIsCountedInTheLaterWindowsThatContainIt) {
  Scenario s;
  s.samples = 4000;
  // Found 9.8 s after its index: its block is still in the ring when window 1 is reported.
  s.detections = {{300, 2750}, {550, 550}, {800, 800}, {1000, 1000}};
  SignalQuality quality = configured(250.0);
  const std::vector<QualityWindow> windows = drive(quality, s);
  ASSERT_GE(windows.size(), 3U);
  EXPECT_GT(windows[1].index, 0.0F);
  EXPECT_EQ(windows[2].index, 0.0F);  // from 500: 550, 800, 1000 only, 3 detections
}

TEST(SignalQuality, ResetStartsTheWindowsAgainFromTheFirstSample) {
  Scenario s;
  s.samples = 5000;
  s.detections = regular(300, 250, 19);
  SignalQuality used = configured(250.0);
  (void)drive(used, s);
  used.reset();
  SignalQuality fresh = configured(250.0);
  const std::vector<QualityWindow> a = drive(used, s);
  const std::vector<QualityWindow> b = drive(fresh, s);
  ASSERT_EQ(a.size(), b.size());
  for (std::size_t k = 0; k < a.size(); ++k) {
    EXPECT_EQ(a[k].first_sample, b[k].first_sample);
    EXPECT_EQ(a[k].reported_at, b[k].reported_at);
    EXPECT_EQ(a[k].index, b[k].index);
  }
}

TEST(SignalQuality, Preconditions) {
  SignalQuality quality;
  DetectorStep step;
  bool has_window = true;
  QualityWindow window{};
  EXPECT_EQ(quality.step(0.0F, step, has_window, window), Status::kNotConfigured);
  EXPECT_FALSE(has_window);
  EXPECT_EQ(quality.configure(100.0), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(quality.step(0.0F, step, has_window, window), Status::kNotConfigured);
  quality.reset();  // harmless
  ASSERT_EQ(quality.configure(360.0), Status::kOk);
  step.count = sinus::dsp::kMaxDetectionsPerSample + 1U;
  EXPECT_EQ(quality.step(0.0F, step, has_window, window), Status::kInvalidArgument);
  step.count = 0;
  EXPECT_EQ(quality.step(0.0F, step, has_window, window), Status::kOk);
}

TEST(SignalQuality, TheIndexIsZeroWhenThereIsNoZoneInTheWindow) {
  Scenario s;
  s.samples = 2800;
  SignalQuality quality = configured(250.0);
  const std::vector<QualityWindow> windows = drive(quality, s);
  ASSERT_FALSE(windows.empty());
  EXPECT_EQ(windows[0].index, 0.0F);
}

}  // namespace
