#pragma once

// SRS-037: the results of the equivalence check as a Markdown file (architecture-m2.md 14.12): the
// build target, the identity of the library and of the reference software, and for each file and
// each compared output the largest difference, its tolerance and the outcome. The text is the same,
// byte for byte, on every target for the same results.

#include <cstddef>
#include <string>

#include "sinus/dsp/verification/equivalence.hpp"

namespace sinus::dsp::verification {

struct ReportInfo {
  std::string build_target;  // "computer (x86_64, Linux, GNU 14.2.0)"
  std::string library_version;
  std::string library_sha256;
  std::size_t chain_bytes = 0;
  std::size_t chain_limit = 0;
};

// The identity of the library (version.hpp), the size of the Chain and its limit, and the given
// build target.
[[nodiscard]] ReportInfo make_report_info(const std::string& build_target);

// A number as the shortest text that converts back to the same binary64 value; 0 for zero.
[[nodiscard]] std::string format_number(double value);

[[nodiscard]] std::string render_equivalence_report(const SetResult& set, const ReportInfo& info);

}  // namespace sinus::dsp::verification
