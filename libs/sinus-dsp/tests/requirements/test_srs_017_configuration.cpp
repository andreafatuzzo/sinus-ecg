// Requirement tests of SRS-017: configuration checks of the real-time library.
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/limits.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;

constexpr double kNanD = std::numeric_limits<double>::quiet_NaN();
constexpr double kInfD = std::numeric_limits<double>::infinity();

// A SampleOutput filled with a value that no result can have, so that "no output" is a real clear.
SampleOutput poisoned() {
  SampleOutput out;
  out.baseline_mv = 7.0F;
  out.conditioned_mv = 7.0F;
  out.detection_count = 5;
  return out;
}

// No output of any kind: every field of SampleOutput holds its empty value. Extended with the
// heart-rate and window fields when the chain gets them.
void expect_no_output(const SampleOutput& out) {
  EXPECT_EQ(out.baseline_mv, 0.0F);
  EXPECT_EQ(out.conditioned_mv, 0.0F);
  EXPECT_EQ(out.detection_count, 0U);
}

// Samples given to a chain that is not configured: every one returns kNotConfigured, no output.
void expect_inert(Chain& chain, int fs) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(fs, 75, 600, 0);
  for (const float x : ecg) {
    SampleOutput out = poisoned();
    EXPECT_EQ(chain.process(x, out), Status::kNotConfigured);
    expect_no_output(out);
  }
  SampleOutput out = poisoned();
  EXPECT_EQ(chain.process(0.0F, out), Status::kNotConfigured);
  expect_no_output(out);
}

// Case: a chain that was never configured. Input: samples of an ECG, a reset, more samples.
// Expected: kNotConfigured with no output at every sample; configured() is false.
// Verifies: SRS-017
TEST(Srs017Configuration, ChainWithoutConfigurationProducesNoOutput) {
  Chain chain;
  EXPECT_FALSE(chain.configured());
  expect_inert(chain, 360);
  chain.reset();
  EXPECT_FALSE(chain.configured());
  expect_inert(chain, 360);
}

// Case: sampling frequency below the lower bound, above the upper bound, not finite.
// Input: 124.9, 1000.1 Hz, NaN, +inf, -inf, plus 0, negative values, the neighbours of the bounds
// and extreme values, each with both mains settings.
// Expected: kInvalidSamplingFrequency, the chain is not configured, and samples given afterwards
// return kNotConfigured with no output.
// Verifies: SRS-017
TEST(Srs017Configuration, RejectedSamplingFrequenciesProduceNoOutput) {
  const double bad[] = {124.9,
                        1000.1,
                        kNanD,
                        kInfD,
                        -kInfD,
                        0.0,
                        -0.0,
                        -360.0,
                        -125.0,
                        1.0,
                        124.99999999,
                        std::nextafter(125.0, 0.0),
                        std::nextafter(1000.0, kInfD),
                        1000.00001,
                        1e9,
                        std::numeric_limits<double>::max(),
                        std::numeric_limits<double>::denorm_min(),
                        std::numeric_limits<double>::lowest()};
  for (const double fs : bad) {
    for (const int mains : {50, 60}) {
      SCOPED_TRACE(testing::Message() << "fs=" << fs << " mains=" << mains);
      Chain chain;
      EXPECT_EQ(chain.configure(Config{fs, mains}), Status::kInvalidSamplingFrequency);
      EXPECT_FALSE(chain.configured());
      expect_inert(chain, 360);
    }
  }
}

// Case: mains setting other than 50 or 60 Hz, with a valid sampling frequency.
// Input: 49, 51, 59, 61, 100, and 0, 1, -50, -60, 5060, INT_MAX, INT_MIN, at 125, 360 and 1000 Hz.
// Expected: kInvalidMainsFrequency, the chain is not configured, later samples give kNotConfigured
// with no output.
// Verifies: SRS-017
TEST(Srs017Configuration, RejectedMainsSettingsProduceNoOutput) {
  const int bad[] = {49,
                     51,
                     59,
                     61,
                     100,
                     0,
                     1,
                     -50,
                     -60,
                     5060,
                     50000,
                     std::numeric_limits<int>::max(),
                     std::numeric_limits<int>::min()};
  for (const double fs : {125.0, 360.0, 1000.0}) {
    for (const int mains : bad) {
      SCOPED_TRACE(testing::Message() << "fs=" << fs << " mains=" << mains);
      Chain chain;
      EXPECT_EQ(chain.configure(Config{fs, mains}), Status::kInvalidMainsFrequency);
      EXPECT_FALSE(chain.configured());
      expect_inert(chain, 360);
    }
  }
}

