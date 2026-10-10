// Requirement tests of SRS-034: equivalence of the real-time library with the reference on the
// computer. The golden vectors are those of the same commit, in the folder of SINUS_GOLDEN_DIR (a
// precondition: the tests skip with a message when it is not set).
// Each test states the part of the requirement it covers, its inputs and its expected result.
// The comparison of the first group of tests is QA's own (own reader, own run of Chain, own
// tolerances); the other tests check that the library's check detects what it must.

#include <gtest/gtest.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "golden_support.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"
#include "sinus/dsp/verification/golden_set.hpp"

namespace {

using sinus::dsp::verification::check_file;
using sinus::dsp::verification::check_folder;
using sinus::dsp::verification::FileResult;
using sinus::dsp::verification::FileStatus;
using sinus::dsp::verification::OutputResult;
using sinus::dsp::verification::SetResult;
using sinus_qa::golden_dir;
using sinus_qa::path_of;
using sinus_qa::TempFolder;
using sinus_qa::VectorText;

#define SKIP_WITHOUT_GOLDEN_DIR()             \
  do {                                        \
    if (golden_dir().empty()) {               \
      GTEST_SKIP() << sinus_qa::kSkipMessage; \
    }                                         \
  } while (false)

// Part of the requirement: the whole set exists, 32 files.
// Input: the folder of the vectors. Expected: the 32 files written out by QA are all there.
// Verifies: SRS-034
TEST(Srs034Set, TheFolderHoldsTheThirtyTwoExpectedFiles) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const auto ids = sinus_qa::expected_ids();
  ASSERT_EQ(ids.size(), 32U);
  for (const auto& id : ids) {
    EXPECT_TRUE(sinus_qa::fs::is_regular_file(path_of(golden_dir(), id))) << id;
  }
}

class Srs034File : public ::testing::TestWithParam<std::string> {};

// Part of the requirement: for each file, with its sampling frequency and mains setting and the
// input one sample at a time (as binary32), the conditioning outputs are within 2e-5 mV at every
// sample; the detections are as many, with the same mark, the same index and the same report
// sample (also the sample at which the library emits it); the heart rates have the same samples,
// validity and reason, valid ones within 1e-4 bpm; the quality windows have the same first and
// last samples, marks and report samples, with the index within 0.01.
// Input: one file of the set, read and run by QA's own code. Expected: every condition holds.
// Verifies: SRS-034
TEST_P(Srs034File, LibraryReproducesEveryOutputWithinTheApprovedTolerances) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const std::string id = GetParam();
  const sinus_qa::QVector file =
      sinus_qa::parse_vector(sinus_qa::read_text(path_of(golden_dir(), id)));
  ASSERT_EQ(file.id, id);
  ASSERT_GT(file.input.size(), 0U);
  ASSERT_EQ(file.baseline.size(), file.input.size());
  const sinus_qa::QRun run = sinus_qa::run_library_on(file);
  ASSERT_TRUE(run.ok) << id;

  for (const auto& d : sinus_qa::compare_run(file, run)) {
    EXPECT_EQ(d.structural, "") << id << " " << d.output << " (" << d.structural << ")";
    EXPECT_LE(d.largest, sinus_qa::tolerance_of(d.output))
        << id << " " << d.output << " at sample " << d.sample;
  }
  // The report sample is the sample at which the library emits the detection, event or window.
  ASSERT_EQ(run.beats.size(), file.beats.size()) << id;
  for (std::size_t i = 0; i < run.beats.size(); ++i) {
    EXPECT_EQ(run.beat_call[i], file.beats[i].reported) << id << " detection " << i;
    EXPECT_EQ(run.beats[i].reported, run.beat_call[i]) << id << " detection " << i;
    EXPECT_EQ(run.beats[i].index, file.beats[i].index) << id << " detection " << i;
    EXPECT_EQ(run.beats[i].reliable, file.beats[i].reliable) << id << " detection " << i;
  }
  ASSERT_EQ(run.rates.size(), file.rates.size()) << id;
  for (std::size_t i = 0; i < run.rates.size(); ++i) {
    EXPECT_EQ(run.rate_call[i], file.rates[i].sample) << id << " event " << i;
  }
  ASSERT_EQ(run.windows.size(), file.windows.size()) << id;
  for (std::size_t i = 0; i < run.windows.size(); ++i) {
    EXPECT_EQ(run.window_call[i], file.windows[i].reported) << id << " window " << i;
  }
}

