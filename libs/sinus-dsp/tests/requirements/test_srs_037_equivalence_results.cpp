// Requirement tests of SRS-037: content of the equivalence results. The golden vectors are those
// of the same commit, in the folder of SINUS_GOLDEN_DIR (a precondition: the tests skip with a
// message when it is not set). The results file is read by QA's own code and compared with QA's own
// run of the library, own reading of the vectors and own computation of the library identity
// (architecture-m2.md 14.15).
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "golden_support.hpp"
#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/equivalence_report.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"

namespace {

using sinus::dsp::verification::check_file;
using sinus::dsp::verification::check_folder;
using sinus::dsp::verification::FileResult;
using sinus::dsp::verification::make_report_info;
using sinus::dsp::verification::render_equivalence_report;
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

// The results file as QA reads it: the title, the two-column table and the table per file.
struct Report {
  std::string title;
  std::vector<std::pair<std::string, std::string>> items;
  std::vector<std::vector<std::string>>
      rows;  // File, Output, Largest, At sample, Tolerance, Outcome
  std::string text;

  [[nodiscard]] std::string item(const std::string& key) const {
    for (const auto& [k, v] : items) {
      if (k == key) {
        return v;
      }
    }
    return "<absent>";
  }
};

std::vector<std::string> cells(const std::string& line) {
  std::vector<std::string> out;
  std::string current;
  for (std::size_t i = 1; i < line.size(); ++i) {  // after the first '|'
    if (line[i] == '|') {
      std::size_t a = current.find_first_not_of(' ');
      std::size_t b = current.find_last_not_of(' ');
      out.push_back(a == std::string::npos ? "" : current.substr(a, b - a + 1));
      current.clear();
    } else {
      current.push_back(line[i]);
    }
  }
  return out;
}

Report parse_report(const std::string& text) {
  Report r;
  r.text = text;
  std::string section;
  for (const auto& line : sinus_qa::split(text, '\n')) {
    if (line.rfind("# ", 0) == 0) {
      r.title = line;
    } else if (line.rfind("## ", 0) == 0) {
      section = line;
    } else if (!line.empty() && line[0] == '|') {
      const auto c = cells(line);
      if (c.empty() || c[0] == "Item" || c[0] == "File" || c[0].rfind("---", 0) == 0 ||
          c[0].rfind(":--", 0) == 0) {
        continue;
      }
      if (section.empty()) {
        r.items.emplace_back(c[0], c.size() > 1 ? c[1] : "");
      } else {
        r.rows.push_back(c);
      }
    }
  }
  return r;
}

// What QA computes for the whole set, once.
struct Own {
  std::map<std::string, sinus_qa::QVector> vectors;
  std::map<std::string, std::vector<sinus_qa::QDiff>> diffs;
  std::map<std::string, sinus_qa::QRun> runs;
};

const Own& own() {
  static const Own o = [] {
    Own r;
    for (const auto& id : sinus_qa::expected_ids()) {
      auto v = sinus_qa::parse_vector(sinus_qa::read_text(path_of(golden_dir(), id)));
      auto run = sinus_qa::run_library_on(v);
      r.diffs[id] = sinus_qa::compare_run(v, run);
      r.runs[id] = std::move(run);
      r.vectors[id] = std::move(v);
    }
    return r;
  }();
  return o;
}

std::string library_version() {
  std::string text = sinus_qa::read_text(std::string(SINUS_QA_LIBRARY_DIR) + "/VERSION");
  return sinus_qa::split(text, '\n')[0].substr(0, text.find_first_of("\r\n"));
}

std::string identity_text(const std::string& version, const std::string& digest) {
  return "sinus-dsp " + version + ", source SHA-256 " + digest;
}

// The results file written by the tool on the exported folder (once).
const Report& tool_report() {
  static const Report r = [] {
    static TempFolder folder;
    const std::string results = folder.file("equivalence.md").string();
    const int status =
        sinus_qa::run_tool(golden_dir(), results, folder.file("errors.txt").string());
    EXPECT_EQ(status, 0);
    return parse_report(sinus_qa::read_text(results));
  }();
  return r;
}

const char* const kNotice =
    "The files mitdb-100-first60s, mitdb-105-first60s, mitdb-108-first60s, mitdb-119-first60s, "
    "mitdb-203-first60s and mitdb-207-first60s contain extracts of the MIT-BIH Arrhythmia "
    "Database, "
    "version 1.0.0, made available by PhysioNet under the Open Data Commons Attribution License "
    "v1.0, https://opendatacommons.org/licenses/by/1-0/; the results above are computed from them.";

const std::vector<std::string> kOutputs = {"baseline_mv",      "mains_mv",    "beats",
                                           "beat_reported_at", "heart_rates", "quality_windows"};

// Part of the requirement: the check states the build target, the reference software, the version
// of the library with the identifier of its source code, and the outcome, in the documented form.
// Input: the results file written by the tool on the exported folder. Expected: the title; the
// items Build target, Library, Reference, Golden vectors, Chain size, Database notice, Outcome in
// this order; a build target for the computer; the golden-vector row "32 files of 32 expected,
// format version 2"; the notice sentence of the record segments; the outcome pass.
// Verifies: SRS-037
TEST(Srs037Header, ItemsOfTheResultsFile) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const Report& r = tool_report();
  EXPECT_EQ(r.title, "# Equivalence of the real-time library with the reference");
  const std::vector<std::string> keys = {"Build target",   "Library",    "Reference",
                                         "Golden vectors", "Chain size", "Database notice",
                                         "Outcome"};
  ASSERT_EQ(r.items.size(), keys.size());
  for (std::size_t i = 0; i < keys.size(); ++i) {
    EXPECT_EQ(r.items[i].first, keys[i]);
  }
  const std::string target = r.item("Build target");
  EXPECT_EQ(target.rfind("computer (", 0), 0U) << target;
  EXPECT_EQ(target.back(), ')');
  EXPECT_EQ(r.item("Golden vectors"), "32 files of 32 expected, format version 2");
  EXPECT_EQ(r.item("Chain size"),
            std::to_string(sizeof(sinus::dsp::Chain)) + " bytes, limit 65536");
  EXPECT_EQ(r.item("Database notice"), kNotice);
  EXPECT_EQ(r.item("Outcome"), "pass");
}

