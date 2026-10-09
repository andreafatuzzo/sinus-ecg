// Requirement tests of SRS-020: streaming QRS detection in the real-time library.
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <utility>
#include <vector>

#include "chain_run.hpp"
#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::DetectorStep;
using sinus::dsp::QrsDetector;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;
using sinus_qa::Det;

constexpr int kRates[] = {360, 250};
constexpr int kHeartRates[] = {30, 40, 75, 180, 200};
constexpr std::size_t kSeconds = 60;

// One input of the verification: sampling frequency, heart rate, interference added to the ECG
// (0 = none) and the mains setting given to the library.
struct Case {
  int fs;
  int hr;
  int interference;
  int setting;
};

std::vector<Case> cases(bool interfered) {
  std::vector<Case> out;
  for (const int fs : kRates) {
    for (const int hr : kHeartRates) {
      if (interfered) {
        out.push_back({fs, hr, 50, 50});
        out.push_back({fs, hr, 60, 60});
      } else {
        out.push_back({fs, hr, 0, 50});
        out.push_back({fs, hr, 0, 60});
      }
    }
  }
  return out;
}

void check_case(const Case& c) {
  SCOPED_TRACE(testing::Message() << "fs " << c.fs << " hr " << c.hr << " interference "
                                  << c.interference << " setting " << c.setting);
  const std::size_t n = kSeconds * static_cast<std::size_t>(c.fs);
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(c.fs, c.hr, n, c.interference);
  const std::vector<Det> dets = sinus_qa::run_chain(ecg, c.fs, c.setting);
  const std::vector<std::int64_t> r = sinus_qa::regular_r_positions(c.fs, c.hr, n);
  const std::vector<std::int64_t> offsets = sinus_qa::expect_one_per_beat(dets, r, n, c.fs);
  EXPECT_GE(dets.size(), r.size() - 2);
  // A consistent offset from the R centre: after the first 2 s the detection of every beat lies
  // at the same place of the complex, to within 2 samples.
  std::int64_t lo = 1 << 30;
  std::int64_t hi = -(1 << 30);
  for (std::size_t i = 0; i < dets.size() && i < offsets.size(); ++i) {
    if (dets[i].index >= static_cast<std::uint64_t>(2 * c.fs)) {
      lo = std::min(lo, offsets[i]);
      hi = std::max(hi, offsets[i]);
    }
  }
  EXPECT_LE(hi - lo, 2) << "offsets from " << lo << " to " << hi;
}

// Case: regular rhythms without interference, one sample at a time.
// Input: synthetic ECG of 60 s at 360 and 250 Hz, 30, 40, 75, 180 and 200 bpm (bounds included),
// mains setting 50 and 60.
// Expected: indices strictly increasing and 200 ms apart at least; each known beat has exactly
// one detection within 150 ms and there is no other detection; a consistent offset.
// Verifies: SRS-020
TEST(Srs020Detection, RegularRhythmsWithoutInterference) {
  for (const Case& c : cases(false)) {
    check_case(c);
  }
}

// Case: regular rhythms with the interference of SRS-010.
// Input: the same ECGs plus a 0.3 Hz baseline wander of 1 mV and mains of 0.2 mV at 50 Hz (setting
// 50) and at 60 Hz (setting 60).
// Expected: the same criteria hold.
// Verifies: SRS-020
TEST(Srs020Detection, RegularRhythmsWithInterference) {
  for (const Case& c : cases(true)) {
    check_case(c);
  }
}

// Case: a flat input gives no detection and no error status.
// Input: constant 0.0, 0.7 and -1.5 mV for 10 s, and 0.7 mV for 30 s (the library re-learns its
// levels), at 360 and 250 Hz, both mains settings.
// Expected: every sample returns kOk with detection_count 0.
// Verifies: SRS-020
TEST(Srs020Detection, FlatInputGivesNoDetectionAndNoError) {
  for (const int fs : kRates) {
    for (const int mains : {50, 60}) {
      for (const auto& [value, seconds] :
           {std::pair{0.0F, 10}, std::pair{0.7F, 10}, std::pair{-1.5F, 10}, std::pair{0.7F, 30}}) {
        SCOPED_TRACE(testing::Message() << fs << " Hz mains " << mains << " value " << value
                                        << " for " << seconds << " s");
        Chain chain;
        ASSERT_EQ(chain.configure(Config{static_cast<double>(fs), mains}), Status::kOk);
        SampleOutput out;
        out.detection_count = 3;  // stale
        for (int i = 0; i < seconds * fs; ++i) {
          ASSERT_EQ(chain.process(value, out), Status::kOk) << "sample " << i;
          ASSERT_EQ(out.detection_count, 0U) << "sample " << i;
        }
      }
    }
  }
}

