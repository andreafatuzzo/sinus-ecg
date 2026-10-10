// Requirement tests of SRS-019: real-time signal conditioning.
// Oracle: an own binary64 model of the two stages (support.hpp), written from the formulas of
// architecture.md 8.6; the criteria are those of SRS-004 and SRS-005.
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <utility>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;
using sinus_qa::gain_db;
using sinus_qa::rms_second_half;

struct Streams {
  std::vector<float> baseline;
  std::vector<float> conditioned;
};

// The input one sample at a time; every call must return kOk.
Streams run(int fs, int mains, const std::vector<float>& x) {
  Chain chain;
  EXPECT_EQ(chain.configure(Config{static_cast<double>(fs), mains}), Status::kOk);
  Streams s;
  s.baseline.reserve(x.size());
  s.conditioned.reserve(x.size());
  for (const float v : x) {
    SampleOutput out;
    const Status st = chain.process(v, out);
    EXPECT_EQ(st, Status::kOk);
    s.baseline.push_back(out.baseline_mv);
    s.conditioned.push_back(out.conditioned_mv);
  }
  return s;
}

// Case: baseline wander stage, SRS-004 criteria, at 360 Hz and 250 Hz, both mains settings.
// Input: 1 mV constant for 60 s; 1 mV sinusoids of 0.05 Hz (200 s) and 0.1 Hz (100 s), given one
// sample at a time; amplitude (RMS) measured on the second half of baseline_mv.
// Expected: output RMS at most 1 mV x 10^(-20/20) (attenuation of at least 20 dB) for each.
// Verifies: SRS-019
TEST(Srs019Conditioning, BaselineStageAttenuatesOffsetAndSlowWander) {
  for (const int fs : {360, 250}) {
    for (const int mains : {50, 60}) {
      SCOPED_TRACE(testing::Message() << "fs=" << fs << " mains=" << mains);
      const std::vector<float> offset(static_cast<std::size_t>(60 * fs), 1.0F);
      const Streams so = run(fs, mains, offset);
      EXPECT_LE(rms_second_half(so.baseline), 0.1);

      for (const auto& [f, seconds] : {std::pair{0.05, 200.0}, std::pair{0.1, 100.0}}) {
        SCOPED_TRACE(testing::Message() << "f=" << f);
        const std::vector<float> x = sinus_qa::sine(fs, f, seconds);
        const Streams s = run(fs, mains, x);
        EXPECT_LE(gain_db(rms_second_half(s.baseline), rms_second_half(x)), -20.0);
      }
    }
  }
}

// Case: baseline wander stage, band criterion of SRS-004.
// Input: 1 mV sinusoids of 1, 5, 10, 20 and 40 Hz, each of 10 periods (1 Hz: 10 s), at 360 Hz and
// 250 Hz, both mains settings; gain from the RMS of the second halves of baseline_mv and input.
// Expected: gain within +-0.5 dB.
// Verifies: SRS-019
TEST(Srs019Conditioning, BaselineStageKeepsTheBand) {
  for (const int fs : {360, 250}) {
    for (const int mains : {50, 60}) {
      for (const double f : {1.0, 5.0, 10.0, 20.0, 40.0}) {
        SCOPED_TRACE(testing::Message() << "fs=" << fs << " mains=" << mains << " f=" << f);
        const std::vector<float> x = sinus_qa::sine(fs, f, 10.0 / f);
        const Streams s = run(fs, mains, x);
        EXPECT_NEAR(gain_db(rms_second_half(s.baseline), rms_second_half(x)), 0.0, 0.5);
      }
    }
  }
}

