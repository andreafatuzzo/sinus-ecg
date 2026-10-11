// SRS-019: filter design and second-order sections (architecture-m2.md 14.3). The expressions
// repeat those of the reference (dsp/sinus_dsp/filters.py) in the same order of operations.
#include "sinus/dsp/biquad.hpp"

#include <cmath>

namespace sinus::dsp {

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kNotchQ = 30.0;
constexpr double kBaselineCutoffHz = 0.5;

struct Butterworth2 {
  double kk, norm, a1, a2;
};

// NOLINTNEXTLINE(bugprone-easily-swappable-parameters): the order is that of the reference.
Butterworth2 design_butterworth2(double cutoff_hz, double fs_hz) noexcept {
  const double k = std::tan(kPi * cutoff_hz / fs_hz);
  const double sqrt2 = std::sqrt(2.0);
  const double norm = 1.0 / (1.0 + (sqrt2 * k) + (k * k));
  return Butterworth2{k * k, norm, (2.0 * ((k * k) - 1.0)) * norm,
                      ((1.0 - (sqrt2 * k)) + (k * k)) * norm};
}

}  // namespace

BiquadCoefficients butterworth2_highpass(double cutoff_hz, double fs_hz) noexcept {
  const Butterworth2 d = design_butterworth2(cutoff_hz, fs_hz);
  return BiquadCoefficients{d.norm, (-2.0) * d.norm, d.norm, d.a1, d.a2};
}

BiquadCoefficients butterworth2_lowpass(double cutoff_hz, double fs_hz) noexcept {
  const Butterworth2 d = design_butterworth2(cutoff_hz, fs_hz);
  return BiquadCoefficients{d.kk * d.norm, (2.0 * d.kk) * d.norm, d.kk * d.norm, d.a1, d.a2};
}

// NOLINTNEXTLINE(bugprone-easily-swappable-parameters): the interface of the design (14.4).
BiquadCoefficients notch(double notch_hz, double q, double fs_hz) noexcept {
  const double w = (2.0 * notch_hz) / fs_hz;
  const double bw = (w / q) * kPi;
  const double w0 = w * kPi;
  const double beta = std::tan(bw / 2.0);
  const double g = 1.0 / (1.0 + beta);
  const double b1 = g * ((-2.0) * std::cos(w0));
  const double a1 = ((-2.0) * g) * std::cos(w0);
  const double a2 = (2.0 * g) - 1.0;
  return BiquadCoefficients{g, b1, g, a1, a2};
}

BiquadCoefficients baseline_coefficients(double fs_hz) noexcept {
  return butterworth2_highpass(kBaselineCutoffHz, fs_hz);
}

BiquadCoefficients mains_coefficients(double fs_hz, int mains_hz) noexcept {
  return notch(static_cast<double>(mains_hz), kNotchQ, fs_hz);
}

void BiquadF64::set(const BiquadCoefficients& c) noexcept {
  b0_ = c.b0;
  b1_ = c.b1;
  b2_ = c.b2;
  a1_ = c.a1;
  a2_ = c.a2;
  z1_ = 0.0;
  z2_ = 0.0;
}

void BiquadF64::start(double first_input) noexcept {
  const double gain = (b0_ + b1_ + b2_) / (1.0 + a1_ + a2_);
  z1_ = ((b1_ + b2_) - ((a1_ + a2_) * gain)) * first_input;
  z2_ = (b2_ - (a2_ * gain)) * first_input;
}

double BiquadF64::step(double x) noexcept {
  const double y = (b0_ * x) + z1_;
  z1_ = ((b1_ * x) - (a1_ * y)) + z2_;
  z2_ = (b2_ * x) - (a2_ * y);
  return y;
}

void BiquadF32::set(const BiquadCoefficients& c) noexcept {
  b0_ = static_cast<float>(c.b0);
  b1_ = static_cast<float>(c.b1);
  b2_ = static_cast<float>(c.b2);
  a1_ = static_cast<float>(c.a1);
  a2_ = static_cast<float>(c.a2);
  z1_ = 0.0F;
  z2_ = 0.0F;
}

void BiquadF32::start(float first_input) noexcept {
  const float gain = (b0_ + b1_ + b2_) / (1.0F + a1_ + a2_);
  z1_ = ((b1_ + b2_) - ((a1_ + a2_) * gain)) * first_input;
  z2_ = (b2_ - (a2_ * gain)) * first_input;
}

float BiquadF32::step(float x) noexcept {
  const float y = (b0_ * x) + z1_;
  z1_ = ((b1_ * x) - (a1_ * y)) + z2_;
  z2_ = (b2_ * x) - (a2_ * y);
  return y;
}

}  // namespace sinus::dsp
