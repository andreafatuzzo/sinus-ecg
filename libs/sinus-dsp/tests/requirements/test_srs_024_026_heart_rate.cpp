// Requirement tests of SRS-024, SRS-025 and SRS-026: heart rate from detections marked reliable,
// real-time library part (HeartRateTracker and the heart-rate events of the Chain).
// Each test states the part of the requirement it covers, its inputs and its expected result.
//
// The sequences of detections are built here from the numbers of the SRS: a regular rhythm
// between 30 and 200 bpm, positions rounded to the sample, each detection given to the tracker at
// the sample of its index (the verification of SRS-026), one call per sample from sample 0.

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "chain_run.hpp"
#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/heart_rate.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::HeartRateStatus;
using sinus::dsp::HeartRateStep;
using sinus::dsp::HeartRateTracker;
using sinus::dsp::Mark;
using sinus::dsp::ReportedDetection;
using sinus::dsp::Status;

constexpr int kRates[] = {360, 250};
constexpr int kRegularRates[] = {30, 40, 75, 180, 200};
constexpr std::int64_t kStart = 100;

constexpr HeartRateStatus kValid = HeartRateStatus::kValid;
constexpr HeartRateStatus kNotEnough = HeartRateStatus::kNotEnoughBeats;
constexpr HeartRateStatus kNoRecent = HeartRateStatus::kNoRecentBeat;
constexpr HeartRateStatus kOutOfRange = HeartRateStatus::kOutOfRange;

struct Ev {
  std::uint64_t sample;
  std::uint64_t beat_index;
  bool has_beat;
  HeartRateStatus status;
  float bpm;
};

bool same(const Ev& a, const Ev& b) {
  return a.sample == b.sample && a.has_beat == b.has_beat &&
         (!a.has_beat || a.beat_index == b.beat_index) && a.status == b.status &&
         sinus_qa::same_bits(a.bpm, b.bpm);
}

bool same(const std::vector<Ev>& a, const std::vector<Ev>& b) {
  return a.size() == b.size() && std::equal(a.begin(), a.end(), b.begin(),
                                            [](const Ev& x, const Ev& y) { return same(x, y); });
}

// `count` detections of a regular rhythm of `rate` bpm from `start`: start + floor(k 60 fs / rate
// + 1/2), computed on integers.
std::vector<std::int64_t> rhythm(int rate, int fs, int count, std::int64_t start = kStart) {
  std::vector<std::int64_t> idx;
  for (int k = 0; k < count; ++k) {
    idx.push_back(start + (static_cast<std::int64_t>(k) * 120 * fs + rate) / (2 * rate));
  }
  return idx;
}

std::int64_t three_s(int fs) { return (3000 * static_cast<std::int64_t>(fs) + 999) / 1000; }
std::int64_t samples_200_ms(int fs) { return (200 * static_cast<std::int64_t>(fs) + 999) / 1000; }

std::vector<std::int64_t> sorted_with(std::vector<std::int64_t> idx, std::int64_t extra) {
  idx.push_back(extra);
  std::sort(idx.begin(), idx.end());
  return idx;
}

// Feed a configured tracker from sample 0 to last index + tail - 1, one call per sample, with the
// detections whose index is that sample. `startup` (same length as idx, or empty for all
// reliable) gives the marks. Checks the status and that every event is at the current sample.
std::vector<Ev> track(int fs, const std::vector<std::int64_t>& idx,
                      const std::vector<bool>& startup = {}, std::int64_t tail = 1) {
  HeartRateTracker tracker;
  EXPECT_EQ(tracker.configure(static_cast<double>(fs)), Status::kOk);
  std::vector<Ev> events;
  std::size_t next = 0;
  const std::int64_t n_samples = idx.back() + tail;
  for (std::int64_t n = 0; n < n_samples; ++n) {
    ReportedDetection rep[1];
    std::size_t count = 0;
    if (next < idx.size() && idx[next] == n) {
      const bool su = !startup.empty() && startup[next];
      rep[0] =
          ReportedDetection{static_cast<std::uint64_t>(n), su ? Mark::kStartUp : Mark::kReliable};
      count = 1;
      ++next;
    }
    HeartRateStep step;
    const Status st = tracker.step(count > 0 ? rep : nullptr, count, step);
    EXPECT_EQ(st, Status::kOk) << "sample " << n;
    if (st != Status::kOk) {
      break;
    }
    EXPECT_LE(step.count, step.events.size());
    for (std::size_t j = 0; j < step.count && j < step.events.size(); ++j) {
      const auto& e = step.events[j];
      EXPECT_EQ(e.sample, static_cast<std::uint64_t>(n));
      const bool with_rate = e.status == kValid || e.status == kOutOfRange;
      EXPECT_EQ(with_rate, !std::isnan(e.bpm)) << "sample " << n;
      events.push_back({e.sample, e.beat_index, e.has_beat, e.status, e.bpm});
    }
  }
  return events;
}

std::vector<Ev> at_detections(const std::vector<Ev>& events) {
  std::vector<Ev> out;
  for (const Ev& e : events) {
    if (e.has_beat) {
      out.push_back(e);
    }
  }
  return out;
}

std::vector<Ev> without_detection(const std::vector<Ev>& events) {
  std::vector<Ev> out;
  for (const Ev& e : events) {
    if (!e.has_beat) {
      out.push_back(e);
    }
  }
  return out;
}