// Case: mains stage, SRS-005 attenuation. The stage gain is the ratio of conditioned_mv to
// baseline_mv (its input); the whole conditioning is checked too.
// Input: a 1 mV sinusoid at the mains frequency (50 Hz, 60 Hz) lasting 2 s (the minimum of the
// rule; at least ten periods), at 360 Hz and 250 Hz, matching mains setting; amplitude on the
// second half.
// Expected: attenuation of at least 30 dB.
// Verifies: SRS-019
TEST(Srs019Conditioning, MainsStageAttenuatesMainsInterference) {
  for (const int fs : {360, 250}) {
    for (const int mains : {50, 60}) {
      SCOPED_TRACE(testing::Message() << "fs=" << fs << " mains=" << mains);
      const std::vector<float> x = sinus_qa::sine(fs, mains, 2.0);
      const Streams s = run(fs, mains, x);
      EXPECT_LE(gain_db(rms_second_half(s.conditioned), rms_second_half(s.baseline)), -30.0);
      EXPECT_LE(gain_db(rms_second_half(s.conditioned), rms_second_half(x)), -30.0);
    }
  }
}

// Case: the mains setting selects the frequency that is removed.
// Input: a 1 mV sinusoid of 60 Hz with the setting 50 Hz, and of 50 Hz with the setting 60 Hz,
// 2 s, at 360 Hz.
// Expected: the sinusoid is not attenuated by 30 dB (a notch of the other setting is not
// the configured one): attenuation less than 10 dB.
// Verifies: SRS-019
TEST(Srs019Conditioning, MainsSettingSelectsTheRemovedFrequency) {
  for (const auto& [mains, other] : {std::pair{50, 60}, std::pair{60, 50}}) {
    SCOPED_TRACE(testing::Message() << "setting " << mains << " input " << other);
    const std::vector<float> x = sinus_qa::sine(360, other, 2.0);
    const Streams s = run(360, mains, x);
    EXPECT_GE(gain_db(rms_second_half(s.conditioned), rms_second_half(x)), -10.0);
  }
}

// Case: mains stage, band criterion of SRS-005.
// Input: 1 mV sinusoids of 1, 5, 10, 20 and 40 Hz, each of at least ten periods and 2 s (1 Hz:
// 10 s), at 360 Hz and 250 Hz, both mains settings; stage gain = conditioned_mv / baseline_mv.
// Expected: gain within +-0.5 dB.
// Verifies: SRS-019
TEST(Srs019Conditioning, MainsStageKeepsTheBand) {
  for (const int fs : {360, 250}) {
    for (const int mains : {50, 60}) {
      for (const double f : {1.0, 5.0, 10.0, 20.0, 40.0}) {
        SCOPED_TRACE(testing::Message() << "fs=" << fs << " mains=" << mains << " f=" << f);
        const std::vector<float> x = sinus_qa::sine(fs, f, std::max(2.0, 10.0 / f));
        const Streams s = run(fs, mains, x);
        EXPECT_NEAR(gain_db(rms_second_half(s.conditioned), rms_second_half(s.baseline)), 0.0, 0.5);
      }
    }
  }
}

// Case: values of both stages against an independent binary64 model (stages in order: baseline
// 0.5 Hz Butterworth high-pass, then notch Q = 30), sample by sample.
// Input: the synthetic ECG with the interference of SRS-010 (0.3 Hz 1 mV, mains 0.2 mV), 30 s,
// 75 bpm, at 250 Hz and 360 Hz, both mains settings, and a clean ECG; every sample given alone.
// Expected: baseline_mv and conditioned_mv equal the model rounded to binary32, within two units
// in the last place of binary32 (plus 1e-9 mV).
// Verifies: SRS-019
TEST(Srs019Conditioning, ValuesEqualTheIndependentModel) {
  for (const int fs : {250, 360}) {
    for (const int mains : {50, 60}) {
      for (const int interference : {0, mains}) {
        SCOPED_TRACE(testing::Message()
                     << "fs=" << fs << " mains=" << mains << " bw=" << interference);
        const std::vector<float> x =
            sinus_qa::synthetic_ecg(fs, 75, static_cast<std::size_t>(30 * fs), interference);
        const Streams s = run(fs, mains, x);
        sinus_qa::OracleConditioner model(fs, mains);
        for (std::size_t i = 0; i < x.size(); ++i) {
          double b = 0.0;
          double c = 0.0;
          model.step(static_cast<double>(x[i]), b, c);
          const double tol_b = 2.5e-7 * std::fabs(b) + 1e-9;
          const double tol_c = 2.5e-7 * std::fabs(c) + 1e-9;
          ASSERT_NEAR(static_cast<double>(s.baseline[i]), b, tol_b) << "baseline sample " << i;
          ASSERT_NEAR(static_cast<double>(s.conditioned[i]), c, tol_c)
              << "conditioned sample " << i;
        }
      }
    }
  }
}

