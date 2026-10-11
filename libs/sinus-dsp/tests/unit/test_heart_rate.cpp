#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "sinus/dsp/config.hpp"
#include "sinus/dsp/heart_rate.hpp"
#include "sinus/dsp/limits.hpp"

namespace {

using sinus::dsp::HeartRateEvent;
using sinus::dsp::HeartRateStatus;
using sinus::dsp::HeartRateStep;
using sinus::dsp::HeartRateTracker;
using sinus::dsp::Mark;
using sinus::dsp::ReportedDetection;
using sinus::dsp::Status;

struct Given {
  std::uint64_t index;
  Mark mark;
  std::uint64_t reported_at;
};

Given reliable(std::uint64_t index) { return Given{index, Mark::kReliable, index}; }

// Gives the detections to the tracker sample by sample, from the sample `from` to before `to`.
std::vector<HeartRateEvent> run(HeartRateTracker& tracker, const std::vector<Given>& given,
                                std::uint64_t from, std::uint64_t to) {
  std::vector<HeartRateEvent> events;
  for (std::uint64_t n = from; n < to; ++n) {
    std::vector<ReportedDetection> now;
    for (const Given& g : given) {
      if (g.reported_at == n) {
        now.push_back(ReportedDetection{g.index, g.mark});
      }
    }
    HeartRateStep step;
    EXPECT_EQ(tracker.step(now.data(), now.size(), step), Status::kOk);
    for (std::size_t i = 0; i < step.count; ++i) {
      events.push_back(step.events[i]);
    }
  }
  return events;
}

std::vector<HeartRateEvent> run(HeartRateTracker& tracker, const std::vector<Given>& given,
                                std::uint64_t n_samples) {
  return run(tracker, given, 0, n_samples);
}

std::vector<Given> regular(std::uint64_t first, std::uint64_t interval, std::size_t count) {
  std::vector<Given> given;
  for (std::size_t i = 0; i < count; ++i) {
    given.push_back(reliable(first + (i * interval)));
  }
  return given;
}

HeartRateTracker configured(double fs) {
  HeartRateTracker tracker;
  EXPECT_EQ(tracker.configure(fs), Status::kOk);
  return tracker;
}

TEST(HeartRateTracker, RegularRhythmIsWithheldForFourIntervalsThenValid) {
  HeartRateTracker tracker = configured(360.0);
  const std::vector<HeartRateEvent> events = run(tracker, regular(100, 288, 8), 3000);
  ASSERT_EQ(events.size(), 8U);
  for (std::size_t i = 0; i < events.size(); ++i) {
    EXPECT_TRUE(events[i].has_beat);
    EXPECT_EQ(events[i].sample, events[i].beat_index);
    if (i < 4) {
      EXPECT_EQ(events[i].status, HeartRateStatus::kNotEnoughBeats) << i;
      EXPECT_TRUE(std::isnan(events[i].bpm));
    } else {
      EXPECT_EQ(events[i].status, HeartRateStatus::kValid) << i;
      EXPECT_NEAR(events[i].bpm, 75.0F, 1e-4F);
    }
  }
}

TEST(HeartRateTracker, TheRateIsComputedInBinary32InTheDesignedOrder) {
  HeartRateTracker tracker = configured(360.0);
  const std::vector<HeartRateEvent> events = run(tracker, regular(0, 301, 6), 2000);
  ASSERT_EQ(events.size(), 6U);
  const float expected = (static_cast<float>(60.0 * 360.0) * 5.0F) / static_cast<float>(1505);
  EXPECT_EQ(events[5].bpm, expected);
}

TEST(HeartRateTracker, StartUpDetectionsGiveNoEventAndNoInterval) {
  HeartRateTracker tracker = configured(360.0);
  std::vector<Given> given;
  for (std::uint64_t i = 0; i < 3; ++i) {
    given.push_back(Given{50 + (i * 200), Mark::kStartUp, 50 + (i * 200)});
  }
  for (const Given& g : regular(1000, 288, 6)) {
    given.push_back(g);
  }
  const std::vector<HeartRateEvent> events = run(tracker, given, 3000);
  const std::vector<HeartRateEvent> alone = [&] {
    HeartRateTracker other = configured(360.0);
    return run(other, regular(1000, 288, 6), 3000);
  }();
  ASSERT_EQ(events.size(), alone.size());
  for (std::size_t i = 0; i < events.size(); ++i) {
    EXPECT_EQ(events[i].sample, alone[i].sample);
    EXPECT_EQ(events[i].status, alone[i].status);
  }
  // The first reliable detection after start-up ones has no interval (the previous is start-up).
  EXPECT_EQ(events[0].status, HeartRateStatus::kNotEnoughBeats);
}

TEST(HeartRateTracker, RangeBoundsAreIncludedAtEverySamplingFrequency) {
  for (const double fs : {125.0, 250.0, 360.0, 1000.0}) {
    const auto longest = static_cast<std::uint64_t>(std::floor(2000.0 * fs / 1000.0));
    const auto shortest = static_cast<std::uint64_t>(std::ceil(300.0 * fs / 1000.0));
    struct Case {
      std::uint64_t interval;
      HeartRateStatus status;
    };
    for (const Case& c :
         {Case{longest, HeartRateStatus::kValid}, Case{longest + 1U, HeartRateStatus::kOutOfRange},
          Case{shortest, HeartRateStatus::kValid},
          Case{shortest - 1U, HeartRateStatus::kOutOfRange}}) {
      HeartRateTracker tracker = configured(fs);
      const std::vector<HeartRateEvent> events =
          run(tracker, regular(0, c.interval, 6), (6U * c.interval) + 1U);
      ASSERT_EQ(events.size(), 6U) << fs;
      EXPECT_EQ(events[4].status, c.status) << fs << " " << c.interval;
      EXPECT_FALSE(std::isnan(events[4].bpm));  // the rate is given for out of range too
    }
  }
}

TEST(HeartRateTracker, NoRecentBeatFiresAtExactlyThreeSecondsAfterTheLastDetection) {
  HeartRateTracker tracker = configured(360.0);
  const std::uint64_t wait = sinus::dsp::no_recent_beat_samples(360.0);
  ASSERT_EQ(wait, 1080U);
  std::vector<Given> given = regular(0, 288, 6);  // the last at 1440
  const std::vector<HeartRateEvent> events = run(tracker, given, 1440 + wait + 10U);
  ASSERT_EQ(events.size(), 7U);
  const HeartRateEvent& gap = events[6];
  EXPECT_EQ(gap.sample, 1440U + wait);
  EXPECT_FALSE(gap.has_beat);
  EXPECT_EQ(gap.status, HeartRateStatus::kNoRecentBeat);
  EXPECT_TRUE(std::isnan(gap.bpm));
}

TEST(HeartRateTracker, ADetectionAtTheThresholdSampleCountsBeforeTheCheck) {
  HeartRateTracker tracker = configured(360.0);
  std::vector<Given> given = regular(0, 288, 6);
  given.push_back(reliable(1440 + 1080));  // reported at the sample where "no recent beat" is due
  const std::vector<HeartRateEvent> events = run(tracker, given, 1440 + 1080 + 10U);
  ASSERT_EQ(events.size(), 7U);
  EXPECT_TRUE(events[6].has_beat);  // no gap event
}

TEST(HeartRateTracker, FourNewIntervalsAreNeededAfterNoRecentBeat) {
  HeartRateTracker tracker = configured(360.0);
  std::vector<Given> given = regular(0, 288, 6);
  for (const Given& g : regular(3000, 288, 6)) {
    given.push_back(g);
  }
  const std::vector<HeartRateEvent> events = run(tracker, given, 5000);
  // 6 + gap + 6.
  ASSERT_EQ(events.size(), 13U);
  EXPECT_EQ(events[6].status, HeartRateStatus::kNoRecentBeat);
  for (std::size_t i = 7; i < 11; ++i) {
    EXPECT_EQ(events[i].status, HeartRateStatus::kNoRecentBeat) << i;  // not "not enough beats"
    EXPECT_TRUE(events[i].has_beat);
  }
  EXPECT_EQ(events[11].status, HeartRateStatus::kValid);
  EXPECT_EQ(events[12].status, HeartRateStatus::kValid);
}

TEST(HeartRateTracker, ASecondGapWhileHeldGivesNoSecondEventAndMovesTheReset) {
  HeartRateTracker tracker = configured(360.0);
  std::vector<Given> given = regular(0, 288, 6);
  given.push_back(reliable(3000));
  given.push_back(reliable(3288));
  given.push_back(reliable(6500));  // a new gap after fewer than four intervals
  const std::vector<HeartRateEvent> events = run(tracker, given, 7000);
  std::size_t gaps = 0;
  for (const HeartRateEvent& e : events) {
    if (!e.has_beat) {
      ++gaps;
    }
  }
  EXPECT_EQ(gaps, 1U);
}

TEST(HeartRateTracker, ADetectionWithAnEarlierIndexReportedLateAddsNoInterval) {
  HeartRateTracker tracker = configured(360.0);
  std::vector<Given> given = regular(0, 288, 6);  // the last at 1440; "no recent beat" at 2520
  given.push_back(Given{2000, Mark::kReliable, 2600});  // index before the reset sample 2520
  given.push_back(Given{2530, Mark::kReliable, 2620});  // after it, but the previous one is before
  given.push_back(Given{2830, Mark::kReliable, 2830});  // the first interval since the reset
  given.push_back(Given{3130, Mark::kReliable, 3130});
  given.push_back(Given{3430, Mark::kReliable, 3430});
  given.push_back(Given{3730, Mark::kReliable, 3730});  // the fourth interval
  const std::vector<HeartRateEvent> events = run(tracker, given, 4000);
  ASSERT_EQ(events.size(), 6U + 1U + 6U);
  for (std::size_t i = 7; i < 12; ++i) {
    EXPECT_EQ(events[i].status, HeartRateStatus::kNoRecentBeat) << i;
  }
  EXPECT_EQ(events[12].status, HeartRateStatus::kValid);
  EXPECT_NEAR(events[12].bpm, 72.0F, 1e-4F);  // 4 intervals of 300 samples at 360 Hz
}

TEST(HeartRateTracker, SeveralDetectionsAtOneSampleAreHandledInOrder) {
  HeartRateTracker tracker = configured(360.0);
  std::vector<Given> given;
  for (std::uint64_t i = 0; i < 6; ++i) {
    given.push_back(Given{i * 288, Mark::kReliable, 1800});
  }
  const std::vector<HeartRateEvent> events = run(tracker, given, 1900);
  ASSERT_EQ(events.size(), 6U);
  for (std::size_t i = 0; i < 6; ++i) {
    EXPECT_EQ(events[i].sample, 1800U);
    EXPECT_EQ(events[i].beat_index, i * 288U);
  }
  EXPECT_EQ(events[3].status, HeartRateStatus::kNotEnoughBeats);
  EXPECT_EQ(events[4].status, HeartRateStatus::kValid);
}

TEST(HeartRateTracker, ResetStartsANewStream) {
  HeartRateTracker used = configured(360.0);
  (void)run(used, regular(100, 288, 8), 3000);
  used.reset();
  HeartRateTracker fresh = configured(360.0);
  const std::vector<Given> given = regular(10, 300, 8);
  const std::vector<HeartRateEvent> a = run(used, given, 3000);
  const std::vector<HeartRateEvent> b = run(fresh, given, 3000);
  ASSERT_EQ(a.size(), b.size());
  for (std::size_t i = 0; i < a.size(); ++i) {
    EXPECT_EQ(a[i].sample, b[i].sample);
    EXPECT_EQ(a[i].status, b[i].status);
  }
}

TEST(HeartRateTracker, ResetAfterNoRecentBeatReturnsToNotEnoughBeats) {
  HeartRateTracker tracker = configured(360.0);
  (void)run(tracker, regular(0, 288, 6), 3000);  // "no recent beat" has fired
  tracker.reset();
  const std::vector<HeartRateEvent> events = run(tracker, regular(0, 288, 2), 600);
  ASSERT_EQ(events.size(), 2U);
  EXPECT_EQ(events[0].status, HeartRateStatus::kNotEnoughBeats);
  EXPECT_EQ(events[1].status, HeartRateStatus::kNotEnoughBeats);
}

TEST(HeartRateTracker, Preconditions) {
  HeartRateTracker tracker;
  HeartRateStep step;
  const ReportedDetection d{0, Mark::kReliable};
  EXPECT_EQ(tracker.step(&d, 1, step), Status::kNotConfigured);
  EXPECT_EQ(tracker.configure(124.0), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(tracker.step(&d, 1, step), Status::kNotConfigured);
  tracker.reset();  // harmless
  ASSERT_EQ(tracker.configure(250.0), Status::kOk);
  EXPECT_EQ(tracker.step(nullptr, 1, step), Status::kInvalidArgument);
  EXPECT_EQ(step.count, 0U);
  const std::vector<ReportedDetection> many(sinus::dsp::kMaxDetectionsPerSample + 1,
                                            ReportedDetection{0, Mark::kReliable});
  EXPECT_EQ(tracker.step(many.data(), many.size(), step), Status::kInvalidArgument);
  const ReportedDetection ahead{1, Mark::kReliable};  // above the current sample 0
  EXPECT_EQ(tracker.step(&ahead, 1, step), Status::kInvalidArgument);
  const std::vector<ReportedDetection> twice{{0, Mark::kReliable}, {0, Mark::kReliable}};
  EXPECT_EQ(tracker.step(twice.data(), twice.size(), step), Status::kInvalidArgument);
  // Every rejected call left the state as it was: sample 0 is still the current one.
  EXPECT_EQ(tracker.step(&d, 1, step), Status::kOk);
  ASSERT_EQ(step.count, 1U);
  EXPECT_EQ(step.events[0].sample, 0U);
  EXPECT_EQ(tracker.step(nullptr, 0, step), Status::kOk);          // sample 1, nothing reported
  EXPECT_EQ(tracker.step(&d, 1, step), Status::kInvalidArgument);  // not greater than the last
  EXPECT_EQ(step.count, 0U);
}

TEST(HeartRateTracker, ARejectedCallDoesNotAdvanceTheSampleCounter) {
  HeartRateTracker tracker = configured(250.0);
  HeartRateStep step;
  const ReportedDetection ahead{5, Mark::kReliable};
  EXPECT_EQ(tracker.step(&ahead, 1, step), Status::kInvalidArgument);
  for (int i = 0; i < 5; ++i) {
    ASSERT_EQ(tracker.step(nullptr, 0, step), Status::kOk);
  }
  EXPECT_EQ(tracker.step(&ahead, 1, step), Status::kOk);  // sample 5: the index is not above it
}

TEST(HeartRateTracker, ConfigurationChecksTheSamplingFrequency) {
  HeartRateTracker tracker;
  EXPECT_EQ(tracker.configure(std::nan("")), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(tracker.configure(1000.1), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(tracker.configure(125.0), Status::kOk);
  EXPECT_EQ(tracker.configure(1000.0), Status::kOk);
}

TEST(HeartRateTracker, NoRecentBeatSamplesAreTheCeilingOfThreeSeconds) {
  EXPECT_EQ(sinus::dsp::no_recent_beat_samples(360.0), 1080U);
  EXPECT_EQ(sinus::dsp::no_recent_beat_samples(250.0), 750U);
  EXPECT_EQ(sinus::dsp::no_recent_beat_samples(125.0), 375U);
  EXPECT_EQ(sinus::dsp::no_recent_beat_samples(1000.0), 3000U);
  EXPECT_EQ(sinus::dsp::no_recent_beat_samples(333.5), 1001U);  // 1000.5 rounded up
}

}  // namespace