std::vector<double> valid_rates(const std::vector<Ev>& events) {
  std::vector<double> out;
  for (const Ev& e : events) {
    if (e.status == kValid) {
      out.push_back(static_cast<double>(e.bpm));
    }
  }
  return out;
}

::testing::AssertionResult all_within(const std::vector<double>& rates, double rate, double tol) {
  for (const double r : rates) {
    if (!(std::fabs(r - rate) <= tol)) {
      return ::testing::AssertionFailure()
             << "rate " << r << " differs from " << rate << " by more than " << tol;
    }
  }
  return ::testing::AssertionSuccess();
}

std::vector<HeartRateStatus> statuses(const std::vector<Ev>& events, std::size_t from,
                                      std::size_t to) {
  std::vector<HeartRateStatus> out;
  for (std::size_t i = from; i < to && i < events.size(); ++i) {
    out.push_back(events[i].status);
  }
  return out;
}

// ---------------------------------------------------------------------------------- SRS-024

// Case: regular rhythms at 30, 40, 75, 180 and 200 bpm (rounded to the sample), 40 detections,
// at 360 and 250 Hz.
// Expected: valid heart rates exist, and every valid heart rate is within 2 bpm of the true rate.
// Verifies: SRS-024
TEST(Srs024HeartRate, RegularRhythmValidRatesWithinTwoBpm) {
  for (const int fs : kRates) {
    for (const int rate : kRegularRates) {
      SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm");
      const std::vector<double> rates = valid_rates(track(fs, rhythm(rate, fs, 40)));
      ASSERT_FALSE(rates.empty());
      EXPECT_TRUE(all_within(rates, rate, 2.0));
    }
  }
}

// Case: regular rhythms across the range, bounds included (30, 31, 45, 60, 100, 120, 150, 190,
// 199, 200 bpm), 30 detections, both sampling frequencies.
// Expected: one event per detection; from the fifth detection the status is valid at every
// detection, each within 2 bpm of the true rate.
// Verifies: SRS-024
TEST(Srs024HeartRate, InRangeRhythmIsValidFromTheFifthDetection) {
  for (const int fs : kRates) {
    for (const int rate : {30, 31, 45, 60, 100, 120, 150, 190, 199, 200}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm");
      const std::vector<Ev> events = at_detections(track(fs, rhythm(rate, fs, 30)));
      ASSERT_EQ(events.size(), 30U);
      for (std::size_t i = 4; i < events.size(); ++i) {
        EXPECT_EQ(events[i].status, kValid) << "detection " << i;
        EXPECT_LE(std::fabs(static_cast<double>(events[i].bpm) - rate), 2.0) << "detection " << i;
      }
    }
  }
}

// Case: 20 detections at 75 bpm.
// Expected: a heart rate (or its withholding) at each detection marked reliable: one event per
// detection, at the sample of the detection, naming its index, in order; no other event;
// withheld events carry no rate (NaN), valid and out-of-range ones carry a rate.
// Verifies: SRS-024
TEST(Srs024HeartRate, OneEventPerReliableDetectionAtItsSample) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<std::int64_t> idx = rhythm(75, fs, 20);
    const std::vector<Ev> events = track(fs, idx);
    ASSERT_EQ(events.size(), idx.size());
    for (std::size_t i = 0; i < idx.size(); ++i) {
      EXPECT_TRUE(events[i].has_beat);
      EXPECT_EQ(events[i].beat_index, static_cast<std::uint64_t>(idx[i]));
      EXPECT_EQ(events[i].sample, static_cast<std::uint64_t>(idx[i]));
    }
  }
}

// Case: a change from one rhythm to another: 12 detections of the old rate, then the new rate
// from the last one, 40 to 180, 180 to 40, 75 to 120 and 120 to 75 bpm.
// Expected: the old rate holds before the change; every valid heart rate from the fifth interval
// of the new rhythm (its fifth detection) onwards is within 2 bpm of the new rate, and it is
// valid at each of those detections.
// Verifies: SRS-024
TEST(Srs024HeartRate, HeartRateFollowsAChangeOfRhythm) {
  const int changes[4][2] = {{40, 180}, {180, 40}, {75, 120}, {120, 75}};
  for (const int fs : kRates) {
    for (const auto& change : changes) {
      const int old_rate = change[0];
      const int new_rate = change[1];
      SCOPED_TRACE(testing::Message() << fs << " Hz " << old_rate << " to " << new_rate);
      std::vector<std::int64_t> idx = rhythm(old_rate, fs, 12);
      const std::size_t first_new = idx.size();
      const std::vector<std::int64_t> second = rhythm(new_rate, fs, 16, idx.back());
      idx.insert(idx.end(), second.begin() + 1, second.end());
      const std::vector<Ev> events = at_detections(track(fs, idx));
      ASSERT_EQ(events.size(), idx.size());
      for (std::size_t i = 4; i < first_new; ++i) {
        EXPECT_EQ(events[i].status, kValid);
        EXPECT_LE(std::fabs(static_cast<double>(events[i].bpm) - old_rate), 2.0) << i;
      }
      for (std::size_t i = first_new + 4; i < events.size(); ++i) {
        EXPECT_EQ(events[i].status, kValid) << "detection " << i;
        if (events[i].status == kValid) {
          EXPECT_LE(std::fabs(static_cast<double>(events[i].bpm) - new_rate), 2.0)
              << "detection " << i;
        }
      }
      EXPECT_EQ(events.back().status, kValid);
    }
  }
}