// Part of the requirement: the version of the real-time library and an identifier of its source
// code equal those that the test computes itself with the method documented.
// Input: the results file of the tool; QA reads libs/sinus-dsp/VERSION and computes the SHA-256 of
// the manifest of include/ and src/ (CR LF as LF, hidden paths left out, sorted names). Expected:
// the Library item is "sinus-dsp <version>, source SHA-256 <digest>" with those two values.
// Verifies: SRS-037
TEST(Srs037Identity, LibraryVersionAndSourceDigestAreThoseQaComputes) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const std::string digest = sinus_qa::library_source_digest(SINUS_QA_LIBRARY_DIR);
  ASSERT_EQ(digest.size(), 64U);
  EXPECT_EQ(tool_report().item("Library"), identity_text(library_version(), digest));
}

// Part of the requirement: the reported reference software equals that stated in the files.
// Input: the 32 files, whose header lines software_version and source_sha256 QA reads; the tool's
// results. Expected: the Reference item is "sinus-dsp <version>, source SHA-256 <digest>" with the
// values of the files (all the same).
// Verifies: SRS-037
TEST(Srs037Identity, ReferenceSoftwareIsThatOfTheFiles) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const auto& vectors = own().vectors;
  const auto& first = vectors.begin()->second;
  ASSERT_EQ(first.digest.size(), 64U);
  for (const auto& [id, v] : vectors) {
    EXPECT_EQ(v.version, first.version) << id;
    EXPECT_EQ(v.digest, first.digest) << id;
  }
  EXPECT_EQ(tool_report().item("Reference"), identity_text(first.version, first.digest));
}

// Part of the requirement: the reference is the software that wrote the vectors, from the files.
// Input: two files with the same reference, then the second with another source digest in its
// header (a set from two exports). Expected: the first set states the common reference; the second
// states "not the same in every file" and the outcome fail.
// Verifies: SRS-037
TEST(Srs037Identity, FilesFromTwoReferencesAreStated) {
  SKIP_WITHOUT_GOLDEN_DIR();
  TempFolder folder;
  const std::string a = "syn-fs250-hr075-clean";
  const std::string b = "syn-fs360-hr075-clean";
  const auto& va = own().vectors.at(a);
  SetResult same;
  same.folder_listed = true;
  same.files.push_back(check_file(a, path_of(golden_dir(), a)));
  same.files.push_back(check_file(b, path_of(golden_dir(), b)));
  const auto info = make_report_info("computer (test)");
  {
    const Report r = parse_report(render_equivalence_report(same, info));
    EXPECT_EQ(r.item("Reference"), identity_text(va.version, va.digest));
  }
  VectorText edited(sinus_qa::read_text(path_of(golden_dir(), b)));
  edited.replace_line_starting("source_sha256=", "source_sha256=" + std::string(64, 'a'));
  sinus_qa::write_text(path_of(folder.str(), b), edited.str());
  SetResult mixed;
  mixed.folder_listed = true;
  mixed.files.push_back(check_file(a, path_of(golden_dir(), a)));
  mixed.files.push_back(check_file(b, path_of(folder.str(), b)));
  const Report r = parse_report(render_equivalence_report(mixed, info));
  EXPECT_EQ(r.item("Reference"), "not the same in every file");
  EXPECT_EQ(r.item("Outcome"), "fail");
}

