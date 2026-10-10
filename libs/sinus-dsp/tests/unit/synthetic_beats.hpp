#pragma once

// A simple synthetic ECG for the developer's unit tests of detection: each beat is five Gaussian
// waves (P, Q, R, S, T) around its R wave, scaled by an amplitude factor. It is not the generator
// of the reference; the equivalence with the reference is checked on the golden vectors.

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace sinus_test {

struct Beat {
  double r_s;    // time of the R wave, s
  double scale;  // amplitude factor
};

inline std::vector<float> synthetic_beats(double fs_hz, double duration_s,
                                          const std::vector<Beat>& beats) {
  struct Wave {
    double offset_s, amplitude_mv, sigma_s;
  };
  static constexpr Wave kWaves[] = {
      {-0.200, 0.15, 0.025}, {-0.025, -0.10, 0.010}, {0.0, 1.0, 0.010},
      {0.025, -0.25, 0.010}, {0.300, 0.30, 0.040},
  };
  const auto n = static_cast<std::size_t>(std::floor(duration_s * fs_hz));
  std::vector<double> x(n, 0.0);
  for (const Beat& beat : beats) {
    for (const Wave& w : kWaves) {
      for (std::size_t k = 0; k < n; ++k) {
        const double t = (static_cast<double>(k) / fs_hz) - (beat.r_s + w.offset_s);
        if (std::fabs(t) < 6.0 * w.sigma_s) {
          x[k] += beat.scale * w.amplitude_mv * std::exp(-0.5 * (t / w.sigma_s) * (t / w.sigma_s));
        }
      }
    }
  }
  return std::vector<float>(x.begin(), x.end());
}

// Beats every rr_s seconds from first_s to before end_s, all with the given scale.
inline std::vector<Beat> regular_beats(double first_s, double rr_s, double end_s,
                                       double scale = 1.0) {
  std::vector<Beat> beats;
  for (double t = first_s; t < end_s; t += rr_s) {
    beats.push_back(Beat{t, scale});
  }
  return beats;
}

// The sample of an R wave, rounded half up.
inline std::int64_t r_sample(double r_s, double fs_hz) {
  return static_cast<std::int64_t>(std::floor((r_s * fs_hz) + 0.5));
}

}  // namespace sinus_test
