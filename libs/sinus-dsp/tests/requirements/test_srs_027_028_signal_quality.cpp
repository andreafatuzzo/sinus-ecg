// Requirement tests of SRS-027 and SRS-028: signal quality index per window, real-time library
// part (SignalQuality and the window fields of the Chain).
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/signal_quality.hpp"
#include "support.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::DetectorStep;
using sinus::dsp::QualityWindow;
using sinus::dsp::SampleOutput;
using sinus::dsp::SignalQuality;
using sinus::dsp::Status;

constexpr int kRates[] = {360, 250};
constexpr int kHeartRates[] = {30, 40, 75, 180, 200};
constexpr float kThreshold = 0.5F;

struct Win {
  std::uint64_t first, last, reported_at;
  float index;
  bool usable;
};

std::uint64_t seconds(int fs, std::uint64_t s) { return s * static_cast<std::uint64_t>(fs); }

// The windows reported by a chain given `x` from its first sample, with the sample at which each
// came; checks at every sample that the chain returns kOk and that a window is reported at the
// sample it names.
std::vector<Win> run_windows(const std::vector<float>& x, int fs, int mains) {
  Chain chain;
  EXPECT_EQ(chain.configure(Config{static_cast<double>(fs), mains}), Status::kOk);
  std::vector<Win> out;
  SampleOutput so;
  for (std::size_t n = 0; n < x.size(); ++n) {
    const Status st = chain.process(x[n], so);
    EXPECT_EQ(st, Status::kOk);
    if (st != Status::kOk) {
      break;
    }
    if (so.has_window) {
      const QualityWindow& w = so.window;
      EXPECT_EQ(w.reported_at, n);
      out.push_back({w.first_sample, w.last_sample, w.reported_at, w.index, w.usable});
    }
  }
  return out;
}

// The window count that a stream of n samples gives: windows k = 0, 1, ... with
// k H + W - 1 + delay <= n - 1.
std::size_t expected_count(std::size_t n, int fs) {
  const std::uint64_t h = static_cast<std::uint64_t>(fs);
  const std::uint64_t w = 10 * h;
  const std::uint64_t d = h / 2;
  std::size_t count = 0;
  while (count * h + w - 1 + d <= n - 1) {
    ++count;
  }
  return count;
}

// White Gaussian noise of the given RMS, Box-Muller on the raw mt19937 output (its sequence is
// fixed by the standard).
std::vector<float> white_noise(std::size_t n, double rms, std::uint32_t seed) {
  std::mt19937 gen(seed);
  const auto uniform = [&gen]() { return (static_cast<double>(gen()) + 0.5) / 4294967296.0; };
  std::vector<float> x(n);
  for (std::size_t i = 0; i < n; i += 2) {
    const double r = std::sqrt(-2.0 * std::log(uniform()));
    const double t = 2.0 * sinus_qa::kPi * uniform();
    x[i] = static_cast<float>(rms * r * std::cos(t));
    if (i + 1 < n) {
      x[i + 1] = static_cast<float>(rms * r * std::sin(t));
    }
  }
  return x;
}

bool bits_equal(const Win& a, const Win& b) {
  return a.first == b.first && a.last == b.last && a.reported_at == b.reported_at &&
         sinus_qa::same_bits(a.index, b.index) && a.usable == b.usable;
}

// ---------------------------------------------------------------------------------- SRS-027

// Case: the timing parameters of the index, at 360 and 250 Hz.
// Expected: block (spacing) of 1 s = fs samples, window of 10 s = 10 fs samples, report delay of
// 0.5 s (180 and 125 samples), never above 0.5 s.
// Verifies: SRS-027
TEST(Srs027SignalQuality, TimingParameters) {
  for (const int fs : kRates) {
    const sinus::dsp::QualitySamples q = sinus::dsp::quality_samples(static_cast<double>(fs));
    EXPECT_EQ(q.block, static_cast<std::uint32_t>(fs));
    EXPECT_EQ(q.window, static_cast<std::uint32_t>(10 * fs));
    EXPECT_EQ(q.report_delay, static_cast<std::uint32_t>(fs / 2));
    EXPECT_LE(2 * q.report_delay, static_cast<std::uint32_t>(fs));
  }
  EXPECT_EQ(sinus::dsp::kUsableThreshold, kThreshold);
}

