#pragma once

// Helpers of the requirement tests (QA): an own synthetic ECG (architecture.md 7.2), an own
// binary64 model of the conditioning stages (architecture.md 8.6) used as the oracle of SRS-019,
// and small utilities. Nothing here uses the design functions of the library.

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace sinus_qa {

inline constexpr double kPi = 3.14159265358979323846;

// Synthetic ECG of architecture.md 7.2: five Gaussian waves per beat, R centres on integers.
// mains_hz != 0 adds the baseline wander (0.3 Hz, 1 mV) and then the mains interference
// (mains_hz, 0.2 mV) of SRS-010.
inline std::vector<float> synthetic_ecg(int fs, int hr, std::size_t n, int mains_hz) {
  std::vector<double> x(n, 0.0);
  const double rr = 60.0 / hr;
  const double s = std::sqrt(rr);
  struct Wave {
    double offset_s, amp, sigma_s;
  };
  const Wave waves[5] = {{-0.200 * s, 0.15, 0.025 * s},
                         {-0.030, -0.10, 0.010},
                         {0.0, 1.00, 0.010},
                         {0.030, -0.20, 0.010},
                         {0.280 * s, 0.30, 0.045 * s}};
  for (std::int64_t k = 0;; ++k) {
    const std::int64_t r = (static_cast<std::int64_t>(hr) * (fs + 1) + 120 * k * fs) / (2 * hr);
    if (r - fs >= static_cast<std::int64_t>(n)) {
      break;
    }
    const std::int64_t lo = std::max<std::int64_t>(0, r - fs);
    const std::int64_t hi = std::min<std::int64_t>(static_cast<std::int64_t>(n), r + fs);
    for (std::int64_t i = lo; i < hi; ++i) {
      const double t = static_cast<double>(i) / fs;
      for (const Wave& w : waves) {
        const double d = t - (static_cast<double>(r) / fs + w.offset_s);
        x[static_cast<std::size_t>(i)] += w.amp * std::exp(-d * d / (2.0 * w.sigma_s * w.sigma_s));
      }
    }
  }
  if (mains_hz != 0) {
    for (std::size_t i = 0; i < n; ++i) {
      const double t = static_cast<double>(i) / fs;
      x[i] += 1.0 * std::sin(2.0 * kPi * 0.3 * t);
      x[i] += 0.2 * std::sin(2.0 * kPi * mains_hz * t);
    }
  }
  std::vector<float> out(n);
  for (std::size_t i = 0; i < n; ++i) {
    out[i] = static_cast<float>(x[i]);
  }
  return out;
}

// A sinusoid of the given amplitude (mV), phase 0, lasting at least `seconds`.
inline std::vector<float> sine(int fs, double f_hz, double seconds, double amplitude = 1.0) {
  const auto n = static_cast<std::size_t>(std::ceil(seconds * fs - 1e-9));
  std::vector<float> x(n);
  for (std::size_t i = 0; i < n; ++i) {
    x[i] = static_cast<float>(amplitude * std::sin(2.0 * kPi * f_hz * static_cast<double>(i) / fs));
  }
  return x;
}

template <typename T>
double rms_second_half(const std::vector<T>& x) {
  double sum = 0.0;
  const std::size_t half = x.size() / 2;
  for (std::size_t i = half; i < x.size(); ++i) {
    sum += static_cast<double>(x[i]) * static_cast<double>(x[i]);
  }
  return std::sqrt(sum / static_cast<double>(x.size() - half));
}

inline double gain_db(double rms_out, double rms_in) { return 20.0 * std::log10(rms_out / rms_in); }

inline bool same_bits(float a, float b) { return std::memcmp(&a, &b, sizeof(float)) == 0; }

// Own binary64 model of one second-order section, transposed direct form II, started in the
// steady state of a constant input equal to the first sample (architecture.md 8.6).
struct OracleSection {
  double b0 = 0, b1 = 0, b2 = 0, a1 = 0, a2 = 0, z1 = 0, z2 = 0;
  void start(double u) {
    const double g = (b0 + b1 + b2) / (1.0 + a1 + a2);
    z1 = (b1 + b2 - (a1 + a2) * g) * u;
    z2 = (b2 - a2 * g) * u;
  }
  double step(double x) {
    const double y = b0 * x + z1;
    z1 = b1 * x - a1 * y + z2;
    z2 = b2 * x - a2 * y;
    return y;
  }
};

inline OracleSection oracle_baseline(double fs) {
  const double k = std::tan(kPi * 0.5 / fs);
  const double norm = 1.0 / (1.0 + std::sqrt(2.0) * k + k * k);
  OracleSection s;
  s.a1 = 2.0 * (k * k - 1.0) * norm;
  s.a2 = (1.0 - std::sqrt(2.0) * k + k * k) * norm;
  s.b0 = norm;
  s.b1 = -2.0 * norm;
  s.b2 = norm;
  return s;
}

inline OracleSection oracle_notch(double f0, double q, double fs) {
  const double w = 2.0 * f0 / fs;
  const double bw = (w / q) * kPi;
  const double w0 = w * kPi;
  const double beta = std::tan(bw / 2.0);
  const double g = 1.0 / (1.0 + beta);
  OracleSection s;
  s.b0 = g;
  s.b1 = -2.0 * std::cos(w0) * g;
  s.b2 = g;
  s.a1 = -2.0 * g * std::cos(w0);
  s.a2 = 2.0 * g - 1.0;
  return s;
}

// The two stages in order: baseline (0.5 Hz high-pass), then the notch (Q = 30).
class OracleConditioner {
 public:
  OracleConditioner(double fs, int mains_hz)
      : baseline_(oracle_baseline(fs)), mains_(oracle_notch(mains_hz, 30.0, fs)) {}
  void step(double x, double& baseline_out, double& conditioned_out) {
    if (first_) {
      baseline_.start(x);
    }
    baseline_out = baseline_.step(x);
    if (first_) {
      mains_.start(baseline_out);
      first_ = false;
    }
    conditioned_out = mains_.step(baseline_out);
  }

 private:
  OracleSection baseline_;
  OracleSection mains_;
  bool first_ = true;
};

}  // namespace sinus_qa