// Case: the start of the stream: a constant input gives a baseline output of exactly 0 from the
// first sample (the filter starts from the steady state; architecture-m1.md 8.6).
// Input: a constant 1.5 mV and a constant -0.7 mV, 10 s, 360 Hz.
// Expected: baseline_mv exactly 0 at every sample; conditioned_mv exactly 0 too.
// Verifies: SRS-019
TEST(Srs019Conditioning, ConstantInputGivesZeroFromTheFirstSample) {
  for (const float c : {1.5F, -0.7F, 1000.0F}) {
    SCOPED_TRACE(c);
    const std::vector<float> x(3600, c);
    const Streams s = run(360, 50, x);
    for (std::size_t i = 0; i < x.size(); ++i) {
      ASSERT_EQ(s.baseline[i], 0.0F) << "sample " << i;
      ASSERT_EQ(s.conditioned[i], 0.0F) << "sample " << i;
    }
  }
}

// Case: delay of 0 samples. The output of a sample is returned by the call that takes it and
// does not depend on later samples.
// Input: (a) a 1 mV impulse at sample 200 of a zero stream, at 360 Hz and 250 Hz;
// (b) two streams equal up to sample 3000 and different from sample 3001 on.
// Expected: (a) no output before the impulse and, at the impulse sample itself, a baseline output
// of at least 0.9 mV (the first coefficient of the filter is close to 1) and a conditioned
// output of at least 0.8 mV; (b) identical outputs up to sample 3000 (bit for bit), each returned
// with kOk by its own call.
// Verifies: SRS-019
TEST(Srs019Conditioning, OutputIsReturnedBeforeTheNextSampleWithoutDelay) {
  for (const int fs : {360, 250}) {
    SCOPED_TRACE(fs);
    std::vector<float> x(1000, 0.0F);
    x[200] = 1.0F;
    const Streams s = run(fs, 60, x);
    for (std::size_t i = 0; i < 200; ++i) {
      ASSERT_EQ(s.baseline[i], 0.0F);
      ASSERT_EQ(s.conditioned[i], 0.0F);
    }
    EXPECT_GE(s.baseline[200], 0.9F);
    EXPECT_GE(s.conditioned[200], 0.8F);
  }
  std::vector<float> a = sinus_qa::synthetic_ecg(360, 75, 6000, 50);
  std::vector<float> b = a;
  for (std::size_t i = 3001; i < b.size(); ++i) {
    b[i] = -b[i] + 2.0F;
  }
  const Streams sa = run(360, 50, a);
  const Streams sb = run(360, 50, b);
  for (std::size_t i = 0; i <= 3000; ++i) {
    ASSERT_TRUE(sinus_qa::same_bits(sa.baseline[i], sb.baseline[i])) << i;
    ASSERT_TRUE(sinus_qa::same_bits(sa.conditioned[i], sb.conditioned[i])) << i;
  }
  EXPECT_NE(sa.conditioned[3001], sb.conditioned[3001]);
}

// Case: the conditioning is deterministic and linear in time: the same input gives the same output
// whichever chain object processes it.
// Input: the interfered ECG, 10 s at 360 Hz, given to two chains.
// Expected: bit-identical outputs.
// Verifies: SRS-019
TEST(Srs019Conditioning, SameInputGivesSameOutput) {
  const std::vector<float> x = sinus_qa::synthetic_ecg(360, 180, 3600, 60);
  const Streams a = run(360, 60, x);
  const Streams b = run(360, 60, x);
  for (std::size_t i = 0; i < x.size(); ++i) {
    ASSERT_TRUE(sinus_qa::same_bits(a.conditioned[i], b.conditioned[i]));
  }
}

}  // namespace
