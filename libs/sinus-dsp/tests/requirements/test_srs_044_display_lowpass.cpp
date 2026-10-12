// Requirement tests of SRS-044 (item libs/sinus-dsp): the display low-pass of the real-time
// library, measured through Chain::process one sample at a time (architecture-m3.md 16.8), at 360
// Hz and at 250 Hz, mains setting 50 Hz unless stated. "Display" is SampleOutput::display_mv,
// "conditioned" is SampleOutput::conditioned_mv. The signals, the measures and the criteria are
// QA's own (support.hpp); the library's taps are used only by the property that names them
// (measure 3). Each test states the part of the requirement it covers, its inputs and its expected
// result.

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "golden_support.hpp"
#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/display_lowpass.hpp"
#include "sinus/dsp/limits.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::DisplayLowpass;
using sinus::dsp::DisplayTaps;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;
using sinus_qa::kPi;

constexpr int kRates[] = {360, 250};

struct Streams {
  std::vector<double> conditioned;
  std::vector<double> display;
  std::uint32_t delay = 0;
};

// The input one sample at a time through a configured chain; every call must return kOk.
Streams run(int fs, int mains, const std::vector<float>& x, bool display_on = true) {
  Chain chain;
  Config config;
  config.sampling_frequency_hz = fs;
  config.mains_frequency_hz = mains;
  config.display_lowpass = display_on;
  EXPECT_EQ(chain.configure(config), Status::kOk);
  Streams s;
  s.delay = chain.display_delay_samples();
  s.conditioned.reserve(x.size());
  s.display.reserve(x.size());
  for (const float v : x) {
    SampleOutput out;
    EXPECT_EQ(chain.process(v, out), Status::kOk);
    s.conditioned.push_back(static_cast<double>(out.conditioned_mv));
    s.display.push_back(static_cast<double>(out.display_mv));
  }
  return s;
}

double rms_from(const std::vector<double>& x, std::size_t first) {
  double sum = 0.0;
  for (std::size_t i = first; i < x.size(); ++i) {
    sum += x[i] * x[i];
  }
  return std::sqrt(sum / static_cast<double>(x.size() - first));
}

// G = 20 log10 (RMS display / RMS conditioned), second half.
double gain_of(const Streams& s) {
  const std::size_t half = s.display.size() / 2;
  return sinus_qa::gain_db(rms_from(s.display, half), rms_from(s.conditioned, half));
}

// Expected delay in samples, written by QA from the requirement of the design: round(30 ms * fs).
std::uint32_t expected_delay(int fs) {
  return static_cast<std::uint32_t>(std::floor(30.0 * fs / 1000.0 + 0.5));
}

std::vector<float> cosine_nyquist(std::size_t n) {
  std::vector<float> x(n);
  for (std::size_t i = 0; i < n; ++i) {
    x[i] = (i % 2 == 0) ? 1.0F : -1.0F;
  }
  return x;
}

// ---------------------------------------------------------------------------------------------
// Properties 1 and 2: gain and attenuation with sinusoids.

// Case: gain from 1 Hz to 30 Hz.
// Input: x[n] = sin(2 pi f n / fs) mV, f = 1, 5, 10, 20, 30 Hz, 10 s, at 360 and 250 Hz.
// Expected: |G| <= 1 dB, G = 20 log10(RMS display / RMS conditioned) over the second half.
// Verifies: SRS-044
TEST(Srs044Gain, WithinOneDecibelFromOneToThirtyHertz) {
  for (const int fs : kRates) {
    for (const double f : {1.0, 5.0, 10.0, 20.0, 30.0}) {
      const Streams s = run(fs, 50, sinus_qa::sine(fs, f, 10.0));
      EXPECT_LE(std::fabs(gain_of(s)), 1.0) << "fs " << fs << " f " << f << " G " << gain_of(s);
    }
  }
}

// Case: attenuation from 80 Hz to the Nyquist frequency.
// Input: sinusoids of 80, 100, 120 Hz, 10 s; and x[n] = (-1)^n mV (the Nyquist frequency, 180 and
// 125 Hz), 10 s, at 360 and 250 Hz.
// Expected: G <= -20 dB in each case.
// Verifies: SRS-044
TEST(Srs044Attenuation, AtLeastTwentyDecibelsFromEightyHertzToNyquist) {
  for (const int fs : kRates) {
    for (const double f : {80.0, 100.0, 120.0}) {
      const Streams s = run(fs, 50, sinus_qa::sine(fs, f, 10.0));
      EXPECT_LE(gain_of(s), -20.0) << "fs " << fs << " f " << f;
    }
    const Streams n = run(fs, 50, cosine_nyquist(static_cast<std::size_t>(10 * fs)));
    EXPECT_LE(gain_of(n), -20.0) << "fs " << fs << " Nyquist";
  }
}