// Case: detections are reported with the index in the time base of the stream, at the sample at
// which they are found, never before their index.
// Input: the interfered ECG at 75 bpm, 360 Hz, 20 s.
// Expected: every detection is reported at the call that gives its sample (checked per sample by
// the runner), index <= reported_at, and the first sample given is index 0: the first beat
// (R at 0.5 s) is detected within 150 ms of sample 180.
// Verifies: SRS-020
TEST(Srs020Detection, IndicesAreInTheTimeBaseOfTheStream) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(360, 75, 20 * 360, 50);
  const std::vector<Det> dets = sinus_qa::run_chain(ecg, 360, 50);
  ASSERT_FALSE(dets.empty());
  EXPECT_LE(std::abs(static_cast<std::int64_t>(dets.front().index) - 180), 54);
  for (std::size_t i = 1; i < dets.size(); ++i) {
    EXPECT_GE(dets[i].reported_at, dets[i - 1].reported_at);
  }
}

// Case: the detector works on the conditioned signal of SRS-019.
// Input: the interfered ECG at 75 bpm and 180 bpm, 360 Hz, 30 s through a chain; its
// conditioned_mv output sample by sample into a separately configured QrsDetector.
// Expected: the detector alone reports the same detections (index, report sample, mark, path) as
// the chain, at the same samples, and the same number per sample.
// Verifies: SRS-020
TEST(Srs020Detection, DetectorAloneOnTheConditionedSignalEqualsTheChain) {
  for (const int hr : {75, 180}) {
    SCOPED_TRACE(hr);
    const std::vector<float> ecg = sinus_qa::synthetic_ecg(360, hr, 30 * 360, 50);
    Chain chain;
    ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
    QrsDetector detector;
    ASSERT_EQ(detector.configure(360.0), Status::kOk);
    std::size_t total = 0;
    for (std::size_t i = 0; i < ecg.size(); ++i) {
      SampleOutput out;
      ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
      DetectorStep step;
      ASSERT_EQ(detector.process(out.conditioned_mv, step), Status::kOk);
      ASSERT_EQ(step.count, out.detection_count) << "sample " << i;
      for (std::size_t j = 0; j < step.count; ++j) {
        const Det a{step.detections[j].index, step.detections[j].reported_at,
                    step.detections[j].mark, step.detections[j].path};
        const Det b{out.detections[j].index, out.detections[j].reported_at, out.detections[j].mark,
                    out.detections[j].path};
        ASSERT_TRUE(a == b) << "sample " << i;
      }
      total += step.count;
    }
    EXPECT_GT(total, 20U);
  }
}

// Case: a non-ok status gives no detection.
// Input: 12 s of ECG, then an invalid sample (NaN), then the ECG (kStopped), on an output that
// holds a stale detection count.
// Expected: detection_count 0 at the invalid sample and at every stopped sample.
// Verifies: SRS-020
TEST(Srs020Detection, NoDetectionWithAnErrorStatus) {
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(360, 75, 20 * 360, 50);
  Chain chain;
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  SampleOutput out;
  std::size_t i = 0;
  for (; i < 12 * 360; ++i) {
    ASSERT_EQ(chain.process(ecg[i], out), Status::kOk);
  }
  out.detection_count = 4;
  ASSERT_EQ(chain.process(std::numeric_limits<float>::quiet_NaN(), out), Status::kInvalidSample);
  EXPECT_EQ(out.detection_count, 0U);
  for (std::size_t j = 0; j < 3 * 360; ++j, ++i) {
    out.detection_count = 4;
    ASSERT_EQ(chain.process(ecg[i], out), Status::kStopped);
    ASSERT_EQ(out.detection_count, 0U);
  }
}

}  // namespace
