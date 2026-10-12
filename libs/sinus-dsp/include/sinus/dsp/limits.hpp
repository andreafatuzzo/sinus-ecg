#pragma once

// SRS-017, SRS-018, SRS-032: supported range of the sampling frequency and of the amplitude, and
// the capacities of the library (architecture-m2.md 14.4, 14.10; architecture-m3.md 16.6).

#include <cstddef>
#include <cstdint>

namespace sinus::dsp {

// SRS-017: the sampling frequencies that the library accepts, bounds included.
inline constexpr double kMinSamplingFrequencyHz = 125.0;
inline constexpr double kMaxSamplingFrequencyHz = 1000.0;
// SRS-018: the largest magnitude of an input sample, in mV.
inline constexpr float kMaxAbsSampleMv = 1000.0F;
// Capacities, sized for kMaxSamplingFrequencyHz (architecture-m2.md 14.10).
inline constexpr std::size_t kMaxDetectionsPerSample = 12;
inline constexpr std::size_t kMaxHeartRateEventsPerSample = 12;
// Capacities of the detector (architecture-m2.md 14.7, 14.10), from its parameters at 1000 Hz:
// N = 150, P = 95, L = 2000 samples. Every parameter in samples grows with the sampling frequency.
inline constexpr std::size_t kDetectorWindowCapacity = 150;      // s: N
inline constexpr std::size_t kDetectorBandpassCapacity = 248;    // b: N + P + 3
inline constexpr std::size_t kDetectorDerivativeCapacity = 246;  // d: N + P + 1
inline constexpr std::size_t kDetectorLearningCapacity = 2000;   // y and |b|: L
inline constexpr std::size_t kDetectorPeakStoreCapacity = 1000;  // peaks: L / 2
inline constexpr std::size_t kDetectorRrIntervalCapacity = 8;    // RR intervals of search-back
// SRS-044: the display low-pass (architecture-m3.md 16.2, 16.6): M = round(30 ms * fs) is at
// most 30 samples (at 1000 Hz), and the filter has 2M + 1 taps.
inline constexpr std::uint32_t kDisplayMaxDelaySamples = 30;
inline constexpr std::size_t kDisplayTapCapacity = (2 * std::size_t{kDisplayMaxDelaySamples}) + 1;
// SRS-032: the most that one complete processing chain occupies.
inline constexpr std::size_t kChainMemoryLimitBytes = 65536;

}  // namespace sinus::dsp
