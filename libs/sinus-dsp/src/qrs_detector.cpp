// SRS-020, SRS-021, SRS-022: streaming QRS detection (architecture-m2.md 14.7). The procedure of
// architecture-m1.md 8.7.3 sample by sample, with the bookkeeping of architecture-m2.md 13.3 and
// the binary32 arithmetic of architecture-m2.md 14.3. The reference's _trace (dsp/sinus_dsp/qrs.py)
// is its specification: every step below names the part of _trace it reproduces.
#include "sinus/dsp/qrs_detector.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "array_index.hpp"
#include "compensated_sum.hpp"
#include "search_back_limit.hpp"
#include "sinus/dsp/biquad.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

namespace {

constexpr double kBandLowHz = 5.0;
constexpr double kBandHighHz = 15.0;
// The smallest binary32 value not below 1e-4 (architecture-m2.md 14.3, step 5): for every binary32
// y, y >= kMinIntegrated gives the result of the reference's y >= 1e-4.
constexpr float kMinIntegrated = 0x1.a36e3p-14F;

// Element k of a fixed ring (a ring indexed by the sample counter, or by head + offset). Every
// access to the arrays of the detector goes through it: the index is reduced modulo the size, so it
// is always in range, and the callers read only what the capacities of limits.hpp guarantee is
// still there (architecture-m2.md 14.7; unit tests DetectorCapacities).
template <typename Array>
auto& at(Array& ring, std::uint64_t k) noexcept {
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-avoid-unchecked-container-access): k % size.
  return ring[array_index(k % ring.size())];
}

// k - j for stream samples, as a signed number (the reference computes on Python integers).
std::int64_t diff(std::uint64_t k, std::uint64_t j) noexcept {
  return static_cast<std::int64_t>(k) - static_cast<std::int64_t>(j);
}

// The first sample of a stretch of `length` samples that ends at `last`, clipped at 0.
std::uint64_t first_of(std::uint64_t last, std::uint64_t length) noexcept {
  return (last + 1U >= length) ? (last + 1U - length) : 0U;
}

}  // namespace

Status QrsDetector::configure(double fs_hz) noexcept {
  configured_ = false;
  const Status status = validate(Config{fs_hz, 50});  // the checks of SRS-017 on fs_hz
  if (status != Status::kOk) {
    return status;
  }
  samples_ = detector_samples(fs_hz);
  block_ = quality_samples(fs_hz).block;
  highpass_.set(butterworth2_highpass(kBandLowHz, fs_hz));
  lowpass_.set(butterworth2_lowpass(kBandHighHz, fs_hz));
  c0_ = static_cast<float>(fs_hz / 8.0);
  c1_ = static_cast<float>(fs_hz / 4.0);
  configured_ = true;
  start_stream();
  return Status::kOk;
}

void QrsDetector::reset() noexcept {
  if (configured_) {
    start_stream();
  }
}

void QrsDetector::start_stream() noexcept {
  // The rings need no clearing: a sample before the start of the stream is never read (b[k] and
  // s[k] for k < 0 are zeros by the code that reads them), and the band-pass states are set by the
  // first sample.
  tracker_value_ = 0.0F;
  tracker_index_ = 0;
  tracker_has_index_ = false;
  previous_integrated_ = 0.0F;
  peaks_head_ = 0;
  peaks_count_ = 0;
  last_ = PeakRecord{};
  candidate_ = PeakRecord{};
  has_last_ = false;
  has_candidate_ = false;
  spki_ = 0.0F;
  npki_ = 0.0F;
  spkf_ = 0.0F;
  npkf_ = 0.0F;
  rr_head_ = 0;
  rr_count_ = 0;
  rr_flag_ = false;
  init_n_ = 0;
  initialised_ = false;
  path_ = DetectionPath::kNormal;
  n_ = 0;
}

