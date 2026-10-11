// Requirement tests of SRS-021: delay of streaming detection in the real-time library.
// The delay of a detection is reported_at - index, in samples (architecture-m2.md 13.4).
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <vector>

#include "chain_run.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::DetectionPath;
using sinus::dsp::Mark;
using sinus_qa::Det;

// Bounds of architecture-m2.md 13.4, in samples, at the two rates of the verification.
struct Bounds {
  int fs;
  std::uint64_t learning;  // L: first initialisation reports at L - 1
  std::uint64_t normal;    // N + P + D + 2
  std::uint64_t relearn;   // L + N + D
  std::uint64_t maximum;   // G + N + D + 1 - R, the documented maximum (about 8 s)
};
constexpr Bounds kBounds[] = {{360, 720, 103, 787, 2876}, {250, 500, 73, 547, 1998}};

constexpr const char* kEvents[] = {"artefact", "small-beat", "held", "rate-change"};

std::uint64_t delay(const Det& d) { return d.reported_at - d.index; }

// Case: the delay of a regular rhythm after the start-up period, noise-free.
// Input: synthetic ECG of 60 s at 360 and 250 Hz, 30, 40, 60, 75, 120, 180 and 200 bpm (bounds
// included), mains setting 50 and 60, one sample at a time.
// Expected: every detection with an index after the first 2 s is reported at most 0.35 s after
// its index (floor(0.35 fs) = 126 and 87 samples), and at most N + P + D + 2 samples (103 and 73)
// on the normal path; they all have path normal.
// Verifies: SRS-021
TEST(Srs021Delay, RegularRhythmAfterStartUpIsWithin035Seconds) {
  for (const Bounds& b : kBounds) {
    const auto limit = static_cast<std::uint64_t>((35 * b.fs) / 100);
    for (const int hr : {30, 40, 60, 75, 120, 180, 200}) {
      for (const int mains : {50, 60}) {
        SCOPED_TRACE(testing::Message() << b.fs << " Hz " << hr << " bpm mains " << mains);
        const std::size_t n = 60 * static_cast<std::size_t>(b.fs);
        const std::vector<Det> dets =
            sinus_qa::run_chain(sinus_qa::synthetic_ecg(b.fs, hr, n, 0), b.fs, mains);
        std::size_t after = 0;
        for (const Det& d : dets) {
          if (d.index >= b.learning) {
            ++after;
            EXPECT_LE(delay(d), limit) << "index " << d.index;
            EXPECT_LE(delay(d), b.normal) << "index " << d.index;
            EXPECT_EQ(d.path, DetectionPath::kNormal) << "index " << d.index;
          }
        }
        EXPECT_GE(after, 10U);
      }
    }
  }
}

// Case: the same input with the interference of SRS-010 still meets the documented maximum.
// Input: 60 s at 360 and 250 Hz, 30, 75 and 200 bpm, baseline wander and mains at 50 Hz and 60 Hz
// (matching setting).
// Expected: every delay at most G + N + D + 1 - R samples (2876 and 1998).
// Verifies: SRS-021
TEST(Srs021Delay, InterferedRhythmMeetsTheDocumentedMaximum) {
  for (const Bounds& b : kBounds) {
    for (const int hr : {30, 75, 200}) {
      for (const int mains : {50, 60}) {
        SCOPED_TRACE(testing::Message() << b.fs << " Hz " << hr << " bpm mains " << mains);
        const std::size_t n = 60 * static_cast<std::size_t>(b.fs);
        const std::vector<Det> dets =
            sinus_qa::run_chain(sinus_qa::synthetic_ecg(b.fs, hr, n, mains), b.fs, mains);
        EXPECT_GE(dets.size(), 10U);
        for (const Det& d : dets) {
          EXPECT_LE(delay(d), b.maximum) << "index " << d.index;
        }
      }
    }
  }
}

// Case: the detections of the first learning period of every event input.
// Input: the four event inputs of architecture-m2.md 13.9 at 360 and 250 Hz (mains setting 50).
// Expected: there are detections in the first 2 s; each is reported at sample L - 1 (719, 499)
// with path learning, so its delay is at most L - 1 and at most the documented maximum.
// Verifies: SRS-021
TEST(Srs021Delay, DetectionsOfTheLearningPeriodAreWithinTheMaximum) {
  for (const Bounds& b : kBounds) {
    for (const char* event : kEvents) {
      SCOPED_TRACE(testing::Message() << b.fs << " Hz " << event);
      const std::vector<Det> dets =
          sinus_qa::run_chain(sinus_qa::event_ecg(b.fs, event, nullptr), b.fs, 50);
      std::size_t first = 0;
      for (const Det& d : dets) {
        if (d.index < b.learning) {
          ++first;
          EXPECT_EQ(d.reported_at, b.learning - 1);
          EXPECT_EQ(d.path, DetectionPath::kLearning);
          EXPECT_LE(delay(d), b.learning - 1);
          EXPECT_LE(delay(d), b.maximum);
        }
      }
      EXPECT_GE(first, 1U);
    }
  }
}