INSTANTIATE_TEST_SUITE_P(GoldenSet, Srs034File, ::testing::ValuesIn(sinus_qa::expected_ids()),
                         [](const ::testing::TestParamInfo<std::string>& info) {
                           std::string name = info.param;
                           for (char& c : name) {
                             if (c == '-') {
                               c = '_';
                             }
                           }
                           return name;
                         });

// Part of the requirement: "every file passes", by the library's own check.
// Input: the folder of the vectors. Expected: all 32 files are compared and pass, with the six
// outputs each, and the set passes.
// Verifies: SRS-034
TEST(Srs034Set, TheCheckPassesEveryFileOfTheExport) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const SetResult set = check_folder(golden_dir());
  EXPECT_TRUE(set.folder_listed);
  ASSERT_EQ(set.files.size(), 32U);
  EXPECT_EQ(set.expected_present(), 32U);
  EXPECT_TRUE(sinus::dsp::verification::set_passed(set));
  for (const FileResult& f : set.files) {
    EXPECT_EQ(f.status, FileStatus::kCompared) << f.input_id << " " << f.detail;
    EXPECT_TRUE(f.passed()) << f.input_id;
    EXPECT_EQ(f.outputs.size(), 6U) << f.input_id;
    for (const OutputResult& o : f.outputs) {
      EXPECT_TRUE(o.pass) << f.input_id << " " << o.output;
    }
  }
}

// ---------------------------------------------------------------------------------------------
// A copy of a file in which one value of each compared output is changed by more than its
// tolerance fails, and the failure names the file, the output and the sample.

constexpr const char* kFileId = "syn-fs360-hr075-bw-mains50";

struct Subject {
  std::string text;
  sinus_qa::QVector parsed;
};

const Subject& subject() {
  static const Subject s = [] {
    Subject r;
    r.text = sinus_qa::read_text(path_of(golden_dir(), kFileId));
    r.parsed = sinus_qa::parse_vector(r.text);
    return r;
  }();
  return s;
}

// Checks an edited copy of the subject file with the library's check.
FileResult check_edited(const VectorText& edited) {
  TempFolder folder;
  const std::string path = path_of(folder.str(), kFileId);
  sinus_qa::write_text(path, edited.str());
  return check_file(kFileId, path);
}

const OutputResult* find_output(const FileResult& file, const std::string& name) {
  for (const OutputResult& o : file.outputs) {
    if (o.output == name) {
      return &o;
    }
  }
  return nullptr;
}

// Expects that exactly the output `name` fails, naming the file and a sample.
void expect_only_failing(const FileResult& file, const std::string& name) {
  ASSERT_EQ(file.status, FileStatus::kCompared) << file.detail;
  EXPECT_EQ(file.input_id, kFileId);
  EXPECT_FALSE(file.passed());
  ASSERT_EQ(file.outputs.size(), 6U);
  for (const OutputResult& o : file.outputs) {
    EXPECT_EQ(o.pass, o.output != name) << o.output;
  }
  const OutputResult* failing = find_output(file, name);
  ASSERT_NE(failing, nullptr);
  EXPECT_TRUE(failing->has_sample);
}

void expect_passes(const FileResult& file) {
  ASSERT_EQ(file.status, FileStatus::kCompared) << file.detail;
  EXPECT_TRUE(file.passed());
  for (const OutputResult& o : file.outputs) {
    EXPECT_TRUE(o.pass) << o.output;
  }
}

// Part of the requirement: conditioning stage outputs within 2e-5 mV, for each stage.
// Input: one sample of the baseline (resp. mains) column changed by +1.9e-5 (just inside, the
// library's own difference being about 1e-7) and by +2.1e-5 (just outside). Expected: inside
// passes; outside fails that output only, at that sample.
// Verifies: SRS-034
TEST(Srs034Detects, ConditioningOutputsBeyondTwoTimesTenToMinusFiveMv) {
  SKIP_WITHOUT_GOLDEN_DIR();
  struct Case {
    const char* output;
    std::size_t column;
    std::size_t row;
  };
  for (const Case c : {Case{"baseline_mv", 1, 4321}, Case{"mains_mv", 2, 7777}}) {
    const std::vector<double>& column =
        c.column == 1 ? subject().parsed.baseline : subject().parsed.mains_out;
    for (const double delta : {1.9e-5, -1.9e-5}) {
      VectorText edited(subject().text);
      edited.set_field("[signals]", c.row, c.column, sinus_qa::number_text(column[c.row] + delta));
      expect_passes(check_edited(edited));
    }
    for (const double delta : {2.1e-5, -2.1e-5}) {
      VectorText edited(subject().text);
      edited.set_field("[signals]", c.row, c.column, sinus_qa::number_text(column[c.row] + delta));
      const FileResult result = check_edited(edited);
      expect_only_failing(result, c.output);
      const OutputResult* o = find_output(result, c.output);
      ASSERT_NE(o, nullptr);
      EXPECT_EQ(o->sample, c.row) << c.output;
      EXPECT_DOUBLE_EQ(o->tolerance, 2e-5);
    }
  }
}