// Part of the requirement: the build target is stated. Input: the report rendered with a given
// build target (the target of another build, an ESP32-S3 emulator one). Expected: the item Build
// target holds it unchanged.
// Verifies: SRS-037
TEST(Srs037Identity, BuildTargetIsStatedAsGiven) {
  SKIP_WITHOUT_GOLDEN_DIR();
  SetResult set;
  set.folder_listed = true;
  const std::string id = "syn-fs250-hr075-clean";
  set.files.push_back(check_file(id, path_of(golden_dir(), id)));
  for (const std::string target :
       {"computer (x86_64, Linux, GNU 14.2.0)", "ESP32-S3 (emulator, ESP-IDF v6.1, GNU 15.2.0)"}) {
    const Report r = parse_report(render_equivalence_report(set, make_report_info(target)));
    EXPECT_EQ(r.item("Build target"), target);
    const auto info = make_report_info(target);
    EXPECT_EQ(r.item("Library"), identity_text(info.library_version, info.library_sha256));
  }
}

// Part of the requirement: "for each golden-vector file and each compared output, the largest
// difference found, its tolerance and the outcome". Input: the tool's results on the export, and
// QA's own run. Expected: 32 x 6 rows, in the order of the set (code-point order of the file
// names) and of the outputs; every tolerance is the approved one; every outcome is pass; the
// largest difference of the conditioning, heart-rate and quality outputs equals QA's own largest
// difference (computed in binary64 on the library's binary32 outputs), at the same sample; for
// detections the largest difference is 0.
// Verifies: SRS-037
TEST(Srs037Rows, EveryFileAndOutputHasLargestDifferenceToleranceAndOutcome) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const Report& r = tool_report();
  const auto ids = sinus_qa::expected_ids();
  ASSERT_EQ(r.rows.size(), ids.size() * kOutputs.size());
  std::size_t at = 0;
  for (const auto& id : ids) {
    const auto& expected = own().diffs.at(id);
    for (std::size_t o = 0; o < kOutputs.size(); ++o, ++at) {
      const auto& row = r.rows[at];
      ASSERT_EQ(row.size(), 6U) << id;
      EXPECT_EQ(row[0], id);
      EXPECT_EQ(row[1], kOutputs[o]);
      EXPECT_EQ(row[5], "pass") << id << " " << kOutputs[o];
      EXPECT_DOUBLE_EQ(std::strtod(row[4].c_str(), nullptr), sinus_qa::tolerance_of(kOutputs[o]))
          << id << " " << kOutputs[o] << " tolerance text " << row[4];
      const double largest = std::strtod(row[2].c_str(), nullptr);
      EXPECT_NEAR(largest, expected[o].largest, 1e-12) << id << " " << kOutputs[o] << " " << row[2];
      if (o < 2 || o == 4 || o == 5) {
        if (expected[o].largest > 0.0) {
          EXPECT_EQ(row[3], std::to_string(expected[o].sample)) << id << " " << kOutputs[o];
        }
      } else {
        EXPECT_EQ(largest, 0.0) << id << " " << kOutputs[o];
      }
    }
  }
}

// Part of the requirement: the results are the same for the same inputs. Input: the tool run
// twice on the export. Expected: the same bytes.
// Verifies: SRS-037
TEST(Srs037Rows, ResultsAreReproducible) {
  SKIP_WITHOUT_GOLDEN_DIR();
  TempFolder folder;
  const std::string a = folder.file("a.md").string();
  const std::string b = folder.file("b.md").string();
  const std::string errors = folder.file("e.txt").string();
  ASSERT_EQ(sinus_qa::run_tool(golden_dir(), a, errors), 0);
  ASSERT_EQ(sinus_qa::run_tool(golden_dir(), b, errors), 0);
  EXPECT_EQ(sinus_qa::read_text(a), sinus_qa::read_text(b));
  EXPECT_EQ(sinus_qa::read_text(a), tool_report().text);
}

