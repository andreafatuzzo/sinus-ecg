// Requirement tests of SRS-018: invalid input samples in the real-time library.
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/limits.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;

constexpr int kFs = 360;
constexpr std::size_t kSamples = 30 * kFs;
constexpr float kLimit = sinus::dsp::kMaxAbsSampleMv;
constexpr float kInf = std::numeric_limits<float>::infinity();

struct BadSample {
  const char* name;
  float value;
};

// The values of the SRS verification: NaN, +-infinity, the smallest binary32 above the limit and
// its negative.
std::vector<BadSample> bad_samples() {
  return {{"NaN", std::numeric_limits<float>::quiet_NaN()},
          {"-NaN", -std::numeric_limits<float>::quiet_NaN()},
          {"+inf", kInf},
          {"-inf", -kInf},
          {"next above limit", std::nextafter(kLimit, kInf)},
          {"next below -limit", -std::nextafter(kLimit, kInf)},
          {"max float", std::numeric_limits<float>::max()},
          {"lowest float", std::numeric_limits<float>::lowest()},
          {"1001", 1001.0F},
          {"-1e6", -1.0e6F}};
}

SampleOutput poisoned() {
  SampleOutput out;
  out.baseline_mv = 7.0F;
  out.conditioned_mv = 7.0F;
  return out;
}

// Extended with the detection, heart-rate and window fields when the chain gets them.
void expect_no_output(const SampleOutput& out) {
  EXPECT_EQ(out.baseline_mv, 0.0F);
  EXPECT_EQ(out.conditioned_mv, 0.0F);
}

Chain configured_chain(int mains) {
  Chain chain;
  EXPECT_EQ(chain.configure(Config{static_cast<double>(kFs), mains}), Status::kOk);
  return chain;
}

// Case: one invalid sample after at least 10 s of a synthetic ECG at 360 Hz, in turn NaN,
// +infinity, -infinity, the smallest binary32 above the limit and its negative (and other
// values beyond the limit), with both mains settings.
// Expected: kOk before it; kInvalidSample with no output at that sample; kStopped with no output at
// every later sample, whatever the later value (valid or invalid); no output of any kind.
// Verifies: SRS-018
TEST(Srs018InvalidSamples, InvalidSampleStopsTheChain) {
  for (const int mains : {50, 60}) {
    const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, kSamples, mains);
    for (const BadSample& bad : bad_samples()) {
      for (const std::size_t at :
           {std::size_t{10 * kFs}, std::size_t{10 * kFs + 137}, std::size_t{20 * kFs}}) {
        SCOPED_TRACE(testing::Message() << bad.name << " at " << at << " mains " << mains);
        Chain chain = configured_chain(mains);
        for (std::size_t i = 0; i < ecg.size(); ++i) {
          SampleOutput out = poisoned();
          if (i < at) {
            ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
          } else if (i == at) {
            ASSERT_EQ(chain.process(bad.value, out), Status::kInvalidSample);
            expect_no_output(out);
          } else {
            // The rest of the ECG, with a second invalid value in the middle of it.
            const float v = (i == at + 5) ? bad.value : ecg[i];
            ASSERT_EQ(chain.process(v, out), Status::kStopped);
            expect_no_output(out);
          }
        }
        EXPECT_TRUE(chain.configured());
      }
    }
  }
}

// Case: the invalid sample is the first sample of the stream (before 10 s).
// Input: each invalid value as sample 0, then valid samples.
// Expected: kInvalidSample at sample 0, kStopped after, no output.
// Verifies: SRS-018
TEST(Srs018InvalidSamples, InvalidFirstSample) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 2000, 50);
  for (const BadSample& bad : bad_samples()) {
    SCOPED_TRACE(bad.name);
    Chain chain = configured_chain(50);
    SampleOutput out = poisoned();
    EXPECT_EQ(chain.process(bad.value, out), Status::kInvalidSample);
    expect_no_output(out);
    for (const float x : ecg) {
      out = poisoned();
      EXPECT_EQ(chain.process(x, out), Status::kStopped);
      expect_no_output(out);
    }
  }
}