// The vector of the subject file as the library's reader gives it, and a mutated copy checked.
using sinus::dsp::verification::GoldenVector;

const GoldenVector& subject_vector() {
  static const GoldenVector v = [] {
    auto read = sinus::dsp::verification::read_golden_vector(path_of(golden_dir(), kFileId));
    EXPECT_TRUE(read.ok) << read.error.reason;
    return read.vector;
  }();
  return v;
}

// The check of a copy of the subject vector changed by `edit` (changes that the text rules of the
// reader tie to several sections, such as a removed detection, are made on the vector itself).
template <typename Edit>
FileResult check_mutated(Edit edit) {
  GoldenVector copy = subject_vector();
  edit(copy);
  return sinus::dsp::verification::check_vector(kFileId, copy);
}

// Expects that the output `name` fails, naming a sample (other outputs may fail too: a changed
// detection also changes what the rates and windows are tied to).
void expect_failing(const FileResult& file, const std::string& name) {
  ASSERT_EQ(file.status, FileStatus::kCompared) << file.detail;
  EXPECT_EQ(file.input_id, kFileId);
  EXPECT_FALSE(file.passed());
  const OutputResult* o = find_output(file, name);
  ASSERT_NE(o, nullptr);
  EXPECT_FALSE(o->pass) << name;
  EXPECT_TRUE(o->has_sample) << name;
}

// The unchanged copy passes (the starting point of the tests below).
// Verifies: SRS-034
TEST(Srs034Detects, TheUnchangedCopyPasses) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const FileResult r = check_mutated([](GoldenVector&) {});
  ASSERT_EQ(r.status, FileStatus::kCompared) << r.detail;
  EXPECT_TRUE(r.passed());
}

// Part of the requirement: the same mark for each detection. Input: the mark of one detection
// changed (the first start-up one to reliable, the last reliable one to start-up). Expected: the
// output beats fails, naming a sample.
// Verifies: SRS-034
TEST(Srs034Detects, ADetectionWithAnotherMark) {
  SKIP_WITHOUT_GOLDEN_DIR();
  using sinus::dsp::Mark;
  const auto& beats = subject_vector().beats;
  ASSERT_GT(beats.size(), 10U);
  std::size_t startup = beats.size();
  std::size_t reliable = beats.size();
  for (std::size_t i = 0; i < beats.size(); ++i) {
    if (beats[i].mark == Mark::kStartUp && startup == beats.size()) {
      startup = i;
    }
    if (beats[i].mark == Mark::kReliable) {
      reliable = i;
    }
  }
  ASSERT_LT(startup, beats.size());
  ASSERT_LT(reliable, beats.size());
  {
    const FileResult r =
        check_mutated([&](GoldenVector& v) { v.beats[startup].mark = Mark::kReliable; });
    expect_failing(r, "beats");
    EXPECT_EQ(find_output(r, "beats")->sample, beats[startup].index);
  }
  {
    const FileResult r =
        check_mutated([&](GoldenVector& v) { v.beats[reliable].mark = Mark::kStartUp; });
    expect_failing(r, "beats");
    EXPECT_EQ(find_output(r, "beats")->sample, beats[reliable].index);
  }
}