// Case: 1, 2 or 5 detections marked start-up at irregular positions before 20 reliable detections
// at 40, 75 and 180 bpm.
// Expected: the same events (sample, index, status, rate bit for bit) as the sequence of the
// reliable detections alone; no event names a start-up detection.
// Verifies: SRS-024
TEST(Srs024HeartRate, StartUpDetectionsAreLeftOut) {
  for (const int fs : kRates) {
    for (const int rate : {40, 75, 180}) {
      for (const int n_startup : {1, 2, 5}) {
        SCOPED_TRACE(testing::Message()
                     << fs << " Hz " << rate << " bpm " << n_startup << " start-up");
        const std::vector<std::int64_t> reliable = rhythm(rate, fs, 20, kStart + 700);
        std::vector<std::int64_t> full;
        for (int k = 0; k < n_startup; ++k) {
          full.push_back(kStart + 13 * (k + 1) * (k + 1) + 30 * k);
        }
        ASSERT_LT(full.back(), reliable.front());
        const std::vector<std::int64_t> startup_idx = full;
        full.insert(full.end(), reliable.begin(), reliable.end());
        std::vector<bool> marks(static_cast<std::size_t>(n_startup), true);
        marks.resize(full.size(), false);
        const std::vector<Ev> with_startup = track(fs, full, marks);
        EXPECT_TRUE(same(with_startup, track(fs, reliable)));
        for (const Ev& e : with_startup) {
          for (const std::int64_t s : startup_idx) {
            EXPECT_FALSE(e.has_beat && e.beat_index == static_cast<std::uint64_t>(s));
          }
        }
      }
    }
  }
}

// Case: a start-up detection before 12 reliable detections at 75 bpm.
// Expected: no interval spans the start-up detection: "not enough beats" at the first four
// reliable detections, the first valid heart rate at the fifth (four reliable intervals).
// Verifies: SRS-024
TEST(Srs024HeartRate, NoIntervalSpansAStartUpDetection) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    std::vector<std::int64_t> idx{kStart};
    const std::vector<std::int64_t> reliable = rhythm(75, fs, 12, kStart + 400);
    idx.insert(idx.end(), reliable.begin(), reliable.end());
    std::vector<bool> marks(idx.size(), false);
    marks[0] = true;
    const std::vector<Ev> events = at_detections(track(fs, idx, marks));
    ASSERT_EQ(events.size(), 12U);
    EXPECT_EQ(statuses(events, 0, 4), std::vector<HeartRateStatus>(4, kNotEnough));
    EXPECT_EQ(events[4].status, kValid);
  }
}

// Case: four detections marked start-up only, then 10 s of samples.
// Expected: no event at all (no heart rate at a start-up detection, no reliable detection to age).
// Verifies: SRS-024
TEST(Srs024HeartRate, OnlyStartUpDetectionsGiveNoEvent) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<std::int64_t> idx = rhythm(75, fs, 4);
    EXPECT_TRUE(track(fs, idx, std::vector<bool>(4, true), 10 * fs).empty());
  }
}

// Case: the interface of the tracker.
// Expected: before configure every call returns kNotConfigured; a count above 12, a null pointer
// with a count, an index above the current sample and an index not increasing return
// kInvalidArgument and change nothing (the next valid calls give the same events as on a tracker
// that never saw the call).
// Verifies: SRS-024
TEST(Srs024HeartRate, PreconditionsOfTheTracker) {
  HeartRateTracker unconfigured;
  HeartRateStep step;
  EXPECT_EQ(unconfigured.step(nullptr, 0, step), Status::kNotConfigured);
  const ReportedDetection one{0, Mark::kReliable};
  EXPECT_EQ(unconfigured.step(&one, 1, step), Status::kNotConfigured);

  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<std::int64_t> idx = rhythm(75, fs, 10);
    const std::vector<Ev> reference = track(fs, idx);
    // The same stream with a rejected call before every detection.
    HeartRateTracker tracker;
    ASSERT_EQ(tracker.configure(static_cast<double>(fs)), Status::kOk);
    std::vector<Ev> events;
    std::size_t next = 0;
    std::vector<ReportedDetection> too_many(13, ReportedDetection{0, Mark::kReliable});
    for (std::int64_t n = 0; n <= idx.back(); ++n) {
      HeartRateStep rejected;
      EXPECT_EQ(tracker.step(too_many.data(), 13, rejected), Status::kInvalidArgument);
      EXPECT_EQ(rejected.count, 0U);
      EXPECT_EQ(tracker.step(nullptr, 1, rejected), Status::kInvalidArgument);
      const ReportedDetection future{static_cast<std::uint64_t>(n) + 1, Mark::kReliable};
      EXPECT_EQ(tracker.step(&future, 1, rejected), Status::kInvalidArgument);
      EXPECT_EQ(rejected.count, 0U);
      if (next > 0) {
        const ReportedDetection back{static_cast<std::uint64_t>(idx[next - 1]), Mark::kReliable};
        EXPECT_EQ(tracker.step(&back, 1, rejected), Status::kInvalidArgument);
        EXPECT_EQ(rejected.count, 0U);
      }
      ReportedDetection rep{0, Mark::kReliable};
      std::size_t count = 0;
      if (next < idx.size() && idx[next] == n) {
        rep.index = static_cast<std::uint64_t>(n);
        count = 1;
        ++next;
      }
      HeartRateStep ok;
      ASSERT_EQ(tracker.step(count > 0 ? &rep : nullptr, count, ok), Status::kOk);
      for (std::size_t j = 0; j < ok.count; ++j) {
        const auto& e = ok.events[j];
        events.push_back({e.sample, e.beat_index, e.has_beat, e.status, e.bpm});
      }
    }
    EXPECT_TRUE(same(events, reference));
  }
}

