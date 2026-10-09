#pragma once

// Helpers of the detection requirement tests (QA): run a Chain one sample at a time and collect
// the detections it reports, and score them against known R-wave positions with the criteria of
// SRS-006 stated in samples.

#include <gtest/gtest.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/limits.hpp"

namespace sinus_qa {

using sinus::dsp::DetectionPath;
using sinus::dsp::Mark;

struct Det {
  std::uint64_t index;
  std::uint64_t reported_at;
  Mark mark;
  DetectionPath path;
};

inline bool operator==(const Det& a, const Det& b) {
  return a.index == b.index && a.reported_at == b.reported_at && a.mark == b.mark &&
         a.path == b.path;
}

// Learning samples L = round(2 fs): the 2 s of SRS-022.
inline std::uint64_t learning_samples(int fs) { return static_cast<std::uint64_t>(2 * fs); }

// Feed ecg to `chain` one sample at a time, starting at stream sample 0 of the chain's current
// stream (the chain was configured or reset just before). Checks, at every sample, the status,
// the count bound, that every entry is reported at the current sample and not before its index.
// Detections of the sample are appended in the order reported.
inline std::vector<Det> feed(sinus::dsp::Chain& chain, const std::vector<float>& ecg,
                             std::size_t first = 0) {
  std::vector<Det> all;
  sinus::dsp::SampleOutput out;  // reused: a stale count would show
  for (std::size_t i = first; i < ecg.size(); ++i) {
    const std::uint64_t n = i - first;
    const sinus::dsp::Status st = chain.process(ecg[i], out);
    EXPECT_EQ(st, sinus::dsp::Status::kOk) << "sample " << n;
    if (st != sinus::dsp::Status::kOk) {
      break;
    }
    EXPECT_LE(out.detection_count, sinus::dsp::kMaxDetectionsPerSample) << "sample " << n;
    const std::size_t count = std::min(out.detection_count, sinus::dsp::kMaxDetectionsPerSample);
    for (std::size_t j = 0; j < count; ++j) {
      const auto& d = out.detections[j];
      EXPECT_EQ(d.reported_at, n) << "sample " << n;
      EXPECT_LE(d.index, d.reported_at) << "sample " << n;
      all.push_back({d.index, d.reported_at, d.mark, d.path});
    }
  }
  return all;
}

inline std::vector<Det> run_chain(const std::vector<float>& ecg, int fs, int mains) {
  sinus::dsp::Chain chain;
  const sinus::dsp::Status st = chain.configure(sinus::dsp::Config{static_cast<double>(fs), mains});
  EXPECT_EQ(st, sinus::dsp::Status::kOk);
  if (st != sinus::dsp::Status::kOk) {
    return {};
  }
  return feed(chain, ecg);
}

inline std::int64_t within_150_ms(int fs) { return (150 * fs) / 1000; }
inline std::int64_t min_spacing_200_ms(int fs) { return (200 * fs + 999) / 1000; }

// SRS-006 criteria on `dets` for known R positions `r` in a stream of n samples:
// - indices strictly increasing and no two closer than 200 ms;
// - every detection lies within 150 ms of exactly one R, and each R has at most one detection;
// - each R with r + tail < n has one (the last beats may be reported after the end).
// Returns the offsets (index - r) of the detections, in order.
inline std::vector<std::int64_t> expect_one_per_beat(const std::vector<Det>& dets,
                                                     const std::vector<std::int64_t>& r,
                                                     std::size_t n, int fs) {
  std::vector<std::int64_t> offsets;
  const std::int64_t tol = within_150_ms(fs);
  const std::int64_t gap = min_spacing_200_ms(fs);
  std::vector<int> hits(r.size(), 0);
  for (std::size_t i = 0; i < dets.size(); ++i) {
    const auto idx = static_cast<std::int64_t>(dets[i].index);
    if (i > 0) {
      const auto prev = static_cast<std::int64_t>(dets[i - 1].index);
      EXPECT_GT(idx, prev) << "not increasing at " << idx;
      EXPECT_GE(idx - prev, gap) << "closer than 200 ms at " << idx;
    }
    int near = 0;
    for (std::size_t k = 0; k < r.size(); ++k) {
      if (std::abs(idx - r[k]) <= tol) {
        ++hits[k];
        ++near;
        offsets.push_back(idx - r[k]);
      }
    }
    EXPECT_EQ(near, 1) << "detection at " << idx << " is not within 150 ms of exactly one beat";
  }
  const std::int64_t tail = (400 * fs) / 1000;  // above the 0.31 s of the normal path
  for (std::size_t k = 0; k < r.size(); ++k) {
    if (r[k] + tail < static_cast<std::int64_t>(n)) {
      EXPECT_EQ(hits[k], 1) << "beat at sample " << r[k];
    } else {
      EXPECT_LE(hits[k], 1) << "beat at sample " << r[k];
    }
  }
  return offsets;
}

}  // namespace sinus_qa
