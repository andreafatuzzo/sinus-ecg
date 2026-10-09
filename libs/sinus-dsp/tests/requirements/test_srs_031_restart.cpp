// Requirement tests of SRS-031: restart of the real-time library (signal conditioning part; the
// detections, heart rates and windows are added with their components).
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <cstddef>
#include <limits>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;

constexpr int kFs = 360;

// Every output field of the two samples is identical, bit for bit. Extended with the detection,
// heart-rate and window fields when the chain gets them.
::testing::AssertionResult identical(const SampleOutput& a, const SampleOutput& b) {
  if (!sinus_qa::same_bits(a.baseline_mv, b.baseline_mv)) {
    return ::testing::AssertionFailure() << "baseline " << a.baseline_mv << " vs " << b.baseline_mv;
  }
  if (!sinus_qa::same_bits(a.conditioned_mv, b.conditioned_mv)) {
    return ::testing::AssertionFailure()
           << "conditioned " << a.conditioned_mv << " vs " << b.conditioned_mv;
  }
  return ::testing::AssertionSuccess();
}

// Process ecg[0..reset_at), reset, then ecg[reset_at..) on `chain`, and ecg[reset_at..) on a newly
// configured chain; every output after the reset must be identical.
void check_reset_at(const std::vector<float>& ecg, std::size_t reset_at, int mains) {
  Chain chain;
  ASSERT_EQ(chain.configure(Config{static_cast<double>(kFs), mains}), Status::kOk);
  SampleOutput out;
  for (std::size_t i = 0; i < reset_at; ++i) {
    ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
  }
  chain.reset();
  ASSERT_TRUE(chain.configured());
  Chain fresh;
  ASSERT_EQ(fresh.configure(Config{static_cast<double>(kFs), mains}), Status::kOk);
  for (std::size_t i = reset_at; i < ecg.size(); ++i) {
    SampleOutput a;
    SampleOutput b;
    ASSERT_EQ(chain.process(ecg[i], a), Status::kOk);
    ASSERT_EQ(fresh.process(ecg[i], b), Status::kOk);
    ASSERT_TRUE(identical(a, b)) << "reset at " << reset_at << ", sample " << i;
  }
}

// Case: reset after 20 s, at several points of the cardiac cycle.
// Input: the interfered synthetic ECG (SRS-010: 0.3 Hz 1 mV, mains 0.2 mV) at 360 Hz, 75 bpm
// (288 samples per cycle), 20 s processed, then a reset at 20 s + k x 24 samples for k = 0 ... 12,
// the ECG continuing 10 s, both mains settings.
// Expected: the outputs after the reset equal those of a newly configured chain given the same
// samples, bit for bit.
// Verifies: SRS-031
TEST(Srs031Restart, ResetAtSeveralPointsOfTheCardiacCycle) {
  for (const int mains : {50, 60}) {
    const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 30 * kFs, mains);
    for (std::size_t k = 0; k <= 12; ++k) {
      SCOPED_TRACE(testing::Message() << "mains " << mains << " k " << k);
      check_reset_at(ecg, 20 * kFs + 24 * k, mains);
    }
  }
}

// Case: reset during the start-up period of the stream.
// Input: the same ECG, reset after 0, 1, 2, 3, 10, 36, 100, 359, 360, 361, 720 and 1000 samples.
// Expected: outputs after the reset identical to those of a newly configured chain.
// Verifies: SRS-031
TEST(Srs031Restart, ResetDuringStartUp) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 30 * kFs, 50);
  for (const std::size_t at : {0, 1, 2, 3, 10, 36, 100, 359, 360, 361, 720, 1000}) {
    SCOPED_TRACE(at);
    check_reset_at(ecg, at, 50);
  }
}

// Case: no sample given before the reset is used after it.
// Input: a history with a large offset (500 mV plus a 5 Hz sinusoid of 300 mV) for 15 s, then a
// reset and the interfered ECG; the ECG alone to a newly configured chain.
// Expected: identical outputs, bit for bit, from the first sample after the reset.
// Verifies: SRS-031
TEST(Srs031Restart, EarlierSamplesHaveNoEffect) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 10 * kFs, 60);
  std::vector<float> history = sinus_qa::sine(kFs, 5.0, 15.0, 300.0);
  for (float& h : history) {
    h += 500.0F;
  }
  Chain chain;
  ASSERT_EQ(chain.configure(Config{static_cast<double>(kFs), 60}), Status::kOk);
  SampleOutput out;
  for (const float h : history) {
    ASSERT_EQ(chain.process(h, out), Status::kOk);
  }
  chain.reset();
  Chain fresh;
  ASSERT_EQ(fresh.configure(Config{static_cast<double>(kFs), 60}), Status::kOk);
  for (const float x : ecg) {
    SampleOutput a;
    SampleOutput b;
    ASSERT_EQ(chain.process(x, a), Status::kOk);
    ASSERT_EQ(fresh.process(x, b), Status::kOk);
    ASSERT_TRUE(identical(a, b));
  }
}