// Case: 12 detections reported at one sample, in increasing order, after a stream of 8 detections.
// Expected: accepted (kOk), at most 12 events at the sample.
// Verifies: SRS-024
TEST(Srs024HeartRate, TwelveDetectionsAtOneSampleAreAccepted) {
  HeartRateTracker tracker;
  ASSERT_EQ(tracker.configure(360.0), Status::kOk);
  HeartRateStep step;
  std::vector<ReportedDetection> twelve;
  for (std::uint64_t k = 0; k < 12; ++k) {
    twelve.push_back({1000 + 80 * k, Mark::kReliable});
  }
  for (std::uint64_t n = 0; n < 1000 + 80 * 11; ++n) {
    ASSERT_EQ(tracker.step(nullptr, 0, step), Status::kOk);
  }
  EXPECT_EQ(tracker.step(twelve.data(), 12, step), Status::kOk);
  EXPECT_LE(step.count, 12U);
}

// Case: a tracker reset after 12 detections at 75 bpm, then 12 more detections.
// Expected: the events after the reset are those of a newly configured tracker given the same
// detections (no interval spans the reset); "not enough beats" at the first four.
// Verifies: SRS-024
TEST(Srs024HeartRate, ResetStartsANewStream) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<std::int64_t> second = rhythm(75, fs, 12, 50);
    HeartRateTracker tracker;
    ASSERT_EQ(tracker.configure(static_cast<double>(fs)), Status::kOk);
    HeartRateStep step;
    const std::vector<std::int64_t> first = rhythm(75, fs, 12);
    std::size_t next = 0;
    for (std::int64_t n = 0; n <= first.back(); ++n) {
      ReportedDetection rep{static_cast<std::uint64_t>(n), Mark::kReliable};
      const bool has = next < first.size() && first[next] == n;
      next += has ? 1 : 0;
      ASSERT_EQ(tracker.step(has ? &rep : nullptr, has ? 1 : 0, step), Status::kOk);
    }
    tracker.reset();
    std::vector<Ev> events;
    next = 0;
    for (std::int64_t n = 0; n <= second.back(); ++n) {
      ReportedDetection rep{static_cast<std::uint64_t>(n), Mark::kReliable};
      const bool has = next < second.size() && second[next] == n;
      next += has ? 1 : 0;
      ASSERT_EQ(tracker.step(has ? &rep : nullptr, has ? 1 : 0, step), Status::kOk);
      for (std::size_t j = 0; j < step.count; ++j) {
        const auto& e = step.events[j];
        events.push_back({e.sample, e.beat_index, e.has_beat, e.status, e.bpm});
      }
    }
    EXPECT_TRUE(same(events, track(fs, second)));
    EXPECT_EQ(statuses(events, 0, 4), std::vector<HeartRateStatus>(4, kNotEnough));
    EXPECT_EQ(events[4].status, kValid);
  }
}

// ---------------------------------------------------------------------------------- SRS-025

// Case: a regular rhythm of 30 detections at 30, 40, 75, 180 and 200 bpm from which one detection
// is removed, at each position after the first valid heart rate (position 5 on) except the last.
// Expected: every valid heart rate within 5 bpm of the true rate; the heart rate is valid again
// at the end (at 30 bpm the missing detection leaves 4 s: "no recent beat" appears, SRS-026).
// Verifies: SRS-025
TEST(Srs025MissedOrExtraDetection, MissedDetectionWithinFiveBpm) {
  for (const int fs : kRates) {
    for (const int rate : kRegularRates) {
      const std::vector<std::int64_t> idx = rhythm(rate, fs, 30);
      for (std::size_t j = 5; j + 1 < idx.size(); ++j) {
        SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm, missing " << j);
        std::vector<std::int64_t> seq = idx;
        seq.erase(seq.begin() + static_cast<std::ptrdiff_t>(j));
        const std::vector<Ev> events = track(fs, seq);
        EXPECT_TRUE(all_within(valid_rates(events), rate, 5.0));
        if (rate == 30) {
          EXPECT_FALSE(without_detection(events).empty());
        } else {
          EXPECT_EQ(events.back().status, kValid);
        }
      }
    }
  }
}

// Case: one detection missing at any position from the second on (before the first valid heart
// rate), 24 detections at 30, 75, 180 and 200 bpm.
// Expected: every valid heart rate within 5 bpm of the true rate.
// Verifies: SRS-025
TEST(Srs025MissedOrExtraDetection, MissedEarlyDetectionWithinFiveBpm) {
  for (const int fs : kRates) {
    for (const int rate : {30, 75, 180, 200}) {
      const std::vector<std::int64_t> idx = rhythm(rate, fs, 24);
      for (std::size_t j = 1; j < 5; ++j) {
        SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm, missing " << j);
        std::vector<std::int64_t> seq = idx;
        seq.erase(seq.begin() + static_cast<std::ptrdiff_t>(j));
        EXPECT_TRUE(all_within(valid_rates(track(fs, seq)), rate, 5.0));
      }
    }
  }
}

