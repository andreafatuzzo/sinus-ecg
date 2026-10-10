// Requirement tests of SRS-031: restart of the real-time library (conditioning, detection,
// heart rates and signal quality windows).
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "chain_run.hpp"
#include "sinus/dsp/chain.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;

constexpr int kFs = 360;

// Every output field of the two samples is identical, bit for bit: the conditioned samples, the
// detections (count, index, report sample, mark, path), the heart-rate events (count, sample, beat,
// status, rate) and the quality window (presence, samples, index, mark).
::testing::AssertionResult identical(const SampleOutput& a, const SampleOutput& b) {
  if (!sinus_qa::same_bits(a.baseline_mv, b.baseline_mv)) {
    return ::testing::AssertionFailure() << "baseline " << a.baseline_mv << " vs " << b.baseline_mv;
  }
  if (!sinus_qa::same_bits(a.conditioned_mv, b.conditioned_mv)) {
    return ::testing::AssertionFailure()
           << "conditioned " << a.conditioned_mv << " vs " << b.conditioned_mv;
  }
  if (a.detection_count != b.detection_count) {
    return ::testing::AssertionFailure()
           << "detection count " << a.detection_count << " vs " << b.detection_count;
  }
  for (std::size_t j = 0; j < a.detection_count && j < a.detections.size(); ++j) {
    const auto& x = a.detections[j];
    const auto& y = b.detections[j];
    if (x.index != y.index || x.reported_at != y.reported_at || x.mark != y.mark ||
        x.path != y.path) {
      return ::testing::AssertionFailure()
             << "detection " << j << ": index " << x.index << " vs " << y.index << ", reported at "
             << x.reported_at << " vs " << y.reported_at;
    }
  }
  if (a.heart_rate_count != b.heart_rate_count) {
    return ::testing::AssertionFailure()
           << "heart-rate count " << a.heart_rate_count << " vs " << b.heart_rate_count;
  }
  for (std::size_t j = 0; j < a.heart_rate_count && j < a.heart_rates.size(); ++j) {
    const auto& x = a.heart_rates[j];
    const auto& y = b.heart_rates[j];
    if (x.sample != y.sample || x.has_beat != y.has_beat ||
        (x.has_beat && x.beat_index != y.beat_index) || x.status != y.status ||
        !sinus_qa::same_bits(x.bpm, y.bpm)) {
      return ::testing::AssertionFailure()
             << "heart-rate event " << j << ": sample " << x.sample << " vs " << y.sample
             << ", rate " << x.bpm << " vs " << y.bpm;
    }
  }
  if (a.has_window != b.has_window) {
    return ::testing::AssertionFailure() << "window presence differs";
  }
  if (a.has_window && (a.window.first_sample != b.window.first_sample ||
                       a.window.last_sample != b.window.last_sample ||
                       a.window.reported_at != b.window.reported_at ||
                       !sinus_qa::same_bits(a.window.index, b.window.index) ||
                       a.window.usable != b.window.usable)) {
    return ::testing::AssertionFailure()
           << "window " << a.window.first_sample << " vs " << b.window.first_sample << ", index "
           << a.window.index << " vs " << b.window.index;
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

// Case: detections after a reset, and a history that would hide them.
// Input: the event input artefact (a beat 20 times larger at 10.1 s, which raises the detection
// levels so that the next beats are missed) for 13 s, a reset, then the regular 75 bpm ECG with
// interference for 30 s; the same ECG to a newly configured chain.
// Expected: the detections after the reset equal, one for one (index, report sample, mark, path),
// those of the new chain, which has one for each beat; the first is reported at sample 719 and
// all the detections of the first 2 s are marked start-up.
// Verifies: SRS-031
TEST(Srs031Restart, DetectionsAfterResetIgnoreTheHistory) {
  const std::vector<float> history = sinus_qa::event_ecg(kFs, "artefact", nullptr);
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 30 * kFs, 50);
  Chain chain;
  ASSERT_EQ(chain.configure(Config{static_cast<double>(kFs), 50}), Status::kOk);
  (void)sinus_qa::feed(chain, std::vector<float>(history.begin(), history.begin() + 13 * kFs));
  chain.reset();
  const std::vector<sinus_qa::Det> after = sinus_qa::feed(chain, ecg);
  const std::vector<sinus_qa::Det> fresh = sinus_qa::run_chain(ecg, kFs, 50);
  EXPECT_TRUE(after == fresh);
  const std::vector<std::int64_t> r = sinus_qa::regular_r_positions(kFs, 75, ecg.size());
  (void)sinus_qa::expect_one_per_beat(after, r, ecg.size(), kFs);
  ASSERT_FALSE(after.empty());
  EXPECT_EQ(after.front().reported_at, 719U);
  EXPECT_EQ(after.front().mark, sinus::dsp::Mark::kStartUp);
}

// Case: reset between the samples of a stretch of detection in progress, with detections after.
// Input: the interfered ECG at 180 bpm (fast: a detection about every 0.33 s), reset at 9.0 s + k x
// 7 samples for k = 0 ... 9 (inside a beat's confirmation delay), 15 s more.
// Expected: the detections after the reset equal those of a newly configured chain given the
// samples after the reset, and there are some.
// Verifies: SRS-031
TEST(Srs031Restart, DetectionsAfterResetsInsideTheConfirmationDelay) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 180, 25 * kFs, 60);
  for (std::size_t k = 0; k <= 9; ++k) {
    SCOPED_TRACE(k);
    const std::size_t at = 9 * kFs + 7 * k;
    Chain chain;
    ASSERT_EQ(chain.configure(Config{static_cast<double>(kFs), 60}), Status::kOk);
    (void)sinus_qa::feed(chain, std::vector<float>(ecg.begin(), ecg.begin() + at));
    chain.reset();
    const std::vector<sinus_qa::Det> after = sinus_qa::feed(chain, ecg, at);
    const std::vector<sinus_qa::Det> fresh = sinus_qa::run_chain(
        std::vector<float>(ecg.begin() + static_cast<std::ptrdiff_t>(at), ecg.end()), kFs, 60);
    EXPECT_TRUE(after == fresh);
    EXPECT_GE(after.size(), 20U);
  }
}