Status QrsDetector::process(float conditioned_mv, DetectorStep& out) noexcept {
  out.squared_derivative = 0.0F;
  out.count = 0;
  if (!configured_) {
    return Status::kNotConfigured;
  }
  const std::uint64_t n = n_;
  const std::uint64_t window = samples_.window;

  // 1. Band-pass (architecture-m2.md 14.3, step 1), from the steady state of a constant input
  // equal to the first sample. The high-pass has a DC gain of exactly 0 in binary32
  // (b0 + b1 + b2 = norm - 2 norm + norm), so the low-pass starts from the state of a zero input.
  if (n == 0) {
    highpass_.start(conditioned_mv);
    lowpass_.start(0.0F);
  }
  const float b = lowpass_.step(highpass_.step(conditioned_mv));
  at(bandpassed_, n) = b;
  const auto band = [this, n](std::uint64_t lag) noexcept -> float {
    return (n >= lag) ? at(bandpassed_, n - lag) : 0.0F;
  };

  // 2. Derivative, in the order of 14.3 step 2; the tap of b[n-2] is zero and left out.
  const float c3 = -c1_;
  const float c4 = -c0_;
  const float d = (((c4 * band(4)) + (c3 * band(3))) + (c1_ * band(1))) + (c0_ * b);
  at(derivative_, n) = d;

  // 3. Squaring.
  const float s = d * d;
  at(squared_, n) = s;
  out.squared_derivative = s;

  // 4. Integration: s[n-N+1] .. s[n], oldest first; s[k] = 0 for k < 0 adds nothing.
  float sum = 0.0F;
  for (std::uint64_t k = first_of(n, window); k <= n; ++k) {
    sum += at(squared_, k);
  }
  const float y = sum / static_cast<float>(window);
  at(learning_integrated_, n) = y;
  at(learning_abs_bandpassed_, n) = std::fabs(b);

  // 5. Peak tracker (architecture-m1.md 8.7.2; _PeakTracker.step), for n >= 1.
  if (n >= 1) {
    if (y > previous_integrated_ && y > tracker_value_ && y >= kMinIntegrated) {
      tracker_value_ = y;
      tracker_index_ = n;
      tracker_has_index_ = true;
    } else if (tracker_has_index_ &&
               (y < tracker_value_ * 0.5F ||
                diff(n, tracker_index_) > static_cast<std::int64_t>(samples_.peak_timeout))) {
      // Step 1 of the procedure: the peak is stored, and classified once initialised.
      confirm_peak(n, out);
    }
  }
  previous_integrated_ = y;

  // Step 2: first initialisation, at the end of the learning period.
  if (n + 1U == samples_.learning) {
    initialise(n, out);
  } else if (n >= samples_.learning) {
    // Step 3: search-back, then re-learning.
    search_back(n, out);
    if (relearn_due(n)) {
      initialise(n, out);
    }
  }
  ++n_;
  return Status::kOk;
}

void QrsDetector::confirm_peak(std::uint64_t n, DetectorStep& out) noexcept {
  // The tracker restarts (v = 0, no index) and gives its peak m, with y[m] = v.
  const std::uint64_t m = tracker_index_;
  const float peak_i = tracker_value_;
  tracker_value_ = 0.0F;
  tracker_has_index_ = false;
  const std::uint64_t window = samples_.window;
  // Features (_peak_features): the first index of the largest |b| over [max(0, m-N-1), max(0,
  // m-2)].
  const std::uint64_t low = first_of(m, window + 2U);
  const std::uint64_t high = (m >= 2U) ? (m - 2U) : 0U;
  std::uint64_t k_star = low;
  float peak_f = std::fabs(at(bandpassed_, low));
  for (std::uint64_t k = low + 1U; k <= high; ++k) {
    const float magnitude = std::fabs(at(bandpassed_, k));
    if (magnitude > peak_f) {
      peak_f = magnitude;
      k_star = k;
    }
  }
  const std::uint64_t f = (k_star >= samples_.band_delay) ? (k_star - samples_.band_delay) : 0U;
  // The largest |d| over [max(0, m-N+1), m]; the zone of the signal quality index is the same
  // stretch, split at the block boundary that it crosses (architecture-m2.md 14.7).
  const std::uint64_t zone_low = first_of(m, window);
  const std::uint64_t boundary = ((zone_low / block_) + 1U) * block_;
  float slope = 0.0F;
  CompensatedSum first_part;
  CompensatedSum second_part;
  for (std::uint64_t k = zone_low; k <= m; ++k) {
    const float dk = at(derivative_, k);
    slope = std::max(slope, std::fabs(dk));
    if (k < boundary) {
      first_part.add(dk * dk);
    } else {
      second_part.add(dk * dk);
    }
  }
  const PeakRecord peak{m,
                        static_cast<std::uint16_t>(m - f),
                        peak_i,
                        peak_f,
                        slope,
                        first_part.value(),
                        (m >= boundary) ? second_part.value() : 0.0F};
  store(peak);
  if (initialised_) {
    classify(peak, n, out);
  }
}

