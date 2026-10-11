// SRS-036: sinus_dsp_golden_pack --vectors <folder> --output <file>
// Converts the golden vectors of the folder into the binary pack that the ESP32-S3 test app reads
// (architecture-m2.md 14.13). Every expected file is read with the verified reader of the text
// files; a missing, unexpected or rejected file fails the tool, so that no pack is written for an
// incomplete set. Exit status: 0 written, 1 the set is wrong, 2 usage or file error.
#include <cstddef>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <set>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

#include "sinus/dsp/verification/golden_pack.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"
#include "sinus/dsp/verification/golden_set.hpp"

namespace {

using sinus::dsp::verification::GoldenVector;

constexpr int kExitPass = 0;
constexpr int kExitFail = 1;
constexpr int kExitUsage = 2;

struct Arguments {
  std::string vectors;
  std::string output;
  bool ok = false;
};

Arguments parse_arguments(const std::vector<std::string_view>& args) {
  Arguments parsed;
  bool has_vectors = false;
  bool has_output = false;
  for (std::size_t i = 0; i < args.size(); i += 2) {
    if (i + 1 >= args.size()) {
      return parsed;
    }
    if (args.at(i) == "--vectors" && !has_vectors) {
      parsed.vectors = std::string(args.at(i + 1));
      has_vectors = true;
    } else if (args.at(i) == "--output" && !has_output) {
      parsed.output = std::string(args.at(i + 1));
      has_output = true;
    } else {
      return parsed;
    }
  }
  parsed.ok = has_vectors && has_output;
  return parsed;
}

bool ends_with(std::string_view text, std::string_view suffix) noexcept {
  return text.size() >= suffix.size() && text.substr(text.size() - suffix.size()) == suffix;
}

// The *.golden.txt files of the folder that the set does not expect; false if it cannot be listed.
bool list_unexpected(const std::string& folder, std::vector<std::string>& unexpected) {
  std::set<std::string> expected;
  for (const std::string_view id : sinus::dsp::verification::expected_inputs()) {
    expected.emplace(id);
  }
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
    const std::string_view suffix = sinus::dsp::verification::kGoldenFileSuffix;
    if (it->is_regular_file(error) && ends_with(name, suffix) &&
        expected.count(name.substr(0, name.size() - suffix.size())) == 0) {
      unexpected.push_back(name);
    }
  }
  return !error;
}

// NOLINTNEXTLINE(bugprone-easily-swappable-parameters): the path and the bytes.
bool write_file(const std::string& path, const std::string& bytes) {
  // <cstdio>, as in sinus_dsp_equivalence.
  // NOLINTNEXTLINE(cppcoreguidelines-owning-memory): closed below, no RAII type in <cstdio>.
  std::FILE* file = std::fopen(path.c_str(), "wb");
  if (file == nullptr) {
    return false;
  }
  bool written = std::fwrite(bytes.data(), 1, bytes.size(), file) == bytes.size();
  // NOLINTNEXTLINE(cppcoreguidelines-owning-memory): the close of the file opened above.
  written = (std::fclose(file) == 0) && written;
  return written;
}

}  // namespace

int main(int argc, char** argv) {
  std::vector<std::string_view> args;
  for (int i = 1; i < argc; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): the command line.
    args.emplace_back(argv[i]);
  }
  const Arguments arguments = parse_arguments(args);
  if (!arguments.ok) {
    std::cerr << "usage: sinus_dsp_golden_pack --vectors <folder> --output <file>\n";
    return kExitUsage;
  }
  std::vector<std::string> unexpected;
  if (!list_unexpected(arguments.vectors, unexpected)) {
    std::cerr << "cannot list the folder " << arguments.vectors << '\n';
    return kExitUsage;
  }
  bool complete = true;
  for (const std::string& name : unexpected) {
    std::cerr << "FAIL " << name << ": unexpected\n";
    complete = false;
  }
  std::vector<GoldenVector> vectors;
  for (const std::string_view id : sinus::dsp::verification::expected_inputs()) {
    const std::string path =
        (std::filesystem::path(arguments.vectors) /
         (std::string(id) + std::string(sinus::dsp::verification::kGoldenFileSuffix)))
            .string();
    sinus::dsp::verification::ReadResult read = sinus::dsp::verification::read_golden_vector(path);
    if (!read.ok) {
      std::cerr << "FAIL " << id << ": " << path << ": ";
      if (read.error.has_line) {
        std::cerr << "line " << read.error.line << ": ";
      }
      std::cerr << read.error.reason << '\n';
      complete = false;
      continue;
    }
    vectors.push_back(std::move(read.vector));
  }
  if (!complete) {
    return kExitFail;
  }
  std::string bytes;
  const sinus::dsp::verification::PackOutcome built =
      sinus::dsp::verification::build_pack(vectors, bytes);
  if (!built.ok) {
    std::cerr << "FAIL " << built.error << '\n';
    return kExitFail;
  }
  if (!write_file(arguments.output, bytes)) {
    std::cerr << "cannot write the pack to " << arguments.output << '\n';
    return kExitUsage;
  }
  std::cout << "pack: " << bytes.size() << " bytes, " << vectors.size()
            << " files: " << arguments.output << '\n';
  return kExitPass;
}