// Case: repeated resets, and a reset on a chain without samples.
// Input: 5 s, reset, 3 s, reset, reset, 0 s, reset, then the ECG for 10 s.
// Expected: identical to a newly configured chain given the final ECG.
// Verifies: SRS-031
TEST(Srs031Restart, RepeatedResets) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 180, 10 * kFs, 50);
  Chain chain;
  ASSERT_EQ(chain.configure(Config{static_cast<double>(kFs), 50}), Status::kOk);
  chain.reset();
  SampleOutput out;
  for (std::size_t i = 0; i < 5 * kFs; ++i) {
    ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
  }
  chain.reset();
  for (std::size_t i = 0; i < 3 * kFs; ++i) {
    ASSERT_EQ(chain.process(ecg[i] + 3.0F, out), Status::kOk);
  }
  chain.reset();
  chain.reset();
  chain.reset();
  Chain fresh;
  ASSERT_EQ(fresh.configure(Config{static_cast<double>(kFs), 50}), Status::kOk);
  for (const float x : ecg) {
    SampleOutput a;
    SampleOutput b;
    ASSERT_EQ(chain.process(x, a), Status::kOk);
    ASSERT_EQ(fresh.process(x, b), Status::kOk);
    ASSERT_TRUE(identical(a, b));
  }
}

// Case: reset after an invalid sample (the way SRS-018 resumes processing).
// Input: 12 s of ECG, a NaN, 100 stopped samples, reset, then the ECG continuing.
// Expected: identical to a newly configured chain given the samples after the reset.
// Verifies: SRS-031
TEST(Srs031Restart, ResetAfterAStop) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 30 * kFs, 50);
  Chain chain;
  ASSERT_EQ(chain.configure(Config{static_cast<double>(kFs), 50}), Status::kOk);
  SampleOutput out;
  std::size_t i = 0;
  for (; i < 12 * kFs; ++i) {
    ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
  }
  ASSERT_EQ(chain.process(std::numeric_limits<float>::quiet_NaN(), out), Status::kInvalidSample);
  for (std::size_t j = 0; j < 100; ++j) {
    ASSERT_EQ(chain.process(ecg[i + j], out), Status::kStopped);
  }
  i += 100;
  chain.reset();
  Chain fresh;
  ASSERT_EQ(fresh.configure(Config{static_cast<double>(kFs), 50}), Status::kOk);
  for (; i < ecg.size(); ++i) {
    SampleOutput a;
    SampleOutput b;
    ASSERT_EQ(chain.process(ecg[i], a), Status::kOk);
    ASSERT_EQ(fresh.process(ecg[i], b), Status::kOk);
    ASSERT_TRUE(identical(a, b));
  }
}

// Case: the same property at the other sampling frequencies of the library.
// Input: the interfered ECG at 125, 250, 500 and 1000 Hz, reset after 20 s + 0.3 s.
// Expected: outputs after the reset identical to a newly configured chain.
// Verifies: SRS-031
TEST(Srs031Restart, ResetAtOtherSamplingFrequencies) {
  for (const int fs : {125, 250, 500, 1000}) {
    SCOPED_TRACE(fs);
    const std::vector<float> ecg =
        sinus_qa::synthetic_ecg(fs, 75, static_cast<std::size_t>(26 * fs), 50);
    const auto reset_at = static_cast<std::size_t>(20.3 * fs);
    Chain chain;
    ASSERT_EQ(chain.configure(Config{static_cast<double>(fs), 50}), Status::kOk);
    SampleOutput out;
    for (std::size_t i = 0; i < reset_at; ++i) {
      ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
    }
    chain.reset();
    Chain fresh;
    ASSERT_EQ(fresh.configure(Config{static_cast<double>(fs), 50}), Status::kOk);
    for (std::size_t i = reset_at; i < ecg.size(); ++i) {
      SampleOutput a;
      SampleOutput b;
      ASSERT_EQ(chain.process(ecg[i], a), Status::kOk);
      ASSERT_EQ(fresh.process(ecg[i], b), Status::kOk);
      ASSERT_TRUE(identical(a, b)) << "sample " << i;
    }
  }
}

}  // namespace