// Case: one detection added in the middle of an interval, at each interval (rates whose interval
// is at least 400 ms: 30, 40 and 75 bpm), 30 detections.
// Expected: every valid heart rate within 5 bpm of the true rate; valid at the end.
// Verifies: SRS-025
TEST(Srs025MissedOrExtraDetection, ExtraDetectionInTheMiddleWithinFiveBpm) {
  for (const int fs : kRates) {
    for (const int rate : {30, 40, 75}) {
      const std::vector<std::int64_t> idx = rhythm(rate, fs, 30);
      for (std::size_t j = 0; j + 1 < idx.size(); ++j) {
        SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm, interval " << j);
        const std::int64_t extra = (idx[j] + idx[j + 1]) / 2;
        ASSERT_GE(extra - idx[j], samples_200_ms(fs));
        const std::vector<Ev> events = track(fs, sorted_with(idx, extra));
        EXPECT_TRUE(all_within(valid_rates(events), rate, 5.0));
        EXPECT_EQ(events.back().status, kValid);
      }
    }
  }
}

// Case: one detection added 200 ms after a detection, at each interval, at 30, 40 and 75 bpm.
// Expected: every valid heart rate within 5 bpm of the true rate; valid at the end.
// Verifies: SRS-025
TEST(Srs025MissedOrExtraDetection, ExtraDetection200MsAfterADetectionWithinFiveBpm) {
  for (const int fs : kRates) {
    for (const int rate : {30, 40, 75}) {
      const std::vector<std::int64_t> idx = rhythm(rate, fs, 30);
      for (std::size_t j = 0; j + 1 < idx.size(); ++j) {
        SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm, interval " << j);
        const std::vector<Ev> events = track(fs, sorted_with(idx, idx[j] + samples_200_ms(fs)));
        EXPECT_TRUE(all_within(valid_rates(events), rate, 5.0));
        EXPECT_EQ(events.back().status, kValid);
      }
    }
  }
}

// Case: one detection added 200 ms before a detection, at each interval after the first.
// Expected: every valid heart rate within 5 bpm of the true rate.
// Verifies: SRS-025
TEST(Srs025MissedOrExtraDetection, ExtraDetection200MsBeforeADetectionWithinFiveBpm) {
  for (const int fs : kRates) {
    for (const int rate : {30, 40, 75}) {
      const std::vector<std::int64_t> idx = rhythm(rate, fs, 30);
      for (std::size_t j = 1; j < idx.size(); ++j) {
        SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm, before " << j);
        const std::vector<Ev> events = track(fs, sorted_with(idx, idx[j] - samples_200_ms(fs)));
        EXPECT_TRUE(all_within(valid_rates(events), rate, 5.0));
      }
    }
  }
}

// ---------------------------------------------------------------------------------- SRS-026

// Case: 10 detections at 30, 75 and 200 bpm.
// Expected: "not enough beats" with no rate at the first four detections (0 to 3 intervals); the
// fifth detection (fourth interval) gives the first valid heart rate, at its own sample, and all
// later ones are valid.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, FirstValidRateComesWithTheFourthInterval) {
  for (const int fs : kRates) {
    for (const int rate : {30, 75, 200}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm");
      const std::vector<std::int64_t> idx = rhythm(rate, fs, 10);
      const std::vector<Ev> events = track(fs, idx);
      ASSERT_EQ(events.size(), 10U);
      EXPECT_EQ(statuses(events, 0, 4), std::vector<HeartRateStatus>(4, kNotEnough));
      for (std::size_t i = 0; i < 4; ++i) {
        EXPECT_TRUE(std::isnan(events[i].bpm));
      }
      EXPECT_EQ(events[4].status, kValid);
      EXPECT_EQ(events[4].sample, static_cast<std::uint64_t>(idx[4]));
      for (std::size_t i = 4; i < events.size(); ++i) {
        EXPECT_EQ(events[i].status, kValid);
      }
    }
  }
}

// Case: no detection at all, 20 s.
// Expected: no event ("not enough beats" from the start, and no beat to be recent).
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, NoEventWithoutDetections) {
  for (const int fs : kRates) {
    HeartRateTracker tracker;
    ASSERT_EQ(tracker.configure(static_cast<double>(fs)), Status::kOk);
    for (int n = 0; n < 20 * fs; ++n) {
      HeartRateStep step;
      ASSERT_EQ(tracker.step(nullptr, 0, step), Status::kOk);
      ASSERT_EQ(step.count, 0U) << "sample " << n;
    }
  }
}

