#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/status.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/golden_pack.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"
#include "sinus/dsp/verification/golden_set.hpp"
#include "synthetic_beats.hpp"

namespace {

using sinus::dsp::Chain;
using sinus::dsp::SampleOutput;
using sinus::dsp::verification::build_pack;
using sinus::dsp::verification::check_pack;
using sinus::dsp::verification::check_vector;
using sinus::dsp::verification::FileResult;
using sinus::dsp::verification::FileStatus;
using sinus::dsp::verification::GoldenVector;
using sinus::dsp::verification::LibraryOutputs;
using sinus::dsp::verification::MemorySource;
using sinus::dsp::verification::OutputResult;
using sinus::dsp::verification::PackCheck;
using sinus::dsp::verification::verify_pack;

// A vector that the library reproduces exactly (its file values are the library's own outputs).
GoldenVector library_vector(const std::string& id) {
  constexpr double kFs = 250.0;
  GoldenVector v;
  v.input_id = id;
  v.input_source = "synthetic";
  v.input_parameters = "unit";
  v.fs_hz = kFs;
  v.mains_hz = 50;
  v.software_version = "x";
  v.source_sha256 = std::string(64, 'a');
  v.stages = {"baseline", "mains"};
  v.coefficients = {{{1.0, 2.0, 3.0, 4.0, 5.0}}, {{6.0, 7.0, 8.0, 9.0, 10.0}, {1, 2, 3, 4, 5}}};
  const std::vector<float> x =
      sinus_test::synthetic_beats(kFs, 12.0, sinus_test::regular_beats(1.0, 0.8, 12.0));
  for (const float s : x) {
    v.input_mv.push_back(static_cast<double>(s));
  }
  const LibraryOutputs run = sinus::dsp::verification::run_library(v);
  EXPECT_EQ(run.status, sinus::dsp::Status::kOk);
  v.stage_outputs_mv = {run.baseline_mv, run.conditioned_mv};
  v.beats = run.beats;
  v.heart_rates = run.heart_rates;
  v.windows = run.windows;
  return v;
}

// The expected set: one library vector under each expected identifier.
std::vector<GoldenVector> expected_set() {
  const GoldenVector base = library_vector("base");
  std::vector<GoldenVector> set;
  for (const std::string_view id : sinus::dsp::verification::expected_inputs()) {
    GoldenVector v = base;
    v.input_id = std::string(id);
    set.push_back(v);
  }
  return set;
}

struct Storage {
  std::unique_ptr<Chain> chain = std::make_unique<Chain>();
  std::unique_ptr<SampleOutput> out = std::make_unique<SampleOutput>();
};

PackCheck check(const std::string& bytes) {
  Storage storage;
  MemorySource source(bytes);
  return check_pack(source, *storage.chain, *storage.out);
}

std::string pack_of(const std::vector<GoldenVector>& vectors) {
  std::string bytes;
  const auto built = build_pack(vectors, bytes);
  EXPECT_TRUE(built.ok) << built.error;
  return bytes;
}

const OutputResult& output_of(const FileResult& file, const std::string& name) {
  for (const OutputResult& output : file.outputs) {
    if (output.output == name) {
      return output;
    }
  }
  ADD_FAILURE() << "no output " << name;
  return file.outputs.front();
}

TEST(GoldenPack, HeaderLayout) {
  const std::string bytes = pack_of(expected_set());
  ASSERT_GT(bytes.size(), 56U);
  EXPECT_EQ(bytes.substr(0, 8), "SINUSGVP");
  EXPECT_EQ(static_cast<unsigned char>(bytes.at(8)), 1U);  // version, little-endian
  EXPECT_EQ(static_cast<unsigned char>(bytes.at(9)), 0U);
  EXPECT_EQ(static_cast<unsigned char>(bytes.at(12)), 32U);  // number of files
  std::uint64_t payload = 0;
  for (unsigned i = 0; i < 8; ++i) {
    payload |= static_cast<std::uint64_t>(static_cast<unsigned char>(bytes.at(16 + i))) << (8U * i);
  }
  EXPECT_EQ(payload, bytes.size() - 56U);
  EXPECT_EQ(bytes.substr(56, 4), "GVF2");
}

TEST(GoldenPack, SizeOfOneFile) {
  GoldenVector v = library_vector(std::string(sinus::dsp::verification::expected_inputs().at(0)));
  std::string bytes;
  ASSERT_TRUE(build_pack({v}, bytes).ok);
  const std::size_t texts = 5 * 2 + v.input_id.size() + v.input_source.size() +
                            v.input_parameters.size() + v.software_version.size() +
                            v.source_sha256.size();
  const std::size_t expected = 56 + 4 + texts + 8 + 4 + 5 * 4 + 3 * 42 + v.input_mv.size() * 20 +
                               v.beats.size() * 17 + v.heart_rates.size() * 25 +
                               v.windows.size() * 33;
  EXPECT_EQ(bytes.size(), expected);
}

TEST(GoldenPack, AnIntactPackIsVerified) {
  const std::string bytes = pack_of(expected_set());
  MemorySource source(bytes);
  EXPECT_TRUE(verify_pack(source).ok);
}

TEST(GoldenPack, AChangedPayloadByteFailsTheSeal) {
  std::string bytes = pack_of(expected_set());
  bytes.at(bytes.size() / 2) = static_cast<char>(bytes.at(bytes.size() / 2) ^ 1);
  MemorySource source(bytes);
  const auto outcome = verify_pack(source);
  EXPECT_FALSE(outcome.ok);
  EXPECT_NE(outcome.error.find("SHA-256"), std::string::npos) << outcome.error;
}

TEST(GoldenPack, ATruncatedPackIsRefused) {
  const std::string bytes = pack_of(expected_set());
  for (const std::size_t keep :
       {std::size_t{0}, std::size_t{10}, std::size_t{55}, bytes.size() - 1}) {
    const std::string cut = bytes.substr(0, keep);
    MemorySource source(cut);
    EXPECT_FALSE(verify_pack(source).ok) << keep;
    EXPECT_FALSE(check(cut).outcome.ok) << keep;
  }
}

TEST(GoldenPack, BadMagicAndVersionAreRefused) {
  std::string bytes = pack_of(expected_set());
  std::string wrong_magic = bytes;
  wrong_magic.at(0) = 'X';
  MemorySource a(wrong_magic);
  EXPECT_FALSE(verify_pack(a).ok);
  std::string wrong_version = bytes;
  wrong_version.at(8) = 2;
  MemorySource b(wrong_version);
  EXPECT_FALSE(verify_pack(b).ok);
  EXPECT_FALSE(check(wrong_version).outcome.ok);
}

TEST(GoldenPack, TheLibraryAgreesWithItselfOnEveryFile) {
  const PackCheck result = check(pack_of(expected_set()));
  ASSERT_TRUE(result.outcome.ok) << result.outcome.error;
  EXPECT_TRUE(result.set.folder_listed);
  ASSERT_EQ(result.set.files.size(), 32U);
  EXPECT_TRUE(sinus::dsp::verification::set_passed(result.set));
  for (const FileResult& file : result.set.files) {
    EXPECT_EQ(file.status, FileStatus::kCompared) << file.input_id;
    ASSERT_EQ(file.outputs.size(), 6U) << file.input_id;
    for (const OutputResult& output : file.outputs) {
      EXPECT_EQ(output.largest, 0.0) << file.input_id << " " << output.output;
    }
  }
}

TEST(GoldenPack, TheResultsAreThoseOfTheTextCheck) {
  // A disturbance within and beyond the tolerance: the pack and the vector give the same results.
  GoldenVector v = library_vector(std::string(sinus::dsp::verification::expected_inputs().at(3)));
  v.stage_outputs_mv.at(0).at(700) += 1.5e-5;
  v.stage_outputs_mv.at(1).at(900) += 3e-5;
  v.heart_rates.at(2).bpm += 5e-5;
  v.windows.at(0).index += 0.002;
  std::string bytes;
  ASSERT_TRUE(build_pack({v}, bytes).ok);
  const PackCheck packed = check(bytes);
  ASSERT_TRUE(packed.outcome.ok) << packed.outcome.error;
  const FileResult text = check_vector(v.input_id, v);
  const FileResult* file = nullptr;
  for (const FileResult& f : packed.set.files) {
    if (f.input_id == v.input_id) {
      file = &f;
    }
  }
  ASSERT_NE(file, nullptr);
  ASSERT_EQ(file->outputs.size(), text.outputs.size());
  for (std::size_t i = 0; i < text.outputs.size(); ++i) {
    EXPECT_EQ(file->outputs.at(i).output, text.outputs.at(i).output);
    EXPECT_EQ(file->outputs.at(i).pass, text.outputs.at(i).pass) << text.outputs.at(i).output;
    EXPECT_EQ(file->outputs.at(i).sample, text.outputs.at(i).sample) << text.outputs.at(i).output;
    EXPECT_EQ(file->outputs.at(i).difference, text.outputs.at(i).difference);
    EXPECT_NEAR(file->outputs.at(i).largest, text.outputs.at(i).largest, 1e-15);
  }
  EXPECT_TRUE(output_of(*file, "baseline_mv").pass);
  EXPECT_FALSE(output_of(*file, "mains_mv").pass);
  EXPECT_EQ(output_of(*file, "mains_mv").sample, 900U);
}

TEST(GoldenPack, AValueChangedBeyondItsToleranceFailsAndNamesFileOutputAndSample) {
  std::vector<GoldenVector> set = expected_set();
  set.at(7).stage_outputs_mv.at(0).at(1234) += 3e-5;
  const PackCheck result = check(pack_of(set));
  ASSERT_TRUE(result.outcome.ok);
  EXPECT_FALSE(sinus::dsp::verification::set_passed(result.set));
  const FileResult& file = result.set.files.at(7);
  EXPECT_FALSE(file.passed());
  EXPECT_FALSE(output_of(file, "baseline_mv").pass);
  EXPECT_EQ(output_of(file, "baseline_mv").sample, 1234U);
  for (std::size_t i = 0; i < result.set.files.size(); ++i) {
    EXPECT_EQ(result.set.files.at(i).passed(), i != 7U) << i;
  }
}

TEST(GoldenPack, ARemovedDetectionFails) {
  std::vector<GoldenVector> set = expected_set();
  ASSERT_GT(set.at(0).beats.size(), 3U);
  set.at(0).beats.erase(set.at(0).beats.begin() + 2);
  const PackCheck result = check(pack_of(set));
  ASSERT_TRUE(result.outcome.ok);
  const OutputResult& beats = output_of(result.set.files.at(0), "beats");
  EXPECT_FALSE(beats.pass);
  EXPECT_FALSE(beats.difference.empty());
}

TEST(GoldenPack, EventsWithoutBeatOrRateSurviveThePack) {
  GoldenVector v = library_vector(std::string(sinus::dsp::verification::expected_inputs().at(0)));
  bool no_beat = false;
  bool no_rate = false;
  for (const auto& e : v.heart_rates) {
    no_beat = no_beat || !e.has_beat;
    no_rate = no_rate || !e.has_rate;
  }
  EXPECT_TRUE(no_rate);
  static_cast<void>(no_beat);  // the beat-less event needs a stream that goes quiet
  std::string bytes;
  ASSERT_TRUE(build_pack({v}, bytes).ok);
  const PackCheck result = check(bytes);
  ASSERT_TRUE(result.outcome.ok);
  EXPECT_TRUE(output_of(result.set.files.at(0), "heart_rates").pass);
  EXPECT_EQ(output_of(result.set.files.at(0), "heart_rates").difference, "");
}

TEST(GoldenPack, AMissingFileIsNamed) {
  std::vector<GoldenVector> set = expected_set();
  const std::string gone = set.at(5).input_id;
  set.erase(set.begin() + 5);
  const PackCheck result = check(pack_of(set));
  ASSERT_TRUE(result.outcome.ok);
  ASSERT_EQ(result.set.files.size(), 32U);
  EXPECT_EQ(result.set.files.at(5).input_id, gone);
  EXPECT_EQ(result.set.files.at(5).status, FileStatus::kMissing);
  EXPECT_FALSE(sinus::dsp::verification::set_passed(result.set));
}

TEST(GoldenPack, AnUnexpectedFileAndARepeatAreNamed) {
  std::vector<GoldenVector> set = expected_set();
  GoldenVector extra = set.at(0);
  extra.input_id = "not-in-the-set";
  set.push_back(extra);
  set.push_back(set.at(1));  // a repeat of an expected file
  const PackCheck result = check(pack_of(set));
  ASSERT_TRUE(result.outcome.ok);
  ASSERT_EQ(result.set.files.size(), 34U);
  EXPECT_EQ(result.set.files.at(32).input_id, "not-in-the-set");
  EXPECT_EQ(result.set.files.at(32).status, FileStatus::kUnexpected);
  EXPECT_EQ(result.set.files.at(33).input_id, set.at(1).input_id);
  EXPECT_EQ(result.set.files.at(33).status, FileStatus::kUnexpected);
  EXPECT_FALSE(sinus::dsp::verification::set_passed(result.set));
}

TEST(GoldenPack, AFileTheLibraryCannotRunIsNotComparable) {
  std::vector<GoldenVector> set = expected_set();
  set.at(2).fs_hz = 50.0;  // below the supported range
  const PackCheck result = check(pack_of(set));
  ASSERT_TRUE(result.outcome.ok);
  EXPECT_EQ(result.set.files.at(2).status, FileStatus::kNotComparable);
  EXPECT_TRUE(result.set.files.at(3).passed());  // the next file is still read correctly
}

TEST(GoldenPack, AnInvalidSampleStopsThatFileOnly) {
  std::vector<GoldenVector> set = expected_set();
  set.at(4).input_mv.at(100) = std::numeric_limits<double>::quiet_NaN();
  const PackCheck result = check(pack_of(set));
  ASSERT_TRUE(result.outcome.ok);
  EXPECT_EQ(result.set.files.at(4).status, FileStatus::kNotComparable);
  EXPECT_NE(result.set.files.at(4).detail.find("sample 100"), std::string::npos);
  EXPECT_TRUE(result.set.files.at(5).passed());
}

TEST(GoldenPack, TheWriterRefusesWhatTheTargetCannotRead) {
  std::string bytes;
  GoldenVector wrong_stages = library_vector("a");
  wrong_stages.stages = {"baseline"};
  EXPECT_FALSE(build_pack({wrong_stages}, bytes).ok);
  GoldenVector short_output = library_vector("b");
  short_output.stage_outputs_mv.at(1).pop_back();
  EXPECT_FALSE(build_pack({short_output}, bytes).ok);
  GoldenVector long_text = library_vector("c");
  long_text.input_parameters = std::string(70000, 'p');
  const auto outcome = build_pack({long_text}, bytes);
  EXPECT_FALSE(outcome.ok);
  EXPECT_NE(outcome.error.find("c:"), std::string::npos);
}

TEST(MemorySource, ReadsInOrderAndRefusesPastTheEnd) {
  const std::string bytes = "abcdef";
  MemorySource source(bytes);
  std::uint8_t buffer[4] = {};
  EXPECT_TRUE(source.read(buffer, 4));
  EXPECT_EQ(buffer[0], 'a');
  EXPECT_EQ(buffer[3], 'd');
  EXPECT_TRUE(source.read(buffer, 0));
  EXPECT_FALSE(source.read(buffer, 3));
  EXPECT_TRUE(source.read(buffer, 2));
  EXPECT_EQ(buffer[1], 'f');
}

}  // namespace