// Part of the requirement: the same index, tolerance 0 samples. Input: the index of one detection
// moved by one sample (+1 and -1). Expected: beats fails, at a sample of that detection (its index
// in the file or in the library).
// Verifies: SRS-034
TEST(Srs034Detects, ADetectionIndexOffByOneSample) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const auto& beats = subject_vector().beats;
  const std::size_t k = 12;
  ASSERT_GT(beats.size(), k + 1);
  for (const std::int64_t shift : {1, -1}) {
    const FileResult r = check_mutated([&](GoldenVector& v) {
      v.beats[k].index =
          static_cast<std::uint64_t>(static_cast<std::int64_t>(beats[k].index) + shift);
    });
    expect_failing(r, "beats");
    const OutputResult* o = find_output(r, "beats");
    EXPECT_GE(o->sample, beats[k].index - 1);
    EXPECT_LE(o->sample, beats[k].index + 1);
    EXPECT_DOUBLE_EQ(o->tolerance, 0.0);
  }
}

// Part of the requirement: the same report sample, tolerance 0. Input: the report sample of one
// detection moved by one sample (+1 and -1). Expected: beat_reported_at fails, at a sample of that
// detection; the index output beats still passes.
// Verifies: SRS-034
TEST(Srs034Detects, ADetectionReportedOneSampleOff) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const auto& beats = subject_vector().beats;
  const std::size_t k = 20;
  ASSERT_GT(beats.size(), k + 1);
  for (const std::int64_t shift : {1, -1}) {
    const FileResult r = check_mutated([&](GoldenVector& v) {
      v.beats[k].reported_at =
          static_cast<std::uint64_t>(static_cast<std::int64_t>(beats[k].reported_at) + shift);
    });
    expect_failing(r, "beat_reported_at");
    const OutputResult* o = find_output(r, "beat_reported_at");
    EXPECT_GE(o->sample, beats[k].index);
    EXPECT_LE(o->sample, beats[k].reported_at + 1);
    EXPECT_TRUE(find_output(r, "beats")->pass);
  }
}

// Part of the requirement: as many detections as the file. Input: one detection removed from the
// file (the first, a middle one, the last). Expected: beats fails and names a sample.
// Verifies: SRS-034
TEST(Srs034Detects, ARemovedDetection) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const auto n = subject_vector().beats.size();
  for (const std::size_t k : {std::size_t{0}, n / 2, n - 1}) {
    const FileResult r = check_mutated(
        [&](GoldenVector& v) { v.beats.erase(v.beats.begin() + static_cast<std::ptrdiff_t>(k)); });
    expect_failing(r, "beats");
  }
}

// Part of the requirement: heart rates, each valid one within 1e-4 bpm. Input: one valid rate
// changed by +/-9e-5 (just inside) and by +/-1.1e-4 (just outside). Expected: inside passes;
// outside fails heart_rates only, at the sample of that event.
// Verifies: SRS-034
TEST(Srs034Detects, AHeartRateBeyondOneTimesTenToMinusFourBpm) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const auto& rates = subject().parsed.rates;
  std::size_t k = rates.size();
  for (std::size_t i = rates.size() / 2; i < rates.size(); ++i) {
    if (rates[i].status == "valid") {
      k = i;
      break;
    }
  }
  ASSERT_LT(k, rates.size());
  for (const double delta : {9e-5, -9e-5}) {
    VectorText edited(subject().text);
    edited.set_field("[heart_rates]", k, 3, sinus_qa::number_text(rates[k].bpm + delta));
    expect_passes(check_edited(edited));
  }
  for (const double delta : {1.1e-4, -1.1e-4}) {
    VectorText edited(subject().text);
    edited.set_field("[heart_rates]", k, 3, sinus_qa::number_text(rates[k].bpm + delta));
    const FileResult result = check_edited(edited);
    expect_only_failing(result, "heart_rates");
    const OutputResult* o = find_output(result, "heart_rates");
    ASSERT_NE(o, nullptr);
    EXPECT_EQ(o->sample, rates[k].sample);
    EXPECT_DOUBLE_EQ(o->tolerance, 1e-4);
  }
}