// Case: the bounds of the sampling frequency and both mains settings are accepted.
// Input: 125 Hz and 1000 Hz (and 250, 360, 500 Hz) with 50 Hz and 60 Hz.
// Expected: kOk, configured() is true, config() returns the configuration, and a sample is
// processed (kOk) afterwards.
// Verifies: SRS-017
TEST(Srs017Configuration, AcceptedConfigurations) {
  for (const double fs : {125.0, 250.0, 360.0, 500.0, 1000.0}) {
    for (const int mains : {50, 60}) {
      SCOPED_TRACE(testing::Message() << "fs=" << fs << " mains=" << mains);
      Chain chain;
      EXPECT_EQ(chain.configure(Config{fs, mains}), Status::kOk);
      EXPECT_TRUE(chain.configured());
      EXPECT_EQ(chain.config().sampling_frequency_hz, fs);
      EXPECT_EQ(chain.config().mains_frequency_hz, mains);
      SampleOutput out = poisoned();
      EXPECT_EQ(chain.process(0.5F, out), Status::kOk);
      EXPECT_EQ(chain.process(0.6F, out), Status::kOk);
    }
  }
}

// Case: validate() reports the same status as configure() for each rejected or accepted value.
// Input: the configurations of the SRS verification and the bounds.
// Expected: kInvalidSamplingFrequency / kInvalidMainsFrequency / kOk as for the chain.
// Verifies: SRS-017
TEST(Srs017Configuration, ValidateAgreesWithTheRequirement) {
  EXPECT_EQ(sinus::dsp::validate(Config{124.9, 50}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(sinus::dsp::validate(Config{1000.1, 60}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(sinus::dsp::validate(Config{kNanD, 50}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(sinus::dsp::validate(Config{kInfD, 50}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(sinus::dsp::validate(Config{-kInfD, 50}), Status::kInvalidSamplingFrequency);
  for (const int mains : {49, 51, 59, 61, 100}) {
    EXPECT_EQ(sinus::dsp::validate(Config{360.0, mains}), Status::kInvalidMainsFrequency);
  }
  EXPECT_EQ(sinus::dsp::validate(Config{125.0, 50}), Status::kOk);
  EXPECT_EQ(sinus::dsp::validate(Config{1000.0, 60}), Status::kOk);
  EXPECT_EQ(sinus::dsp::kMinSamplingFrequencyHz, 125.0);
  EXPECT_EQ(sinus::dsp::kMaxSamplingFrequencyHz, 1000.0);
}

// Case: both settings invalid. Input: 50 kHz with mains 49 Hz, NaN with mains 100 Hz.
// Expected: the sampling frequency is checked first (architecture-m2.md 14.5), so the status is
// kInvalidSamplingFrequency; the chain stays not configured.
// Verifies: SRS-017
TEST(Srs017Configuration, SamplingFrequencyIsCheckedBeforeMains) {
  Chain chain;
  EXPECT_EQ(chain.configure(Config{50000.0, 49}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(chain.configure(Config{kNanD, 100}), Status::kInvalidSamplingFrequency);
  EXPECT_FALSE(chain.configured());
}

// Case: a rejected configuration after a valid one. Input: configure(360, 50), process samples,
// then each rejected configuration, then samples.
// Expected: the chain is not configured whatever it was before; samples give kNotConfigured with
// no output, also after reset().
// Verifies: SRS-017
TEST(Srs017Configuration, FailedConfigureLeavesTheChainNotConfigured) {
  const std::vector<Config> bad = {{124.9, 50}, {1000.1, 50}, {kNanD, 50}, {kInfD, 60},
                                   {360.0, 49}, {360.0, 61},  {360.0, 100}};
  for (const Config& c : bad) {
    SCOPED_TRACE(testing::Message()
                 << "fs=" << c.sampling_frequency_hz << " mains=" << c.mains_frequency_hz);
    Chain chain;
    ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
    SampleOutput out = poisoned();
    ASSERT_EQ(chain.process(0.2F, out), Status::kOk);
    EXPECT_NE(chain.configure(c), Status::kOk);
    EXPECT_FALSE(chain.configured());
    expect_inert(chain, 360);
    chain.reset();
    EXPECT_FALSE(chain.configured());
    expect_inert(chain, 360);
  }
}

// Case: a valid configuration after a rejected one works as on a new chain.
// Input: reject 1000.1 Hz, accept 250 Hz / 60 Hz, then 2000 samples of an ECG.
// Expected: outputs bit for bit equal to those of a new chain configured the same way.
// Verifies: SRS-017
TEST(Srs017Configuration, ValidConfigurationAfterARejectedOneBehavesAsNew) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(250, 75, 2000, 60);
  Chain fresh;
  ASSERT_EQ(fresh.configure(Config{250.0, 60}), Status::kOk);
  Chain chain;
  ASSERT_NE(chain.configure(Config{1000.1, 60}), Status::kOk);
  ASSERT_EQ(chain.configure(Config{250.0, 60}), Status::kOk);
  for (const float x : ecg) {
    SampleOutput a;
    SampleOutput b;
    ASSERT_EQ(chain.process(x, a), Status::kOk);
    ASSERT_EQ(fresh.process(x, b), Status::kOk);
    ASSERT_TRUE(sinus_qa::same_bits(a.baseline_mv, b.baseline_mv));
    ASSERT_TRUE(sinus_qa::same_bits(a.conditioned_mv, b.conditioned_mv));
  }
}

}  // namespace