// Case: 10 detections at 30 or 75 bpm, a stretch without detections of 3.1, 3.5 and 5 s, then 10
// more detections at the same rate.
// Expected: exactly one event without a detection, "no recent beat" with no rate, at the sample
// ceil(3 fs) after the last detection (1080 or 750 samples); the detections after the stretch are
// "no recent beat" for four intervals, the next valid heart rate comes with the fourth interval;
// valid heart rates within 2 bpm.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, StretchLongerThanThreeSecondsGivesNoRecentBeat) {
  for (const int fs : kRates) {
    for (const int rate : {30, 75}) {
      for (const double gap_s : {3.1, 3.5, 5.0}) {
        SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm gap " << gap_s);
        const std::vector<std::int64_t> first = rhythm(rate, fs, 10);
        const auto gap = static_cast<std::int64_t>(std::lround(gap_s * fs));
        const std::vector<std::int64_t> after = rhythm(rate, fs, 10, first.back() + gap);
        std::vector<std::int64_t> all = first;
        all.insert(all.end(), after.begin(), after.end());
        const std::vector<Ev> events = track(fs, all);
        const std::vector<Ev> none = without_detection(events);
        ASSERT_EQ(none.size(), 1U);
        EXPECT_EQ(none[0].sample, static_cast<std::uint64_t>(first.back() + three_s(fs)));
        EXPECT_EQ(none[0].status, kNoRecent);
        EXPECT_TRUE(std::isnan(none[0].bpm));
        for (std::size_t i = 1; i < events.size(); ++i) {
          EXPECT_LE(events[i - 1].sample, events[i].sample);
        }
        const std::vector<Ev> beats = at_detections(events);
        ASSERT_EQ(beats.size(), all.size());
        for (std::size_t i = 4; i < first.size(); ++i) {
          EXPECT_EQ(beats[i].status, kValid) << i;
        }
        for (std::size_t i = 0; i < 4; ++i) {
          EXPECT_EQ(beats[first.size() + i].status, kNoRecent) << i;
          EXPECT_TRUE(std::isnan(beats[first.size() + i].bpm));
        }
        for (std::size_t i = first.size() + 4; i < beats.size(); ++i) {
          EXPECT_EQ(beats[i].status, kValid) << i;
        }
        EXPECT_TRUE(all_within(valid_rates(events), rate, 2.0));
      }
    }
  }
}

// Case: a stretch without detections of 2.9 s, of ceil(3 fs) - 1 samples and of exactly ceil(3 fs)
// samples (the detection at that sample counts), at 30 and 75 bpm.
// Expected: no event without a detection, no "no recent beat" at all, and valid from the fifth
// detection.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, StretchShorterThanThreeSecondsGivesNone) {
  for (const int fs : kRates) {
    for (const int rate : {30, 75}) {
      const std::vector<std::int64_t> first = rhythm(rate, fs, 10);
      for (const std::int64_t gap :
           {static_cast<std::int64_t>(std::lround(2.9 * fs)), three_s(fs) - 1, three_s(fs)}) {
        SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm gap " << gap);
        const std::vector<std::int64_t> after = rhythm(rate, fs, 6, first.back() + gap);
        std::vector<std::int64_t> all = first;
        all.insert(all.end(), after.begin(), after.end());
        const std::vector<Ev> events = track(fs, all);
        EXPECT_TRUE(without_detection(events).empty());
        for (const Ev& e : events) {
          EXPECT_NE(e.status, kNoRecent);
        }
        for (std::size_t i = 4; i < events.size(); ++i) {
          EXPECT_EQ(events[i].status, kValid);
        }
      }
    }
  }
}

// Case: 8 detections at 75 bpm and then samples with no detection, to the sample ceil(3 fs) - 1
// after the last, and one more.
// Expected: the event "no recent beat" is at the first sample at least 3 s after the last
// detection (index + 1080 at 360 Hz, + 750 at 250 Hz) and not one sample before.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, NoRecentBeatAtTheFirstSampleThreeSecondsAfter) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<std::int64_t> idx = rhythm(75, fs, 8);
    const std::int64_t n3 = three_s(fs);
    EXPECT_EQ(n3, fs == 360 ? 1080 : 750);
    const std::vector<Ev> base = track(fs, idx);
    EXPECT_TRUE(same(track(fs, idx, {}, n3), base));  // ends one sample before
    const std::vector<Ev> with = track(fs, idx, {}, n3 + 1);
    ASSERT_EQ(with.size(), base.size() + 1);
    EXPECT_FALSE(with.back().has_beat);
    EXPECT_EQ(with.back().sample, static_cast<std::uint64_t>(idx.back() + n3));
    EXPECT_EQ(with.back().status, kNoRecent);
  }
}

// Case: only two detections, then a stretch of 3.4 s (the heart rate is withheld as "not enough
// beats"), then 8 detections; and the same after three detections and 4 s.
// Expected: "no recent beat" at the first sample at least 3 s after the last detection before the
// stretch; the detections after it are "no recent beat" for four intervals (both reasons apply),
// then valid.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, NoRecentBeatWhileNotEnoughBeats) {
  for (const int fs : kRates) {
    for (const int before : {2, 3}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz after " << before << " detections");
      const std::vector<std::int64_t> first = rhythm(75, fs, before);
      const std::int64_t gap =
          before == 2 ? std::lround(3.4 * fs) : 4 * static_cast<std::int64_t>(fs);
      const std::vector<std::int64_t> after = rhythm(75, fs, 8, first.back() + gap);
      std::vector<std::int64_t> all = first;
      all.insert(all.end(), after.begin(), after.end());
      const std::vector<Ev> events = track(fs, all);
      ASSERT_EQ(events.size(), all.size() + 1);
      const std::size_t b = static_cast<std::size_t>(before);
      for (std::size_t i = 0; i < b; ++i) {
        EXPECT_EQ(events[i].status, kNotEnough);
      }
      EXPECT_FALSE(events[b].has_beat);
      EXPECT_EQ(events[b].sample, static_cast<std::uint64_t>(first.back() + three_s(fs)));
      EXPECT_EQ(events[b].status, kNoRecent);
      for (std::size_t i = 0; i < after.size(); ++i) {
        const Ev& e = events[b + 1 + i];
        ASSERT_TRUE(e.has_beat);
        EXPECT_EQ(e.beat_index, static_cast<std::uint64_t>(after[i]));
        EXPECT_EQ(e.status, i < 4 ? kNoRecent : kValid) << i;
      }
    }
  }
}