// Part of the requirement (Verification line): with a set in which one output of one file is
// changed by a known amount, larger than every other difference of that output and within its
// tolerance, the reported largest difference for that file and output equals that amount within
// the rounding of the comparison.
// Input: a folder of the export in which one value of the baseline, of the mains, of one valid
// heart rate and of one window index are changed (four different files) by +1.2e-5 mV, -1.5e-5 mV,
// +6e-5 bpm and +0.005; the other differences are of the order of 1e-7 or less. Expected: the
// reported largest difference of each is the amount, within QA's own difference at that sample
// (the rounding of the library's output); the sample is the changed one; all rows pass, the
// outcome is pass; the other outputs of those files are as in the unchanged export.
// Verifies: SRS-037
TEST(Srs037Known, ReportedLargestDifferenceEqualsTheChange) {
  SKIP_WITHOUT_GOLDEN_DIR();
  struct Change {
    std::string id;
    std::size_t output;  // index into kOutputs
    double delta;
    std::size_t row;  // row of the section of the output
  };
  const std::vector<Change> changes = {{"syn-fs360-hr075-bw-mains50", 0, 1.2e-5, 4321},
                                       {"syn-fs250-hr040-bw-mains60", 1, -1.5e-5, 2500},
                                       {"syn-fs360-hr180-clean", 4, 6e-5, 0},
                                       {"mitdb-108-first60s", 5, 0.005, 17}};
  std::vector<Change> resolved = changes;
  TempFolder folder;
  std::vector<std::string> skipped;
  for (const auto& c : changes) {
    skipped.push_back(c.id);
  }
  folder.import_vectors(golden_dir(), skipped);
  std::vector<double> own_difference(changes.size(), 0.0);
  std::vector<std::vector<std::uint64_t>> window_samples(changes.size());
  for (std::size_t n = 0; n < changes.size(); ++n) {
    Change& c = resolved[n];
    const auto& v = own().vectors.at(c.id);
    const auto& run = own().runs.at(c.id);
    VectorText edited(sinus_qa::read_text(path_of(golden_dir(), c.id)));
    if (c.output == 0) {
      own_difference[n] = std::fabs(run.baseline[c.row] - v.baseline[c.row]);
      edited.set_field("[signals]", c.row, 1, sinus_qa::number_text(v.baseline[c.row] + c.delta));
    } else if (c.output == 1) {
      own_difference[n] = std::fabs(run.mains_out[c.row] - v.mains_out[c.row]);
      edited.set_field("[signals]", c.row, 2, sinus_qa::number_text(v.mains_out[c.row] + c.delta));
    } else if (c.output == 4) {
      std::size_t k = 0;
      while (k < v.rates.size() && v.rates[k].status != "valid") {
        ++k;
      }
      ASSERT_LT(k, v.rates.size());
      c.row = k;
      own_difference[n] = std::fabs(run.rates[k].bpm - v.rates[k].bpm);
      edited.set_field("[heart_rates]", k, 3, sinus_qa::number_text(v.rates[k].bpm + c.delta));
    } else {
      ASSERT_LT(c.row, v.windows.size());
      ASSERT_LT(v.windows[c.row].index + c.delta, 1.0);
      own_difference[n] = std::fabs(run.windows[c.row].index - v.windows[c.row].index);
      edited.set_field("[quality_windows]", c.row, 3,
                       sinus_qa::number_text(v.windows[c.row].index + c.delta));
      window_samples[n] = {v.windows[c.row].first, v.windows[c.row].last,
                           v.windows[c.row].reported};
    }
    sinus_qa::write_text(path_of(folder.str(), c.id), edited.str());
  }
  const SetResult set = check_folder(folder.str());
  const Report r =
      parse_report(render_equivalence_report(set, make_report_info("computer (test)")));
  EXPECT_EQ(r.item("Outcome"), "pass");

  for (const auto& row : r.rows) {
    EXPECT_EQ(row[5], "pass") << row[0] << " " << row[1];
  }
  for (std::size_t n = 0; n < resolved.size(); ++n) {
    const Change& c = resolved[n];
    const auto& base = own().diffs.at(c.id);
    for (const auto& row : r.rows) {
      if (row[0] != c.id) {
        continue;
      }
      std::size_t o = 0;
      while (kOutputs[o] != row[1]) {
        ++o;
      }
      const double reported = std::strtod(row[2].c_str(), nullptr);
      if (o == c.output) {
        EXPECT_NEAR(reported, std::fabs(c.delta), own_difference[n] + 1e-12)
            << c.id << " " << row[1] << " reported " << row[2];
        if (o <= 4) {
          const std::uint64_t sample = o < 2 ? c.row : own().vectors.at(c.id).rates[c.row].sample;
          EXPECT_EQ(row[3], std::to_string(sample)) << c.id << " " << row[1];
        } else {
          bool found = false;
          for (const auto s : window_samples[n]) {
            found = found || row[3] == std::to_string(s);
          }
          EXPECT_TRUE(found) << c.id << " " << row[1] << " at " << row[3];
        }
      } else {
        EXPECT_NEAR(reported, base[o].largest, 1e-12) << c.id << " " << row[1];
      }
    }
  }
}

