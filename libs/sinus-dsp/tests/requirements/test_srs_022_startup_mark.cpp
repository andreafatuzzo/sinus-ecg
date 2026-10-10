// Requirement tests of SRS-022: start-up mark of detections, library part.
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <set>
#include <vector>

#include "chain_run.hpp"
#include "sinus/dsp/chain.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::DetectionPath;
using sinus::dsp::Mark;
using sinus::dsp::Status;
using sinus_qa::Det;

constexpr int kRates[] = {360, 250};

// Marks of a stream whose only learning stretch is the first 2 s: start-up iff index <= L - 1.
// Returns the number of start-up detections.
std::size_t expect_first_stretch_marks(const std::vector<Det>& dets, int fs) {
  const std::uint64_t l = sinus_qa::learning_samples(fs);
  std::size_t startup = 0;
  for (const Det& d : dets) {
    if (d.index <= l - 1) {
      ++startup;
      EXPECT_EQ(d.mark, Mark::kStartUp) << "index " << d.index;
    } else {
      EXPECT_EQ(d.mark, Mark::kReliable) << "index " << d.index;
    }
  }
  return startup;
}

// Case: the marks of regular rhythms.
// Input: the synthetic ECGs of SRS-006, 60 s at 360 and 250 Hz, 40, 75 and 180 bpm, clean and with
// the interference of SRS-010 (50 Hz, 60 Hz with the matching setting).
// Expected: each detection with an index in the first 2 s (index <= 719 at 360 Hz, <= 499 at
// 250 Hz) is marked start-up, all others reliable; there is at least one start-up detection;
// the detections found by the learning are reported at sample L - 1 (719, 499); and the detections
// are those of SRS-006 (one per beat, no other).
// Verifies: SRS-022
TEST(Srs022StartUpMark, FirstTwoSecondsAreStartUpAndTheRestReliable) {
  for (const int fs : kRates) {
    const std::uint64_t l = sinus_qa::learning_samples(fs);
    for (const int hr : {40, 75, 180}) {
      for (const int interference : {0, 50, 60}) {
        SCOPED_TRACE(testing::Message()
                     << fs << " Hz " << hr << " bpm interference " << interference);
        const std::size_t n = 60 * static_cast<std::size_t>(fs);
        const int setting = interference == 0 ? 50 : interference;
        const std::vector<Det> dets =
            sinus_qa::run_chain(sinus_qa::synthetic_ecg(fs, hr, n, interference), fs, setting);
        EXPECT_GE(expect_first_stretch_marks(dets, fs), 1U);
        std::size_t at_learning = 0;
        for (const Det& d : dets) {
          // Found by the learning itself (reported at L - 1), or, for an index just before 2 s
          // whose peak lies after it, later by the normal rules (architecture-m2.md 13.3).
          if (d.index < l) {
            EXPECT_GE(d.reported_at, l - 1);
            if (d.reported_at == l - 1) {
              EXPECT_EQ(d.path, DetectionPath::kLearning);
              ++at_learning;
            }
          }
        }
        EXPECT_GE(at_learning, 1U);
        sinus_qa::expect_one_per_beat(dets, sinus_qa::regular_r_positions(fs, hr, n), n, fs);
      }
    }
  }
}

// Case: the boundary of the 2 s, at many positions of the beats.
// Input: clean ECGs of 12 s at 360 and 250 Hz, every heart rate from 30 to 200 bpm in steps of
// 5 (the first detections fall at different distances from 2 s).
// Expected: start-up iff the index is at most L - 1; the last start-up detection and the first
// reliable one are either side of the boundary.
// Verifies: SRS-022
TEST(Srs022StartUpMark, MarkFollowsTheIndexAtTheBoundaryOfTwoSeconds) {
  for (const int fs : kRates) {
    const std::uint64_t l = sinus_qa::learning_samples(fs);
    std::set<std::uint64_t> distances;
    for (int hr = 30; hr <= 200; hr += 5) {
      SCOPED_TRACE(testing::Message() << fs << " Hz " << hr << " bpm");
      const std::size_t n = 12 * static_cast<std::size_t>(fs);
      const std::vector<Det> dets =
          sinus_qa::run_chain(sinus_qa::synthetic_ecg(fs, hr, n, 0), fs, 50);
      EXPECT_GE(expect_first_stretch_marks(dets, fs), 1U);
      for (const Det& d : dets) {
        if (d.index >= l && d.index < l + 40) {
          distances.insert(d.index - l);
        }
        if (d.index < l && d.index + 40 >= l) {
          distances.insert(l - d.index + 1000);
        }
      }
    }
    // The sweep reaches detections on both sides of the boundary within 40 samples.
    EXPECT_GE(distances.size(), 4U);
  }
}