// Process `history` (reset follows), then `ecg` on `chain`, and `ecg` on a newly configured chain;
// returns the number of heart-rate events and of windows seen after the reset, after checking that
// the outputs are identical at every sample.
struct Seen {
  std::size_t events = 0;
  std::size_t windows = 0;
};

Seen check_history_then_ecg(const std::vector<float>& history, const std::vector<float>& ecg,
                            int mains) {
  Seen seen;
  Chain chain;
  EXPECT_EQ(chain.configure(Config{static_cast<double>(kFs), mains}), Status::kOk);
  SampleOutput out;
  for (const float h : history) {
    EXPECT_EQ(chain.process(h, out), Status::kOk);
  }
  chain.reset();
  Chain fresh;
  EXPECT_EQ(fresh.configure(Config{static_cast<double>(kFs), mains}), Status::kOk);
  for (std::size_t i = 0; i < ecg.size(); ++i) {
    SampleOutput a;
    SampleOutput b;
    EXPECT_EQ(chain.process(ecg[i], a), Status::kOk);
    EXPECT_EQ(fresh.process(ecg[i], b), Status::kOk);
    EXPECT_TRUE(identical(a, b)) << "sample " << i;
    seen.events += b.heart_rate_count;
    seen.windows += b.has_window ? 1U : 0U;
    if (a.has_window) {
      EXPECT_EQ(a.window.first_sample % 360U, 0U);
      EXPECT_LE(a.window.reported_at, i);
    }
  }
  return seen;
}

// Case: no interval, heart rate or window uses a sample given before the reset.
// Input: 25 s of the 40 bpm interfered ECG (heart rate valid, windows reported), a reset at a point
// of a beat, then 40 s of the 180 bpm ECG with interference; the same ECG to a newly configured
// chain.
// Expected: every output after the reset identical to the new chain, including the heart-rate
// events
// ("not enough beats" first, no interval across the reset) and the windows (the first window starts
// at the first sample after the reset); both are present.
// Verifies: SRS-031
TEST(Srs031Restart, HeartRatesAndWindowsAfterResetIgnoreTheHistory) {
  for (const int mains : {50, 60}) {
    SCOPED_TRACE(mains);
    const std::vector<float> history = sinus_qa::synthetic_ecg(kFs, 40, 25 * kFs + 100, mains);
    const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 180, 40 * kFs, mains);
    const Seen seen = check_history_then_ecg(history, ecg, mains);
    EXPECT_GE(seen.events, 20U);
    EXPECT_GE(seen.windows, 25U);
  }
}

// Case: reset while the heart rate is withheld as "no recent beat" and while a window is held.
// Input: 15 s of ECG at 75 bpm, then 12 s held at 2 mV (so "no recent beat" has been reported, and
// the held gate is in progress), a reset, then 30 s of the ECG at 75 bpm.
// Expected: every output after the reset identical to a newly configured chain: the status starts
// at "not enough beats" (no event carries "no recent beat" before the 3 s that follow a reliable
// detection), the windows are those of the ECG alone and are usable.
// Verifies: SRS-031
TEST(Srs031Restart, ResetWhileNoRecentBeatAndHeldInput) {
  std::vector<float> history = sinus_qa::synthetic_ecg(kFs, 75, 27 * kFs, 50);
  std::fill(history.begin() + 15 * kFs, history.end(), 2.0F);
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 30 * kFs, 50);
  const Seen seen = check_history_then_ecg(history, ecg, 50);
  EXPECT_GE(seen.events, 20U);
  EXPECT_GE(seen.windows, 15U);
}

// Case: the first window after a reset.
// Input: 30 s of ECG, a reset, 20 s of ECG, at 360 Hz.
// Expected: the first window after the reset has first sample 0, last sample 3599 and is reported
// at sample 3779 of the new stream; the next starts at 360.
// Verifies: SRS-031
TEST(Srs031Restart, WindowsRestartFromTheReset) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(kFs, 75, 50 * kFs, 50);
  Chain chain;
  ASSERT_EQ(chain.configure(Config{static_cast<double>(kFs), 50}), Status::kOk);
  SampleOutput out;
  for (std::size_t i = 0; i < 30 * kFs; ++i) {
    ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
  }
  chain.reset();
  std::vector<std::uint64_t> first;
  for (std::size_t i = 0; i < 20 * kFs; ++i) {
    ASSERT_EQ(chain.process(ecg[30 * kFs + i], out), Status::kOk);
    if (out.has_window) {
      first.push_back(out.window.first_sample);
      if (first.size() == 1) {
        EXPECT_EQ(out.window.last_sample, 3599U);
        EXPECT_EQ(out.window.reported_at, 3779U);
        EXPECT_EQ(i, 3779U);
      }
    }
  }
  ASSERT_GE(first.size(), 2U);
  EXPECT_EQ(first[0], 0U);
  EXPECT_EQ(first[1], 360U);
}

}  // namespace
