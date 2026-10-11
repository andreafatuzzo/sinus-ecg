// SRS-027, SRS-028: the signal quality index, streaming (architecture-m2.md 13.6, 14.9). The
// computation of assess_quality (dsp/sinus_dsp/quality.py) with a ring of blocks instead of the
// whole stream, in the binary32 arithmetic of architecture-m2.md 14.3.
#include "sinus/dsp/signal_quality.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>

#include "array_index.hpp"
#include "compensated_sum.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

namespace {

constexpr std::uint64_t kWindowBlocks = 10;   // SRS-027
constexpr std::uint64_t kHeldBlocks = 5;      // SRS-028
constexpr std::uint32_t kMinDetections = 4;   // SRS-028
constexpr std::uint32_t kMaxDetections = 34;  // SRS-028

// The first sample of a stretch of `length` samples that ends at `last`, clipped at 0.
std::uint64_t first_of(std::uint64_t last, std::uint64_t length) noexcept {
  return (last + 1U >= length) ? (last + 1U - length) : 0U;
}

}  // namespace

Status SignalQuality::configure(double fs_hz) noexcept {
  configured_ = false;
  const Status status = validate(Config{fs_hz, 50});  // the checks of SRS-017 on fs_hz
  if (status != Status::kOk) {
    return status;
  }
  samples_ = quality_samples(fs_hz);
  configured_ = true;
  start_stream();
  return Status::kOk;
}

void SignalQuality::reset() noexcept {
  if (configured_) {
    start_stream();  // SRS-027: the windows start again from the first sample after the reset
  }
}

void SignalQuality::start_stream() noexcept {
  ring_ = {};
  held_run_ = 0;
  previous_input_ = 0.0F;
  next_window_ = 0;
  n_ = 0;
}

SignalQuality::Block& SignalQuality::slot(std::uint64_t number) noexcept {
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-avoid-unchecked-container-access): number % size.
  return ring_[array_index(number % kRing)];
}

// SRS-027: the zone of a detection is the N samples that end at its peak, split at the block
// boundary that it crosses (the parts were summed by the detector); its index is counted in the
// block that holds it. Blocks that have left the ring are not needed by any window still to come.
void SignalQuality::add_detection(const Detection& detection, const ZoneSums& zone) noexcept {
  const std::uint64_t h = samples_.block;
  const std::uint64_t current = n_ / h;
  const auto in_ring = [current](std::uint64_t number) {
    return number <= current && current - number < kRing;
  };
  const std::uint64_t index_block = detection.index / h;
  if (in_ring(index_block)) {
    ++slot(index_block).detections;
  }
  const std::uint64_t zone_low = first_of(zone.peak, samples_.zone);
  const std::uint64_t first_block = zone_low / h;
  const std::uint64_t boundary = (first_block + 1U) * h;
  if (in_ring(first_block)) {
    Block& block = slot(first_block);
    compensated_add(block.zone.sum, block.zone.compensation, zone.first_part);
    block.zone_samples += static_cast<std::uint32_t>(std::min(zone.peak + 1U, boundary) - zone_low);
  }
  if (zone.peak >= boundary && in_ring(first_block + 1U)) {
    Block& block = slot(first_block + 1U);
    compensated_add(block.zone.sum, block.zone.compensation, zone.second_part);
    block.zone_samples += static_cast<std::uint32_t>(zone.peak - boundary + 1U);
  }
}

// SRS-027, SRS-028: window k, from blocks k to k + 9.
QualityWindow SignalQuality::make_window(std::uint64_t k) noexcept {
  const std::uint64_t h = samples_.block;
  const std::uint64_t w = samples_.window;
  float total_sum = 0.0F;
  float total_compensation = 0.0F;
  float zone_sum = 0.0F;
  float zone_compensation = 0.0F;
  std::uint64_t zone_samples = 0;
  std::uint64_t detections = 0;
  std::uint64_t held_longest = slot(k + (kHeldBlocks - 1U)).held_end;
  for (std::uint64_t j = 0; j < kWindowBlocks; ++j) {
    const Block& block = slot(k + j);
    compensated_add(total_sum, total_compensation,
                    compensated_value(block.total.sum, block.total.compensation));
    compensated_add(zone_sum, zone_compensation,
                    compensated_value(block.zone.sum, block.zone.compensation));
    zone_samples += block.zone_samples;
    detections += block.detections;
    if (j >= kHeldBlocks) {
      held_longest = std::max(held_longest, block.held_max);
    }
  }
  const bool held = held_longest >= samples_.held;  // SRS-028: 5 s held inside the window
  QualityWindow result{k * h, (k * h) + w - 1U, n_, 0.0F, false};
  if (zone_samples > 0 && zone_samples < w) {
    const float e_total = compensated_value(total_sum, total_compensation);
    const float e_zone = compensated_value(zone_sum, zone_compensation);
    const float signal = e_zone / static_cast<float>(zone_samples);
    const float background =
        std::max(0.0F, e_total - e_zone) / static_cast<float>(w - zone_samples);
    const float denominator = signal + (kBackgroundWeight * background);
    // SRS-028: 0 for a held input and for an implausible number of detections.
    if (!held && detections >= kMinDetections && detections <= kMaxDetections &&
        denominator > 0.0F) {
      result.index = signal / denominator;
    }
  }
  result.usable = result.index >= kUsableThreshold;
  return result;
}

Status SignalQuality::step(float input_mv, const DetectorStep& detector, bool& has_window,
                           QualityWindow& window) noexcept {
  has_window = false;
  window = QualityWindow{};
  if (!configured_) {
    return Status::kNotConfigured;
  }
  if (detector.count > kMaxDetectionsPerSample) {
    return Status::kInvalidArgument;
  }
  const std::uint64_t h = samples_.block;
  const std::uint64_t n = n_;
  Block& block = slot(n / h);
  if (n % h == 0) {
    block = Block{};
  }
  // The run of equal consecutive input samples, as given (SRS-028); neither < nor > is exact
  // equality for the finite samples that the chain passes.
  if (n > 0 && !(input_mv < previous_input_) && !(input_mv > previous_input_)) {
    ++held_run_;
  } else {
    held_run_ = 1;
  }
  previous_input_ = input_mv;
  block.held_max = std::max(block.held_max, held_run_);
  block.held_end = held_run_;
  compensated_add(block.total.sum, block.total.compensation, detector.squared_derivative);
  for (std::size_t i = 0; i < detector.count; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-avoid-unchecked-container-access): count checked.
    add_detection(detector.detections[i], detector.zones[i]);
  }
  // SRS-027: window k is reported at its last sample plus the report delay.
  if (n == (next_window_ * h) + samples_.window - 1U + samples_.report_delay) {
    window = make_window(next_window_);
    has_window = true;
    ++next_window_;
  }
  ++n_;
  return Status::kOk;
}

}  // namespace sinus::dsp
