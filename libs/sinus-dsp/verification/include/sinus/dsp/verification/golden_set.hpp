#pragma once

// SRS-034: the input identifiers that the folder of golden vectors must hold, written out
// (architecture.md 7.2, architecture-m2.md 13.9, 14.12): 18 synthetic inputs, 8 event inputs and
// 6 record segments. A new input of the reference fails the check until this list follows it.

#include <array>
#include <cstddef>
#include <string_view>

namespace sinus::dsp::verification {

inline constexpr std::size_t kExpectedInputCount = 32;

// In code-point order; the file of an identifier is "<identifier>.golden.txt".
[[nodiscard]] const std::array<std::string_view, kExpectedInputCount>& expected_inputs() noexcept;

inline constexpr std::string_view kGoldenFileSuffix = ".golden.txt";

// A segment of a record of the MIT-BIH Arrhythmia Database (identifier "mitdb-<record>-first60s").
[[nodiscard]] bool is_record_segment(std::string_view input_id) noexcept;

}  // namespace sinus::dsp::verification
