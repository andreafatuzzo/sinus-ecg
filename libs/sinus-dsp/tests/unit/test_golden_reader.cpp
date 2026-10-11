#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

#include "reader_parity_cases.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"

namespace {

using sinus::dsp::HeartRateStatus;
using sinus::dsp::Mark;
using sinus::dsp::verification::parse_golden_vector;
using sinus::dsp::verification::ReadResult;

// Applies the edits of a parity case to the base text, as the generator did.
std::string build(const std::vector<parity::Edit>& edits) {
  std::vector<std::string> lines;
  for (const std::string_view line : parity::kBase) {
    lines.emplace_back(line);
  }
  std::string separator = "\n";
  std::string prefix;
  std::string suffix;
  std::string whole;
  bool has_whole = false;
  bool final_feed = true;
  for (const parity::Edit& edit : edits) {
    const auto at = static_cast<std::size_t>(edit.line > 0 ? edit.line - 1 : 0);
    switch (edit.op) {
      case parity::Op::kReplace:
        lines.at(at) = std::string(edit.text);
        break;
      case parity::Op::kDelete:
        lines.erase(lines.begin() + static_cast<std::ptrdiff_t>(at));
        break;
      case parity::Op::kInsert:
        lines.insert(lines.begin() + static_cast<std::ptrdiff_t>(at), std::string(edit.text));
        break;
      case parity::Op::kKeep:
        lines.resize(static_cast<std::size_t>(edit.line));
        break;
      case parity::Op::kKeepNoLf:
        lines.resize(static_cast<std::size_t>(edit.line));
        final_feed = false;
        break;
      case parity::Op::kAppend:
        suffix += std::string(edit.text);
        break;
      case parity::Op::kWhole:
        whole = std::string(edit.text);
        has_whole = true;
        break;
      case parity::Op::kCrlf:
        separator = "\r\n";
        break;
      case parity::Op::kBom:
        prefix = "\xEF\xBB\xBF";
        break;
    }
  }
  if (has_whole) {
    return whole;
  }
  std::string text = prefix;
  for (std::size_t i = 0; i < lines.size(); ++i) {
    text += (i == 0 ? "" : separator) + lines.at(i);
  }
  return text + (final_feed ? separator : "") + suffix;
}

std::string base_text() { return build({}); }

// Every text rejected or accepted by the Python reader is rejected or accepted here, at the same
// line (architecture.md 7.3: the line, not the wording, is compared).
TEST(GoldenReaderParity, SameOutcomeAsThePythonReaderOnEveryCase) {
  for (const parity::Case& c : parity::cases()) {
    const ReadResult result = parse_golden_vector(build(c.edits));
    if (c.expected == 0) {
      EXPECT_TRUE(result.ok) << c.name << ": " << result.error.reason << " (line "
                             << result.error.line << ")";
    } else if (c.expected < 0) {
      EXPECT_FALSE(result.ok) << c.name;
      EXPECT_FALSE(result.error.has_line) << c.name;
    } else {
      EXPECT_FALSE(result.ok) << c.name;
      EXPECT_TRUE(result.error.has_line) << c.name;
      EXPECT_EQ(result.error.line, static_cast<std::uint64_t>(c.expected))
          << c.name << ": " << result.error.reason;
    }
  }
}

TEST(GoldenReaderParity, EveryKindOfOutcomeIsCovered) {
  int accepted = 0;
  int without_line = 0;
  int with_line = 0;
  for (const parity::Case& c : parity::cases()) {
    (c.expected == 0 ? accepted : (c.expected < 0 ? without_line : with_line))++;
  }
  EXPECT_GE(accepted, 20);
  EXPECT_GE(without_line, 5);
  EXPECT_GE(with_line, 200);
}

TEST(GoldenReader, ReadsTheBaseVector) {
  const ReadResult result = parse_golden_vector(base_text());
  ASSERT_TRUE(result.ok) << result.error.reason << " at " << result.error.line;
  const auto& v = result.vector;
  EXPECT_EQ(v.input_id, "t1");
  EXPECT_EQ(v.input_source, "synthetic");
  EXPECT_EQ(v.input_parameters, "a=1;b=2");
  EXPECT_EQ(v.fs_hz, 360.0);
  EXPECT_EQ(v.mains_hz, 60);
  EXPECT_EQ(v.software_version, "0.2.0");
  EXPECT_EQ(v.source_sha256.size(), 64U);
  ASSERT_EQ(v.stages.size(), 2U);
  EXPECT_EQ(v.stages.at(0), "baseline");
  EXPECT_EQ(v.stages.at(1), "mains");
  ASSERT_EQ(v.coefficients.size(), 2U);
  EXPECT_EQ(v.coefficients.at(0).size(), 2U);
  EXPECT_EQ(v.coefficients.at(1).size(), 1U);
  EXPECT_EQ(v.coefficients.at(0).at(0).at(3), -0.5);
  ASSERT_EQ(v.input_mv.size(), 12U);
  ASSERT_EQ(v.stage_outputs_mv.size(), 2U);
  EXPECT_EQ(v.stage_outputs_mv.at(1).at(4), -0.1);
  ASSERT_EQ(v.beats.size(), 3U);
  EXPECT_EQ(v.beats.at(0).mark, Mark::kStartUp);
  EXPECT_EQ(v.beats.at(1).mark, Mark::kReliable);
  EXPECT_EQ(v.beats.at(2).index, 8U);
  EXPECT_EQ(v.beats.at(2).reported_at, 10U);
  ASSERT_EQ(v.reference_beats.size(), 2U);
  ASSERT_EQ(v.heart_rates.size(), 3U);
  EXPECT_EQ(v.heart_rates.at(0).status, HeartRateStatus::kNotEnoughBeats);
  EXPECT_TRUE(v.heart_rates.at(0).has_beat);
  EXPECT_FALSE(v.heart_rates.at(0).has_rate);
  EXPECT_EQ(v.heart_rates.at(1).bpm, 70.5);
  EXPECT_TRUE(v.heart_rates.at(1).has_rate);
  EXPECT_FALSE(v.heart_rates.at(2).has_beat);
  EXPECT_EQ(v.heart_rates.at(2).status, HeartRateStatus::kNoRecentBeat);
  ASSERT_EQ(v.windows.size(), 2U);
  EXPECT_EQ(v.windows.at(0).reported_at, 8U);
  EXPECT_EQ(v.windows.at(0).index, 0.75);
  EXPECT_TRUE(v.windows.at(0).usable);
  EXPECT_FALSE(v.windows.at(1).usable);
}

// Exact read-back (architecture.md 7.4): the value read has the bits of the value written.
double signal_value(const std::string& text) {
  std::vector<parity::Edit> edits{{parity::Op::kReplace, 28, text}};
  const ReadResult result = parse_golden_vector(build(edits));
  EXPECT_TRUE(result.ok) << text << ": " << result.error.reason;
  return result.ok ? result.vector.input_mv.at(5) : 0.0;
}

TEST(GoldenReaderReadBack, EdgeValuesAreExact) {
  EXPECT_EQ(signal_value("5e-324,0.0,0.0"), 4.9406564584124654e-324);
  EXPECT_EQ(signal_value("1.7976931348623157e+308,0.0,0.0"), 1.7976931348623157e308);
  EXPECT_EQ(signal_value("-1.7976931348623157e+308,0.0,0.0"), -1.7976931348623157e308);
  EXPECT_EQ(signal_value("0.30000000000000004,0.0,0.0"), 0.30000000000000004);
  EXPECT_EQ(signal_value("0.1,0.0,0.0"), 0.1);
  EXPECT_EQ(signal_value("-1.2345e-05,0.0,0.0"), -1.2345e-05);
  EXPECT_EQ(signal_value("1e+16,0.0,0.0"), 1e16);
  EXPECT_EQ(signal_value("0.0e-400,0.0,0.0"), 0.0);
  EXPECT_EQ(signal_value("2.2250738585072014e-308,0.0,0.0"), 2.2250738585072014e-308);
  EXPECT_EQ(signal_value("2.225073858507201e-308,0.0,0.0"), 2.225073858507201e-308);
}

TEST(GoldenReaderReadBack, NegativeZeroKeepsItsSign) {
  EXPECT_TRUE(std::signbit(signal_value("-0.0,0.0,0.0")));
  EXPECT_FALSE(std::signbit(signal_value("0.0,0.0,0.0")));
  EXPECT_TRUE(std::signbit(signal_value("-0.0e-400,0.0,0.0")));
}

TEST(GoldenReaderReadBack, LargestIntegerIsExact) {
  std::vector<parity::Edit> edits{{parity::Op::kReplace, 37, "9,reliable,9223372036854775807"}};
  const ReadResult result = parse_golden_vector(build(edits));
  EXPECT_FALSE(result.ok);  // the integer is read (2^63 - 1), then found beyond the signal
  EXPECT_EQ(result.error.line, 37U);
  EXPECT_NE(result.error.reason.find("outside"), std::string::npos);
}

TEST(GoldenReader, NotUtf8HasNoLine) {
  const ReadResult result = parse_golden_vector("\xFF");
  EXPECT_FALSE(result.ok);
  EXPECT_FALSE(result.error.has_line);
  EXPECT_EQ(result.error.reason, "not UTF-8 text");
}

TEST(GoldenReader, MissingFileHasNoLine) {
  const auto path = std::filesystem::temp_directory_path() / "sinus_dsp_no_such_vector.golden.txt";
  const ReadResult result = sinus::dsp::verification::read_golden_vector(path.string());
  EXPECT_FALSE(result.ok);
  EXPECT_FALSE(result.error.has_line);
}

}  // namespace