// Case: after the invalid sample, reset(), then the samples that follow the invalid one.
// Input: the ECG with one sample replaced after 10 s, reset, the rest of the ECG; the same rest
// of the ECG given to a newly configured chain.
// Expected: every output after the reset equals, bit for bit, the output of the new chain, and the
// status is kOk.
// Verifies: SRS-018
TEST(Srs018InvalidSamples, ResetAfterInvalidSampleEqualsNewlyConfiguredChain) {
  for (const int mains : {50, 60}) {
    const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, kSamples, mains);
    for (const BadSample& bad : bad_samples()) {
      for (const std::size_t at : {std::size_t{10 * kFs}, std::size_t{10 * kFs + 211}}) {
        SCOPED_TRACE(testing::Message() << bad.name << " at " << at << " mains " << mains);
        Chain chain = configured_chain(mains);
        SampleOutput out;
        for (std::size_t i = 0; i < at; ++i) {
          ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
        }
        ASSERT_EQ(chain.process(bad.value, out), Status::kInvalidSample);
        ASSERT_EQ(chain.process(ecg[at + 1], out), Status::kStopped);
        chain.reset();
        EXPECT_TRUE(chain.configured());
        Chain fresh = configured_chain(mains);
        for (std::size_t i = at + 1; i < ecg.size(); ++i) {
          SampleOutput a = poisoned();
          SampleOutput b = poisoned();
          ASSERT_EQ(chain.process(ecg[i], a), Status::kOk);
          ASSERT_EQ(fresh.process(ecg[i], b), Status::kOk);
          ASSERT_TRUE(sinus_qa::same_bits(a.baseline_mv, b.baseline_mv)) << "sample " << i;
          ASSERT_TRUE(sinus_qa::same_bits(a.conditioned_mv, b.conditioned_mv)) << "sample " << i;
        }
      }
    }
  }
}

// Case: a sample equal to the limit, and one equal to its negative, are processed.
// Input: 10 s of ECG, then 1000.0, -1000.0, 999.99994 (the binary32 below the limit), -999.99994,
// then ECG again, at both mains settings.
// Expected: kOk at each, with finite outputs, and kOk for the samples that follow.
// Verifies: SRS-018
TEST(Srs018InvalidSamples, SamplesAtTheLimitAreProcessed) {
  for (const int mains : {50, 60}) {
    const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 20 * kFs, mains);
    const float below = std::nextafter(kLimit, 0.0F);
    for (const float v : {kLimit, -kLimit, below, -below}) {
      SCOPED_TRACE(testing::Message() << "value " << v << " mains " << mains);
      Chain chain = configured_chain(mains);
      std::size_t i = 0;
      for (; i < 10 * kFs; ++i) {
        SampleOutput out;
        ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
      }
      SampleOutput out = poisoned();
      EXPECT_EQ(chain.process(v, out), Status::kOk);
      EXPECT_TRUE(std::isfinite(out.baseline_mv));
      EXPECT_TRUE(std::isfinite(out.conditioned_mv));
      for (; i < ecg.size(); ++i) {
        ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
        ASSERT_TRUE(std::isfinite(out.conditioned_mv));
      }
    }
  }
}

// Case: limit samples as the very first and as consecutive samples.
// Input: 1000, -1000, 1000, -1000 ... for 100 samples at 360 Hz.
// Expected: kOk each time, finite outputs.
// Verifies: SRS-018
TEST(Srs018InvalidSamples, ExtremeValidSamplesAtTheStartOfTheStream) {
  Chain chain = configured_chain(50);
  for (int i = 0; i < 100; ++i) {
    SampleOutput out;
    ASSERT_EQ(chain.process((i % 2 == 0) ? kLimit : -kLimit, out), Status::kOk);
    ASSERT_TRUE(std::isfinite(out.baseline_mv));
    ASSERT_TRUE(std::isfinite(out.conditioned_mv));
  }
}

// Case: a stopped chain stays stopped until reset: a new configure with the same valid
// configuration is a new stream, reset() clears the stop and keeps the configuration.
// Input: stop with NaN, reset, process; stop again, configure, process.
// Expected: kOk after the reset and after the configure; configured() remains true after reset.
// Verifies: SRS-018
TEST(Srs018InvalidSamples, StopIsClearedByResetOrConfigure) {
  Chain chain = configured_chain(60);
  SampleOutput out;
  ASSERT_EQ(chain.process(std::numeric_limits<float>::quiet_NaN(), out), Status::kInvalidSample);
  ASSERT_EQ(chain.process(0.5F, out), Status::kStopped);
  chain.reset();
  EXPECT_TRUE(chain.configured());
  EXPECT_EQ(chain.config().mains_frequency_hz, 60);
  EXPECT_EQ(chain.process(0.5F, out), Status::kOk);
  ASSERT_EQ(chain.process(kInf, out), Status::kInvalidSample);
  EXPECT_EQ(chain.configure(Config{250.0, 50}), Status::kOk);
  EXPECT_EQ(chain.process(0.5F, out), Status::kOk);
}

}  // namespace