// Part of the requirement: heart rates with the same validity and reason at the same samples.
// Input: one event removed; the sample of one event moved by one; a valid event made "not enough
// beats" (validity); a "not enough beats" event made "no recent beat" (reason); the beat of one
// event changed. Expected: heart_rates fails, naming a sample.
// Verifies: SRS-034
TEST(Srs034Detects, AHeartRateEventMissingOrWithAnotherSampleValidityOrReason) {
  SKIP_WITHOUT_GOLDEN_DIR();
  using sinus::dsp::HeartRateStatus;
  const auto& rates = subject_vector().heart_rates;
  ASSERT_GT(rates.size(), 10U);
  std::size_t valid = rates.size();
  std::size_t few = rates.size();
  for (std::size_t i = 0; i < rates.size(); ++i) {
    if (rates[i].status == HeartRateStatus::kValid && valid == rates.size()) {
      valid = i;
    }
    if (rates[i].status == HeartRateStatus::kNotEnoughBeats && few == rates.size()) {
      few = i;
    }
  }
  ASSERT_LT(valid, rates.size());
  ASSERT_LT(few, rates.size());
  expect_failing(
      check_mutated([&](GoldenVector& v) { v.heart_rates.erase(v.heart_rates.begin() + 5); }),
      "heart_rates");
  expect_failing(check_mutated([&](GoldenVector& v) { v.heart_rates[3].sample += 1; }),
                 "heart_rates");
  expect_failing(check_mutated([&](GoldenVector& v) {
                   v.heart_rates[valid].status = HeartRateStatus::kNotEnoughBeats;
                   v.heart_rates[valid].has_rate = false;
                 }),
                 "heart_rates");
  expect_failing(check_mutated([&](GoldenVector& v) {
                   v.heart_rates[few].status = HeartRateStatus::kNoRecentBeat;
                 }),
                 "heart_rates");
  expect_failing(check_mutated([&](GoldenVector& v) { v.heart_rates[valid].beat_index += 1; }),
                 "heart_rates");
}

// Part of the requirement: the same quality windows, with the index within 0.01. Input: the index
// of one usable window (far from the usable threshold) changed by +/-0.009 (just inside) and by
// +/-0.011 (just outside). Expected: inside passes; outside fails quality_windows only, at a
// sample of that window.
// Verifies: SRS-034
TEST(Srs034Detects, AWindowIndexBeyondOnePercent) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const auto& windows = subject().parsed.windows;
  std::size_t k = windows.size();
  for (std::size_t i = 0; i < windows.size(); ++i) {
    if (windows[i].usable && windows[i].index > 0.6 && windows[i].index < 0.985) {
      k = i;
      break;
    }
  }
  ASSERT_LT(k, windows.size());
  for (const double delta : {0.009, -0.009}) {
    VectorText edited(subject().text);
    edited.set_field("[quality_windows]", k, 3, sinus_qa::number_text(windows[k].index + delta));
    expect_passes(check_edited(edited));
  }
  for (const double delta : {0.011, -0.011}) {
    VectorText edited(subject().text);
    edited.set_field("[quality_windows]", k, 3, sinus_qa::number_text(windows[k].index + delta));
    const FileResult result = check_edited(edited);
    expect_only_failing(result, "quality_windows");
    const OutputResult* o = find_output(result, "quality_windows");
    ASSERT_NE(o, nullptr);
    EXPECT_GE(o->sample, windows[k].first);
    EXPECT_LE(o->sample, windows[k].reported);
    EXPECT_DOUBLE_EQ(o->tolerance, 0.01);
  }
}

// Part of the requirement: the same windows (first and last samples), the same marks. Input: one
// window removed; the first sample, the last sample, the report sample or the usable mark of one
// window changed. Expected: quality_windows fails, naming a sample.
// Verifies: SRS-034
TEST(Srs034Detects, AWindowMissingOrWithAnotherSampleOrMark) {
  SKIP_WITHOUT_GOLDEN_DIR();
  ASSERT_GT(subject_vector().windows.size(), 10U);
  expect_failing(check_mutated([](GoldenVector& v) { v.windows.erase(v.windows.begin() + 7); }),
                 "quality_windows");
  expect_failing(check_mutated([](GoldenVector& v) { v.windows[7].first_sample += 1; }),
                 "quality_windows");
  expect_failing(check_mutated([](GoldenVector& v) { v.windows[7].last_sample += 1; }),
                 "quality_windows");
  expect_failing(check_mutated([](GoldenVector& v) { v.windows[7].reported_at += 1; }),
                 "quality_windows");
  expect_failing(check_mutated([](GoldenVector& v) { v.windows[7].usable = !v.windows[7].usable; }),
                 "quality_windows");
}

