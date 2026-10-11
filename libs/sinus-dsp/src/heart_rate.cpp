// SRS-024, SRS-025, SRS-026: the heart-rate tracker (architecture-m2.md 13.5, 14.8). The two steps
// per sample of track_heart_rate (dsp/sinus_dsp/heart_rate.py), with integer decisions and the
// rate in binary32 (architecture-m2.md 14.3).
#include "sinus/dsp/heart_rate.hpp"

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

#include "interval_estimate.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

namespace {

constexpr double kMinIntervalMs = 300.0;   // 200 bpm (SRS-026)
constexpr double kMaxIntervalMs = 2000.0;  // 30 bpm (SRS-026)

// Element k of a fixed array, with k always in range by the callers.
template <typename Array>
auto& element(Array& array, std::size_t k) noexcept {
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-avoid-unchecked-container-access): k % size.
  return array[k % array.size()];
}

}  // namespace

Status HeartRateTracker::configure(double fs_hz) noexcept {
  configured_ = false;
  const Status status = validate(Config{fs_hz, 50});  // the checks of SRS-017 on fs_hz
  if (status != Status::kOk) {
    return status;
  }
  rate60_ = static_cast<float>(60.0 * fs_hz);
  wait_ = no_recent_beat_samples(fs_hz);
  // SRS-026: the mean interval from 300 ms to 2000 ms, bounds included: for k intervals,
  // ceil(300 k fs / 1000) <= span <= floor(2000 k fs / 1000).
  for (std::size_t k = 1; k <= kMeanWindow; ++k) {
    const auto intervals = static_cast<double>(k);
    element(low_, k) =
        static_cast<std::uint64_t>(std::ceil(((kMinIntervalMs * intervals) * fs_hz) / 1000.0));
    element(high_, k) =
        static_cast<std::uint64_t>(std::floor(((kMaxIntervalMs * intervals) * fs_hz) / 1000.0));
  }
  configured_ = true;
  start_stream();
  return Status::kOk;
}

void HeartRateTracker::reset() noexcept {
  if (configured_) {
    start_stream();  // SRS-024: no interval spans a reset
  }
}

void HeartRateTracker::start_stream() noexcept {
  intervals_ = {};
  kept_ = 0;
  count_ = 0;
  has_reset_ = false;
  reset_at_ = 0;
  has_previous_ = false;
  previous_index_ = 0;
  previous_startup_ = false;
  has_last_ = false;
  last_ = 0;
  has_fired_ = false;
  fired_for_ = 0;
  status_ = HeartRateStatus::kNotEnoughBeats;
  has_index_ = false;
  last_index_ = 0;
  n_ = 0;
}

// Step 2 of 13.5: "no recent beat" fires for the last reliable detection.
void HeartRateTracker::fire(std::uint64_t n, HeartRateStep& out) noexcept {
  has_fired_ = true;
  fired_for_ = last_;
  has_reset_ = true;
  reset_at_ = n;
  kept_ = 0;
  count_ = 0;
  if (status_ != HeartRateStatus::kNoRecentBeat) {
    status_ = HeartRateStatus::kNoRecentBeat;
    element(out.events, out.count) =
        HeartRateEvent{n, 0U, false, status_, std::numeric_limits<float>::quiet_NaN()};
    ++out.count;
  }
}

// Step 1 of 13.5 for a reliable detection (SRS-024).
void HeartRateTracker::reliable(std::uint64_t n, std::uint64_t index, HeartRateStep& out) noexcept {
  if (has_previous_ && !previous_startup_ && (!has_reset_ || previous_index_ > reset_at_)) {
    const std::uint64_t interval = index - previous_index_;
    if (kept_ == kMeanWindow) {
      for (std::size_t i = 1; i < kMeanWindow; ++i) {
        element(intervals_, i - 1) = element(intervals_, i);
      }
      --kept_;
    }
    element(intervals_, kept_) = interval;
    ++kept_;
    ++count_;
  }
  has_previous_ = true;
  previous_index_ = index;
  previous_startup_ = false;
  has_last_ = true;
  last_ = index;
  HeartRateEvent event{n, index, true, HeartRateStatus::kNotEnoughBeats,
                       std::numeric_limits<float>::quiet_NaN()};
  if (count_ < kEstimateMinIntervals) {
    event.status = has_reset_ ? HeartRateStatus::kNoRecentBeat : HeartRateStatus::kNotEnoughBeats;
  } else {
    const IntervalEstimate estimate = estimate_intervals(intervals_.data(), kept_);
    const bool in_range = element(low_, estimate.n_intervals) <= estimate.span_samples &&
                          estimate.span_samples <= element(high_, estimate.n_intervals);
    event.status = in_range ? HeartRateStatus::kValid : HeartRateStatus::kOutOfRange;
    // The rate: 60 fs k / span, in binary32, in this order (architecture-m2.md 14.3).
    event.bpm = (rate60_ * static_cast<float>(estimate.n_intervals)) /
                static_cast<float>(estimate.span_samples);
  }
  status_ = event.status;
  element(out.events, out.count) = event;
  ++out.count;
}

Status HeartRateTracker::step(const ReportedDetection* reported, std::size_t count,
                              HeartRateStep& out) noexcept {
  out = HeartRateStep{};
  if (!configured_) {
    return Status::kNotConfigured;
  }
  if (count > kMaxDetectionsPerSample || (count > 0 && reported == nullptr)) {
    return Status::kInvalidArgument;
  }
  // The preconditions on the indices, before any change of state.
  bool have = has_index_;
  std::uint64_t previous = last_index_;
  for (std::size_t i = 0; i < count; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): count entries are given.
    const std::uint64_t index = reported[i].index;
    if (index > n_ || (have && index <= previous)) {
      return Status::kInvalidArgument;
    }
    have = true;
    previous = index;
  }
  has_index_ = have;
  last_index_ = previous;

  const std::uint64_t n = n_;
  for (std::size_t i = 0; i < count; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): count entries are given.
    const ReportedDetection& detection = reported[i];
    if (detection.mark == Mark::kStartUp) {
      // SRS-024: a start-up detection enters no interval and gives no event.
      has_previous_ = true;
      previous_index_ = detection.index;
      previous_startup_ = true;
    } else {
      reliable(n, detection.index, out);
    }
  }
  // Step 2: no recent beat (SRS-026).
  if (has_last_ && (!has_fired_ || fired_for_ != last_) && n - last_ >= wait_) {
    fire(n, out);
  }
  ++n_;
  return Status::kOk;
}

}  // namespace sinus::dsp