// Case: 8 detections, 4 s, 3 detections, 4 s, 9 detections at 75 bpm.
// Expected: "no recent beat" is reported once, after the first 8 (the reason does not change at the
// second stretch, before four new intervals); the detections up to four intervals after the second
// stretch are "no recent beat", then valid.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, SecondStretchBeforeFourNewIntervalsAddsNoEvent) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<std::int64_t> a = rhythm(75, fs, 8);
    const std::vector<std::int64_t> b = rhythm(75, fs, 3, a.back() + 4 * fs);
    const std::vector<std::int64_t> c = rhythm(75, fs, 9, b.back() + 4 * fs);
    std::vector<std::int64_t> all = a;
    all.insert(all.end(), b.begin(), b.end());
    all.insert(all.end(), c.begin(), c.end());
    const std::vector<Ev> events = track(fs, all);
    const std::vector<Ev> none = without_detection(events);
    ASSERT_EQ(none.size(), 1U);
    EXPECT_EQ(none[0].sample, static_cast<std::uint64_t>(a.back() + three_s(fs)));
    const std::vector<Ev> beats = at_detections(events);
    ASSERT_EQ(beats.size(), all.size());
    for (std::size_t i = 0; i < b.size(); ++i) {
      EXPECT_EQ(beats[a.size() + i].status, kNoRecent);
    }
    for (std::size_t i = 0; i < c.size(); ++i) {
      EXPECT_EQ(beats[a.size() + b.size() + i].status, i < 4 ? kNoRecent : kValid) << i;
    }
  }
}

// Case: valid, a stretch of 4 s, valid again, a stretch of 4 s and the end 3 s later.
// Expected: an event without a detection at each change into "no recent beat", once per change,
// at 3 s after the last detection before each stretch.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, AnEventAtEachChangeOfReason) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<std::int64_t> a = rhythm(75, fs, 8);
    const std::vector<std::int64_t> b = rhythm(75, fs, 8, a.back() + 4 * fs);
    std::vector<std::int64_t> all = a;
    all.insert(all.end(), b.begin(), b.end());
    const std::int64_t n3 = three_s(fs);
    const std::vector<Ev> none = without_detection(track(fs, all, {}, 1 + n3));
    ASSERT_EQ(none.size(), 2U);
    EXPECT_EQ(none[0].sample, static_cast<std::uint64_t>(a.back() + n3));
    EXPECT_EQ(none[1].sample, static_cast<std::uint64_t>(b.back() + n3));
    EXPECT_EQ(none[0].status, kNoRecent);
    EXPECT_EQ(none[1].status, kNoRecent);
  }
}

// Case: 8 detections at 75 bpm, a detection marked start-up 1.5 s after the last, then silence.
// Expected: the 3 s are counted from the last detection marked reliable: "no recent beat" is at
// that detection + 3 s, once; the start-up detection gives no event.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, StartUpDetectionDoesNotRestartTheTimer) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    std::vector<std::int64_t> idx = rhythm(75, fs, 8);
    const std::int64_t last = idx.back();
    idx.push_back(last + std::lround(1.5 * fs));
    std::vector<bool> marks(idx.size(), false);
    marks.back() = true;
    const std::int64_t n3 = three_s(fs);
    const std::vector<Ev> events = track(fs, idx, marks, 1 + 2 * n3);
    const std::vector<Ev> none = without_detection(events);
    ASSERT_EQ(none.size(), 1U);
    EXPECT_EQ(none[0].sample, static_cast<std::uint64_t>(last + n3));
    EXPECT_EQ(at_detections(events).size(), 8U);
  }
}

// Case: regular rhythms at 29 and 201 bpm, 30 detections.
// Expected: "not enough beats" at the first four, then "out of range" at every detection with a
// rate below 30 (29 bpm) or above 200 (201 bpm); never valid.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, RatesOutsideTheRangeAreOutOfRange) {
  for (const int fs : kRates) {
    for (const int rate : {29, 201}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm");
      const std::vector<Ev> events = track(fs, rhythm(rate, fs, 30));
      ASSERT_EQ(events.size(), 30U);
      EXPECT_EQ(statuses(events, 0, 4), std::vector<HeartRateStatus>(4, kNotEnough));
      for (std::size_t i = 4; i < events.size(); ++i) {
        EXPECT_EQ(events[i].status, kOutOfRange) << i;
        ASSERT_FALSE(std::isnan(events[i].bpm));
        if (rate < 30) {
          EXPECT_LT(events[i].bpm, 30.0F);
        } else {
          EXPECT_GT(events[i].bpm, 200.0F);
        }
      }
    }
  }
}

// Case: regular rhythms at the bounds, 30 and 200 bpm, 30 detections.
// Expected: valid at every detection from the fifth; never "out of range".
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, BoundsOfTheRangeAreNotOutOfRange) {
  for (const int fs : kRates) {
    for (const int rate : {30, 200}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm");
      const std::vector<Ev> events = track(fs, rhythm(rate, fs, 30));
      for (std::size_t i = 4; i < events.size(); ++i) {
        EXPECT_EQ(events[i].status, kValid) << i;
      }
    }
  }
}

