// SRS-037: the equivalence results (architecture-m2.md 14.12).
#include "sinus/dsp/verification/equivalence_report.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cstddef>
#include <string>
#include <string_view>
#include <system_error>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"
#include "sinus/dsp/verification/golden_set.hpp"
#include "sinus/dsp/version.hpp"

namespace sinus::dsp::verification {

namespace {

constexpr std::string_view kDash = "\xE2\x80\x94";  // U+2014, where there is no value
constexpr std::string_view kDatabaseNotice =
    "The files mitdb-100-first60s, mitdb-105-first60s, mitdb-108-first60s, mitdb-119-first60s, "
    "mitdb-203-first60s and mitdb-207-first60s contain extracts of the MIT-BIH Arrhythmia "
    "Database, version 1.0.0, made available by PhysioNet under the Open Data Commons "
    "Attribution License v1.0, https://opendatacommons.org/licenses/by/1-0/; the results above "
    "are computed from them.";
constexpr std::size_t kNumberBuffer = 64;
constexpr unsigned char kAsciiLimit = 0x80;
constexpr unsigned char kFirstPrintable = 0x20;

// A text in a table cell: no bar, no control character and nothing outside ASCII.
std::string cell(std::string_view text) {
  std::string out;
  for (const char c : text) {
    const auto byte = static_cast<unsigned char>(c);
    out += (c == '|' || byte < kFirstPrintable || byte >= kAsciiLimit) ? '?' : c;
  }
  return out;
}

std::string sample_text(const OutputResult& output) {
  return output.has_sample ? std::to_string(output.sample) : std::string(kDash);
}

std::string row(const std::string& file, std::string_view output, std::string_view difference,
                std::string_view sample, std::string_view tolerance, bool pass) {
  return "| " + file + " | " + std::string(output) + " | " + std::string(difference) + " | " +
         std::string(sample) + " | " + std::string(tolerance) + " | " + (pass ? "pass" : "fail") +
         " |\n";
}

void append_file(const FileResult& file, std::string& out) {
  const std::string name = cell(file.input_id);
  if (file.status != FileStatus::kCompared) {
    out += row(name, "file", cell(file.detail), kDash, kDash, false);
    return;
  }
  for (const OutputResult& output : file.outputs) {
    const std::string difference =
        output.difference.empty() ? format_number(output.largest) : cell(output.difference);
    out += row(name, output.output, difference, sample_text(output),
               format_number(output.tolerance), output.pass);
  }
}

std::string reference_text(const ReferenceIdentity& identity) {
  switch (identity.state) {
    case ReferenceState::kNone:
      return "no file could be read";
    case ReferenceState::kMixed:
      return "not the same in every file";
    case ReferenceState::kSame:
      break;
  }
  return "sinus-dsp " + cell(identity.software_version) + ", source SHA-256 " +
         cell(identity.source_sha256);
}

bool has_record_segment(const SetResult& set) {
  return std::any_of(set.files.begin(), set.files.end(), [](const FileResult& file) {
    return file.status != FileStatus::kMissing && is_record_segment(file.input_id);
  });
}

}  // namespace

ReportInfo make_report_info(const std::string& build_target) {
  const LibraryIdentity identity = library_identity();
  ReportInfo info;
  info.build_target = build_target;
  info.library_version = identity.version;
  info.library_sha256 = identity.source_sha256;
  info.chain_bytes = sizeof(Chain);
  info.chain_limit = kChainMemoryLimitBytes;
  return info;
}

std::string format_number(double value) {
  std::array<char, kNumberBuffer> buffer{};
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): the end of the buffer.
  const auto result = std::to_chars(buffer.data(), buffer.data() + buffer.size(), value);
  if (result.ec != std::errc()) {
    return "?";
  }
  return {buffer.data(), result.ptr};
}

std::string render_equivalence_report(const SetResult& set, const ReportInfo& info) {
  std::string out = "# Equivalence of the real-time library with the reference\n\n";
  out += "| Item | Value |\n|---|---|\n";
  out += "| Build target | " + cell(info.build_target) + " |\n";
  out += "| Library | sinus-dsp " + cell(info.library_version) + ", source SHA-256 " +
         cell(info.library_sha256) + " |\n";
  out += "| Reference | " + reference_text(reference_identity(set)) + " |\n";
  out += "| Golden vectors | " + std::to_string(set.expected_present()) + " files of " +
         std::to_string(kExpectedInputCount) + " expected, format version " +
         std::to_string(kGoldenFormatVersion) + " |\n";
  out += "| Chain size | " + std::to_string(info.chain_bytes) + " bytes, limit " +
         std::to_string(info.chain_limit) + " |\n";
  if (has_record_segment(set)) {
    out += "| Database notice | " + std::string(kDatabaseNotice) + " |\n";
  }
  out += std::string("| Outcome | ") + (set_passed(set) ? "pass" : "fail") + " |\n";
  out += "\n## Results per file\n\n";
  out += "| File | Output | Largest difference | At sample | Tolerance | Outcome |\n";
  out += "|---|---|---:|---:|---:|---|\n";
  for (const FileResult& file : set.files) {
    append_file(file, out);
  }
  return out;
}

}  // namespace sinus::dsp::verification
