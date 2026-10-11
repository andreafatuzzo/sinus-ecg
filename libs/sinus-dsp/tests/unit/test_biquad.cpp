#include <gtest/gtest.h>

#include <array>
#include <cmath>

#include "reference_values.hpp"
#include "sinus/dsp/biquad.hpp"
#include "ulp.hpp"

namespace {

using sinus::dsp::BiquadCoefficients;
using sinus::dsp::BiquadF32;
using sinus::dsp::BiquadF64;
using sinus::dsp::testing::ulp_distance;

void expect_close(const BiquadCoefficients& got, const std::array<double, 5>& want,
                  const char* what, double fs) {
  EXPECT_LE(ulp_distance(got.b0, want[0]), 4) << what << " b0 at " << fs;
  EXPECT_LE(ulp_distance(got.b1, want[1]), 4) << what << " b1 at " << fs;
  EXPECT_LE(ulp_distance(got.b2, want[2]), 4) << what << " b2 at " << fs;
  EXPECT_LE(ulp_distance(got.a1, want[3]), 4) << what << " a1 at " << fs;
  EXPECT_LE(ulp_distance(got.a2, want[4]), 4) << what << " a2 at " << fs;
}

TEST(Biquad, DesignsMatchTheReferenceWithinFourUlp) {
  for (const auto& c : sinus::dsp::reference::kDesigns) {
    expect_close(sinus::dsp::baseline_coefficients(c.fs_hz), c.baseline, "baseline", c.fs_hz);
    expect_close(sinus::dsp::mains_coefficients(c.fs_hz, 50), c.notch50, "notch 50", c.fs_hz);
    expect_close(sinus::dsp::mains_coefficients(c.fs_hz, 60), c.notch60, "notch 60", c.fs_hz);
    expect_close(sinus::dsp::butterworth2_highpass(5.0, c.fs_hz), c.highpass5, "hp 5", c.fs_hz);
    expect_close(sinus::dsp::butterworth2_lowpass(15.0, c.fs_hz), c.lowpass15, "lp 15", c.fs_hz);
  }
}

TEST(Biquad, NotchHasTheSymmetryOfItsDesign) {
  const BiquadCoefficients c = sinus::dsp::notch(50.0, 30.0, 360.0);
  EXPECT_EQ(c.b0, c.b2);
  EXPECT_EQ(c.b1, c.a1);
}

TEST(Biquad, HighPassHasZeroGainAtDc) {
  for (const double fs : {125.0, 360.0, 1000.0}) {
    const BiquadCoefficients c = sinus::dsp::baseline_coefficients(fs);
    EXPECT_EQ(c.b0 + c.b1 + c.b2, 0.0) << fs;
  }
}

// The recursion of the difference equation, in the dyadic coefficients below exact in binary32.
constexpr BiquadCoefficients kDyadic{0.5, 0.25, 0.125, -0.5, 0.25};

std::array<double, 6> difference_equation_impulse() {
  std::array<double, 6> y{};
  for (std::size_t n = 0; n < y.size(); ++n) {
    const double x0 = n == 0 ? 1.0 : 0.0;
    const double x1 = n == 1 ? 1.0 : 0.0;
    const double x2 = n == 2 ? 1.0 : 0.0;
    const double y1 = n >= 1 ? y[n - 1] : 0.0;
    const double y2 = n >= 2 ? y[n - 2] : 0.0;
    y[n] = 0.5 * x0 + 0.25 * x1 + 0.125 * x2 - (-0.5) * y1 - 0.25 * y2;
  }
  return y;
}

TEST(Biquad, F64ImpulseResponseFollowsTheDifferenceEquation) {
  BiquadF64 f;
  f.set(kDyadic);
  const auto want = difference_equation_impulse();
  for (std::size_t n = 0; n < want.size(); ++n) {
    EXPECT_EQ(f.step(n == 0 ? 1.0 : 0.0), want[n]) << n;
  }
}

TEST(Biquad, F32ImpulseResponseFollowsTheDifferenceEquation) {
  BiquadF32 f;
  f.set(kDyadic);
  const auto want = difference_equation_impulse();
  for (std::size_t n = 0; n < want.size(); ++n) {
    EXPECT_EQ(f.step(n == 0 ? 1.0F : 0.0F), static_cast<float>(want[n])) << n;
  }
}

TEST(Biquad, SetClearsTheState) {
  BiquadF64 f;
  f.set(kDyadic);
  (void)f.step(3.0);
  f.set(kDyadic);
  EXPECT_EQ(f.step(1.0), 0.5);
}

TEST(Biquad, StartGivesTheSteadyStateOfAConstantInput) {
  // DC gain (0.5 + 0.25 + 0.125) / (1 - 0.5 + 0.25) = 7 / 6.
  BiquadF64 d;
  d.set(kDyadic);
  d.start(0.75);
  BiquadF32 s;
  s.set(kDyadic);
  s.start(0.75F);
  for (int n = 0; n < 20; ++n) {
    EXPECT_NEAR(d.step(0.75), 0.75 * 7.0 / 6.0, 1e-14) << n;
    EXPECT_NEAR(s.step(0.75F), 0.75F * 7.0F / 6.0F, 1e-6) << n;
  }
}

TEST(Biquad, HighPassStartedOnAConstantGivesExactlyZeroAtTheFirstSample) {
  for (const double fs : {125.0, 360.0, 1000.0}) {
    for (const double level : {0.37, -2.5, 999.0, 1e-3}) {
      BiquadF64 f;
      f.set(sinus::dsp::baseline_coefficients(fs));
      f.start(level);
      EXPECT_EQ(f.step(level), 0.0) << fs << " " << level;
    }
  }
}

TEST(Biquad, HighPassStaysAtZeroOnAConstantWithinRounding) {
  BiquadF64 f;
  f.set(sinus::dsp::baseline_coefficients(1000.0));
  f.start(5.0);
  for (int n = 0; n < 5000; ++n) {
    ASSERT_NEAR(f.step(5.0), 0.0, 1e-12) << n;
  }
}

TEST(Biquad, F32LowPassSettlesAtUnitGain) {
  BiquadF32 f;
  f.set(sinus::dsp::butterworth2_lowpass(15.0, 360.0));
  float y = 0.0F;
  for (int n = 0; n < 2000; ++n) {
    y = f.step(1.0F);
  }
  EXPECT_NEAR(y, 1.0F, 1e-5F);
}

}  // namespace