// Case: the synthetic ECG of SRS-006 of 60 s at 75 bpm, 360 and 250 Hz, both mains settings.
// Expected: windows of 10 s starting every 1 s from the first sample: window k has first sample
// k fs, last sample first + 10 fs - 1, is reported at its last sample + fs / 2 (at most 0.5 s
// after) and at the sample it names; 50 windows in all, none missing or added, in order.
// Verifies: SRS-027
TEST(Srs027SignalQuality, WindowsAreTenSecondsEverySecond) {
  for (const int fs : kRates) {
    for (const int mains : {50, 60}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz mains " << mains);
      const std::size_t n = 60 * static_cast<std::size_t>(fs);
      const std::vector<Win> w = run_windows(sinus_qa::synthetic_ecg(fs, 75, n, mains), fs, mains);
      ASSERT_EQ(w.size(), expected_count(n, fs));
      ASSERT_EQ(w.size(), 50U);
      for (std::size_t k = 0; k < w.size(); ++k) {
        EXPECT_EQ(w[k].first, seconds(fs, k)) << k;
        EXPECT_EQ(w[k].last, seconds(fs, k) + seconds(fs, 10) - 1) << k;
        EXPECT_EQ(w[k].reported_at, w[k].last + static_cast<std::uint64_t>(fs / 2)) << k;
      }
    }
  }
}

// Case: the same 60 s ECG, looking at the samples before the first window.
// Expected: no window before the sample 10 fs - 1 + fs / 2 (3779 at 360 Hz, 2624 at 250 Hz); the
// first one is reported there.
// Verifies: SRS-027
TEST(Srs027SignalQuality, FirstWindowIsReportedAtItsReportSample) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<Win> w =
        run_windows(sinus_qa::synthetic_ecg(fs, 75, seconds(fs, 20), 0), fs, 50);
    ASSERT_FALSE(w.empty());
    EXPECT_EQ(w[0].reported_at, seconds(fs, 10) - 1 + static_cast<std::uint64_t>(fs / 2));
    EXPECT_EQ(w[0].reported_at, fs == 360 ? 3779U : 2624U);
    EXPECT_EQ(w[0].first, 0U);
  }
}

// Case: ECGs of every heart rate of SRS-006 (30, 40, 75, 180, 200 bpm), a flat line, white noise
// and an ECG held at 2 mV from 20 s to 40 s, 60 s each, 360 and 250 Hz.
// Expected: every window has an index between 0 and 1 (not NaN) and is marked usable exactly when
// its index is at or above the threshold 0.5.
// Verifies: SRS-027
TEST(Srs027SignalQuality, IndexIsInRangeAndMarkFollowsTheThreshold) {
  for (const int fs : kRates) {
    const std::size_t n = 60 * static_cast<std::size_t>(fs);
    std::vector<std::vector<float>> inputs;
    for (const int hr : kHeartRates) {
      inputs.push_back(sinus_qa::synthetic_ecg(fs, hr, n, 50));
    }
    inputs.emplace_back(n, 0.0F);
    inputs.push_back(white_noise(n, 0.1, 7));
    std::vector<float> held = sinus_qa::synthetic_ecg(fs, 75, n, 0);
    std::fill(held.begin() + static_cast<std::ptrdiff_t>(seconds(fs, 20)),
              held.begin() + static_cast<std::ptrdiff_t>(seconds(fs, 40)), 2.0F);
    inputs.push_back(held);
    for (std::size_t c = 0; c < inputs.size(); ++c) {
      SCOPED_TRACE(testing::Message() << fs << " Hz input " << c);
      const std::vector<Win> w = run_windows(inputs[c], fs, 50);
      ASSERT_EQ(w.size(), 50U);
      std::size_t usable = 0;
      for (const Win& x : w) {
        ASSERT_FALSE(std::isnan(x.index));
        EXPECT_GE(x.index, 0.0F);
        EXPECT_LE(x.index, 1.0F);
        EXPECT_EQ(x.usable, x.index >= kThreshold) << "window " << x.first;
        usable += x.usable ? 1U : 0U;
      }
      if (c < 5) {
        EXPECT_GT(usable, 0U);  // the ECGs are not all rejected
      }
    }
  }
}