void QrsDetector::store(const PeakRecord& peak) noexcept {
  // Decisions.store: drop the records whose m can no longer enter a learning window, then append.
  // Dropping first keeps at most L / 2 records (consecutive peaks are at least 2 samples apart),
  // so the store never overflows (architecture-m2.md 14.7).
  const std::uint64_t oldest = first_of(peak.m, samples_.learning);
  while (peaks_count_ > 0 && at(peaks_, peaks_head_).m < oldest) {
    peaks_head_ = (peaks_head_ + 1U) % peaks_.size();
    --peaks_count_;
  }
  if (peaks_count_ == peaks_.size()) {  // unreachable by the bound above; keeps the ring valid
    peaks_head_ = (peaks_head_ + 1U) % peaks_.size();
    --peaks_count_;
  }
  at(peaks_, peaks_head_ + peaks_count_) = peak;
  ++peaks_count_;
}

void QrsDetector::classify(const PeakRecord& peak, std::uint64_t n, DetectorStep& out) noexcept {
  // _Decisions.classify, in its order.
  const auto refractory = static_cast<std::int64_t>(samples_.refractory);
  const std::uint64_t f = peak.m - peak.m_minus_f;
  // 1. Refractory period, on the peak position and on the reported index.
  if (has_last_) {
    const std::uint64_t last_f = last_.m - last_.m_minus_f;
    if (diff(peak.m, last_.m) < refractory || diff(f, last_f) < refractory) {
      return;
    }
  }
  // 2. Above the first thresholds of both signals.
  const float threshold_i1 = npki_ + (0.25F * (spki_ - npki_));
  const float threshold_f1 = npkf_ + (0.25F * (spkf_ - npkf_));
  if (peak.peak_i > threshold_i1 && peak.peak_f > threshold_f1) {
    if (has_last_ && diff(peak.m, last_.m) < static_cast<std::int64_t>(samples_.t_wave_window) &&
        peak.slope < 0.5F * last_.slope) {
      noise(peak);  // T wave
      return;
    }
    accept(peak, false, n, out);
    return;
  }
  // 3. Noise peak; the largest one since the last QRS is the search-back candidate.
  noise(peak);
  if (!has_candidate_ || peak.peak_i > candidate_.peak_i) {
    candidate_ = peak;
    has_candidate_ = true;
  }
}

void QrsDetector::accept(const PeakRecord& peak, bool search_back, std::uint64_t n,
                         DetectorStep& out) noexcept {
  // _Decisions._accept.
  if (search_back) {
    spki_ = (0.25F * peak.peak_i) + (0.75F * spki_);
    spkf_ = (0.25F * peak.peak_f) + (0.75F * spkf_);
  } else {
    spki_ = (0.125F * peak.peak_i) + (0.875F * spki_);
    spkf_ = (0.125F * peak.peak_f) + (0.875F * spkf_);
  }
  if (has_last_ && rr_flag_) {
    const std::uint64_t interval = peak.m - last_.m;
    if (rr_count_ == rr_intervals_.size()) {  // the oldest is dropped beyond 8
      rr_head_ = (rr_head_ + 1U) % rr_intervals_.size();
      --rr_count_;
    }
    at(rr_intervals_, rr_head_ + rr_count_) = interval;
    ++rr_count_;
  }
  last_ = peak;
  has_last_ = true;
  rr_flag_ = true;
  has_candidate_ = false;
  // SRS-022: the mark uses the latest initialisation i: start-up if max(0, i-L+1) <= f <= i.
  const std::uint64_t f = peak.m - peak.m_minus_f;
  const bool startup = first_of(init_n_, samples_.learning) <= f && f <= init_n_;
  // SRS-020, SRS-021: the detection, reported at n. The count is at most kMaxDetectionsPerSample
  // (architecture-m2.md 14.4, "Capacities per sample").
  if (out.count < out.detections.size()) {
    at(out.detections, out.count) =
        Detection{f, n, startup ? Mark::kStartUp : Mark::kReliable, path_};
    at(out.zones, out.count) = ZoneSums{peak.m, peak.zone_first, peak.zone_second};
    ++out.count;
  }
}

