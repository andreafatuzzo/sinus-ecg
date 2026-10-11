#pragma once

// SRS-024, SRS-025, SRS-026: the heart rate from the reliable detections (architecture-m2.md 13.5,
// 14.4, 14.8). HeartRateTracker is dsp/sinus_dsp/heart_rate.py (track_heart_rate) made streaming:
// the same state, the same two steps per sample, the same estimator; every decision is made on
// integers and only the rate is a binary32 number (architecture-m2.md 14.3).

#include <array>
#include <cstddef>
#include <cstdint>

#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

enum class HeartRateStatus : std::uint8_t { kValid, kNotEnoughBeats, kNoRecentBeat, kOutOfRange };

struct HeartRateEvent {
  std::uint64_t sample;      // the sample at which it is reported
  std::uint64_t beat_index;  // index of its reliable detection; meaningful when has_beat
  bool has_beat;             // false for a change of status at no detection
  HeartRateStatus status;
  float bpm;  // kValid and kOutOfRange; a quiet NaN otherwise
};

struct ReportedDetection {
  std::uint64_t index;
  Mark mark;
};

struct HeartRateStep {
  std::size_t count = 0;
  std::array<HeartRateEvent, kMaxHeartRateEventsPerSample> events{};
};

class HeartRateTracker {
 public:
  // SRS-017: the checks on fs_hz; a failure leaves the tracker not configured. On success a new
  // stream starts, as after reset().
  [[nodiscard]] Status configure(double fs_hz) noexcept;
  // SRS-024: a new stream: no interval kept, the status "not enough beats".
  void reset() noexcept;
  // SRS-024, SRS-025, SRS-026: one sample of the stream, with the detections reported at it, in
  // order. Also the entry point with which the tests give sequences of detections directly.
  // kNotConfigured before configure; kInvalidArgument (no state changed, out empty) for a count
  // above kMaxDetectionsPerSample, a null pointer with a non-zero count, an index above the
  // current sample, or an index not greater than every earlier one.
  [[nodiscard]] Status step(const ReportedDetection* reported, std::size_t count,
                            HeartRateStep& out) noexcept;

 private:
  static constexpr std::size_t kMeanWindow = 6;  // intervals kept (architecture-m2.md 13.5)

  void start_stream() noexcept;
  void fire(std::uint64_t n, HeartRateStep& out) noexcept;
  void reliable(std::uint64_t n, std::uint64_t index, HeartRateStep& out) noexcept;

  // Configuration.
  std::uint64_t wait_ = 0;
  std::array<std::uint64_t, kMeanWindow + 1> low_{};   // by k: ceil(300 k fs / 1000)
  std::array<std::uint64_t, kMeanWindow + 1> high_{};  // by k: floor(2000 k fs / 1000)
  float rate60_ = 0.0F;                                // 60 * fs, rounded once to binary32

  // The stream.
  std::array<std::uint64_t, kMeanWindow> intervals_{};  // oldest first
  std::size_t kept_ = 0;                                // intervals held, up to 6
  std::uint64_t count_ = 0;                             // intervals since the last reset
  std::uint64_t reset_at_ = 0;
  std::uint64_t previous_index_ = 0;
  std::uint64_t last_ = 0;  // the last reliable detection reported
  std::uint64_t fired_for_ = 0;
  std::uint64_t last_index_ = 0;
  std::uint64_t n_ = 0;  // the current sample of the stream
  HeartRateStatus status_ = HeartRateStatus::kNotEnoughBeats;
  bool configured_ = false;
  bool has_reset_ = false;  // reset_at >= 0
  bool has_previous_ = false;
  bool previous_startup_ = false;
  bool has_last_ = false;
  bool has_fired_ = false;  // "no recent beat" has fired for fired_for_
  bool has_index_ = false;  // any detection given since the stream began
};

}  // namespace sinus::dsp
