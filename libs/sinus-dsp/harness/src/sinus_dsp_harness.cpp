// SRS-038: the C interface of the harness (architecture-m2.md 14.14). It runs the library on a
// whole record and returns the detections; the scoring is done by the Python evaluation.
#include "sinus_dsp_harness.h"

#include <cstddef>
#include <cstdint>
#include <string>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/status.hpp"
#include "sinus/dsp/version.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::Status;

std::int64_t failure(Status status) noexcept { return -1 - static_cast<std::int64_t>(status); }

// Writes one detection at `slot` of the output arrays.
void store(const sinus::dsp::Detection& detection, std::uint64_t slot, std::uint64_t* indices,
           std::uint8_t* startup, std::uint64_t* reported_at) noexcept {
  // NOLINTBEGIN(cppcoreguidelines-pro-bounds-pointer-arithmetic): the caller gives `capacity`
  // slots in each array, and `slot < capacity` is checked before the call.
  indices[slot] = detection.index;
  startup[slot] = detection.mark == sinus::dsp::Mark::kStartUp ? 1U : 0U;
  reported_at[slot] = detection.reported_at;
  // NOLINTEND(cppcoreguidelines-pro-bounds-pointer-arithmetic)
}

}  // namespace

extern "C" {

std::int64_t sinus_dsp_harness_detect(double fs_hz, std::int32_t mains_hz, const float* samples_mv,
                                      std::uint64_t n, std::uint64_t* indices,
                                      std::uint8_t* startup, std::uint64_t* reported_at,
                                      std::uint64_t capacity) {
  if ((n > 0 && samples_mv == nullptr) ||
      (capacity > 0 && (indices == nullptr || startup == nullptr || reported_at == nullptr))) {
    return failure(Status::kInvalidArgument);
  }
  Chain chain;
  const Status configured = chain.configure(Config{fs_hz, mains_hz});
  if (configured != Status::kOk) {
    return failure(configured);
  }
  std::uint64_t total = 0;
  sinus::dsp::SampleOutput out;
  for (std::uint64_t i = 0; i < n; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): i < n samples were given.
    const Status status = chain.process(samples_mv[i], out);
    if (status != Status::kOk) {
      return failure(status);
    }
    for (std::size_t k = 0; k < out.detection_count; ++k) {
      if (total < capacity) {
        // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-constant-array-index): k < detection_count
        store(out.detections.at(k), total, indices, startup, reported_at);
      }
      ++total;
    }
  }
  return static_cast<std::int64_t>(total);
}

const char* sinus_dsp_harness_identity(void) {
  static const std::string text = [] {
    const sinus::dsp::LibraryIdentity identity = sinus::dsp::library_identity();
    return std::string(identity.version) + ";" + identity.source_sha256;
  }();
  return text.c_str();
}

}  // extern "C"