// Case: 75 bpm, then 250 bpm (intervals of 240 ms, above the range), then 75 bpm.
// Expected: "out of range" while the rate computed is above 200 bpm, with its rate; valid again
// when the rhythm returns to 75 bpm; no valid heart rate above 200.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, OutOfRangeThenBackToValid) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<std::int64_t> a = rhythm(75, fs, 10);
    const std::vector<std::int64_t> b = rhythm(250, fs, 20, a.back());
    const std::vector<std::int64_t> c = rhythm(75, fs, 14, b.back());
    std::vector<std::int64_t> all = a;
    all.insert(all.end(), b.begin() + 1, b.end());
    all.insert(all.end(), c.begin() + 1, c.end());
    const std::vector<Ev> events = track(fs, all);
    const std::vector<Ev> beats = at_detections(events);
    ASSERT_EQ(beats.size(), all.size());
    const std::size_t last_b = a.size() + b.size() - 2;
    EXPECT_EQ(beats[last_b].status, kOutOfRange);
    EXPECT_GT(beats[last_b].bpm, 200.0F);
    EXPECT_EQ(beats.back().status, kValid);
    for (const double r : valid_rates(events)) {
      EXPECT_LE(r, 200.0);
    }
  }
}

// ---------------------------------------------------------------------------------- the chain

struct ChainRun {
  std::vector<sinus_qa::Det> detections;
  std::vector<Ev> events;
};

ChainRun run_with_heart_rate(const std::vector<float>& ecg, int fs, int mains) {
  sinus::dsp::Chain chain;
  EXPECT_EQ(chain.configure(sinus::dsp::Config{static_cast<double>(fs), mains}), Status::kOk);
  ChainRun run;
  sinus::dsp::SampleOutput out;
  for (std::size_t i = 0; i < ecg.size(); ++i) {
    EXPECT_EQ(chain.process(ecg[i], out), Status::kOk);
    EXPECT_LE(out.heart_rate_count, sinus::dsp::kMaxHeartRateEventsPerSample);
    for (std::size_t j = 0; j < out.detection_count; ++j) {
      const auto& d = out.detections[j];
      run.detections.push_back({d.index, d.reported_at, d.mark, d.path});
    }
    for (std::size_t j = 0; j < out.heart_rate_count && j < out.heart_rates.size(); ++j) {
      const auto& e = out.heart_rates[j];
      EXPECT_EQ(e.sample, static_cast<std::uint64_t>(i));
      run.events.push_back({e.sample, e.beat_index, e.has_beat, e.status, e.bpm});
    }
  }
  return run;
}

// Case: the synthetic ECGs of SRS-006 of 60 s at 40, 75 and 180 bpm through the chain (50 Hz
// setting), 360 and 250 Hz.
// Expected: an event with a detection for each detection marked reliable, at its report sample
// and naming its index, none for the start-up detections (there is at least one); "not enough
// beats" at the first events; every valid heart rate within 2 bpm of the true rate; valid at the
// end.
// Verifies: SRS-024, SRS-026
TEST(Srs024HeartRateInTheChain, SyntheticEcgGivesTheHeartRate) {
  for (const int fs : kRates) {
    for (const int rate : {40, 75, 180}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz " << rate << " bpm");
      const std::vector<float> ecg =
          sinus_qa::synthetic_ecg(fs, rate, 60 * static_cast<std::size_t>(fs), 0);
      const ChainRun run = run_with_heart_rate(ecg, fs, 50);
      std::vector<sinus_qa::Det> reliable;
      std::size_t startup = 0;
      for (const auto& d : run.detections) {
        if (d.mark == Mark::kReliable) {
          reliable.push_back(d);
        } else {
          ++startup;
        }
      }
      EXPECT_GE(startup, 1U);
      const std::vector<Ev> beats = at_detections(run.events);
      ASSERT_EQ(beats.size(), reliable.size());
      for (std::size_t i = 0; i < beats.size(); ++i) {
        EXPECT_EQ(beats[i].beat_index, reliable[i].index);
        EXPECT_EQ(beats[i].sample, reliable[i].reported_at);
      }
      ASSERT_GT(beats.size(), 8U);
      EXPECT_EQ(statuses(beats, 0, 4), std::vector<HeartRateStatus>(4, kNotEnough));
      EXPECT_EQ(beats[4].status, kValid);
      EXPECT_TRUE(all_within(valid_rates(run.events), rate, 2.0));
      EXPECT_EQ(run.events.back().status, kValid);
    }
  }
}

// Case: a synthetic ECG at 75 bpm of 40 s whose second half (from 20 s) is silent (zeros).
// Expected: the last event is "no recent beat" with no rate, at no detection, at ceil(3 fs)
// samples after the index of the last detection marked reliable; some heart rate was valid
// before.
// Verifies: SRS-026
TEST(Srs026WithheldHeartRate, SilentStretchInTheChainGivesNoRecentBeat) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    std::vector<float> ecg = sinus_qa::synthetic_ecg(fs, 75, 40 * static_cast<std::size_t>(fs), 0);
    std::fill(ecg.begin() + 20 * fs, ecg.end(), 0.0F);
    const ChainRun run = run_with_heart_rate(ecg, fs, 50);
    std::uint64_t last_reliable = 0;
    for (const auto& d : run.detections) {
      if (d.mark == Mark::kReliable) {
        last_reliable = d.index;
      }
    }
    ASSERT_FALSE(run.events.empty());
    const Ev& last = run.events.back();
    EXPECT_EQ(last.status, kNoRecent);
    EXPECT_FALSE(last.has_beat);
    EXPECT_TRUE(std::isnan(last.bpm));
    EXPECT_EQ(last.sample, last_reliable + static_cast<std::uint64_t>(three_s(fs)));
    EXPECT_FALSE(valid_rates(run.events).empty());
  }
}

}  // namespace
