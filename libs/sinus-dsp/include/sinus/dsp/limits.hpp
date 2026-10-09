#pragma once

// SRS-017, SRS-018, SRS-032: supported range of the sampling frequency and of the amplitude, and
// the capacities of the library (architecture-m2.md 14.4, 14.10).

#include <cstddef>

namespace sinus::dsp {

// SRS-017: the sampling frequencies that the library accepts, bounds included.
inline constexpr double kMinSamplingFrequencyHz = 125.0;
inline constexpr double kMaxSamplingFrequencyHz = 1000.0;
// SRS-018: the largest magnitude of an input sample, in mV.
inline constexpr float kMaxAbsSampleMv = 1000.0F;
// Capacities, sized for kMaxSamplingFrequencyHz (architecture-m2.md 14.10).
inline constexpr std::size_t kMaxDetectionsPerSample = 12;
inline constexpr std::size_t kMaxHeartRateEventsPerSample = 12;
// SRS-032: the most that one complete processing chain occupies.
inline constexpr std::size_t kChainMemoryLimitBytes = 65536;

}  // namespace sinus::dsp
