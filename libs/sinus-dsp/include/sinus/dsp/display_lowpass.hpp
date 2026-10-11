#pragma once

// SRS-044: the display low-pass (architecture-m3.md 16.2, 16.6): a Hamming-windowed sinc of
// cut-off 50 Hz and 2M + 1 taps, M = round(30 ms * fs), linear phase with a constant delay of M
// samples. It filters the binary64 output of the mains stage in binary64, in the operation order
// of the reference (dsp/sinus_dsp/display.py), and rounds the result once to binary32. The
// arithmetic is in display_lowpass.cpp, compiled without contraction into fused multiply-adds.

#include <array>
#include <cstddef>
#include <cstdint>

#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

inline constexpr double kDisplayCutoffHz = 50.0;
inline constexpr double kDisplayHalfLengthMs = 30.0;
using DisplayTaps = std::array<double, kDisplayTapCapacity>;

// SRS-044: M = floor(30 * fs / 1000 + 0.5). Precondition: a sampling frequency that validate()
// accepts.
[[nodiscard]] std::uint32_t display_delay_samples(double fs_hz) noexcept;
// SRS-044: writes the 2M + 1 taps of architecture-m3.md 16.2 to taps[0 .. 2M] and 0.0 to the
// rest; returns 2M + 1. Precondition: a sampling frequency that validate() accepts.
std::size_t display_lowpass_taps(double fs_hz, DisplayTaps& taps) noexcept;

class DisplayLowpass {
 public:
  // SRS-017: kInvalidSamplingFrequency for a sampling frequency that validate() rejects; a
  // failure leaves the stage not configured. On success a new stream starts, as after reset().
  [[nodiscard]] Status configure(double fs_hz) noexcept;
  // SRS-031: the next sample starts a new stream (the taps are kept).
  void reset() noexcept;
  // SRS-044: the display value given with this sample, that of the sample M earlier. The first
  // value of a stream fills the history (the steady state of a constant input). Precondition: a
  // finite value. Returns kNotConfigured, with display_mv 0, before a successful configure.
  [[nodiscard]] Status process(double conditioned_mv, float& display_mv) noexcept;
  [[nodiscard]] std::uint32_t delay_samples() const noexcept;  // M; 0 when not configured
  [[nodiscard]] std::size_t tap_count() const noexcept;        // N; 0 when not configured
  [[nodiscard]] const DisplayTaps& taps() const noexcept { return taps_; }

 private:
  DisplayTaps taps_{};
  std::array<double, kDisplayTapCapacity> history_{};  // x[n - k] at (n - k) mod N
  std::uint64_t n_ = 0;                                // the current sample of the stream
  std::size_t tap_count_ = 0;
  std::uint32_t delay_ = 0;
  bool configured_ = false;
  bool started_ = false;  // the first sample of the stream has been given
};

}  // namespace sinus::dsp