// Case: gain and attenuation at every frequency, from the taps the chain uses.
// Input: |H(f)| = |sum h[k] exp(-2 pi i f k / fs)| of display_lowpass_taps(fs), on a 0.25 Hz grid
// from 1 to 30 Hz and from 80 Hz to the Nyquist frequency (included), 360 and 250 Hz.
// Expected: 20 log10 |H| within +-1 dB from 1 to 30 Hz and <= -20 dB from 80 Hz.
// Verifies: SRS-044
TEST(Srs044Response, TapsMeetGainAndAttenuationOnTheWholeGrid) {
  for (const int fs : kRates) {
    DisplayTaps taps{};
    const std::size_t count = sinus::dsp::display_lowpass_taps(fs, taps);
    ASSERT_EQ(count, 2 * expected_delay(fs) + 1);
    const double nyquist = fs / 2.0;
    for (double f = 1.0; f <= nyquist + 1e-9; f += 0.25) {
      if (f > 30.0 && f < 80.0) {
        continue;
      }
      double re = 0.0;
      double im = 0.0;
      for (std::size_t k = 0; k < count; ++k) {
        const double w = 2.0 * kPi * f * static_cast<double>(k) / fs;
        re += taps[k] * std::cos(w);
        im -= taps[k] * std::sin(w);
      }
      const double db = 20.0 * std::log10(std::hypot(re, im));
      if (f <= 30.0) {
        EXPECT_LE(std::fabs(db), 1.0) << "fs " << fs << " f " << f;
      } else {
        EXPECT_LE(db, -20.0) << "fs " << fs << " f " << f;
      }
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Property 4: group delay.

// Phase of a sin(w n) + b cos(w n) fitted by least squares on the second half: atan2(b, a).
double fitted_phase(const std::vector<double>& x, double g, int fs) {
  const std::size_t first = x.size() / 2;
  double ss = 0.0, sc = 0.0, cc = 0.0, xs = 0.0, xc = 0.0;
  for (std::size_t i = first; i < x.size(); ++i) {
    const double w = 2.0 * kPi * g * static_cast<double>(i) / fs;
    const double s = std::sin(w);
    const double c = std::cos(w);
    ss += s * s;
    sc += s * c;
    cc += c * c;
    xs += x[i] * s;
    xc += x[i] * c;
  }
  const double det = ss * cc - sc * sc;
  const double a = (xs * cc - xc * sc) / det;
  const double b = (xc * ss - xs * sc) / det;
  return std::atan2(b, a);
}

double wrap(double a) {
  while (a > kPi) {
    a -= 2.0 * kPi;
  }
  while (a <= -kPi) {
    a += 2.0 * kPi;
  }
  return a;
}

// Case: the group delay is constant and equals M / fs.
// Input: sinusoids of 10 s at f -+ 0.5 Hz, f = 1, 10, 20, 30 Hz; the phase of the display and of
// the conditioned signal by a least-squares fit on the second half; tau(f) = -Delta / (2 pi 1 Hz)
// with Delta the difference between the phase differences (display - conditioned) at f + 0.5 and
// f - 0.5 Hz, wrapped.
// Expected: max tau - min tau <= 20 ms; each tau within 0.01 ms of M / fs (30.556 ms at 360 Hz, 32
// ms at 250 Hz); Chain::display_delay_samples() = M.
// Verifies: SRS-044
TEST(Srs044GroupDelay, ConstantAndEqualToTheDocumentedDelay) {
  for (const int fs : kRates) {
    const double expected_ms = 1000.0 * expected_delay(fs) / fs;
    double tmin = 1e9;
    double tmax = -1e9;
    for (const double f : {1.0, 10.0, 20.0, 30.0}) {
      double phase_difference[2];
      int at = 0;
      for (const double g : {f - 0.5, f + 0.5}) {
        const Streams s = run(fs, 50, sinus_qa::sine(fs, g, 10.0));
        EXPECT_EQ(s.delay, expected_delay(fs));
        phase_difference[at++] =
            wrap(fitted_phase(s.display, g, fs) - fitted_phase(s.conditioned, g, fs));
      }
      const double delta = wrap(phase_difference[1] - phase_difference[0]);
      const double tau_ms = -delta / (2.0 * kPi * 1.0) * 1000.0;
      EXPECT_NEAR(tau_ms, expected_ms, 0.01) << "fs " << fs << " f " << f;
      tmin = std::min(tmin, tau_ms);
      tmax = std::max(tmax, tau_ms);
    }
    EXPECT_LE(tmax - tmin, 20.0) << "fs " << fs;
  }
}

// ---------------------------------------------------------------------------------------------
// Property 5: R-wave peak.

// Case: the peak R-wave amplitude is kept to at least 90 %.
// Input: the synthetic ECG of SRS-006, 30 s, at 30, 75, 200 bpm, 360 and 250 Hz. For each true R
// centre r with 2 fs <= r and r + M + w < n (w = floor(50 fs / 1000)): max display over
// [r + M - w, r + M + w] divided by max conditioned over [r - w, r + w].
// Expected: every ratio >= 0.90, and at least 10 beats checked per run.
// Verifies: SRS-044
TEST(Srs044RWave, PeakKeptToAtLeastNinetyPercent) {
  for (const int fs : kRates) {
    const std::int64_t m = expected_delay(fs);
    const std::int64_t w = (50 * fs) / 1000;
    for (const int hr : {30, 75, 200}) {
      const auto n = static_cast<std::size_t>(30 * fs);
      const Streams s = run(fs, 50, sinus_qa::synthetic_ecg(fs, hr, n, 0));
      int checked = 0;
      for (const std::int64_t r : sinus_qa::regular_r_positions(fs, hr, n)) {
        if (r < 2 * fs || r + m + w >= static_cast<std::int64_t>(n)) {
          continue;
        }
        double peak_in = -1e9;
        double peak_out = -1e9;
        for (std::int64_t i = -w; i <= w; ++i) {
          peak_in = std::max(peak_in, s.conditioned[static_cast<std::size_t>(r + i)]);
          peak_out = std::max(peak_out, s.display[static_cast<std::size_t>(r + m + i)]);
        }
        EXPECT_GE(peak_out / peak_in, 0.90) << "fs " << fs << " hr " << hr << " r " << r;
        ++checked;
      }
      EXPECT_GE(checked, hr == 30 ? 10 : 20) << "fs " << fs << " hr " << hr;
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Property 6: band-limited noise.

// SplitMix64 and the Box-Muller transform: the same sequence on every standard library.
class Gaussian {
 public:
  explicit Gaussian(std::uint64_t seed) : state_(seed) {}
  double next() {
    if (have_spare_) {
      have_spare_ = false;
      return spare_;
    }
    const double u1 = uniform();
    const double u2 = uniform();
    const double radius = std::sqrt(-2.0 * std::log(u1));
    spare_ = radius * std::sin(2.0 * kPi * u2);
    have_spare_ = true;
    return radius * std::cos(2.0 * kPi * u2);
  }

 private:
  std::uint64_t raw() {
    state_ += 0x9E3779B97F4A7C15ULL;
    std::uint64_t z = state_;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
  }
  double uniform() { return (static_cast<double>(raw() >> 11) + 0.5) / 9007199254740992.0; }
  std::uint64_t state_;
  bool have_spare_ = false;
  double spare_ = 0.0;
};

// White Gaussian noise of n samples with every DFT component below 40 Hz removed (by a direct
// DFT of those bins), scaled to an RMS of 0.1 mV over the n samples.
std::vector<double> band_limited_noise(std::uint64_t seed, int fs, std::size_t n) {
  Gaussian gaussian(seed);
  std::vector<double> x(n);
  for (double& v : x) {
    v = gaussian.next();
  }
  std::vector<double> cs(n);
  std::vector<double> sn(n);
  for (std::size_t m = 0; m < n; ++m) {
    const double a = 2.0 * kPi * static_cast<double>(m) / static_cast<double>(n);
    cs[m] = std::cos(a);
    sn[m] = std::sin(a);
  }
  // Bin k is at k fs / n Hz; below 40 Hz means k < 40 n / fs (= 2400 for 60 s).
  const auto bins = static_cast<std::size_t>(std::ceil(40.0 * static_cast<double>(n) / fs));
  std::vector<double> removed(n, 0.0);
  for (std::size_t k = 0; k < bins; ++k) {
    double re = 0.0;
    double im = 0.0;
    std::size_t idx = 0;
    for (std::size_t i = 0; i < n; ++i) {
      re += x[i] * cs[idx];
      im += x[i] * sn[idx];
      idx += k;
      if (idx >= n) {
        idx -= n;
      }
    }
    const double scale = (k == 0 ? 1.0 : 2.0) / static_cast<double>(n);
    idx = 0;
    for (std::size_t i = 0; i < n; ++i) {
      removed[i] += scale * (re * cs[idx] + im * sn[idx]);
      idx += k;
      if (idx >= n) {
        idx -= n;
      }
    }
  }
  double sum = 0.0;
  for (std::size_t i = 0; i < n; ++i) {
    x[i] -= removed[i];
    sum += x[i] * x[i];
  }
  const double factor = 0.1 / std::sqrt(sum / static_cast<double>(n));
  for (double& v : x) {
    v *= factor;
  }
  return x;
}

// Case: noise in the band from 40 Hz to the Nyquist frequency is reduced by at least 6 dB.
// Input: the synthetic ECG at 75 bpm, 60 s, and the same plus white Gaussian noise of 0.1 mV RMS
// with every component below 40 Hz removed (3 seeds). e_in = conditioned(ECG + w) -
// conditioned(ECG); e_out = display(ECG + w) - display(ECG).
// Expected: 20 log10 (RMS e_out / RMS e_in) <= -6 dB over the samples from 2 fs to the end; the
// noise has an RMS of 0.1 mV and no component below 40 Hz (the generator is checked first).
// Verifies: SRS-044
TEST(Srs044Noise, ReducedByAtLeastSixDecibels) {
  for (const int fs : kRates) {
    const auto n = static_cast<std::size_t>(60 * fs);
    const std::vector<float> ecg = sinus_qa::synthetic_ecg(fs, 75, n, 0);
    const Streams clean = run(fs, 50, ecg);
    for (const std::uint64_t seed : {1ULL, 2ULL, 3ULL}) {
      const std::vector<double> noise = band_limited_noise(seed, fs, n);
      EXPECT_NEAR(rms_from(noise, 0), 0.1, 1e-12);
      std::vector<float> noisy(n);
      for (std::size_t i = 0; i < n; ++i) {
        noisy[i] = static_cast<float>(static_cast<double>(ecg[i]) + noise[i]);
      }
      const Streams with_noise = run(fs, 50, noisy);
      std::vector<double> e_in(n);
      std::vector<double> e_out(n);
      for (std::size_t i = 0; i < n; ++i) {
        e_in[i] = with_noise.conditioned[i] - clean.conditioned[i];
        e_out[i] = with_noise.display[i] - clean.display[i];
      }
      const auto first = static_cast<std::size_t>(2 * fs);
      const double db = sinus_qa::gain_db(rms_from(e_out, first), rms_from(e_in, first));
      EXPECT_LE(db, -6.0) << "fs " << fs << " seed " << seed << " " << db << " dB";
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Property 7: detections, heart rates and windows unchanged.

// Every field of the two outputs except display_mv is identical, bit for bit.
::testing::AssertionResult same_except_display(const SampleOutput& a, const SampleOutput& b) {
  if (!sinus_qa::same_bits(a.baseline_mv, b.baseline_mv) ||
      !sinus_qa::same_bits(a.conditioned_mv, b.conditioned_mv)) {
    return ::testing::AssertionFailure() << "conditioned values differ";
  }
  if (a.detection_count != b.detection_count) {
    return ::testing::AssertionFailure() << "detection count differs";
  }
  for (std::size_t j = 0; j < a.detection_count && j < a.detections.size(); ++j) {
    const auto& x = a.detections[j];
    const auto& y = b.detections[j];
    if (x.index != y.index || x.reported_at != y.reported_at || x.mark != y.mark ||
        x.path != y.path) {
      return ::testing::AssertionFailure() << "detection " << j << " differs";
    }
  }
  if (a.heart_rate_count != b.heart_rate_count) {
    return ::testing::AssertionFailure() << "heart-rate count differs";
  }
  for (std::size_t j = 0; j < a.heart_rate_count && j < a.heart_rates.size(); ++j) {
    const auto& x = a.heart_rates[j];
    const auto& y = b.heart_rates[j];
    if (x.sample != y.sample || x.has_beat != y.has_beat ||
        (x.has_beat && x.beat_index != y.beat_index) || x.status != y.status ||
        !sinus_qa::same_bits(x.bpm, y.bpm)) {
      return ::testing::AssertionFailure() << "heart-rate event " << j << " differs";
    }
  }
  if (a.has_window != b.has_window) {
    return ::testing::AssertionFailure() << "window presence differs";
  }
  if (a.has_window && (a.window.first_sample != b.window.first_sample ||
                       a.window.last_sample != b.window.last_sample ||
                       a.window.reported_at != b.window.reported_at ||
                       !sinus_qa::same_bits(a.window.index, b.window.index) ||
                       a.window.usable != b.window.usable)) {
    return ::testing::AssertionFailure() << "window differs";
  }
  return ::testing::AssertionSuccess();
}

// Feeds `x` to a chain with the stage on and to one with it off; checks every sample. Returns the
// number of detections seen, so that a test is not vacuous.
std::size_t expect_on_equals_off(int fs, int mains, const std::vector<float>& x) {
  Chain on;
  Chain off;
  Config config;
  config.sampling_frequency_hz = fs;
  config.mains_frequency_hz = mains;
  config.display_lowpass = true;
  EXPECT_EQ(on.configure(config), Status::kOk);
  config.display_lowpass = false;
  EXPECT_EQ(off.configure(config), Status::kOk);
  std::size_t detections = 0;
  for (std::size_t i = 0; i < x.size(); ++i) {
    SampleOutput a;
    SampleOutput b;
    EXPECT_EQ(on.process(x[i], a), Status::kOk);
    EXPECT_EQ(off.process(x[i], b), Status::kOk);
    if (!same_except_display(a, b)) {
      ADD_FAILURE() << "sample " << i << ": " << same_except_display(a, b).message();
      return detections;
    }
    if (!std::isfinite(a.display_mv) || !std::isnan(b.display_mv)) {
      ADD_FAILURE() << "sample " << i << ": display value " << a.display_mv << " (on), "
                    << b.display_mv << " (off)";
      return detections;
    }
    detections += a.detection_count;
  }
  return detections;
}

// Case: the stage does not change what is detected, the heart rates or the windows.
// Input: the synthetic ECGs of SRS-010 (30, 40, 75, 180, 200 bpm, 30 s, baseline wander and
// interference at 50 Hz with setting 50, at 60 Hz with setting 60), 360 and 250 Hz; one chain with
// the display stage on, one with it off, given the same samples.
// Expected: at every sample every field except display_mv is identical, bit for bit; display_mv is
// finite with the stage on and a NaN with it off.
// Verifies: SRS-044
TEST(Srs044Unchanged, DetectionsRatesAndWindowsOnSynthetic) {
  for (const int fs : kRates) {
    for (const int mains : {50, 60}) {
      for (const int hr : {30, 40, 75, 180, 200}) {
        const std::vector<float> x =
            sinus_qa::synthetic_ecg(fs, hr, static_cast<std::size_t>(30 * fs), mains);
        const std::size_t detections = expect_on_equals_off(fs, mains, x);
        EXPECT_GT(detections, 5U) << "fs " << fs << " mains " << mains << " hr " << hr;
      }
    }
  }
}

// Case: the same on the input signals of the golden vectors.
// Input: the input column of each of the 32 files of SINUS_GOLDEN_DIR, with its sampling
// frequency and mains setting (skipped with a message when the folder is not given).
// Expected: as above.
// Verifies: SRS-044
TEST(Srs044Unchanged, DetectionsRatesAndWindowsOnGoldenInputs) {
  if (sinus_qa::golden_dir().empty()) {
    GTEST_SKIP() << sinus_qa::kSkipMessage;
  }
  for (const auto& id : sinus_qa::expected_ids()) {
    const sinus_qa::QVector v =
        sinus_qa::parse_vector(sinus_qa::read_text(sinus_qa::path_of(sinus_qa::golden_dir(), id)));
    ASSERT_GT(v.input.size(), 0U) << id;
    std::vector<float> x;
    x.reserve(v.input.size());
    for (const double value : v.input) {
      x.push_back(static_cast<float>(value));
    }
    SCOPED_TRACE(id);
    expect_on_equals_off(static_cast<int>(v.fs), v.mains, x);
  }
}

// ---------------------------------------------------------------------------------------------
// Interfaces and error behaviour.

// Case: the constants of the interface.
// Expected: the stage has a cut-off of 50 Hz and a half length of 30 ms; the delay is at most 30
// samples and the taps fit in 61.
// Verifies: SRS-044
TEST(Srs044Interface, DocumentedConstants) {
  EXPECT_DOUBLE_EQ(sinus::dsp::kDisplayCutoffHz, 50.0);
  EXPECT_DOUBLE_EQ(sinus::dsp::kDisplayHalfLengthMs, 30.0);
  EXPECT_EQ(sinus::dsp::kDisplayMaxDelaySamples, 30U);
  EXPECT_EQ(sinus::dsp::kDisplayTapCapacity, 61U);
  EXPECT_TRUE(Config{}.display_lowpass);
}

// Case: delay and taps over the whole range of sampling frequencies.
// Input: fs = 125, 125.5, ..., 1000 Hz.
// Expected: M = floor(30 fs / 1000 + 0.5) <= 30; display_lowpass_taps returns 2M + 1; taps
// beyond that are 0.0; the taps are symmetric (within 1e-15) and sum to 1 (within 1e-12).
// Verifies: SRS-044
TEST(Srs044Interface, DelayAndTapsOverTheSamplingRange) {
  for (int twice = 250; twice <= 2000; ++twice) {
    const double fs = twice / 2.0;
    const std::uint32_t m = sinus::dsp::display_delay_samples(fs);
    ASSERT_EQ(m, static_cast<std::uint32_t>(std::floor(30.0 * fs / 1000.0 + 0.5))) << fs;
    ASSERT_LE(m, 30U);
    DisplayTaps taps;
    taps.fill(7.0);
    const std::size_t count = sinus::dsp::display_lowpass_taps(fs, taps);
    ASSERT_EQ(count, 2U * m + 1U) << fs;
    double total = 0.0;
    for (std::size_t k = 0; k < count; ++k) {
      EXPECT_NEAR(taps[k], taps[count - 1 - k], 1e-15) << fs << " tap " << k;
      total += taps[k];
    }
    EXPECT_NEAR(total, 1.0, 1e-12) << fs;
    for (std::size_t k = count; k < taps.size(); ++k) {
      EXPECT_EQ(taps[k], 0.0) << fs << " tap " << k;
    }
  }
}

// Case: DisplayLowpass configuration and use.
// Input: configure with NaN, infinity, 124.9, 1000.1 and 0 Hz; with 125 and 1000 Hz; process before
// configure; a failed configure after a good one.
// Expected: kInvalidSamplingFrequency and not configured (M = N = 0) for the invalid ones; kOk for
// the limits, with N = 2M + 1; process before configure (or after a failed configure) returns
// kNotConfigured with the output 0.0f.
// Verifies: SRS-044
TEST(Srs044Interface, StageConfigurationErrors) {
  DisplayLowpass stage;
  float out = 5.0F;
  EXPECT_EQ(stage.process(1.0, out), Status::kNotConfigured);
  EXPECT_EQ(out, 0.0F);
  EXPECT_EQ(stage.delay_samples(), 0U);
  EXPECT_EQ(stage.tap_count(), 0U);
  for (const double fs : {std::numeric_limits<double>::quiet_NaN(),
                          std::numeric_limits<double>::infinity(), 124.9, 1000.1, 0.0, -360.0}) {
    ASSERT_EQ(stage.configure(360.0), Status::kOk);
    EXPECT_EQ(stage.configure(fs), Status::kInvalidSamplingFrequency) << fs;
    EXPECT_EQ(stage.delay_samples(), 0U) << fs;
    EXPECT_EQ(stage.tap_count(), 0U) << fs;
    out = 5.0F;
    EXPECT_EQ(stage.process(1.0, out), Status::kNotConfigured) << fs;
    EXPECT_EQ(out, 0.0F) << fs;
  }
  for (const double fs : {125.0, 1000.0}) {
    EXPECT_EQ(stage.configure(fs), Status::kOk) << fs;
    EXPECT_EQ(stage.delay_samples(), sinus::dsp::display_delay_samples(fs));
    EXPECT_EQ(stage.tap_count(), 2U * stage.delay_samples() + 1U);
    EXPECT_EQ(stage.process(0.5, out), Status::kOk);
  }
}

// Case: the chain's delay accessor and the stage switch.
// Input: Chain::display_delay_samples() before configure, after a rejected configure, and after a
// good configure with the stage on and off, at 360 and 250 Hz.
// Expected: 0 before and after a rejected configure; M (11 at 360 Hz, 8 at 250 Hz) with the stage
// on and with it off.
// Verifies: SRS-044
TEST(Srs044Interface, ChainDelayAccessor) {
  Chain chain;
  EXPECT_EQ(chain.display_delay_samples(), 0U);
  for (const int fs : kRates) {
    for (const bool on : {true, false}) {
      Config config;
      config.sampling_frequency_hz = fs;
      config.mains_frequency_hz = 50;
      config.display_lowpass = on;
      ASSERT_EQ(chain.configure(config), Status::kOk);
      EXPECT_EQ(chain.display_delay_samples(), expected_delay(fs));
      EXPECT_EQ(chain.display_delay_samples(), fs == 360 ? 11U : 8U);
    }
  }
  EXPECT_EQ(chain.configure(Config{std::numeric_limits<double>::quiet_NaN(), 50}),
            Status::kInvalidSamplingFrequency);
  EXPECT_EQ(chain.display_delay_samples(), 0U);
}

// Case: display_mv with a status other than kOk, and with the stage off.
// Input: process before configure, after an invalid sample (NaN) and while stopped, with
// display_mv preset to 5; then a chain with the stage off given 100 samples.
// Expected: display_mv is 0.0f whenever the status is not kOk; with the stage off it is a NaN at
// every processed sample.
// Verifies: SRS-044
TEST(Srs044Interface, DisplayValueWithoutAResult) {
  Chain chain;
  SampleOutput out;
  out.display_mv = 5.0F;
  EXPECT_EQ(chain.process(0.1F, out), Status::kNotConfigured);
  EXPECT_EQ(out.display_mv, 0.0F);
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  for (int i = 0; i < 50; ++i) {
    ASSERT_EQ(chain.process(0.1F, out), Status::kOk);
  }
  out.display_mv = 5.0F;
  EXPECT_EQ(chain.process(std::numeric_limits<float>::quiet_NaN(), out), Status::kInvalidSample);
  EXPECT_EQ(out.display_mv, 0.0F);
  out.display_mv = 5.0F;
  EXPECT_EQ(chain.process(0.1F, out), Status::kStopped);
  EXPECT_EQ(out.display_mv, 0.0F);

  Config off;
  off.sampling_frequency_hz = 360.0;
  off.mains_frequency_hz = 50;
  off.display_lowpass = false;
  Chain plain;
  ASSERT_EQ(plain.configure(off), Status::kOk);
  for (int i = 0; i < 100; ++i) {
    out.display_mv = 5.0F;
    ASSERT_EQ(plain.process(0.1F, out), Status::kOk);
    EXPECT_TRUE(std::isnan(out.display_mv)) << i;
  }
}

// Case: restart (SRS-031) includes the display stage.
// Input: 20 s of the interfered synthetic ECG, reset, then 10 s more on this chain and on a newly
// configured chain.
// Expected: display_mv after the reset equals, bit for bit, that of the new chain.
// Verifies: SRS-044
TEST(Srs044Interface, ResetRestartsTheDisplayStage) {
  const int fs = 360;
  const std::vector<float> x = sinus_qa::synthetic_ecg(fs, 75, 30 * fs, 50);
  Chain chain;
  Chain fresh;
  ASSERT_EQ(chain.configure(Config{360.0, 50}), Status::kOk);
  ASSERT_EQ(fresh.configure(Config{360.0, 50}), Status::kOk);
  SampleOutput out;
  for (std::size_t i = 0; i < static_cast<std::size_t>(20 * fs); ++i) {
    ASSERT_EQ(chain.process(x[i], out), Status::kOk);
  }
  chain.reset();
  for (std::size_t i = static_cast<std::size_t>(20 * fs); i < x.size(); ++i) {
    SampleOutput a;
    SampleOutput b;
    ASSERT_EQ(chain.process(x[i], a), Status::kOk);
    ASSERT_EQ(fresh.process(x[i], b), Status::kOk);
    ASSERT_TRUE(sinus_qa::same_bits(a.display_mv, b.display_mv)) << "sample " << i;
  }
}

}  // namespace
