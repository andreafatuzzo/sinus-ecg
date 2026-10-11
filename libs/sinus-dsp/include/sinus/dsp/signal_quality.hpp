#pragma once

// SRS-027, SRS-028: the signal quality index per window of ten blocks of about 1 s, made streaming
// with a ring of blocks (architecture-m2.md 13.6, 14.4, 14.9). The reference is
// dsp/sinus_dsp/quality.py (assess_quality); the arithmetic is binary32 (architecture-m2.md 14.3).

#include <array>
#include <cstddef>
#include <cstdint>

#include "sinus/dsp/config.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

inline constexpr float kUsableThreshold = 0.5F;    // SRS-027 (architecture-m2.md 13.6)
inline constexpr float kBackgroundWeight = 16.0F;  // K of the index (architecture-m2.md 13.6)

struct QualityWindow {
  std::uint64_t first_sample, last_sample, reported_at;
  float index;  // 0 to 1
  bool usable;  // index >= kUsableThreshold
};

class SignalQuality {
 public:
  // SRS-017: the checks on fs_hz; a failure leaves the object not configured. On success a new
  // stream starts, as after reset().
  [[nodiscard]] Status configure(double fs_hz) noexcept;
  // SRS-027: a new stream; the windows start again from its first sample.
  void reset() noexcept;
  // SRS-027, SRS-028: one sample: the input sample as given, and the detector's output for it.
  // has_window tells whether a window is reported at this sample (window then holds it).
  // kNotConfigured before configure; kInvalidArgument (no state changed) if the detector's count
  // is above kMaxDetectionsPerSample.
  [[nodiscard]] Status step(float input_mv, const DetectorStep& detector, bool& has_window,
                            QualityWindow& window) noexcept;

 private:
  // The blocks in the ring: a window covers 10 blocks and is reported in the 11th; 12 slots.
  static constexpr std::size_t kRing = 12;
  struct Accumulator {  // a compensated sum (compensated_sum.hpp, private)
    float sum = 0.0F;
    float compensation = 0.0F;
  };
  struct Block {
    Accumulator total;               // s over the block
    Accumulator zone;                // the zone parts added to the block
    std::uint32_t zone_samples = 0;  // their samples
    std::uint32_t detections = 0;    // reported detections whose index lies in the block
    std::uint64_t held_max = 0;      // the longest run of equal input samples ending in the block
    std::uint64_t held_end = 0;      // the run at the block's last sample
  };

  void start_stream() noexcept;
  void add_detection(const Detection& detection, const ZoneSums& zone) noexcept;
  [[nodiscard]] Block* block_of(std::uint64_t number) noexcept;
  [[nodiscard]] QualityWindow make_window(std::uint64_t k) noexcept;
  [[nodiscard]] Block& slot(std::uint64_t number) noexcept;

  QualitySamples samples_{};
  bool configured_ = false;

  std::array<Block, kRing> ring_{};
  std::uint64_t held_run_ = 0;
  float previous_input_ = 0.0F;
  std::uint64_t next_window_ = 0;  // the window reported next
  std::uint64_t n_ = 0;            // the current sample of the stream
};

}  // namespace sinus::dsp
