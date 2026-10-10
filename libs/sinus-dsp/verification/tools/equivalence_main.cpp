// SRS-034, SRS-037: sinus_dsp_equivalence --vectors <folder> --results <file>
// Checks the real-time library against the golden vectors of the folder and writes the results.
// Exit status: 0 if every expected file is present and passes, 1 otherwise, 2 on a usage error (or
// if the folder cannot be listed or the results cannot be written).
#include <cstddef>
#include <fstream>
#include <ios>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/equivalence_report.hpp"

#ifndef SINUS_DSP_BUILD_TARGET
#define SINUS_DSP_BUILD_TARGET "computer (unknown)"
#endif

namespace {

using sinus::dsp::verification::FileResult;
using sinus::dsp::verification::FileStatus;
using sinus::dsp::verification::OutputResult;
using sinus::dsp::verification::SetResult;

constexpr int kExitPass = 0;
constexpr int kExitFail = 1;
constexpr int kExitUsage = 2;

struct Arguments {
  std::string vectors;
  std::string results;
  bool ok = false;
};

Arguments parse_arguments(const std::vector<std::string_view>& args) {
  Arguments parsed;
  bool has_vectors = false;
  bool has_results = false;
  for (std::size_t i = 0; i < args.size(); i += 2) {
    if (i + 1 >= args.size()) {
      return parsed;
    }
    if (args.at(i) == "--vectors" && !has_vectors) {
      parsed.vectors = std::string(args.at(i + 1));
      has_vectors = true;
    } else if (args.at(i) == "--results" && !has_results) {
      parsed.results = std::string(args.at(i + 1));
      has_results = true;
    } else {
      return parsed;
    }
  }
  parsed.ok = has_vectors && has_results;
  return parsed;
}

// One line on standard error for each failure: the file, the output and the sample.
void print_failures(const SetResult& set) {
  for (const FileResult& file : set.files) {
    if (file.status != FileStatus::kCompared) {
      std::cerr << "FAIL " << file.input_id << ": " << file.detail << '\n';
      continue;
    }
    for (const OutputResult& output : file.outputs) {
      if (output.pass) {
        continue;
      }
      const std::string what =
          output.difference.empty()
              ? "largest difference " + sinus::dsp::verification::format_number(output.largest) +
                    ", tolerance " + sinus::dsp::verification::format_number(output.tolerance)
              : output.difference;
      const std::string sample = output.has_sample ? std::to_string(output.sample) : "-";
      std::cerr << "FAIL " << file.input_id << ": " << output.output << " at sample " << sample
                << ": " << what << '\n';
    }
  }
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
    std::cerr << "usage: sinus_dsp_equivalence --vectors <folder> --results <file>\n";
    return kExitUsage;
  }
  const SetResult set = sinus::dsp::verification::check_folder(arguments.vectors);
  if (!set.folder_listed) {
    std::cerr << "cannot list the folder " << arguments.vectors << '\n';
    return kExitUsage;
  }
  const std::string text = sinus::dsp::verification::render_equivalence_report(
      set, sinus::dsp::verification::make_report_info(SINUS_DSP_BUILD_TARGET));
  {
    std::ofstream file(arguments.results, std::ios::binary | std::ios::trunc);
    file.write(text.data(), static_cast<std::streamsize>(text.size()));
    file.flush();
    if (!file) {
      std::cerr << "cannot write the results to " << arguments.results << '\n';
      return kExitUsage;
    }
  }
  const bool passed = sinus::dsp::verification::set_passed(set);
  print_failures(set);
  std::cout << (passed ? "pass" : "fail") << ": " << arguments.results << '\n';
  return passed ? kExitPass : kExitFail;
}
