#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "compensated_sum.hpp"
#include "search_back_limit.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/limits.hpp"

namespace {

using sinus::dsp::CompensatedSum;
using sinus::dsp::DetectorSamples;

TEST(CompensatedSum, RecoversWhatAPlainBinary32SumLoses) {
  // 1 + 1e-8 * 1000: a plain binary32 sum stays at 1.0F; the exact value is 1.00001.
  CompensatedSum sum;
  float plain = 0.0F;
  sum.add(1.0F);
  plain += 1.0F;
  for (int i = 0; i < 1000; ++i) {
    sum.add(1e-8F);
    plain += 1e-8F;
  }
  EXPECT_EQ(plain, 1.0F);
  EXPECT_EQ(sum.value(), static_cast<float>(1.0 + (1000.0 * static_cast<double>(1e-8F))));
}

TEST(CompensatedSum, CancellationIsExact) {
  CompensatedSum sum;
  for (const float v : {1e8F, 1.0F, -1e8F}) {
    sum.add(v);
  }
  EXPECT_EQ(sum.value(), 1.0F);
  EXPECT_EQ(CompensatedSum{}.value(), 0.0F);
}

TEST(CompensatedSum, IsWithinAFewUnitsOfTheCorrectlyRoundedSum) {
  std::vector<float> values;
  std::uint32_t state = 12345U;
  for (int i = 0; i < 2000; ++i) {
    state = (state * 1664525U) + 1013904223U;
    values.push_back(static_cast<float>(state % 100000U) * 1e-3F + 1e-4F);
  }
  CompensatedSum sum;
  long double exact = 0.0L;
  for (const float v : values) {
    sum.add(v);
    exact += static_cast<long double>(v);
  }
  const auto correct = static_cast<float>(exact);
  EXPECT_LE(std::fabs(sum.value() - correct),
            2.0F * std::nextafter(correct, 1e30F) - 2.0F * correct);
}

TEST(SearchBackLimit, EqualsTheBinary64ExpressionOverItsDomain) {
  // architecture-m2.md 14.3, step 9: every total up to 200 000 and every count from 1 to 8.
  for (std::uint64_t count = 1; count <= 8; ++count) {
    for (std::uint64_t total = count; total <= 200000U; ++total) {
      const double mean = static_cast<double>(total) / static_cast<double>(count);
      const auto expected = static_cast<std::uint64_t>(std::floor((1.66 * mean) + 0.5));
      ASSERT_EQ(sinus::dsp::search_back_limit(total, count), expected) << total << " " << count;
    }
  }
}

TEST(DetectorSamples, ValuesAt360And250Hz) {
  const DetectorSamples a = sinus::dsp::detector_samples(360.0);
  EXPECT_EQ(a.band_delay, 13U);
  EXPECT_EQ(a.window, 54U);
  EXPECT_EQ(a.peak_timeout, 34U);
  EXPECT_EQ(a.refractory, 72U);
  EXPECT_EQ(a.t_wave_window, 130U);
  EXPECT_EQ(a.learning, 720U);
  EXPECT_EQ(a.relearn_after, 2880U);
  const DetectorSamples b = sinus::dsp::detector_samples(250.0);
  EXPECT_EQ(b.band_delay, 9U);
  EXPECT_EQ(b.window, 38U);
  EXPECT_EQ(b.peak_timeout, 24U);
  EXPECT_EQ(b.refractory, 50U);
  EXPECT_EQ(b.t_wave_window, 90U);
  EXPECT_EQ(b.learning, 500U);
  EXPECT_EQ(b.relearn_after, 2000U);
  // 125 Hz (architecture-m2.md 13.4): N = 19, P = 12, D = 5, R = 25, L = 250, G = 1000.
  const DetectorSamples c = sinus::dsp::detector_samples(125.0);
  EXPECT_EQ(c.window, 19U);
  EXPECT_EQ(c.peak_timeout, 12U);
  EXPECT_EQ(c.band_delay, 5U);
  EXPECT_EQ(c.refractory, 25U);
  EXPECT_EQ(c.learning, 250U);
  EXPECT_EQ(c.relearn_after, 1000U);
}

TEST(QualitySamples, ValuesAt360And250Hz) {
  const sinus::dsp::QualitySamples a = sinus::dsp::quality_samples(360.0);
  EXPECT_EQ(a.block, 360U);
  EXPECT_EQ(a.window, 3600U);
  EXPECT_EQ(a.held, 1800U);
  EXPECT_EQ(a.report_delay, 180U);
  EXPECT_EQ(a.zone, 54U);
  const sinus::dsp::QualitySamples b = sinus::dsp::quality_samples(250.0);
  EXPECT_EQ(b.block, 250U);
  EXPECT_EQ(b.window, 2500U);
  EXPECT_EQ(b.held, 1250U);
  EXPECT_EQ(b.report_delay, 125U);
  EXPECT_EQ(b.zone, 38U);
}

TEST(DetectorCapacities, HoldAtEverySamplingFrequency) {
  // 125 Hz to 1000 Hz in steps of 0.5 Hz (architecture-m2.md 14.4, 14.7, 14.10).
  std::uint32_t largest_window = 0;
  for (int half_hz = 250; half_hz <= 2000; ++half_hz) {
    const double fs = 0.5 * static_cast<double>(half_hz);
    const DetectorSamples p = sinus::dsp::detector_samples(fs);
    largest_window = std::max(largest_window, p.window);
    ASSERT_LE(p.window, sinus::dsp::kDetectorWindowCapacity) << fs;
    ASSERT_LE(p.window + p.peak_timeout + 3U, sinus::dsp::kDetectorBandpassCapacity) << fs;
    ASSERT_LE(p.window + p.peak_timeout + 1U, sinus::dsp::kDetectorDerivativeCapacity) << fs;
    ASSERT_LE(p.learning, sinus::dsp::kDetectorLearningCapacity) << fs;
    ASSERT_LE((p.learning + 1U) / 2U, sinus::dsp::kDetectorPeakStoreCapacity) << fs;
    ASSERT_LE(p.window + 1U + p.band_delay, 65535U) << fs;  // m - f in 16 bits
    // At most ceil(L / R) detections at an initialisation, plus one by the normal thresholds and
    // one by search-back.
    ASSERT_LE(((p.learning + p.refractory - 1U) / p.refractory) + 2U,
              sinus::dsp::kMaxDetectionsPerSample)
        << fs;
    ASSERT_GT(p.relearn_after, p.learning) << fs;  // G > L, used by the proof of the marks
    ASSERT_GT(p.refractory, p.window) << fs;       // R > N: the zones are disjoint
  }
  EXPECT_EQ(largest_window, sinus::dsp::kDetectorWindowCapacity);
  const DetectorSamples top = sinus::dsp::detector_samples(1000.0);
  EXPECT_EQ(top.window + top.peak_timeout + 3U, sinus::dsp::kDetectorBandpassCapacity);
  EXPECT_EQ(top.learning, sinus::dsp::kDetectorLearningCapacity);
}

}  // namespace