// Case: a window depends only on the samples up to its report sample.
// Input: the 60 s ECG, and the same ECG cut at 35 s.
// Expected: the windows of the short stream are the first windows of the long one, bit for bit.
// Verifies: SRS-027
TEST(Srs027SignalQuality, WindowsDoNotDependOnLaterSamples) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    std::vector<float> ecg = sinus_qa::synthetic_ecg(fs, 75, seconds(fs, 60), 60);
    const std::vector<Win> full = run_windows(ecg, fs, 60);
    ecg.resize(seconds(fs, 35));
    const std::vector<Win> cut = run_windows(ecg, fs, 60);
    ASSERT_FALSE(cut.empty());
    ASSERT_LE(cut.size(), full.size());
    for (std::size_t k = 0; k < cut.size(); ++k) {
      EXPECT_TRUE(bits_equal(cut[k], full[k])) << k;
    }
  }
}

// Case: the same input twice on two chains, and on one chain reset in between.
// Expected: the same windows, bit for bit.
// Verifies: SRS-027
TEST(Srs027SignalQuality, SameInputSameWindows) {
  const int fs = 360;
  const std::vector<float> ecg = sinus_qa::synthetic_ecg(fs, 75, seconds(fs, 30), 50);
  const std::vector<Win> a = run_windows(ecg, fs, 50);
  const std::vector<Win> b = run_windows(ecg, fs, 50);
  ASSERT_EQ(a.size(), b.size());
  for (std::size_t k = 0; k < a.size(); ++k) {
    EXPECT_TRUE(bits_equal(a[k], b[k])) << k;
  }
}

// Case: a reset of the chain after 25 s, then 30 s of ECG, at 360 and 250 Hz.
// Expected: the windows start again from the reset: the first window after it has first sample 0
// and last sample 10 fs - 1 and is reported at 10 fs - 1 + fs / 2 samples after the reset; the k-th
// has first sample k fs; and the windows are the same, bit for bit, as those of a newly configured
// chain given the samples after the reset.
// Verifies: SRS-027
TEST(Srs027SignalQuality, WindowsRestartFromTheReset) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    const std::vector<float> ecg = sinus_qa::synthetic_ecg(fs, 75, seconds(fs, 60), 50);
    const std::size_t reset_at = seconds(fs, 25) + 37;
    Chain chain;
    ASSERT_EQ(chain.configure(Config{static_cast<double>(fs), 50}), Status::kOk);
    SampleOutput so;
    std::size_t before = 0;
    for (std::size_t n = 0; n < reset_at; ++n) {
      ASSERT_EQ(chain.process(ecg[n], so), Status::kOk);
      before += so.has_window ? 1U : 0U;
    }
    EXPECT_GE(before, 10U);
    chain.reset();
    std::vector<Win> after;
    for (std::size_t n = reset_at; n < ecg.size(); ++n) {
      ASSERT_EQ(chain.process(ecg[n], so), Status::kOk);
      if (so.has_window) {
        EXPECT_EQ(so.window.reported_at, n - reset_at);
        after.push_back({so.window.first_sample, so.window.last_sample, so.window.reported_at,
                         so.window.index, so.window.usable});
      }
    }
    const std::vector<Win> fresh = run_windows(
        std::vector<float>(ecg.begin() + static_cast<std::ptrdiff_t>(reset_at), ecg.end()), fs, 50);
    ASSERT_GE(after.size(), 20U);
    ASSERT_EQ(after.size(), fresh.size());
    for (std::size_t k = 0; k < after.size(); ++k) {
      EXPECT_EQ(after[k].first, seconds(fs, k));
      EXPECT_TRUE(bits_equal(after[k], fresh[k])) << k;
    }
    EXPECT_EQ(after[0].last, seconds(fs, 10) - 1);
    EXPECT_EQ(after[0].reported_at, seconds(fs, 10) - 1 + static_cast<std::uint64_t>(fs / 2));
  }
}

