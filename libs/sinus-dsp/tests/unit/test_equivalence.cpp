#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/status.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"
#include "sinus/dsp/verification/golden_set.hpp"
#include "synthetic_beats.hpp"

namespace {

using sinus::dsp::HeartRateStatus;
using sinus::dsp::Mark;
using sinus::dsp::Status;
using sinus::dsp::verification::BeatRow;
using sinus::dsp::verification::compare_outputs;
using sinus::dsp::verification::FileResult;
using sinus::dsp::verification::FileStatus;
using sinus::dsp::verification::GoldenVector;
using sinus::dsp::verification::HeartRateRow;
using sinus::dsp::verification::LibraryOutputs;
using sinus::dsp::verification::OutputResult;
using sinus::dsp::verification::WindowRow;

constexpr std::size_t kBaseline = 0;
constexpr std::size_t kMains = 1;
constexpr std::size_t kBeats = 2;
constexpr std::size_t kReported = 3;
constexpr std::size_t kRates = 4;
constexpr std::size_t kWindows = 5;

// A file and a library output that agree exactly.
struct Pair {
  GoldenVector file;
  LibraryOutputs library;
};

Pair agreeing() {
  Pair p;
  p.library.baseline_mv = {0.0, 0.1, 0.2, 0.3, 0.4, 0.5};
  p.library.conditioned_mv = {0.0, -0.1, -0.2, -0.3, -0.4, -0.5};
  p.library.beats = {
      {10, Mark::kStartUp, 14}, {50, Mark::kReliable, 54}, {90, Mark::kReliable, 94}};
  p.library.heart_rates = {
      {54, true, 50, HeartRateStatus::kNotEnoughBeats, false, 0.0},
      {94, true, 90, HeartRateStatus::kValid, true, 70.0},
      {200, false, 0, HeartRateStatus::kNoRecentBeat, false, 0.0},
  };
  p.library.windows = {{0, 99, 120, 0.75, true}, {10, 109, 130, 0.25, false}};
  p.file.stage_outputs_mv = {p.library.baseline_mv, p.library.conditioned_mv};
  p.file.beats = p.library.beats;
  p.file.heart_rates = p.library.heart_rates;
  p.file.windows = p.library.windows;
  return p;
}

std::vector<OutputResult> compare(const Pair& p) { return compare_outputs(p.file, p.library); }

TEST(Equivalence, AgreeingOutputsPassWithZeroDifference) {
  const auto results = compare(agreeing());
  ASSERT_EQ(results.size(), 6U);
  const char* names[] = {"baseline_mv",      "mains_mv",    "beats",
                         "beat_reported_at", "heart_rates", "quality_windows"};
  for (std::size_t i = 0; i < results.size(); ++i) {
    EXPECT_EQ(results.at(i).output, names[i]);
    EXPECT_TRUE(results.at(i).pass) << results.at(i).output;
    EXPECT_TRUE(results.at(i).difference.empty());
    EXPECT_EQ(results.at(i).largest, 0.0) << results.at(i).output;
  }
}

TEST(Equivalence, TolerancesAreThoseOfTheDesign) {
  const auto results = compare(agreeing());
  EXPECT_EQ(results.at(kBaseline).tolerance, 2e-5);
  EXPECT_EQ(results.at(kMains).tolerance, 2e-5);
  EXPECT_EQ(results.at(kBeats).tolerance, 0.0);
  EXPECT_EQ(results.at(kReported).tolerance, 0.0);
  EXPECT_EQ(results.at(kRates).tolerance, 1e-4);
  EXPECT_EQ(results.at(kWindows).tolerance, 0.01);
}

TEST(Equivalence, ConditioningAtTheToleranceFailsJustAbove) {
  Pair p = agreeing();
  p.library.baseline_mv.at(3) = 0.0;
  p.file.stage_outputs_mv.at(0).at(3) = 2e-5;  // exactly the tolerance
  EXPECT_TRUE(compare(p).at(kBaseline).pass);
  EXPECT_EQ(compare(p).at(kBaseline).largest, 2e-5);
  EXPECT_EQ(compare(p).at(kBaseline).sample, 3U);
  p.file.stage_outputs_mv.at(0).at(3) = std::nextafter(2e-5, 1.0);
  const OutputResult above = compare(p).at(kBaseline);
  EXPECT_FALSE(above.pass);
  EXPECT_TRUE(above.difference.empty());
  EXPECT_EQ(above.sample, 3U);
}

TEST(Equivalence, TheSampleIsThatOfTheLargestDifferenceAndTheFirstOfSeveral) {
  Pair p = agreeing();
  p.file.stage_outputs_mv.at(1).at(1) += 1e-6;
  p.file.stage_outputs_mv.at(1).at(2) += 5e-6;
  p.file.stage_outputs_mv.at(1).at(4) -= 5e-6;
  const OutputResult r = compare(p).at(kMains);
  EXPECT_TRUE(r.pass);
  EXPECT_EQ(r.sample, 2U);
  EXPECT_NEAR(r.largest, 5e-6, 1e-12);
}

TEST(Equivalence, DetectionIndexHasNoTolerance) {
  Pair p = agreeing();
  p.file.beats.at(1).index = 51;
  p.file.beats.at(2).index = 93;
  const OutputResult r = compare(p).at(kBeats);
  EXPECT_FALSE(r.pass);
  EXPECT_TRUE(r.difference.empty());
  EXPECT_EQ(r.largest, 3.0);
  EXPECT_EQ(r.sample, 93U);
  EXPECT_TRUE(compare(p).at(kReported).pass);
}

TEST(Equivalence, ReportSampleHasNoTolerance) {
  Pair p = agreeing();
  p.file.beats.at(2).reported_at = 95;
  const auto results = compare(p);
  EXPECT_TRUE(results.at(kBeats).pass);
  EXPECT_FALSE(results.at(kReported).pass);
  EXPECT_EQ(results.at(kReported).largest, 1.0);
  EXPECT_EQ(results.at(kReported).sample, 90U);
}

TEST(Equivalence, ADifferentMarkIsStructural) {
  Pair p = agreeing();
  p.file.beats.at(1).mark = Mark::kStartUp;
  const OutputResult r = compare(p).at(kBeats);
  EXPECT_FALSE(r.pass);
  EXPECT_EQ(r.difference, "mark");
  EXPECT_EQ(r.sample, 50U);
}

TEST(Equivalence, ADetectionLessIsAMismatchOfCountsAtTheExtraDetection) {
  Pair p = agreeing();
  p.file.beats.pop_back();
  const auto results = compare(p);
  EXPECT_EQ(results.at(kBeats).difference, "count 3, file 2");
  EXPECT_EQ(results.at(kBeats).sample, 90U);
  EXPECT_FALSE(results.at(kReported).pass);
  EXPECT_FALSE(results.at(kReported).has_sample);
  p = agreeing();
  p.library.beats.pop_back();
  const OutputResult fewer = compare(p).at(kBeats);
  EXPECT_EQ(fewer.difference, "count 2, file 3");
  EXPECT_EQ(fewer.sample, 90U);
}

TEST(Equivalence, HeartRateAtTheToleranceAndAbove) {
  Pair p = agreeing();
  p.library.heart_rates.at(1).bpm = 0.5;
  p.file.heart_rates.at(1).bpm = 0.5 + 9.9e-5;
  EXPECT_TRUE(compare(p).at(kRates).pass);
  EXPECT_EQ(compare(p).at(kRates).sample, 94U);
  p.file.heart_rates.at(1).bpm = 0.5 + 1.01e-4;
  EXPECT_FALSE(compare(p).at(kRates).pass);
  EXPECT_TRUE(compare(p).at(kRates).difference.empty());
}

TEST(Equivalence, HeartRateStructureIsExact) {
  Pair p = agreeing();
  p.file.heart_rates.at(1).status = HeartRateStatus::kOutOfRange;
  EXPECT_EQ(compare(p).at(kRates).difference, "status");
  EXPECT_EQ(compare(p).at(kRates).sample, 94U);
  p = agreeing();
  p.file.heart_rates.at(0).sample = 55;
  EXPECT_EQ(compare(p).at(kRates).difference, "sample");
  p = agreeing();
  p.file.heart_rates.at(1).beat_index = 91;
  EXPECT_EQ(compare(p).at(kRates).difference, "beat index");
  p = agreeing();
  p.file.heart_rates.at(2).has_beat = true;
  EXPECT_EQ(compare(p).at(kRates).difference, "beat index");
  p = agreeing();
  p.file.heart_rates.pop_back();
  EXPECT_EQ(compare(p).at(kRates).difference, "count 3, file 2");
  EXPECT_EQ(compare(p).at(kRates).sample, 200U);
}

TEST(Equivalence, QualityIndexAtTheToleranceAndAbove) {
  Pair p = agreeing();
  p.library.windows.at(1).index = 0.0;
  p.library.windows.at(1).usable = false;
  p.file.windows.at(1) = p.library.windows.at(1);
  p.file.windows.at(1).index = 0.01;
  EXPECT_TRUE(compare(p).at(kWindows).pass);
  EXPECT_EQ(compare(p).at(kWindows).largest, 0.01);
  EXPECT_EQ(compare(p).at(kWindows).sample, 10U);
  p.file.windows.at(1).index = std::nextafter(0.01, 1.0);
  EXPECT_FALSE(compare(p).at(kWindows).pass);
}

TEST(Equivalence, WindowStructureIsExact) {
  const char* what[] = {"first sample", "last sample", "report sample", "usable mark"};
  for (int field = 0; field < 4; ++field) {
    Pair p = agreeing();
    WindowRow& w = p.file.windows.at(0);
    if (field == 0) {
      w.first_sample += 1;
    } else if (field == 1) {
      w.last_sample += 1;
    } else if (field == 2) {
      w.reported_at += 1;
    } else {
      w.usable = !w.usable;
    }
    const OutputResult r = compare(p).at(kWindows);
    EXPECT_FALSE(r.pass) << what[field];
    EXPECT_EQ(r.difference, what[field]);
    EXPECT_EQ(r.sample, p.file.windows.at(0).first_sample);
  }
  Pair p = agreeing();
  p.file.windows.push_back({20, 119, 140, 0.9, true});
  EXPECT_EQ(compare(p).at(kWindows).difference, "count 2, file 3");
  EXPECT_EQ(compare(p).at(kWindows).sample, 20U);
}

TEST(Equivalence, ANonFiniteLibraryValueFails) {
  Pair p = agreeing();
  p.library.baseline_mv.at(2) = std::numeric_limits<double>::quiet_NaN();
  EXPECT_FALSE(compare(p).at(kBaseline).pass);
}

// --- the library on an input
// ----------------------------------------------------------------------

GoldenVector vector_of_library_run() {
  constexpr double kFs = 250.0;
  GoldenVector v;
  v.input_id = "unit";
  v.fs_hz = kFs;
  v.mains_hz = 50;
  v.software_version = "x";
  v.source_sha256 = std::string(64, 'a');
  v.stages = {"baseline", "mains"};
  const std::vector<float> x =
      sinus_test::synthetic_beats(kFs, 24.0, sinus_test::regular_beats(1.0, 0.8, 24.0));
  for (const float s : x) {
    v.input_mv.push_back(static_cast<double>(s));
  }
  const LibraryOutputs run = sinus::dsp::verification::run_library(v);
  EXPECT_EQ(run.status, Status::kOk);
  v.stage_outputs_mv = {run.baseline_mv, run.conditioned_mv};
  v.beats = run.beats;
  v.heart_rates = run.heart_rates;
  v.windows = run.windows;
  return v;
}

TEST(EquivalenceRun, TheLibraryAgreesWithItself) {
  const GoldenVector v = vector_of_library_run();
  EXPECT_GE(v.beats.size(), 20U);
  EXPECT_GE(v.heart_rates.size(), 10U);
  EXPECT_GE(v.windows.size(), 1U);
  const FileResult result = sinus::dsp::verification::check_vector("unit", v);
  EXPECT_EQ(result.status, FileStatus::kCompared);
  EXPECT_TRUE(result.passed());
  for (const OutputResult& output : result.outputs) {
    EXPECT_EQ(output.largest, 0.0) << output.output;
  }
}

TEST(EquivalenceRun, TheInputIsGivenAsBinary32) {
  // A value that binary32 rounds changes the run by the rounding, not the file's value.
  GoldenVector v = vector_of_library_run();
  v.input_mv.at(100) = 0.5;
  const LibraryOutputs a = sinus::dsp::verification::run_library(v);
  v.input_mv.at(100) = 0.5 + 1e-12;
  const LibraryOutputs b = sinus::dsp::verification::run_library(v);
  EXPECT_EQ(a.baseline_mv, b.baseline_mv);
}

TEST(EquivalenceRun, ADisturbedOutputNamesTheFileTheOutputAndTheSample) {
  GoldenVector v = vector_of_library_run();
  v.stage_outputs_mv.at(0).at(1234) += 3e-5;
  v.beats.at(4).index += 1;
  std::size_t rated = 0;
  while (!v.heart_rates.at(rated).has_rate) {
    ++rated;
  }
  v.heart_rates.at(rated).bpm += 1e-3;
  v.windows.at(0).index += 0.02;
  const FileResult result = sinus::dsp::verification::check_vector("unit", v);
  EXPECT_FALSE(result.passed());
  EXPECT_EQ(result.input_id, "unit");
  EXPECT_FALSE(result.outputs.at(kBaseline).pass);
  EXPECT_EQ(result.outputs.at(kBaseline).sample, 1234U);
  EXPECT_NEAR(result.outputs.at(kBaseline).largest, 3e-5, 1e-9);
  EXPECT_TRUE(result.outputs.at(kMains).pass);
  EXPECT_FALSE(result.outputs.at(kBeats).pass);
  EXPECT_EQ(result.outputs.at(kBeats).sample, v.beats.at(4).index);
  EXPECT_FALSE(result.outputs.at(kRates).pass);
  EXPECT_EQ(result.outputs.at(kRates).sample, v.heart_rates.at(rated).sample);
  EXPECT_FALSE(result.outputs.at(kWindows).pass);
}

TEST(EquivalenceRun, ADetectionRemovedFromTheFileIsACountMismatch) {
  GoldenVector v = vector_of_library_run();
  v.beats.erase(v.beats.begin() + 7);
  const FileResult result = sinus::dsp::verification::check_vector("unit", v);
  EXPECT_FALSE(result.passed());
  EXPECT_NE(result.outputs.at(kBeats).difference.find("count"), std::string::npos);
}

TEST(EquivalenceRun, AFileOtherThanBaselineMainsCannotBeCompared) {
  GoldenVector v = vector_of_library_run();
  v.stages = {"baseline", "mains", "third"};
  const FileResult result = sinus::dsp::verification::check_vector("unit", v);
  EXPECT_EQ(result.status, FileStatus::kNotComparable);
  EXPECT_FALSE(result.passed());
  EXPECT_TRUE(result.outputs.empty());
}

TEST(EquivalenceRun, ASamplingFrequencyTheLibraryRejectsCannotBeCompared) {
  GoldenVector v = vector_of_library_run();
  v.fs_hz = 100.0;
  const FileResult result = sinus::dsp::verification::check_vector("unit", v);
  EXPECT_EQ(result.status, FileStatus::kNotComparable);
  EXPECT_NE(result.detail.find("status"), std::string::npos);
}

TEST(EquivalenceRun, TheIdentityOfTheFileIsKept) {
  const FileResult result = sinus::dsp::verification::check_vector("unit", vector_of_library_run());
  EXPECT_TRUE(result.has_identity);
  EXPECT_EQ(result.software_version, "x");
  EXPECT_EQ(result.source_sha256, std::string(64, 'a'));
}

// --- the set
// --------------------------------------------------------------------------------------

TEST(GoldenSet, HoldsThe32ExpectedInputsInCodePointOrder) {
  const auto& ids = sinus::dsp::verification::expected_inputs();
  ASSERT_EQ(ids.size(), 32U);
  int records = 0;
  for (std::size_t i = 0; i < ids.size(); ++i) {
    if (i > 0) {
      EXPECT_LT(ids.at(i - 1), ids.at(i));
    }
    records += sinus::dsp::verification::is_record_segment(ids.at(i)) ? 1 : 0;
  }
  EXPECT_EQ(records, 6);
}

class Folder : public ::testing::Test {
 protected:
  void SetUp() override {
    path_ = std::filesystem::temp_directory_path() / "sinus_dsp_unit_folder";
    std::filesystem::remove_all(path_);
    std::filesystem::create_directories(path_);
  }
  void TearDown() override { std::filesystem::remove_all(path_); }
  void write(const std::string& name, const std::string& text) const {
    std::ofstream file(path_ / name, std::ios::binary);
    file << text;
  }
  std::filesystem::path path_;
};

TEST_F(Folder, AnEmptyFolderLacksEveryFile) {
  const auto set = sinus::dsp::verification::check_folder(path_.string());
  EXPECT_TRUE(set.folder_listed);
  ASSERT_EQ(set.files.size(), 32U);
  EXPECT_EQ(set.expected_present(), 0U);
  for (const FileResult& file : set.files) {
    EXPECT_EQ(file.status, FileStatus::kMissing);
    EXPECT_FALSE(file.passed());
  }
  EXPECT_EQ(set.files.front().input_id, "mitdb-100-first60s");
  EXPECT_FALSE(sinus::dsp::verification::set_passed(set));
}

TEST_F(Folder, AnUnexpectedFileIsNamedAndOtherFilesAreIgnored) {
  write("surplus.golden.txt", "x");
  write("NOTICE.md", "notice");
  write("syn-fs250-hr075-clean.golden.txt.part~", "x");
  const auto set = sinus::dsp::verification::check_folder(path_.string());
  ASSERT_EQ(set.files.size(), 33U);
  EXPECT_EQ(set.files.back().input_id, "surplus");
  EXPECT_EQ(set.files.back().status, FileStatus::kUnexpected);
  EXPECT_EQ(set.expected_present(), 0U);
}

TEST_F(Folder, ARejectedFileNamesItsLine) {
  write("syn-fs250-hr075-clean.golden.txt", "format=other\n");
  const auto set = sinus::dsp::verification::check_folder(path_.string());
  const FileResult* found = nullptr;
  for (const FileResult& file : set.files) {
    if (file.input_id == "syn-fs250-hr075-clean") {
      found = &file;
    }
  }
  ASSERT_NE(found, nullptr);
  EXPECT_EQ(found->status, FileStatus::kRejected);
  EXPECT_NE(found->detail.find("line 1"), std::string::npos);
  EXPECT_EQ(set.expected_present(), 1U);
}

TEST(FolderMissing, ANonexistentFolderIsNotListed) {
  const auto set = sinus::dsp::verification::check_folder(
      (std::filesystem::temp_directory_path() / "sinus_dsp_no_such_folder").string());
  EXPECT_FALSE(set.folder_listed);
  EXPECT_FALSE(sinus::dsp::verification::set_passed(set));
}

TEST(ReferenceIdentity, TheSameInEveryFileOrNot) {
  sinus::dsp::verification::SetResult set;
  EXPECT_EQ(sinus::dsp::verification::reference_identity(set).state,
            sinus::dsp::verification::ReferenceState::kNone);
  FileResult a;
  a.has_identity = true;
  a.software_version = "1";
  a.source_sha256 = "x";
  FileResult b = a;
  FileResult none;
  set.files = {a, none, b};
  auto identity = sinus::dsp::verification::reference_identity(set);
  EXPECT_EQ(identity.state, sinus::dsp::verification::ReferenceState::kSame);
  EXPECT_EQ(identity.software_version, "1");
  b.source_sha256 = "y";
  set.files = {a, b};
  EXPECT_EQ(sinus::dsp::verification::reference_identity(set).state,
            sinus::dsp::verification::ReferenceState::kMixed);
  b.source_sha256 = "x";
  b.software_version = "2";
  set.files = {a, b};
  EXPECT_EQ(sinus::dsp::verification::reference_identity(set).state,
            sinus::dsp::verification::ReferenceState::kMixed);
}

}  // namespace
