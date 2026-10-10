#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <string>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/limits.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/equivalence_report.hpp"
#include "sinus/dsp/version.hpp"

namespace {

using sinus::dsp::verification::FileResult;
using sinus::dsp::verification::FileStatus;
using sinus::dsp::verification::format_number;
using sinus::dsp::verification::OutputResult;
using sinus::dsp::verification::ReportInfo;
using sinus::dsp::verification::SetResult;

OutputResult numeric(const char* output, double largest, std::uint64_t sample, double tolerance,
                     bool pass) {
  OutputResult r;
  r.output = output;
  r.largest = largest;
  r.has_sample = true;
  r.sample = sample;
  r.tolerance = tolerance;
  r.pass = pass;
  return r;
}

FileResult compared(const std::string& id) {
  FileResult f;
  f.input_id = id;
  f.has_identity = true;
  f.software_version = "0.2.0.dev0";
  f.source_sha256 = std::string(64, 'b');
  f.outputs = {
      numeric("baseline_mv", 1.2383118956904582e-06, 1850, 2e-5, true),
      numeric("mains_mv", 0.0, 0, 2e-5, true),
      numeric("beats", 0.0, 12, 0.0, true),
      numeric("beat_reported_at", 0.0, 12, 0.0, true),
      numeric("heart_rates", 7.4590110443750746e-06, 3531, 1e-4, true),
      numeric("quality_windows", 0.0075, 11520, 0.01, true),
  };
  return f;
}

ReportInfo info() {
  ReportInfo i;
  i.build_target = "computer (x86_64, Linux, GNU 14.2.0)";
  i.library_version = "0.2.0.dev0";
  i.library_sha256 = std::string(64, 'c');
  i.chain_bytes = 51600;
  i.chain_limit = 65536;
  return i;
}

TEST(FormatNumber, IsTheShortestTextThatReadsBack) {
  EXPECT_EQ(format_number(0.0), "0");
  EXPECT_EQ(format_number(3.0), "3");
  EXPECT_EQ(format_number(2e-5), "2e-05");
  EXPECT_EQ(format_number(0.01), "0.01");
  EXPECT_EQ(format_number(1.2383118956904582e-06), "1.2383118956904582e-06");
  EXPECT_EQ(format_number(1e16), "1e+16");
  EXPECT_EQ(format_number(0.1), "0.1");
  for (const double v :
       {1.0 / 3.0, 5e-324, 1.7976931348623157e308, 123456.789, 0.30000000000000004}) {
    EXPECT_EQ(std::strtod(format_number(v).c_str(), nullptr), v);
  }
}

TEST(Report, HasTheLayoutOfTheDesign) {
  SetResult set;
  set.folder_listed = true;
  set.files = {compared("mitdb-100-first60s")};
  const std::string text = render_equivalence_report(set, info());
  const std::string expected =
      "# Equivalence of the real-time library with the reference\n"
      "\n"
      "| Item | Value |\n"
      "|---|---|\n"
      "| Build target | computer (x86_64, Linux, GNU 14.2.0) |\n"
      "| Library | sinus-dsp 0.2.0.dev0, source SHA-256 " +
      std::string(64, 'c') +
      " |\n"
      "| Reference | sinus-dsp 0.2.0.dev0, source SHA-256 " +
      std::string(64, 'b') +
      " |\n"
      "| Golden vectors | 1 files of 32 expected, format version 2 |\n"
      "| Chain size | 51600 bytes, limit 65536 |\n"
      "| Database notice | The files mitdb-100-first60s, mitdb-105-first60s, mitdb-108-first60s, "
      "mitdb-119-first60s, mitdb-203-first60s and mitdb-207-first60s contain extracts of the "
      "MIT-BIH Arrhythmia Database, version 1.0.0, made available by PhysioNet under the Open "
      "Data Commons Attribution License v1.0, https://opendatacommons.org/licenses/by/1-0/; the "
      "results above are computed from them. |\n"
      "| Outcome | pass |\n"
      "\n"
      "## Results per file\n"
      "\n"
      "| File | Output | Largest difference | At sample | Tolerance | Outcome |\n"
      "|---|---|---:|---:|---:|---|\n"
      "| mitdb-100-first60s | baseline_mv | 1.2383118956904582e-06 | 1850 | 2e-05 | pass |\n"
      "| mitdb-100-first60s | mains_mv | 0 | 0 | 2e-05 | pass |\n"
      "| mitdb-100-first60s | beats | 0 | 12 | 0 | pass |\n"
      "| mitdb-100-first60s | beat_reported_at | 0 | 12 | 0 | pass |\n"
      "| mitdb-100-first60s | heart_rates | 7.4590110443750746e-06 | 3531 | " +
      format_number(1e-4) +
      " | pass |\n"
      "| mitdb-100-first60s | quality_windows | 0.0075 | 11520 | 0.01 | pass |\n";
  EXPECT_EQ(text, expected);
  EXPECT_EQ(text.back(), '\n');
  EXPECT_EQ(text.find('\r'), std::string::npos);
}

TEST(Report, ALaterRowFollowsTheEarlierOnes) {
  SetResult set;
  set.folder_listed = true;
  set.files = {compared("mitdb-100-first60s")};
  const std::string text = render_equivalence_report(set, info());
  EXPECT_NE(text.find("| mitdb-100-first60s | quality_windows | 0.0075 | 11520 | 0.01 | pass |\n"),
            std::string::npos);
  EXPECT_NE(text.find("| mitdb-100-first60s | mains_mv | 0 | 0 | 2e-05 | pass |\n"),
            std::string::npos);
}

TEST(Report, NoDatabaseNoticeWithoutARecordSegment) {
  SetResult set;
  set.folder_listed = true;
  set.files = {compared("syn-fs250-hr075-clean")};
  EXPECT_EQ(render_equivalence_report(set, info()).find("Database notice"), std::string::npos);
}

TEST(Report, AStructuralDifferenceIsWrittenInTheDifferenceColumn) {
  SetResult set;
  set.folder_listed = true;
  FileResult f = compared("syn-fs250-hr075-clean");
  f.outputs.at(2) = numeric("beats", 0.0, 90, 0.0, false);
  f.outputs.at(2).difference = "count 74, file 73";
  f.outputs.at(3).difference = "not compared, the counts differ";
  f.outputs.at(3).has_sample = false;
  f.outputs.at(3).pass = false;
  set.files = {f};
  const std::string text = render_equivalence_report(set, info());
  EXPECT_NE(text.find("| syn-fs250-hr075-clean | beats | count 74, file 73 | 90 | 0 | fail |\n"),
            std::string::npos);
  EXPECT_NE(text.find("| syn-fs250-hr075-clean | beat_reported_at | not compared, the counts "
                      "differ | \xE2\x80\x94 | 0 | fail |\n"),
            std::string::npos);
  EXPECT_NE(text.find("| Outcome | fail |\n"), std::string::npos);
}

TEST(Report, AMissingUnexpectedOrRejectedFileIsAFailureRow) {
  SetResult set;
  set.folder_listed = true;
  FileResult missing;
  missing.input_id = "a";
  missing.status = FileStatus::kMissing;
  missing.detail = "missing";
  FileResult extra;
  extra.input_id = "b";
  extra.status = FileStatus::kUnexpected;
  extra.detail = "unexpected";
  FileResult bad;
  bad.input_id = "c";
  bad.status = FileStatus::kRejected;
  bad.detail = "rejected: line 3: a | b \xC3\xA9";
  set.files = {missing, extra, bad};
  const std::string text = render_equivalence_report(set, info());
  EXPECT_NE(text.find("| a | file | missing | \xE2\x80\x94 | \xE2\x80\x94 | fail |\n"),
            std::string::npos);
  EXPECT_NE(text.find("| b | file | unexpected | \xE2\x80\x94 | \xE2\x80\x94 | fail |\n"),
            std::string::npos);
  EXPECT_NE(
      text.find("| c | file | rejected: line 3: a ? b ?? | \xE2\x80\x94 | \xE2\x80\x94 | fail |\n"),
      std::string::npos);
  EXPECT_NE(text.find("| Golden vectors | 1 files of 32 expected"), std::string::npos);
  EXPECT_NE(text.find("| Reference | no file could be read |\n"), std::string::npos);
  EXPECT_NE(text.find("| Outcome | fail |\n"), std::string::npos);
}

TEST(Report, ADifferentReferenceInTheFilesFailsTheOutcome) {
  SetResult set;
  set.folder_listed = true;
  FileResult a = compared("syn-fs250-hr075-clean");
  FileResult b = compared("syn-fs250-hr180-clean");
  b.source_sha256 = std::string(64, 'd');
  set.files = {a, b};
  const std::string text = render_equivalence_report(set, info());
  EXPECT_NE(text.find("| Reference | not the same in every file |\n"), std::string::npos);
  EXPECT_NE(text.find("| Outcome | fail |\n"), std::string::npos);
}

TEST(Report, IsTheSameTextForTheSameResults) {
  SetResult set;
  set.folder_listed = true;
  set.files = {compared("mitdb-100-first60s"), compared("syn-fs250-hr075-clean")};
  EXPECT_EQ(render_equivalence_report(set, info()), render_equivalence_report(set, info()));
}

TEST(Report, ThePassOutcomeNeedsEveryFileToPass) {
  SetResult set;
  set.folder_listed = true;
  FileResult f = compared("syn-fs250-hr075-clean");
  set.files = {f};
  EXPECT_NE(render_equivalence_report(set, info()).find("| Outcome | pass |\n"), std::string::npos);
  f.outputs.at(5).pass = false;
  set.files = {f};
  EXPECT_NE(render_equivalence_report(set, info()).find("| Outcome | fail |\n"), std::string::npos);
}

TEST(ReportInfo, StatesTheLibraryAndTheChain) {
  const ReportInfo i = sinus::dsp::verification::make_report_info("computer (test)");
  EXPECT_EQ(i.build_target, "computer (test)");
  EXPECT_EQ(i.library_version, std::string(sinus::dsp::library_identity().version));
  EXPECT_EQ(i.library_sha256.size(), 64U);
  EXPECT_EQ(i.chain_bytes, sizeof(sinus::dsp::Chain));
  EXPECT_EQ(i.chain_limit, sinus::dsp::kChainMemoryLimitBytes);
}

}  // namespace