// Case: the component alone, SignalQuality::step with a DetectorStep.
// Expected: kNotConfigured before configure; a detector count above 12 returns kInvalidArgument
// and changes nothing (the windows that follow equal those of a component that never saw the
// call); configure with 100 Hz fails and leaves it not configured.
// Verifies: SRS-027
TEST(Srs027SignalQuality, ComponentPreconditions) {
  SignalQuality q;
  DetectorStep d;
  bool has = true;
  QualityWindow w{};
  EXPECT_EQ(q.step(0.0F, d, has, w), Status::kNotConfigured);
  EXPECT_NE(q.configure(100.0), Status::kOk);
  EXPECT_EQ(q.step(0.0F, d, has, w), Status::kNotConfigured);
  ASSERT_EQ(q.configure(360.0), Status::kOk);
  DetectorStep bad;
  bad.count = 13;
  SignalQuality ref;
  ASSERT_EQ(ref.configure(360.0), Status::kOk);
  std::size_t windows = 0;
  for (std::size_t n = 0; n < 4200; ++n) {
    const float x = static_cast<float>(0.1 * std::sin(0.05 * static_cast<double>(n)));
    has = true;
    EXPECT_EQ(q.step(x, bad, has, w), Status::kInvalidArgument);
    bool has_q = false;
    bool has_r = false;
    QualityWindow wq{};
    QualityWindow wr{};
    ASSERT_EQ(q.step(x, d, has_q, wq), Status::kOk);
    ASSERT_EQ(ref.step(x, d, has_r, wr), Status::kOk);
    ASSERT_EQ(has_q, has_r);
    if (has_q) {
      ++windows;
      EXPECT_EQ(wq.first_sample, wr.first_sample);
      EXPECT_TRUE(sinus_qa::same_bits(wq.index, wr.index));
      EXPECT_EQ(wq.usable, wq.index >= kThreshold);
      EXPECT_EQ(wq.reported_at, n);
    }
  }
  EXPECT_GE(windows, 1U);
}

// ---------------------------------------------------------------------------------- SRS-028

// Case: the synthetic ECGs of SRS-006 of 60 s at 30, 40, 75, 180 and 200 bpm, clean and with the
// interference of SRS-010 at 50 Hz and at 60 Hz (matching setting), 360 and 250 Hz.
// Expected: every window that begins at least 2 s after the first sample is marked usable.
// Verifies: SRS-028
TEST(Srs028SignalQualityOnDefinedSignals, CleanEcgIsUsableFromTwoSeconds) {
  for (const int fs : kRates) {
    for (const int hr : kHeartRates) {
      for (const int interference : {0, 50, 60}) {
        SCOPED_TRACE(testing::Message()
                     << fs << " Hz " << hr << " bpm interference " << interference);
        const std::vector<float> ecg =
            sinus_qa::synthetic_ecg(fs, hr, 60 * static_cast<std::size_t>(fs), interference);
        const std::vector<Win> w = run_windows(ecg, fs, interference == 0 ? 50 : interference);
        ASSERT_EQ(w.size(), 50U);
        for (const Win& x : w) {
          if (x.first >= seconds(fs, 2)) {
            EXPECT_TRUE(x.usable) << "window " << x.first / static_cast<std::uint64_t>(fs)
                                  << " s, index " << x.index;
          }
        }
      }
    }
  }
}

// Case: a constant input of 60 s at 0 mV and at 1 mV, 360 and 250 Hz.
// Expected: 50 windows, every one marked not usable.
// Verifies: SRS-028
TEST(Srs028SignalQualityOnDefinedSignals, FlatLineIsNotUsable) {
  for (const int fs : kRates) {
    for (const float level : {0.0F, 1.0F}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz level " << level);
      const std::vector<Win> w =
          run_windows(std::vector<float>(60 * static_cast<std::size_t>(fs), level), fs, 50);
      ASSERT_EQ(w.size(), 50U);
      for (const Win& x : w) {
        EXPECT_FALSE(x.usable) << "window " << x.first;
        EXPECT_LT(x.index, kThreshold);
      }
    }
  }
}

// Case: white Gaussian noise of RMS 0.01, 0.1 and 1 mV (seeds 1, 2, 3), 60 s, 360 and 250 Hz.
// Expected: 50 windows, none marked usable.
// Verifies: SRS-028
TEST(Srs028SignalQualityOnDefinedSignals, WhiteNoiseIsNotUsable) {
  for (const int fs : kRates) {
    for (const double rms : {0.01, 0.1, 1.0}) {
      for (const std::uint32_t seed : {1U, 2U, 3U}) {
        SCOPED_TRACE(testing::Message() << fs << " Hz rms " << rms << " seed " << seed);
        const std::vector<Win> w =
            run_windows(white_noise(60 * static_cast<std::size_t>(fs), rms, seed), fs, 50);
        ASSERT_EQ(w.size(), 50U);
        for (const Win& x : w) {
          EXPECT_FALSE(x.usable) << "window " << x.first << " index " << x.index;
        }
      }
    }
  }
}