// Case: a beat found by search-back.
// Input: the event input small-beat (one beat of 0.4 times the amplitude) at 360 and 250 Hz.
// Expected: at least one detection has path search-back; every delay of the input is at most the
// documented maximum.
// Verifies: SRS-021
TEST(Srs021Delay, SearchBackDetectionIsWithinTheMaximum) {
  for (const Bounds& b : kBounds) {
    SCOPED_TRACE(b.fs);
    const std::vector<Det> dets =
        sinus_qa::run_chain(sinus_qa::event_ecg(b.fs, "small-beat", nullptr), b.fs, 50);
    std::size_t found = 0;
    for (const Det& d : dets) {
      EXPECT_LE(delay(d), b.maximum) << "index " << d.index;
      if (d.path == DetectionPath::kSearchBack) {
        ++found;
        EXPECT_GT(delay(d), b.normal) << "search-back is later than the normal rules";
      }
    }
    EXPECT_GE(found, 1U);
  }
}

// Case: beats found after detection has learned its levels again.
// Input: the event input artefact (one beat 20 times larger) at 360 and 250 Hz.
// Expected: detection learns again: at least one detection with path learning is reported after
// sample L - 1, at most L + N + D samples (787, 547) after its index; all delays (search-back
// ones included) are at most the documented maximum, and the detections of the normal path are
// at most N + P + D + 2 samples late.
// Verifies: SRS-021
TEST(Srs021Delay, DetectionsAfterRelearningAreWithinTheMaximum) {
  for (const Bounds& b : kBounds) {
    SCOPED_TRACE(b.fs);
    const std::vector<Det> dets =
        sinus_qa::run_chain(sinus_qa::event_ecg(b.fs, "artefact", nullptr), b.fs, 50);
    std::size_t relearned = 0;
    for (const Det& d : dets) {
      EXPECT_LE(delay(d), b.maximum) << "index " << d.index;
      if (d.path == DetectionPath::kLearning && d.reported_at > b.learning - 1) {
        ++relearned;
        EXPECT_LE(delay(d), b.relearn) << "index " << d.index;
      }
      if (d.path == DetectionPath::kNormal) {
        EXPECT_LE(delay(d), b.normal) << "index " << d.index;
      }
    }
    EXPECT_GE(relearned, 1U);
  }
}

// Case: every event input, every delay.
// Input: the four event inputs at 360 and 250 Hz.
// Expected: every delay is at most the documented maximum (2876 samples at 360 Hz, 1998 at
// 250 Hz, 7.989 s and 7.992 s), and in particular below 8.01 s.
// Verifies: SRS-021
TEST(Srs021Delay, EveryDelayOfTheEventInputsIsAtMostTheDocumentedMaximum) {
  for (const Bounds& b : kBounds) {
    for (const char* event : kEvents) {
      SCOPED_TRACE(testing::Message() << b.fs << " Hz " << event);
      const std::vector<Det> dets =
          sinus_qa::run_chain(sinus_qa::event_ecg(b.fs, event, nullptr), b.fs, 50);
      EXPECT_GE(dets.size(), 5U);
      for (const Det& d : dets) {
        EXPECT_LE(delay(d), b.maximum) << "index " << d.index;
        EXPECT_LT(static_cast<double>(delay(d)) / b.fs, 8.01) << "index " << d.index;
      }
    }
  }
}

// Case: a long stretch without a beat, then the ECG (re-learning with an empty stretch).
// Input: ECG at 75 bpm, 40 s, with the samples from 5 s to 25 s set to 0 mV, at 360 and 250 Hz.
// Expected: every delay at most the documented maximum; the beats after 25 s are detected (at
// least 10 detections after sample 25 s).
// Verifies: SRS-021
TEST(Srs021Delay, DelayAfterALongFlatStretchIsWithinTheMaximum) {
  for (const Bounds& b : kBounds) {
    SCOPED_TRACE(b.fs);
    const auto fs = static_cast<std::size_t>(b.fs);
    std::vector<float> ecg = sinus_qa::synthetic_ecg(b.fs, 75, 40 * fs, 50);
    for (std::size_t i = 5 * fs; i < 25 * fs; ++i) {
      ecg[i] = 0.0F;
    }
    const std::vector<Det> dets = sinus_qa::run_chain(ecg, b.fs, 50);
    std::size_t late = 0;
    for (const Det& d : dets) {
      EXPECT_LE(delay(d), b.maximum) << "index " << d.index;
      if (d.index >= 25 * fs) {
        ++late;
      }
    }
    EXPECT_GE(late, 10U);
  }
}

}  // namespace
