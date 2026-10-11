// SRS-034: the expected set of golden vectors (architecture-m2.md 14.12).
#include "sinus/dsp/verification/golden_set.hpp"

#include <array>
#include <string_view>

namespace sinus::dsp::verification {

const std::array<std::string_view, kExpectedInputCount>& expected_inputs() noexcept {
  static constexpr std::array<std::string_view, kExpectedInputCount> inputs{
      "mitdb-100-first60s",          "mitdb-105-first60s",         "mitdb-108-first60s",
      "mitdb-119-first60s",          "mitdb-203-first60s",         "mitdb-207-first60s",
      "syn-fs250-event-artefact",    "syn-fs250-event-held",       "syn-fs250-event-rate-change",
      "syn-fs250-event-small-beat",  "syn-fs250-hr040-bw-mains50", "syn-fs250-hr040-bw-mains60",
      "syn-fs250-hr040-clean",       "syn-fs250-hr075-bw-mains50", "syn-fs250-hr075-bw-mains60",
      "syn-fs250-hr075-clean",       "syn-fs250-hr180-bw-mains50", "syn-fs250-hr180-bw-mains60",
      "syn-fs250-hr180-clean",       "syn-fs360-event-artefact",   "syn-fs360-event-held",
      "syn-fs360-event-rate-change", "syn-fs360-event-small-beat", "syn-fs360-hr040-bw-mains50",
      "syn-fs360-hr040-bw-mains60",  "syn-fs360-hr040-clean",      "syn-fs360-hr075-bw-mains50",
      "syn-fs360-hr075-bw-mains60",  "syn-fs360-hr075-clean",      "syn-fs360-hr180-bw-mains50",
      "syn-fs360-hr180-bw-mains60",  "syn-fs360-hr180-clean"};
  return inputs;
}

bool is_record_segment(std::string_view input_id) noexcept {
  constexpr std::string_view prefix = "mitdb-";
  return input_id.substr(0, prefix.size()) == prefix;
}

}  // namespace sinus::dsp::verification