// Part of the requirement: the outcome of each output against its tolerance, and of the set.
// Input: the export with one baseline value changed by +3e-5 mV (beyond 2e-5), and one detection
// removed, in two other files. Expected: the baseline row of the first file reports about 3e-5
// and fail; the beats row of the second states a difference of count (the counts of the library
// and of the file, "count N, file M") and fail; the item Outcome is fail; every other row passes.
// Verifies: SRS-037
TEST(Srs037Fail, FailingOutputsAreReportedAsFail) {
  SKIP_WITHOUT_GOLDEN_DIR();
  const std::string first = "syn-fs360-hr075-bw-mains50";
  const std::string second = "syn-fs250-hr075-clean";
  TempFolder folder;
  const auto& v1 = own().vectors.at(first);
  const auto& v2 = own().vectors.at(second);
  {
    VectorText edited(sinus_qa::read_text(path_of(golden_dir(), first)));
    edited.set_field("[signals]", 3000, 1, sinus_qa::number_text(v1.baseline[3000] + 3e-5));
    sinus_qa::write_text(path_of(folder.str(), first), edited.str());
  }
  SetResult set;
  set.folder_listed = true;
  set.files.push_back(check_file(first, path_of(folder.str(), first)));
  {
    auto read = sinus::dsp::verification::read_golden_vector(path_of(golden_dir(), second));
    ASSERT_TRUE(read.ok) << read.error.reason;
    read.vector.beats.erase(read.vector.beats.begin() + 4);
    set.files.push_back(sinus::dsp::verification::check_vector(second, read.vector));
  }
  const Report r =
      parse_report(render_equivalence_report(set, make_report_info("computer (test)")));
  EXPECT_EQ(r.item("Outcome"), "fail");
  std::size_t failing = 0;
  for (const auto& row : r.rows) {
    if (row[0] == first && row[1] == "baseline_mv") {
      EXPECT_EQ(row[5], "fail");
      EXPECT_NEAR(std::strtod(row[2].c_str(), nullptr), 3e-5, 1e-6);
      EXPECT_EQ(row[3], "3000");
    } else if (row[0] == second && row[1] == "beats") {
      EXPECT_EQ(row[5], "fail");
      const std::string expected = "count " + std::to_string(v2.beats.size()) + ", file " +
                                   std::to_string(v2.beats.size() - 1);
      EXPECT_NE(row[2].find(expected), std::string::npos) << row[2];
    }
    if (row[5] == "fail") {
      ++failing;
      EXPECT_TRUE(row[0] == first || row[0] == second) << row[0] << " " << row[1];
    }
  }
  EXPECT_GE(failing, 2U);
}

// Part of the requirement: the check reports for each golden-vector file; a file missing from the
// set or not expected is named in the results. Input: the export without one file, and with one
// golden-vector file more. Expected: the Golden vectors item says "31 files of 32 expected"; the
// results have a row for the missing file (output "file", the difference "missing", no sample,
// fail) and one for the extra (difference "unexpected", fail); the outcome is fail.
// Verifies: SRS-037
TEST(Srs037Fail, AMissingAndAnUnexpectedFileAreNamedInTheResults) {
  SKIP_WITHOUT_GOLDEN_DIR();
  TempFolder folder;
  folder.import_vectors(golden_dir(), {"mitdb-207-first60s"});
  folder.link_or_copy(path_of(golden_dir(), "syn-fs360-hr075-clean"), "syn-extra.golden.txt");
  const Report r = parse_report(
      render_equivalence_report(check_folder(folder.str()), make_report_info("computer (test)")));
  EXPECT_EQ(r.item("Golden vectors"), "31 files of 32 expected, format version 2");
  EXPECT_EQ(r.item("Outcome"), "fail");
  std::size_t missing = 0;
  std::size_t extra = 0;
  for (const auto& row : r.rows) {
    if (row[0] == "mitdb-207-first60s") {
      ++missing;
      EXPECT_EQ(row[1], "file");
      EXPECT_EQ(row[2], "missing");
      EXPECT_EQ(row[5], "fail");
    }
    if (row[0] == "syn-extra") {
      ++extra;
      EXPECT_EQ(row[2], "unexpected");
      EXPECT_EQ(row[5], "fail");
    }
  }
  EXPECT_EQ(missing, 1U);
  EXPECT_EQ(extra, 1U);
}

}  // namespace
