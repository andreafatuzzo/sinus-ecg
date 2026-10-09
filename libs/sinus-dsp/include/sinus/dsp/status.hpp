#pragma once

// SRS-017, SRS-018: the status codes of the real-time library (architecture-m2.md 14.4).

#include <cstdint>

namespace sinus::dsp {

enum class Status : std::uint8_t {
  kOk,                        // the sample was processed; the output holds its results
  kNotConfigured,             // no valid configuration (SRS-017)
  kInvalidSamplingFrequency,  // configure: not finite, or outside 125 Hz to 1000 Hz (SRS-017)
  kInvalidMainsFrequency,     // configure: neither 50 Hz nor 60 Hz (SRS-017)
  kInvalidSample,             // process: not finite, or magnitude above 1000 mV (SRS-018)
  kStopped,                   // process: an earlier sample was invalid; no output until reset
                              // (SRS-018)
  kInvalidArgument,           // a component called with arguments that break its preconditions
};

}  // namespace sinus::dsp
