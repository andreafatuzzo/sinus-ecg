// SRS-034, SRS-035: the check of a folder of golden vectors (architecture-m2.md 14.12): every
// expected file present, read and compared, a missing or unexpected one named. Separate from
// equivalence.cpp, which the ESP32-S3 test app also builds and which needs neither the text reader
// nor <filesystem>.
#include <filesystem>
#include <set>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>

#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"
#include "sinus/dsp/verification/golden_set.hpp"

namespace sinus::dsp::verification {

namespace {

std::string reader_detail(const ReadError& error) {
  std::string detail = "rejected: ";
  if (error.has_line) {
    detail += "line " + std::to_string(error.line) + ": ";
  }
  return detail + error.reason;
}

bool ends_with(std::string_view text, std::string_view suffix) noexcept {
  return text.size() >= suffix.size() && text.substr(text.size() - suffix.size()) == suffix;
}

// The identifiers of the *.golden.txt files of a folder.
bool list_golden_files(const std::string& folder, std::set<std::string>& ids) {
  std::error_code error;
  std::filesystem::directory_iterator it(folder, error);
  if (error) {
    return false;
  }
  for (; it != std::filesystem::directory_iterator(); it.increment(error)) {
    if (error) {
      return false;
    }
    const std::string name = it->path().filename().string();
    if (it->is_regular_file(error) && ends_with(name, kGoldenFileSuffix)) {
      ids.insert(name.substr(0, name.size() - kGoldenFileSuffix.size()));
    }
  }
  return !error;
}

FileResult problem_result(const std::string& input_id, FileStatus status, std::string detail) {
  FileResult result;
  result.input_id = input_id;
  result.status = status;
  result.detail = std::move(detail);
  return result;
}

}  // namespace

// NOLINTNEXTLINE(bugprone-easily-swappable-parameters): the file name and its path.
FileResult check_file(const std::string& input_id, const std::string& path) {
  const ReadResult read = read_golden_vector(path);
  if (!read.ok) {
    return problem_result(input_id, FileStatus::kRejected, reader_detail(read.error));
  }
  return check_vector(input_id, read.vector);
}

SetResult check_folder(const std::string& folder) {
  SetResult result;
  std::set<std::string> present;
  result.folder_listed = list_golden_files(folder, present);
  if (!result.folder_listed) {
    return result;
  }
  std::set<std::string> expected;
  for (const std::string_view id : expected_inputs()) {
    const std::string name(id);
    expected.insert(name);
    if (present.count(name) == 0) {
      result.files.push_back(problem_result(name, FileStatus::kMissing, "missing"));
    } else {
      result.files.push_back(check_file(
          name,
          (std::filesystem::path(folder) / (name + std::string(kGoldenFileSuffix))).string()));
    }
  }
  for (const std::string& name : present) {
    if (expected.count(name) == 0) {
      result.files.push_back(problem_result(name, FileStatus::kUnexpected, "unexpected"));
    }
  }
  return result;
}

}  // namespace sinus::dsp::verification
