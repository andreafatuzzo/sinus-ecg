#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "display_reference.hpp"
#include "sinus/dsp/display_lowpass.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/status.hpp"

namespace {

using sinus::dsp::display_delay_samples;
using sinus::dsp::display_lowpass_taps;
using sinus::dsp::DisplayLowpass;
using sinus::dsp::DisplayTaps;
using sinus::dsp::Status;

constexpr double kTapTolerance =
    1e-15;  // sin and cos may differ in the last bit between C libraries

std::vector<float> run(DisplayLowpass& stage, const std::vector<double>& input) {
  std::vector<float> out;
  for (const double x : input) {
    float y = 0.0F;
    EXPECT_EQ(stage.process(x, y), Status::kOk);
    out.push_back(y);
  }
  return out;
}

TEST(DisplayLowpass, DelayAndTapCountAtEveryHalfHertz) {
  // fs = k / 2 Hz: M = floor(30 fs / 1000 + 0.5) = floor((3k + 100) / 200), exact in binary64.
  for (std::uint32_t k = 250; k <= 2000; ++k) {
    const double fs = static_cast<double>(k) / 2.0;
    const std::uint32_t want = ((3U * k) + 100U) / 200U;
    const std::uint32_t m = display_delay_samples(fs);
    ASSERT_EQ(m, want) << fs;
    ASSERT_LE(m, sinus::dsp::kDisplayMaxDelaySamples) << fs;
    DisplayTaps taps{};
    taps.fill(7.0);
    ASSERT_EQ(display_lowpass_taps(fs, taps), (2U * m) + 1U) << fs;
    for (std::size_t i = (2U * m) + 1U; i < taps.size(); ++i) {
      ASSERT_EQ(taps[i], 0.0) << fs << " tap " << i;
    }
  }
  EXPECT_EQ(display_delay_samples(360.0), 11U);
  EXPECT_EQ(display_delay_samples(250.0), 8U);
  EXPECT_EQ(display_delay_samples(1000.0), 30U);
  EXPECT_EQ(sinus::dsp::kDisplayTapCapacity, 61U);
}

TEST(DisplayLowpass, TapsEqualTheReference) {
  for (const auto& r : sinus::dsp::reference::kDisplayTaps) {
    DisplayTaps taps{};
    ASSERT_EQ(display_delay_samples(r.fs_hz), r.delay) << r.fs_hz;
    ASSERT_EQ(display_lowpass_taps(r.fs_hz, taps), r.count) << r.fs_hz;
    for (std::size_t k = 0; k < taps.size(); ++k) {
      EXPECT_NEAR(taps[k], r.taps[k], kTapTolerance) << r.fs_hz << " tap " << k;
    }
  }
}

TEST(DisplayLowpass, TapsAreSymmetricAndSumToOne) {
  for (const double fs : {125.0, 147.5, 250.0, 360.0, 500.0, 999.5, 1000.0}) {
    DisplayTaps taps{};
    const std::size_t n = display_lowpass_taps(fs, taps);
    double total = 0.0;
    for (std::size_t k = 0; k < n; ++k) {
      EXPECT_NEAR(taps[k], taps[n - 1 - k], kTapTolerance) << fs << " tap " << k;
      total += taps[k];
    }
    EXPECT_NEAR(total, 1.0, 1e-14) << fs;
    EXPECT_GT(taps[n / 2], taps[0]) << fs;  // the centre tap is the largest
  }
}

TEST(DisplayLowpass, ConfigureGivesDelayTapsAndTheirCount) {
  DisplayLowpass stage;
  EXPECT_EQ(stage.delay_samples(), 0U);
  EXPECT_EQ(stage.tap_count(), 0U);
  ASSERT_EQ(stage.configure(360.0), Status::kOk);
  EXPECT_EQ(stage.delay_samples(), 11U);
  EXPECT_EQ(stage.tap_count(), 23U);
  DisplayTaps taps{};
  display_lowpass_taps(360.0, taps);
  for (std::size_t k = 0; k < taps.size(); ++k) {
    EXPECT_EQ(stage.taps()[k], taps[k]) << k;
  }
  ASSERT_EQ(stage.configure(250.0), Status::kOk);
  EXPECT_EQ(stage.delay_samples(), 8U);
  EXPECT_EQ(stage.tap_count(), 17U);
}

TEST(DisplayLowpass, NotConfiguredGivesNoOutput) {
  DisplayLowpass stage;
  float y = 1.0F;
  EXPECT_EQ(stage.process(0.5, y), Status::kNotConfigured);
  EXPECT_EQ(y, 0.0F);
}

TEST(DisplayLowpass, RejectedSamplingFrequencyLeavesItNotConfigured) {
  for (const double fs : {124.9, 1000.5, 0.0, -360.0, std::nan(""), HUGE_VAL}) {
    DisplayLowpass stage;
    ASSERT_EQ(stage.configure(360.0), Status::kOk);
    EXPECT_EQ(stage.configure(fs), Status::kInvalidSamplingFrequency) << fs;
    EXPECT_EQ(stage.delay_samples(), 0U) << fs;
    EXPECT_EQ(stage.tap_count(), 0U) << fs;
    float y = 1.0F;
    EXPECT_EQ(stage.process(0.5, y), Status::kNotConfigured) << fs;
    EXPECT_EQ(y, 0.0F) << fs;
  }
}

TEST(DisplayLowpass, AConstantBinary32InputGivesExactlyThatValue) {
  for (const double fs : {125.0, 250.0, 360.0, 500.0, 1000.0}) {
    for (int i = -30; i <= 30; ++i) {
      const float level = 0.987654F * static_cast<float>(i) + 0.001F;
      DisplayLowpass stage;
      ASSERT_EQ(stage.configure(fs), Status::kOk);
      for (int n = 0; n < 100; ++n) {
        float y = 0.0F;
        ASSERT_EQ(stage.process(static_cast<double>(level), y), Status::kOk);
        ASSERT_EQ(y, level) << fs << " " << level << " sample " << n;
      }
    }
  }
}

TEST(DisplayLowpass, AnImpulseAfterAZeroStartGivesTheTapsInOrder) {
  for (const double fs : {125.0, 360.0, 1000.0}) {
    DisplayLowpass stage;
    ASSERT_EQ(stage.configure(fs), Status::kOk);
    std::vector<double> input(stage.tap_count() + 5, 0.0);
    input.at(1) = 1.0;
    const std::vector<float> out = run(stage, input);
    EXPECT_EQ(out.at(0), 0.0F);
    for (std::size_t k = 0; k < stage.tap_count(); ++k) {
      EXPECT_EQ(out.at(1 + k), static_cast<float>(stage.taps()[k])) << fs << " tap " << k;
    }
    for (std::size_t n = stage.tap_count() + 1; n < out.size(); ++n) {
      EXPECT_EQ(out.at(n), 0.0F) << fs << " sample " << n;
    }
  }
}

TEST(DisplayLowpass, FollowsTheReferenceOutput) {
  // The same binary64 operations as apply_display_lowpass: one rounding of the reference value.
  const std::vector<double> input(sinus::dsp::reference::kDisplayRunInput.begin(),
                                  sinus::dsp::reference::kDisplayRunInput.end());
  struct Case {
    double fs_hz;
    const double* want;
  };
  for (const Case c : {Case{360.0, sinus::dsp::reference::kDisplayRunOutput360.data()},
                       Case{250.0, sinus::dsp::reference::kDisplayRunOutput250.data()}}) {
    DisplayLowpass stage;
    ASSERT_EQ(stage.configure(c.fs_hz), Status::kOk);
    const std::vector<float> out = run(stage, input);
    for (std::size_t n = 0; n < out.size(); ++n) {
      // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): n < the array size.
      const double want = c.want[n];
      EXPECT_NEAR(static_cast<double>(out[n]), want, 1e-12 + std::fabs(want) * 1.2e-7)
          << c.fs_hz << " sample " << n;
      EXPECT_EQ(out[n], static_cast<float>(want)) << c.fs_hz << " sample " << n;
    }
  }
}

TEST(DisplayLowpass, TheFirstValueFillsTheHistory) {
  // x[i] = x[0] for i < 0: a stream that starts at a level gives that level until it changes.
  DisplayLowpass stage;
  ASSERT_EQ(stage.configure(250.0), Status::kOk);
  std::vector<double> input(40, 2.5);
  input.at(20) = 0.0;
  const std::vector<float> out = run(stage, input);
  for (std::size_t n = 0; n < 20; ++n) {
    EXPECT_EQ(out.at(n), 2.5F) << n;
  }
  EXPECT_NE(out.at(20), 2.5F);
}

TEST(DisplayLowpass, ResetEqualsANewConfiguration) {
  std::vector<double> input;
  for (int n = 0; n < 300; ++n) {
    input.push_back(std::sin(0.11 * n) + (n % 7 == 0 ? 0.4 : -0.1));
  }
  DisplayLowpass fresh;
  ASSERT_EQ(fresh.configure(360.0), Status::kOk);
  const std::vector<float> want = run(fresh, input);
  DisplayLowpass used;
  ASSERT_EQ(used.configure(360.0), Status::kOk);
  std::vector<double> before(input.begin() + 13, input.begin() + 100);
  static_cast<void>(run(used, before));
  used.reset();
  EXPECT_EQ(used.delay_samples(), 11U);
  const std::vector<float> got = run(used, input);
  for (std::size_t n = 0; n < want.size(); ++n) {
    ASSERT_EQ(got[n], want[n]) << n;
  }
}

}  // namespace