// Part of the requirement: "for every golden-vector file" of the set. Input: the folder without
// one file (the first of the 32, then a record segment). Expected: the missing file is named, the
// set fails, the other 31 files still pass.
// Verifies: SRS-034, SRS-035
TEST(Srs034Set, AMissingFileIsNamedAndFailsTheSet) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const auto ids = sinus_qa::expected_ids();
  for (const std::string& missing : {ids.front(), std::string("mitdb-119-first60s")}) {
    TempFolder folder;
    folder.import_vectors(golden_dir(), {missing});
    const SetResult set = check_folder(folder.str());
    EXPECT_FALSE(sinus::dsp::verification::set_passed(set)) << missing;
    EXPECT_EQ(set.expected_present(), 31U) << missing;
    std::size_t named = 0;
    for (const FileResult& f : set.files) {
      if (f.input_id == missing) {
        ++named;
        EXPECT_EQ(f.status, FileStatus::kMissing);
        EXPECT_FALSE(f.passed());
      } else {
        EXPECT_TRUE(f.passed()) << f.input_id;
      }
    }
    EXPECT_EQ(named, 1U) << missing;
  }
}

// Part of the requirement: the set is exactly the expected one. Input: the folder with one extra
// golden-vector file (an identifier of no expected input) and with NOTICE.md. Expected: the extra
// file is named, the set fails; NOTICE.md alone does not matter (the export has it).
// Verifies: SRS-034
TEST(Srs034Set, AnUnexpectedFileIsNamedAndFailsTheSet) {
  SKIP_WITHOUT_GOLDEN_DIR();
  {
    // The folder as exported, with NOTICE.md if the export wrote it: passes.
    TempFolder folder;
    folder.import_vectors(golden_dir(), {});
    sinus_qa::write_text(folder.file("NOTICE.md").string(), "# Notice\n");
    EXPECT_TRUE(sinus::dsp::verification::set_passed(check_folder(folder.str())));
  }
  TempFolder folder;
  folder.import_vectors(golden_dir(), {});
  folder.link_or_copy(path_of(golden_dir(), "syn-fs360-hr075-clean"),
                      "syn-fs360-hr999-clean.golden.txt");
  const SetResult set = check_folder(folder.str());
  EXPECT_FALSE(sinus::dsp::verification::set_passed(set));
  std::size_t named = 0;
  for (const FileResult& f : set.files) {
    if (f.input_id == "syn-fs360-hr999-clean") {
      ++named;
      EXPECT_EQ(f.status, FileStatus::kUnexpected);
      EXPECT_FALSE(f.passed());
    }
  }
  EXPECT_EQ(named, 1U);
}

#ifdef SINUS_QA_EQUIVALENCE_TOOL
using sinus_qa::run_tool;

// Part of the requirement: "every file passes" and the failure "names the file, the output and
// the sample" on the check as a program. Input: the tool on the exported folder (exit 0, no
// failure line), then on a copy where one baseline value is changed by +3e-5 (exit 1, a line
// "FAIL <file>: baseline_mv at sample <n>: ..." on stderr), then on a copy without a file (exit 1,
// the file named), and with no arguments (exit 2).
// Verifies: SRS-034
TEST(Srs034Tool, ExitStatusAndFailureLines) {
  SKIP_WITHOUT_GOLDEN_DIR();
  TempFolder out;
  const std::string results = out.file("results.md").string();
  const std::string errors = out.file("errors.txt").string();
  EXPECT_EQ(run_tool(golden_dir(), results, errors), 0);
  EXPECT_EQ(sinus_qa::read_text(errors).find("FAIL"), std::string::npos);

  {
    TempFolder folder;
    folder.import_vectors(golden_dir(), {kFileId});
    VectorText edited(subject().text);
    edited.set_field("[signals]", 4321, 1,
                     sinus_qa::number_text(subject().parsed.baseline[4321] + 3e-5));
    sinus_qa::write_text(path_of(folder.str(), kFileId), edited.str());
    EXPECT_EQ(run_tool(folder.str(), results, errors), 1);
    const std::string text = sinus_qa::read_text(errors);
    const std::string expected_start =
        std::string("FAIL ") + kFileId + ": baseline_mv at sample 4321:";
    EXPECT_NE(text.find(expected_start), std::string::npos) << text;
  }
  {
    TempFolder folder;
    folder.import_vectors(golden_dir(), {"mitdb-203-first60s"});
    EXPECT_EQ(run_tool(folder.str(), results, errors), 1);
    EXPECT_NE(sinus_qa::read_text(errors).find("mitdb-203-first60s"), std::string::npos);
  }
  EXPECT_EQ(sinus_qa::run_tool_without_arguments(errors), 2);
}
#endif

}  // namespace
