#pragma once

// WFDB header: the subset read (architecture-m3.md 17.3). Anything outside it is rejected with
// the status of 17.5; nothing is guessed.

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

enum class WfdbFormat : std::uint8_t { kFormat16, kFormat212 };

struct WfdbSignal {
  std::string file_name;
  WfdbFormat format = WfdbFormat::kFormat16;
  double gain_adu_per_mv = 200.0;  // 200 when the header gives 0 or nothing
  std::string gain_text;           // as written, or "200" when the header gives 0 or nothing
  std::int32_t baseline_adu = 0;   // adczero when not given
  std::int32_t adc_zero_adu = 0;
  std::string units;  // as written; "mV" when not given
  std::optional<std::int32_t> initial_value_adu;
  std::optional<std::int32_t> checksum;
  std::string description;
};

struct WfdbHeader {
  std::string record_name;
  std::uint32_t fs_millihertz = 0;
  double fs_hz = 0.0;
  std::uint64_t sample_count = 0;     // per signal
  std::string base_time, base_date;   // as written, may be empty
  std::vector<WfdbSignal> signals;    // nsig entries
  std::vector<std::string> comments;  // in file order
};

// The largest header text read (17.3).
inline constexpr std::size_t kWfdbHeaderMaxBytes = std::size_t{1} << 20U;

// A decimal `[0-9]+(\.[0-9]+)?`, no sign, no exponent, at most 15 digits in all after the leading
// zeros, at most 15 after the point; the value is double(m) / double(10^F), the correctly rounded
// value of the text. false: not such a decimal (`value` unchanged).
[[nodiscard]] bool parse_wfdb_decimal(std::string_view text, double& value) noexcept;

// Parses the text of <record>.hea for the record `record_name`. When the result is not ok, `out`
// is unspecified.
[[nodiscard]] WfdbResult parse_wfdb_header(std::string_view text, std::string_view record_name,
                                           WfdbHeader& out);

}  // namespace sinus::desktop::core