// Case: the ECG at 40 and 75 bpm, 60 s, whose input is held at 2 mV from 20 s to 40 s.
// Expected: every window that contains at least 5 s of the held stretch (starts from 15 s to 35 s,
// 21 windows) is marked not usable; the windows that contain no held sample (start from 2 s to 10 s
// and from 40 s) are usable.
// Verifies: SRS-028
TEST(Srs028SignalQualityOnDefinedSignals, HeldInputIsNotUsable) {
  for (const int fs : kRates) {
    for (const int hr : {40, 75}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz " << hr << " bpm");
      std::vector<float> ecg =
          sinus_qa::synthetic_ecg(fs, hr, 60 * static_cast<std::size_t>(fs), 0);
      std::fill(ecg.begin() + static_cast<std::ptrdiff_t>(seconds(fs, 20)),
                ecg.begin() + static_cast<std::ptrdiff_t>(seconds(fs, 40)), 2.0F);
      const std::vector<Win> w = run_windows(ecg, fs, 50);
      ASSERT_EQ(w.size(), 50U);
      int held = 0;
      for (const Win& x : w) {
        const std::uint64_t s = x.first / static_cast<std::uint64_t>(fs);
        if (s >= 15 && s <= 35) {
          ++held;
          EXPECT_FALSE(x.usable) << "start " << s << " s";
        } else if ((s >= 2 && s <= 10) || s >= 40) {
          EXPECT_TRUE(x.usable) << "start " << s << " s, index " << x.index;
        }
      }
      EXPECT_EQ(held, 21);
    }
  }
}

// Case: a held stretch of exactly 5 s (samples 20 s to 25 s - 1) in the 75 bpm ECG.
// Expected: the windows that contain all of it (start from 15 s to 20 s) are marked not usable.
// Verifies: SRS-028
TEST(Srs028SignalQualityOnDefinedSignals, HeldStretchOfExactlyFiveSeconds) {
  for (const int fs : kRates) {
    SCOPED_TRACE(fs);
    std::vector<float> ecg = sinus_qa::synthetic_ecg(fs, 75, 60 * static_cast<std::size_t>(fs), 0);
    std::fill(ecg.begin() + static_cast<std::ptrdiff_t>(seconds(fs, 20)),
              ecg.begin() + static_cast<std::ptrdiff_t>(seconds(fs, 25)), 2.0F);
    for (const Win& x : run_windows(ecg, fs, 50)) {
      const std::uint64_t s = x.first / static_cast<std::uint64_t>(fs);
      if (s >= 15 && s <= 20) {
        EXPECT_FALSE(x.usable) << "start " << s << " s";
      }
    }
  }
}

// Case: an input held at the limit of the acquisition range (+1000 mV, then -1000 mV) from 20 s to
// 40 s of the 75 bpm ECG.
// Expected: the windows with at least 5 s of the stretch (start 15 s to 35 s) are not usable.
// Verifies: SRS-028
TEST(Srs028SignalQualityOnDefinedSignals, SaturatedInputIsNotUsable) {
  for (const int fs : kRates) {
    for (const float level : {1000.0F, -1000.0F}) {
      SCOPED_TRACE(testing::Message() << fs << " Hz level " << level);
      std::vector<float> ecg =
          sinus_qa::synthetic_ecg(fs, 75, 60 * static_cast<std::size_t>(fs), 0);
      std::fill(ecg.begin() + static_cast<std::ptrdiff_t>(seconds(fs, 20)),
                ecg.begin() + static_cast<std::ptrdiff_t>(seconds(fs, 40)), level);
      for (const Win& x : run_windows(ecg, fs, 50)) {
        const std::uint64_t s = x.first / static_cast<std::uint64_t>(fs);
        if (s >= 15 && s <= 35) {
          EXPECT_FALSE(x.usable) << "start " << s << " s";
        }
      }
    }
  }
}

}  // namespace
