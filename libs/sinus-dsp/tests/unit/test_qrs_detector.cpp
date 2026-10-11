#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "sinus/dsp/config.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/status.hpp"
#include "synthetic_beats.hpp"

namespace sinus::dsp {

// Access to the store of peaks, which no signal can fill (consecutive peaks of the integrated
// signal are in practice far more than 2 samples apart).
struct QrsDetectorProbe {
  static void store(QrsDetector& detector, std::uint64_t m) {
    detector.store(QrsDetector::PeakRecord{m, 0, 1.0F, 1.0F, 1.0F, 0.0F, 0.0F});
  }
  static std::size_t count(const QrsDetector& detector) { return detector.peaks_count_; }
  static std::uint64_t oldest(const QrsDetector& detector) {
    return detector.peaks_[detector.peaks_head_].m;
  }
  static std::uint64_t newest(const QrsDetector& detector) {
    return detector
        .peaks_[(detector.peaks_head_ + detector.peaks_count_ - 1U) % detector.peaks_.size()]
        .m;
  }
};

}  // namespace sinus::dsp

namespace {

using sinus::dsp::Detection;
using sinus::dsp::DetectionPath;
using sinus::dsp::DetectorSamples;
using sinus::dsp::DetectorStep;
using sinus::dsp::Mark;
using sinus::dsp::QrsDetector;
using sinus::dsp::QrsDetectorProbe;
using sinus::dsp::Status;
using sinus::dsp::ZoneSums;
using sinus_test::Beat;
using sinus_test::r_sample;
using sinus_test::regular_beats;
using sinus_test::synthetic_beats;

struct Outputs {
  std::vector<Detection> detections;
  std::vector<ZoneSums> zones;
  std::vector<float> squared;
  std::vector<std::size_t> counts;  // detections per sample
};

Outputs run(QrsDetector& detector, const std::vector<float>& x) {
  Outputs result;
  DetectorStep step;
  for (const float v : x) {
    EXPECT_EQ(detector.process(v, step), Status::kOk);
    result.squared.push_back(step.squared_derivative);
    result.counts.push_back(step.count);
    for (std::size_t i = 0; i < step.count; ++i) {
      result.detections.push_back(step.detections[i]);
      result.zones.push_back(step.zones[i]);
    }
  }
  return result;
}

Outputs run_new(double fs_hz, const std::vector<float>& x) {
  QrsDetector detector;
  EXPECT_EQ(detector.configure(fs_hz), Status::kOk);
  return run(detector, x);
}

bool same(const Detection& a, const Detection& b) {
  return a.index == b.index && a.reported_at == b.reported_at && a.mark == b.mark &&
         a.path == b.path;
}

TEST(QrsDetector, NotConfiguredGivesNoOutput) {
  QrsDetector detector;
  DetectorStep step;
  step.count = 3;
  step.squared_derivative = 1.0F;
  EXPECT_EQ(detector.process(0.5F, step), Status::kNotConfigured);
  EXPECT_EQ(step.count, 0U);
  EXPECT_EQ(step.squared_derivative, 0.0F);
  detector.reset();  // harmless
  EXPECT_EQ(detector.process(0.5F, step), Status::kNotConfigured);
}

TEST(QrsDetector, RejectsAnInvalidSamplingFrequency) {
  QrsDetector detector;
  ASSERT_EQ(detector.configure(360.0), Status::kOk);
  for (const double fs : {124.999, 1000.001, 0.0, -360.0, std::numeric_limits<double>::quiet_NaN(),
                          std::numeric_limits<double>::infinity()}) {
    EXPECT_EQ(detector.configure(fs), Status::kInvalidSamplingFrequency) << fs;
    DetectorStep step;
    EXPECT_EQ(detector.process(0.0F, step), Status::kNotConfigured);
  }
  for (const double fs : {125.0, 1000.0}) {
    EXPECT_EQ(detector.configure(fs), Status::kOk) << fs;
  }
}

TEST(QrsDetector, FlatInputGivesNoDetection) {
  for (const float level : {0.0F, 3.25F, -7.5F}) {
    const std::vector<float> x(3600 * 4, level);  // 40 s at 360 Hz: several re-learnings
    const Outputs r = run_new(360.0, x);
    EXPECT_TRUE(r.detections.empty()) << level;
    for (const float s : r.squared) {
      ASSERT_EQ(s, 0.0F) << level;
    }
  }
}

TEST(QrsDetector, TinySignalStaysBelowTheSmallestIntegratedPeak) {
  // A 10 Hz sinusoid of 0.1 uV: its integrated level is below 1e-4 (mV/s)^2 (architecture-m1.md
  // 8.7.2), so the tracker takes no peak.
  std::vector<float> x(360 * 20);
  for (std::size_t k = 0; k < x.size(); ++k) {
    x[k] = static_cast<float>(
        1e-4 * std::sin(2.0 * 3.141592653589793 * 10.0 * static_cast<double>(k) / 360.0));
  }
  EXPECT_TRUE(run_new(360.0, x).detections.empty());
}

void check_regular_rhythm(double fs, double bpm) {
  const DetectorSamples p = sinus::dsp::detector_samples(fs);
  const double rr = 60.0 / bpm;
  const std::vector<Beat> beats = regular_beats(0.5, rr, 29.5);
  const std::vector<float> x = synthetic_beats(fs, 30.0, beats);
  const Outputs r = run_new(fs, x);
  ASSERT_EQ(r.detections.size(), beats.size()) << fs << " " << bpm;
  const auto tolerance = static_cast<std::int64_t>(std::floor(0.150 * fs));
  for (std::size_t i = 0; i < beats.size(); ++i) {
    const Detection& d = r.detections[i];
    const auto index = static_cast<std::int64_t>(d.index);
    EXPECT_LE(std::abs(index - r_sample(beats[i].r_s, fs)), tolerance) << i;
    EXPECT_LE(d.index, d.reported_at);
    if (i > 0) {
      EXPECT_GE(d.index - r.detections[i - 1].index, p.refractory);
      EXPECT_GE(d.reported_at, r.detections[i - 1].reported_at);
    }
    if (d.index < p.learning) {
      // Found at the first initialisation: start-up, reported at L - 1.
      EXPECT_EQ(d.mark, Mark::kStartUp) << i;
      EXPECT_EQ(d.path, DetectionPath::kLearning) << i;
      EXPECT_EQ(d.reported_at, p.learning - 1U) << i;
    } else {
      EXPECT_EQ(d.mark, Mark::kReliable) << i;
      EXPECT_EQ(d.path, DetectionPath::kNormal) << i;
      EXPECT_LE(d.reported_at - d.index,
                p.window + p.peak_timeout + p.band_delay + 2U)  // architecture-m2.md 13.4
          << i;
    }
  }
}

TEST(QrsDetector, RegularRhythmsAreDetectedWithMarksPathsAndReportSamples) {
  for (const double fs : {125.0, 250.0, 360.0, 1000.0}) {
    for (const double bpm : {30.0, 75.0, 200.0}) {
      check_regular_rhythm(fs, bpm);
    }
  }
}

TEST(QrsDetector, SmallBeatIsFoundBySearchBack) {
  for (const double fs : {250.0, 360.0}) {
    std::vector<Beat> beats = regular_beats(0.5, 0.8, 39.5);
    beats[12].scale = 0.4;
    const Outputs r = run_new(fs, synthetic_beats(fs, 40.0, beats));
    ASSERT_EQ(r.detections.size(), beats.size()) << fs;
    const Detection& small = r.detections[12];
    EXPECT_EQ(small.path, DetectionPath::kSearchBack) << fs;
    EXPECT_EQ(small.mark, Mark::kReliable) << fs;
    // Reported once 1.66 mean intervals have passed since the last QRS; before the next beat's
    // confirmation (which is reported after it).
    EXPECT_LT(small.reported_at, r.detections[13].reported_at);
    EXPECT_GT(small.reported_at - small.index, static_cast<std::uint64_t>(0.5 * fs));
    for (std::size_t i = 0; i < r.detections.size(); ++i) {
      if (i != 12) {
        EXPECT_NE(r.detections[i].path, DetectionPath::kSearchBack) << i;
      }
    }
  }
}

TEST(QrsDetector, LargeArtefactLeadsToReLearningWithStartUpMarks) {
  for (const double fs : {250.0, 360.0}) {
    const DetectorSamples p = sinus::dsp::detector_samples(fs);
    std::vector<Beat> beats = regular_beats(0.5, 0.8, 39.5);
    beats[12].scale = 20.0;
    const Outputs r = run_new(fs, synthetic_beats(fs, 40.0, beats));
    // After the artefact, beats are missed until re-learning, 8 s after it.
    // The re-learning classifies the peaks of its stretch [n - L + 1, n]: start-up if the index
    // lies in it, reliable if only the peak does (the index is up to N + 1 + D samples before it).
    std::size_t startup = 0;
    std::size_t relearned = 0;
    std::uint64_t relearn_at = 0;
    for (const Detection& d : r.detections) {
      if (d.path == DetectionPath::kLearning && d.reported_at > p.learning) {
        ++relearned;
        relearn_at = d.reported_at;
        const bool in_stretch = d.index + p.learning >= d.reported_at + 1U;
        EXPECT_EQ(d.mark, in_stretch ? Mark::kStartUp : Mark::kReliable);
        startup += in_stretch ? 1U : 0U;
        EXPECT_LE(d.reported_at - d.index, p.learning + p.window + p.band_delay);
      }
    }
    EXPECT_GE(relearned, 2U) << fs;
    EXPECT_GE(startup, 1U) << fs;
    const auto artefact = static_cast<std::uint64_t>(r_sample(beats[12].r_s, fs));
    EXPECT_GE(relearn_at, artefact + p.relearn_after) << fs;
    // The detections after the re-learning are reliable and found by the normal thresholds.
    std::size_t after = 0;
    for (const Detection& d : r.detections) {
      EXPECT_LE(d.reported_at - d.index,
                p.relearn_after + p.window + p.band_delay + 1U - p.refractory);
      if (d.reported_at > relearn_at) {
        ++after;
        EXPECT_EQ(d.mark, Mark::kReliable);
        EXPECT_EQ(d.path, DetectionPath::kNormal);
      }
    }
    EXPECT_GE(after, 20U) << fs;
  }
}

TEST(QrsDetector, FlatStretchReLearnsWithoutStartUpDetections) {
  const double fs = 360.0;
  const DetectorSamples p = sinus::dsp::detector_samples(fs);
  std::vector<Beat> beats = regular_beats(0.5, 0.8, 10.0);
  const std::vector<Beat> later = regular_beats(30.0, 0.8, 39.5);
  beats.insert(beats.end(), later.begin(), later.end());
  const Outputs r = run_new(fs, synthetic_beats(fs, 40.0, beats));
  ASSERT_EQ(r.detections.size(), beats.size());
  for (const Detection& d : r.detections) {
    if (d.index >= p.learning) {
      EXPECT_EQ(d.mark, Mark::kReliable) << d.index;
    }
  }
}

TEST(QrsDetector, ResetStartsANewStream) {
  const double fs = 360.0;
  std::vector<Beat> beats = regular_beats(0.5, 0.8, 39.5);
  beats[12].scale = 20.0;
  const std::vector<float> x = synthetic_beats(fs, 40.0, beats);
  const std::vector<float> other = synthetic_beats(fs, 13.3, regular_beats(0.2, 0.6, 13.0, 2.0));
  const Outputs fresh = run_new(fs, x);
  QrsDetector detector;
  ASSERT_EQ(detector.configure(fs), Status::kOk);
  (void)run(detector, other);
  detector.reset();
  const Outputs again = run(detector, x);
  ASSERT_EQ(again.detections.size(), fresh.detections.size());
  for (std::size_t i = 0; i < fresh.detections.size(); ++i) {
    EXPECT_TRUE(same(again.detections[i], fresh.detections[i])) << i;
    EXPECT_EQ(again.zones[i].peak, fresh.zones[i].peak);
    EXPECT_EQ(again.zones[i].first_part, fresh.zones[i].first_part);
    EXPECT_EQ(again.zones[i].second_part, fresh.zones[i].second_part);
  }
  EXPECT_EQ(again.squared, fresh.squared);
  // configure() also starts a new stream.
  ASSERT_EQ(detector.configure(fs), Status::kOk);
  const Outputs configured = run(detector, x);
  ASSERT_EQ(configured.detections.size(), fresh.detections.size());
  for (std::size_t i = 0; i < fresh.detections.size(); ++i) {
    EXPECT_TRUE(same(configured.detections[i], fresh.detections[i])) << i;
  }
}

TEST(QrsDetector, ZoneSumsCoverTheZoneSplitAtTheBlockBoundary) {
  for (const double fs : {250.0, 360.0}) {
    const DetectorSamples p = sinus::dsp::detector_samples(fs);
    const std::uint64_t block = sinus::dsp::quality_samples(fs).block;
    const Outputs r = run_new(fs, synthetic_beats(fs, 60.0, regular_beats(0.5, 0.77, 59.5)));
    ASSERT_FALSE(r.zones.empty());
    std::size_t crossing = 0;
    for (const ZoneSums& z : r.zones) {
      const std::uint64_t low = (z.peak + 1U >= p.window) ? z.peak + 1U - p.window : 0U;
      const std::uint64_t boundary = ((low / block) + 1U) * block;
      double first = 0.0;
      double second = 0.0;
      for (std::uint64_t k = low; k <= z.peak; ++k) {
        (k < boundary ? first : second) += static_cast<double>(r.squared[k]);
      }
      EXPECT_NEAR(z.first_part, first, 1e-5 * first) << z.peak;
      if (z.peak >= boundary) {
        ++crossing;
        EXPECT_NEAR(z.second_part, second, 1e-5 * (first + second)) << z.peak;
      } else {
        EXPECT_EQ(z.second_part, 0.0F) << z.peak;
      }
    }
    EXPECT_GE(crossing, 1U) << fs;
  }
}

TEST(QrsDetector, AtMostTheCapacityOfDetectionsPerSample) {
  const Outputs r = run_new(360.0, synthetic_beats(360.0, 30.0, regular_beats(0.3, 0.3, 29.5)));
  EXPECT_LE(*std::max_element(r.counts.begin(), r.counts.end()),
            sinus::dsp::kMaxDetectionsPerSample);
  // The first initialisation reports every beat of the first 2 s at L - 1.
  EXPECT_GE(r.counts[719], 6U);
}

TEST(QrsDetectorStore, KeepsThePeaksOfTheLastLearningStretchAtItsCapacity) {
  // A peak every 2 samples, the densest possible, at 1000 Hz (L = 2000): the store holds exactly
  // L / 2 = 1000 records, its capacity, and drops the oldest ones.
  QrsDetector detector;
  ASSERT_EQ(detector.configure(1000.0), Status::kOk);
  for (std::uint64_t m = 1; m < 10000; m += 2) {
    QrsDetectorProbe::store(detector, m);
    ASSERT_LE(QrsDetectorProbe::count(detector), sinus::dsp::kDetectorPeakStoreCapacity);
    ASSERT_EQ(QrsDetectorProbe::newest(detector), m);
    ASSERT_GE(QrsDetectorProbe::oldest(detector) + 2000U, m + 1U);  // m - L + 1 <= oldest
  }
  EXPECT_EQ(QrsDetectorProbe::count(detector), sinus::dsp::kDetectorPeakStoreCapacity);
  EXPECT_EQ(QrsDetectorProbe::oldest(detector), 9999U - 1998U);
  // A gap drops every record that has left the stretch.
  QrsDetectorProbe::store(detector, 20000U);
  EXPECT_EQ(QrsDetectorProbe::count(detector), 1U);
  detector.reset();
  EXPECT_EQ(QrsDetectorProbe::count(detector), 0U);
}

}  // namespace
