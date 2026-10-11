#pragma once

// SRS-020, SRS-021, SRS-022: streaming QRS detection with the mark, the report sample and the path
// of every detection (architecture-m2.md 13.3, 13.4, 14.4, 14.7; architecture-m1.md 8.7). The
// per-sample procedure is that of the reference (dsp/sinus_dsp/qrs.py, _trace), in binary32 with
// the operation order of architecture-m2.md 14.3.

#include <array>
#include <cstddef>
#include <cstdint>

#include "sinus/dsp/biquad.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/status.hpp"

namespace sinus::dsp {

enum class Mark : std::uint8_t { kStartUp, kReliable };
enum class DetectionPath : std::uint8_t { kNormal, kSearchBack, kLearning };

struct Detection {
  std::uint64_t index;        // fiducial point, time base of the stream (SRS-020)
  std::uint64_t reported_at;  // the sample at which it is reported (13.3); index <= reported_at
  Mark mark;                  // SRS-022
  DetectionPath path;         // 13.3; diagnostic, not compared with the reference
};

struct ZoneSums {      // for the signal quality index (14.9)
  std::uint64_t peak;  // m, the peak of the integrated signal
  float first_part;    // compensated sum of s over the zone's part in the block of its first sample
  float second_part;   // over the part in the next block (0.0f if none)
};

struct DetectorStep {
  float squared_derivative = 0.0F;  // s of this sample (architecture-m1.md 8.7.1, step 3)
  std::size_t count = 0;            // detections reported at this sample, in the order of 8.7.3
  std::array<Detection, kMaxDetectionsPerSample> detections{};
  std::array<ZoneSums, kMaxDetectionsPerSample> zones{};
};

struct QrsDetectorProbe;  // developer's unit tests: the store of peaks at its capacity

class QrsDetector {
 public:
  // SRS-017: kInvalidSamplingFrequency for a sampling frequency that validate() rejects; a failure
  // leaves the detector not configured. On success a new stream starts, as after reset().
  [[nodiscard]] Status configure(double fs_hz) noexcept;
  // SRS-031: a new stream with the same configuration; sample 0 is the next sample.
  void reset() noexcept;
  // SRS-020, SRS-021, SRS-022: one conditioned sample; out holds the detections reported at it.
  // Returns kNotConfigured, with an empty out, before a successful configure.
  [[nodiscard]] Status process(float conditioned_mv, DetectorStep& out) noexcept;

 private:
  // A confirmed peak (architecture-m2.md 14.7, "Peak records"), 32 bytes.
  struct PeakRecord {
    std::uint64_t m;          // peak of the integrated signal
    std::uint16_t m_minus_f;  // m - f, at most N + 1 + D
    float peak_i;             // y[m]
    float peak_f;             // largest |b| in the window of the peak
    float slope;              // largest |d| in the window of the peak
    float zone_first;         // ZoneSums::first_part
    float zone_second;        // ZoneSums::second_part
  };
  static_assert(sizeof(PeakRecord) == 32);  // architecture-m2.md 14.7, 14.10

  friend struct QrsDetectorProbe;

  void start_stream() noexcept;
  void confirm_peak(std::uint64_t n, DetectorStep& out) noexcept;
  void store(const PeakRecord& peak) noexcept;
  void classify(const PeakRecord& peak, std::uint64_t n, DetectorStep& out) noexcept;
  void accept(const PeakRecord& peak, bool search_back, std::uint64_t n,
              DetectorStep& out) noexcept;
  void noise(const PeakRecord& peak) noexcept;
  void search_back(std::uint64_t n, DetectorStep& out) noexcept;
  [[nodiscard]] bool relearn_due(std::uint64_t n) const noexcept;
  void initialise(std::uint64_t n, DetectorStep& out) noexcept;

  // Configuration.
  DetectorSamples samples_{};
  std::uint32_t block_ = 0;  // H of the signal quality index, for the zone parts
  float c0_ = 0.0F;          // fs / 8
  float c1_ = 0.0F;          // fs / 4
  bool configured_ = false;

  // Linear stages.
  BiquadF32 highpass_;
  BiquadF32 lowpass_;
  std::array<float, kDetectorBandpassCapacity> bandpassed_{};
  std::array<float, kDetectorDerivativeCapacity> derivative_{};
  std::array<float, kDetectorWindowCapacity> squared_{};
  std::array<float, kDetectorLearningCapacity> learning_integrated_{};
  std::array<float, kDetectorLearningCapacity> learning_abs_bandpassed_{};

  // Peak tracker (architecture-m1.md 8.7.2).
  float tracker_value_ = 0.0F;
  std::uint64_t tracker_index_ = 0;
  bool tracker_has_index_ = false;
  float previous_integrated_ = 0.0F;

  // Decisions (architecture-m1.md 8.7.3).
  std::array<PeakRecord, kDetectorPeakStoreCapacity> peaks_{};
  std::size_t peaks_head_ = 0;  // the oldest record
  std::size_t peaks_count_ = 0;
  PeakRecord last_{};
  PeakRecord candidate_{};
  bool has_last_ = false;
  bool has_candidate_ = false;
  float spki_ = 0.0F;
  float npki_ = 0.0F;
  float spkf_ = 0.0F;
  float npkf_ = 0.0F;
  std::array<std::uint64_t, kDetectorRrIntervalCapacity> rr_intervals_{};
  std::size_t rr_head_ = 0;
  std::size_t rr_count_ = 0;
  bool rr_flag_ = false;
  std::uint64_t init_n_ = 0;
  bool initialised_ = false;
  DetectionPath path_ = DetectionPath::kNormal;
  std::uint64_t n_ = 0;  // the current sample of the stream
};

}  // namespace sinus::dsp
