#pragma once

// SRS-019: filter design in binary64 and the second-order sections of the conditioning
// (architecture-m2.md 14.3, 14.4). The arithmetic is in the sources of the library, which are
// compiled without contraction into fused multiply-adds (OP-057).

namespace sinus::dsp {

// a0 = 1, as the rows of the reference: [b0, b1, b2, 1, a1, a2].
struct BiquadCoefficients {
  double b0, b1, b2, a1, a2;
};

// Designs of the reference (filters.py), in the same order of operations. Preconditions: a
// sampling frequency that validate() accepts, 0 < frequency < fs / 2, q > 0.
[[nodiscard]] BiquadCoefficients butterworth2_highpass(double cutoff_hz, double fs_hz) noexcept;
[[nodiscard]] BiquadCoefficients butterworth2_lowpass(double cutoff_hz, double fs_hz) noexcept;
[[nodiscard]] BiquadCoefficients notch(double notch_hz, double q, double fs_hz) noexcept;
// SRS-019: the 0.5 Hz high-pass of the baseline wander stage.
[[nodiscard]] BiquadCoefficients baseline_coefficients(double fs_hz) noexcept;
// SRS-019: the notch of the mains stage, Q = 30; mains_hz is 50 or 60.
[[nodiscard]] BiquadCoefficients mains_coefficients(double fs_hz, int mains_hz) noexcept;

// Transposed direct form II in binary64, the operation order of scipy.signal.sosfilt.
class BiquadF64 {
 public:
  void set(const BiquadCoefficients& c) noexcept;  // new coefficients, zero state
  // The steady state for a constant input equal to first_input (reference: initial_state).
  void start(double first_input) noexcept;
  [[nodiscard]] double step(double x) noexcept;

 private:
  double b0_ = 0.0, b1_ = 0.0, b2_ = 0.0, a1_ = 0.0, a2_ = 0.0;
  double z1_ = 0.0, z2_ = 0.0;
};

// The same in binary32, with the coefficients rounded once.
class BiquadF32 {
 public:
  void set(const BiquadCoefficients& c) noexcept;
  void start(float first_input) noexcept;
  [[nodiscard]] float step(float x) noexcept;

 private:
  float b0_ = 0.0F, b1_ = 0.0F, b2_ = 0.0F, a1_ = 0.0F, a2_ = 0.0F;
  float z1_ = 0.0F, z2_ = 0.0F;
};

}  // namespace sinus::dsp