// Case: after a reset, the same holds from the reset.
// Input: the interfered ECG at 75 bpm, 40 s: processed for 7.3 s (and for 20 s, and for 0 samples),
// reset, the ECG continuing; the stream time base restarts at the reset.
// Expected: with indices counted from the reset, detections with index <= L - 1 are start-up, all
// others reliable, there is at least one start-up detection, and the detections equal those of a
// newly configured chain given the samples after the reset.
// Verifies: SRS-022
TEST(Srs022StartUpMark, MarksAfterAResetCountFromTheReset) {
  for (const int fs : kRates) {
    for (const double seconds : {0.0, 7.3, 20.0}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz reset at " << seconds << " s");
      const auto reset_at = static_cast<std::size_t>(seconds * fs);
      const std::vector<float> ecg = sinus_qa::synthetic_ecg(fs, 75, 50 * fs, 50);
      Chain chain;
      ASSERT_EQ(chain.configure(Config{static_cast<double>(fs), 50}), Status::kOk);
      (void)sinus_qa::feed(chain, std::vector<float>(ecg.begin(), ecg.begin() + reset_at));
      chain.reset();
      const std::vector<Det> after = sinus_qa::feed(chain, ecg, reset_at);
      EXPECT_GE(expect_first_stretch_marks(after, fs), 1U);
      const std::vector<Det> fresh = sinus_qa::run_chain(
          std::vector<float>(ecg.begin() + static_cast<std::ptrdiff_t>(reset_at), ecg.end()), fs,
          50);
      EXPECT_TRUE(after == fresh);
      EXPECT_GE(after.size(), 30U);
    }
  }
}

// Case: the 2 s from which detection learns its levels again.
// Input: the event input artefact (architecture-m2.md 13.9: a beat 20 times larger at 10.1 s) at
// 360 and 250 Hz.
// Expected: the large beat is detected; beats are then missed; detection learns again (a
// detection with path learning is reported after sample L - 1, at the re-learning sample i);
// at least one detection has its index in [i - L + 1, i]; every detection with an index in
// [0, L - 1] or in [i - L + 1, i] is marked start-up and all others reliable.
// Verifies: SRS-022
TEST(Srs022StartUpMark, ArtefactRelearningStretchIsMarkedStartUp) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::uint64_t l = sinus_qa::learning_samples(fs);
    std::vector<sinus_qa::Beat> beats;
    const std::vector<float> ecg = sinus_qa::event_ecg(fs, "artefact", &beats);
    const std::vector<Det> dets = sinus_qa::run_chain(ecg, fs, 50);

    std::set<std::uint64_t> relearn;  // report samples of the learning detections after the first
    for (const Det& d : dets) {
      if (d.path == DetectionPath::kLearning && d.reported_at > l - 1) {
        relearn.insert(d.reported_at);
      }
    }
    ASSERT_FALSE(relearn.empty()) << "detection did not learn its levels again";
    const std::uint64_t first_relearn = *relearn.begin();

    // The large beat (beat 12, R at 10.1 s) is detected, and beats after it are missed until the
    // re-learning.
    const std::int64_t big = (beats[12].t_ms * fs + 500) / 1000;
    bool big_found = false;
    for (const Det& d : dets) {
      if (std::abs(static_cast<std::int64_t>(d.index) - big) <= sinus_qa::within_150_ms(fs)) {
        big_found = true;
      }
    }
    EXPECT_TRUE(big_found);
    std::size_t missed = 0;
    for (std::size_t k = 13; k < beats.size(); ++k) {
      const std::int64_t r = (beats[k].t_ms * fs + 500) / 1000;
      if (r + static_cast<std::int64_t>(l) >= static_cast<std::int64_t>(first_relearn)) {
        break;
      }
      bool found = false;
      for (const Det& d : dets) {
        found = found ||
                std::abs(static_cast<std::int64_t>(d.index) - r) <= sinus_qa::within_150_ms(fs);
      }
      missed += found ? 0 : 1;
    }
    EXPECT_GE(missed, 1U) << "no beat was missed before the re-learning";

    std::size_t in_stretch = 0;
    for (const Det& d : dets) {
      bool expected_startup = d.index <= l - 1;
      bool in_relearn = false;
      for (const std::uint64_t i : relearn) {
        if (d.index + l >= i + 1 && d.index <= i) {
          in_relearn = true;
        }
      }
      expected_startup = expected_startup || in_relearn;
      in_stretch += in_relearn ? 1 : 0;
      EXPECT_EQ(d.mark, expected_startup ? Mark::kStartUp : Mark::kReliable)
          << "index " << d.index << " reported at " << d.reported_at;
    }
    EXPECT_GE(in_stretch, 1U);
    // After the stretch the stream is marked reliable, and the marks are not revised.
    EXPECT_EQ(dets.back().mark, Mark::kReliable);
  }
}

// Case: the marks and detections do not depend on what was processed before a reset.
// Input: the artefact and small-beat inputs, and the regular 75 bpm ECG, at 360 and 250 Hz, run
// twice, from a newly configured chain and from a chain that was reset after other samples.
// Expected: identical detections (index, report sample, mark, path) in both runs.
// Verifies: SRS-022
TEST(Srs022StartUpMark, MarksAreReproducibleAfterAReset) {
  for (const int fs : kRates) {
    for (const char* event : {"artefact", "small-beat"}) {
      SCOPED_TRACE(testing::Message() << fs << " " << event);
      const std::vector<float> ecg = sinus_qa::event_ecg(fs, event, nullptr);
      const std::vector<Det> first = sinus_qa::run_chain(ecg, fs, 50);
      Chain chain;
      ASSERT_EQ(chain.configure(Config{static_cast<double>(fs), 50}), Status::kOk);
      (void)sinus_qa::feed(chain, sinus_qa::synthetic_ecg(fs, 120, 9 * fs, 0));
      chain.reset();
      const std::vector<Det> second = sinus_qa::feed(chain, ecg);
      EXPECT_TRUE(first == second);
      EXPECT_GE(first.size(), 40U);
    }
  }
}

}  // namespace
