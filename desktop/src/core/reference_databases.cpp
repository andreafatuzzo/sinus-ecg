#include "core/reference_databases.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <ios>
#include <map>
#include <string>
#include <string_view>
#include <system_error>

#include "core/mains.hpp"
#include "core/sha256.hpp"
#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

// The constants of sinus_dsp.data.physionet (MITDB, NSTDB); a Python test compares them.
const std::array<ReferenceDatabase, 2> kReferenceDatabases{{
    {"mitdb", "1.0.0", "MIT-BIH Arrhythmia Database",
     "b61158a96d5f2ca80edfb354a9a66a6324836c390a84e1966dcee2b907d6be43", MainsFrequency::k60Hz},
    {"nstdb", "1.0.0", "MIT-BIH Noise Stress Test Database",
     "b76bd98c5111439fcfff2f410afd70d64e79f072049c45b5a9916a3044fdb84f", MainsFrequency::k60Hz},
}};

namespace {

constexpr std::size_t kDigestDigits = 64;

constexpr bool is_hex(char c) noexcept {
  return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

constexpr bool is_path_char(char c) noexcept {
  return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' ||
         c == '_' || c == '+' || c == '-';
}

char lower(char c) noexcept { return c >= 'A' && c <= 'Z' ? static_cast<char>(c - 'A' + 'a') : c; }

// A relative path with '/' separators whose components match [A-Za-z0-9._+-]+ and are not '.'
// or '..' (8.3).
bool is_safe_path(std::string_view path) noexcept {
  std::string_view rest = path;
  while (true) {
    const std::size_t end = rest.find('/');
    const std::string_view component = rest.substr(0, end);
    if (component.empty() || component == "." || component == ".." ||
        !std::all_of(component.begin(), component.end(), is_path_char)) {
      return false;
    }
    if (end == std::string_view::npos) {
      return true;
    }
    rest.remove_prefix(end + 1);
  }
}

using ChecksumList = std::map<std::string, std::string>;  // path -> lowercase digest

// The rules of 8.3: one entry per non-empty line, `^([0-9a-fA-F]{64}) [ *]?(\S+)$`, a safe
// path, no duplicate, at least one entry. false: `what` names the line and the rule.
bool parse_checksum_list(std::string_view text, ChecksumList& list, std::string& what) {
  std::size_t number = 0;
  std::string_view rest = text;
  bool more = !rest.empty();
  while (more) {
    ++number;
    const std::size_t end = rest.find('\n');
    std::string_view line = rest.substr(0, end);
    more = end != std::string_view::npos;
    rest.remove_prefix(more ? end + 1 : rest.size());
    if (!line.empty() && line.back() == '\r') {
      line.remove_suffix(1);
    }
    if (line.empty()) {
      continue;
    }
    const std::string_view digest = line.substr(0, kDigestDigits);
    if (digest.size() != kDigestDigits || !std::all_of(digest.begin(), digest.end(), is_hex) ||
        line.size() <= kDigestDigits || line.at(kDigestDigits) != ' ') {
      what = "line " + std::to_string(number) + " is not a checksum entry";
      return false;
    }
    std::string_view path = line.substr(kDigestDigits + 1);
    if (path.size() > 1 && (path.front() == ' ' || path.front() == '*')) {
      path.remove_prefix(1);
    }
    if (!is_safe_path(path)) {
      what = "line " + std::to_string(number) + " has an unsafe path";
      return false;
    }
    std::string lowercase(digest);
    std::transform(lowercase.begin(), lowercase.end(), lowercase.begin(), lower);
    if (!list.emplace(std::string(path), lowercase).second) {
      what = "line " + std::to_string(number) + " repeats a path";
      return false;
    }
  }
  if (list.empty()) {
    what = "the list has no entry";
    return false;
  }
  return true;
}

// The content of a regular file of at most `limit` bytes. kNotFound: no file; kTooLarge: larger.
enum class ReadOutcome : std::uint8_t { kRead, kNotFound, kTooLarge, kFailed };

ReadOutcome read_small_file(const std::filesystem::path& path, std::uintmax_t limit,
                            std::string& content) {
  std::error_code error;
  const std::filesystem::file_status status = std::filesystem::status(path, error);
  if (status.type() == std::filesystem::file_type::not_found) {
    return ReadOutcome::kNotFound;
  }
  if (error || status.type() != std::filesystem::file_type::regular) {
    return ReadOutcome::kFailed;
  }
  const std::uintmax_t size = std::filesystem::file_size(path, error);
  if (error) {
    return ReadOutcome::kFailed;
  }
  if (size > limit) {
    return ReadOutcome::kTooLarge;
  }
  std::ifstream file(path, std::ios::binary);
  if (!file.is_open()) {
    return ReadOutcome::kFailed;
  }
  content.resize(size);
  file.read(content.data(), static_cast<std::streamsize>(content.size()));
  if (file.bad() || file.gcount() != static_cast<std::streamsize>(content.size())) {
    return ReadOutcome::kFailed;
  }
  // A file that grew while it was read is not the one measured.
  return file.peek() == std::ifstream::traits_type::eof() ? ReadOutcome::kRead
                                                          : ReadOutcome::kFailed;
}

WfdbResult failure(WfdbStatus status, const std::string& record_name, std::string_view what) {
  WfdbResult result;
  result.status = status;
  result.message.assign(record_name).append(": ").append(what);
  return result;
}

}  // namespace

WfdbResult check_reference_record(const std::filesystem::path& record_path,
                                  const ReferenceDatabase* databases, std::size_t count,
                                  ReferenceCheck& check, const ReferenceDatabase*& database) {
  check = ReferenceCheck::kNotReference;
  database = nullptr;
  const std::string record_name = record_path.filename().u8string();
  const std::filesystem::path folder = record_path.parent_path();
  const std::filesystem::path list_path = folder / kChecksumListName;
  std::string content;
  const ReadOutcome outcome = read_small_file(list_path, kChecksumListMaxBytes, content);
  if (outcome == ReadOutcome::kNotFound || outcome == ReadOutcome::kTooLarge) {
    return {};
  }
  if (outcome == ReadOutcome::kFailed) {
    return failure(WfdbStatus::kCannotRead, record_name,
                   "cannot read " + std::string(kChecksumListName));
  }
  Sha256 hash;
  // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): the bytes of the text.
  hash.update(reinterpret_cast<const std::uint8_t*>(content.data()), content.size());
  const std::string digest = to_hex(hash.finish());
  const ReferenceDatabase* found = nullptr;
  for (std::size_t i = 0; i < count && found == nullptr; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): `count` databases.
    const ReferenceDatabase& candidate = databases[i];
    if (candidate.checksum_list_sha256 == digest) {
      found = &candidate;
    }
  }
  if (found == nullptr) {
    return {};
  }
  const std::string list_mismatch = std::string(kChecksumListName) +
                                    " does not match the verified checksum list of the " +
                                    std::string(found->title);
  ChecksumList list;
  std::string what;
  if (!parse_checksum_list(content, list, what)) {
    return failure(WfdbStatus::kReferenceMismatch, record_name, list_mismatch + ": " + what);
  }
  // The files of the record: every top-level path "<record>." followed by at least one character,
  // in code-point order (the order of the map).
  const std::string prefix = record_name + ".";
  bool any = false;
  for (const auto& [path, expected] : list) {
    if (path.size() <= prefix.size() || path.compare(0, prefix.size(), prefix) != 0 ||
        path.find('/') != std::string::npos) {
      continue;
    }
    any = true;
    const std::filesystem::path file = folder / path;
    std::error_code error;
    if (!std::filesystem::is_regular_file(file, error)) {
      return failure(WfdbStatus::kReferenceMismatch, record_name,
                     path + " is missing from the folder of the verified checksum list of the " +
                         std::string(found->title));
    }
    Sha256Digest actual{};
    if (!sha256_file(file, actual) || to_hex(actual) != expected) {
      return failure(
          WfdbStatus::kReferenceMismatch, record_name,
          path + " does not match the verified checksum list of the " + std::string(found->title));
    }
  }
  if (any) {
    check = ReferenceCheck::kVerified;
    database = found;
  }
  return {};
}

}  // namespace sinus::desktop::core