void QrsDetector::noise(const PeakRecord& peak) noexcept {
  npki_ = (0.125F * peak.peak_i) + (0.875F * npki_);
  npkf_ = (0.125F * peak.peak_f) + (0.875F * npkf_);
}

void QrsDetector::search_back(std::uint64_t n, DetectorStep& out) noexcept {
  if (!has_last_ || !has_candidate_ || rr_count_ == 0) {
    return;
  }
  // The limit floor(1.66 * fsum(rr) / count + 0.5) in integers (architecture-m2.md 14.3, step 9).
  std::uint64_t total = 0;
  for (std::size_t i = 0; i < rr_count_; ++i) {
    total += at(rr_intervals_, rr_head_ + i);
  }
  const std::uint64_t limit = search_back_limit(total, rr_count_);
  const float threshold_i2 = 0.5F * (npki_ + (0.25F * (spki_ - npki_)));
  const float threshold_f2 = 0.5F * (npkf_ + (0.25F * (spkf_ - npkf_)));
  if (n - last_.m >= limit && candidate_.peak_i > threshold_i2 &&
      candidate_.peak_f > threshold_f2) {
    path_ = DetectionPath::kSearchBack;
    const PeakRecord candidate = candidate_;
    accept(candidate, true, n, out);
    path_ = DetectionPath::kNormal;
  }
}

bool QrsDetector::relearn_due(std::uint64_t n) const noexcept {
  const std::uint64_t reference = has_last_ ? std::max(last_.m, init_n_) : init_n_;
  return n - reference >= samples_.relearn_after;
}

void QrsDetector::initialise(std::uint64_t n, DetectorStep& out) noexcept {
  // _Decisions.initialise: the levels from the last L samples, then their peaks classified again.
  const std::uint64_t low = first_of(n, samples_.learning);
  const auto count = static_cast<float>(n + 1U - low);
  float max_integrated = at(learning_integrated_, low);
  float max_abs_bandpassed = at(learning_abs_bandpassed_, low);
  CompensatedSum sum_integrated;
  CompensatedSum sum_abs_bandpassed;
  for (std::uint64_t k = low; k <= n; ++k) {
    const float yk = at(learning_integrated_, k);
    const float bk = at(learning_abs_bandpassed_, k);
    max_integrated = std::max(max_integrated, yk);
    max_abs_bandpassed = std::max(max_abs_bandpassed, bk);
    sum_integrated.add(yk);
    sum_abs_bandpassed.add(bk);
  }
  spki_ = max_integrated / 3.0F;
  npki_ = (sum_integrated.value() / count) / 2.0F;
  spkf_ = max_abs_bandpassed / 3.0F;
  npkf_ = (sum_abs_bandpassed.value() / count) / 2.0F;
  rr_head_ = 0;
  rr_count_ = 0;
  has_candidate_ = false;
  rr_flag_ = false;
  init_n_ = n;
  initialised_ = true;
  // The last QRS is kept, for the refractory period and the output spacing.
  path_ = DetectionPath::kLearning;
  for (std::size_t i = 0; i < peaks_count_; ++i) {
    const PeakRecord& peak = at(peaks_, peaks_head_ + i);
    if (low <= peak.m && peak.m <= n) {
      classify(peak, n, out);
    }
  }
  path_ = DetectionPath::kNormal;
}

}  // namespace sinus::dsp
