// SRS-044: the display low-pass in binary64, in the operation order of the reference
// (dsp/sinus_dsp/display.py; architecture-m3.md 16.2, 16.6).
#include "sinus/dsp/display_lowpass.hpp"

#include <cmath>
#include <cstddef>
#include <cstdint>

#include "array_index.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

namespace {

// The binary64 value nearest to pi (Python math.pi); C++17 has no std::numbers.
constexpr double kPi = 3.141592653589793;

// Element k of a fixed array, with k always in range by the callers.
template <typename Array>
auto& element(Array& array, std::size_t k) noexcept {
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-avoid-unchecked-container-access): k % size.
  return array[k % array.size()];
}

}  // namespace

std::uint32_t display_delay_samples(double fs_hz) noexcept {
  // SRS-044: round_samples_ms(30, fs) of the reference.
  return static_cast<std::uint32_t>(std::floor(((kDisplayHalfLengthMs * fs_hz) / 1000.0) + 0.5));
}

std::size_t display_lowpass_taps(double fs_hz, DisplayTaps& taps) noexcept {
  taps.fill(0.0);
  const std::uint32_t m = display_delay_samples(fs_hz);
  const std::size_t n_taps = (2 * std::size_t{m}) + 1;
  if (n_taps > taps.size()) {
    return 0;  // outside the precondition: no taps
  }
  const double fc = kDisplayCutoffHz;
  const auto last = static_cast<double>(n_taps - 1);
  // raw[k] = window * ideal, each operation in the order written (architecture-m3.md 16.2).
  for (std::size_t k = 0; k < n_taps; ++k) {
    const std::int64_t j_int = static_cast<std::int64_t>(k) - static_cast<std::int64_t>(m);
    const auto j = static_cast<double>(j_int);
    const double ideal =
        j_int == 0 ? (2.0 * fc) / fs_hz : std::sin((((2.0 * kPi) * fc) * j) / fs_hz) / (kPi * j);
    const double window = 0.54 - (0.46 * std::cos(((2.0 * kPi) * static_cast<double>(k)) / last));
    element(taps, k) = window * ideal;
  }
  // The total added one term at a time in index order, then one division per tap.
  double total = 0.0;
  for (std::size_t k = 0; k < n_taps; ++k) {
    total = total + element(taps, k);
  }
  for (std::size_t k = 0; k < n_taps; ++k) {
    element(taps, k) = element(taps, k) / total;
  }
  return n_taps;
}

Status DisplayLowpass::configure(double fs_hz) noexcept {
  configured_ = false;
  started_ = false;
  n_ = 0;
  delay_ = 0;
  tap_count_ = 0;
  taps_.fill(0.0);
  const Status status = validate(Config{fs_hz, 50});  // the checks of SRS-017 on fs_hz
  if (status != Status::kOk) {
    return status;
  }
  tap_count_ = display_lowpass_taps(fs_hz, taps_);
  delay_ = display_delay_samples(fs_hz);
  configured_ = true;
  return Status::kOk;
}

void DisplayLowpass::reset() noexcept {
  // SRS-031: the taps are kept; the first sample of the new stream fills the history.
  started_ = false;
  n_ = 0;
}

Status DisplayLowpass::process(double conditioned_mv, float& display_mv) noexcept {
  if (!configured_) {
    display_mv = 0.0F;
    return Status::kNotConfigured;
  }
  if (!started_) {
    history_.fill(conditioned_mv);  // x[i] = x[0] for i < 0 (architecture-m3.md 16.2)
    started_ = true;
  }
  const std::size_t n_taps = tap_count_;
  const std::size_t now = array_index(n_ % n_taps);
  element(history_, now) = conditioned_mv;
  // y[n] = (...((h[0] x[n] + h[1] x[n-1]) + h[2] x[n-2]) + ...) + h[N-1] x[n-N+1]
  double acc = element(taps_, 0) * conditioned_mv;
  for (std::size_t k = 1; k < n_taps; ++k) {
    const std::size_t position = (now + n_taps - k) % n_taps;
    acc = acc + (element(taps_, k) * element(history_, position));
  }
  ++n_;
  display_mv = static_cast<float>(acc);  // one rounding to binary32
  return Status::kOk;
}

std::uint32_t DisplayLowpass::delay_samples() const noexcept { return delay_; }

std::size_t DisplayLowpass::tap_count() const noexcept { return tap_count_; }

}  // namespace sinus::dsp
