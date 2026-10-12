// Developer's unit tests of the WFDB header subset and its number grammar (architecture-m3.md 17.3,
// 17.5).

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <string>
#include <string_view>

#include "core/wfdb_header.hpp"
#include "core/wfdb_status.hpp"

namespace {

using sinus::desktop::core::kWfdbHeaderMaxBytes;
using sinus::desktop::core::parse_wfdb_decimal;
using sinus::desktop::core::parse_wfdb_header;
using sinus::desktop::core::WfdbFormat;
using sinus::desktop::core::WfdbHeader;
using sinus::desktop::core::WfdbResult;
using sinus::desktop::core::WfdbStatus;

// The header of MIT-BIH record 100, as published.
constexpr std::string_view kRecord100 =
    "100 2 360 650000 0:0:0 0/0/0\n"
    "100.dat 212 200 11 1024 995 -22131 0 MLII\n"
    "100.dat 212 200 11 1024 1011 20052 0 V5\n"
    "# 69 M 1085 1629 x1\n"
    "# Aldomet, Inderal\n";

WfdbResult parse(std::string_view text, WfdbHeader& header) {
  return parse_wfdb_header(text, "100", header);
}

// A one-signal header with the given record line fields after the name, and signal line.
std::string header_of(std::string_view record_fields, std::string_view signal_line) {
  std::string text = "100 ";
  text.append(record_fields).append("\n").append(signal_line).append("\n");
  return text;
}

std::string signal_header(std::string_view signal_line) {
  return header_of("1 360 1000", signal_line);
}

// The status, and a message that starts with the record name and contains every fragment.
void expect_failure(std::string_view text, WfdbStatus status,
                    std::initializer_list<std::string_view> fragments) {
  WfdbHeader header;
  const WfdbResult result = parse(text, header);
  EXPECT_EQ(result.status, status) << text << "\n" << result.message;
  EXPECT_FALSE(result.ok());
  EXPECT_EQ(result.message.rfind("100: ", 0), 0U) << result.message;
  for (const std::string_view fragment : fragments) {
    EXPECT_NE(result.message.find(fragment), std::string::npos)
        << "'" << fragment << "' not in: " << result.message;
  }
}

double decimal(std::string_view text) {
  double value = -1.0;
  EXPECT_TRUE(parse_wfdb_decimal(text, value)) << text;
  return value;
}

TEST(WfdbDecimal, IsTheCorrectlyRoundedValueOfTheText) {
  EXPECT_EQ(decimal("360"), 360.0);
  EXPECT_EQ(decimal("360.0"), 360.0);
  EXPECT_EQ(decimal("0"), 0.0);
  EXPECT_EQ(decimal("0.1"), 0.1);
  EXPECT_EQ(decimal("0.3"), 0.3);
  EXPECT_EQ(decimal("128.5"), 128.5);
  EXPECT_EQ(decimal("123.456"), 123.456);
  EXPECT_EQ(decimal("128.123456789"), 128.123456789);
  EXPECT_EQ(decimal("1000.5"), 1000.5);
  EXPECT_EQ(decimal("000000000000000000001"), 1.0);
  EXPECT_EQ(decimal("123456789012345"), 123456789012345.0);
  EXPECT_EQ(decimal("0.000000000000001"), 1e-15);
  EXPECT_EQ(decimal("99999999999999.9"), 99999999999999.9);
  EXPECT_EQ(decimal("0.123456789012345"), 0.123456789012345);
}

TEST(WfdbDecimal, RejectsEverythingOutsideTheGrammar) {
  for (const std::string_view text :
       {"", ".", "1.", ".5", "+1", "-1", "1e3", "1E3", "1.2.3", " 1", "1 ", "0x10", "inf", "nan",
        "1,5", "1234567890123456", "1000.000000000000", "0.0000000000000001",
        "12345678901234.56"}) {
    double value = -7.0;
    EXPECT_FALSE(parse_wfdb_decimal(text, value)) << "'" << text << "'";
    EXPECT_EQ(value, -7.0) << text;
  }
}

TEST(WfdbHeader, ReadsTheHeaderOfRecord100) {
  WfdbHeader header;
  const WfdbResult result = parse(kRecord100, header);
  ASSERT_TRUE(result.ok()) << result.message;
  EXPECT_TRUE(result.message.empty());
  EXPECT_EQ(header.record_name, "100");
  EXPECT_EQ(header.fs_millihertz, 360000U);
  EXPECT_EQ(header.fs_hz, 360.0);
  EXPECT_EQ(header.sample_count, 650000U);
  EXPECT_EQ(header.base_time, "0:0:0");
  EXPECT_EQ(header.base_date, "0/0/0");
  ASSERT_EQ(header.signals.size(), 2U);
  const auto& s0 = header.signals.at(0);
  EXPECT_EQ(s0.file_name, "100.dat");
  EXPECT_EQ(s0.format, WfdbFormat::kFormat212);
  EXPECT_EQ(s0.gain_adu_per_mv, 200.0);
  EXPECT_EQ(s0.gain_text, "200");
  EXPECT_EQ(s0.adc_zero_adu, 1024);
  EXPECT_EQ(s0.baseline_adu, 1024);
  EXPECT_EQ(s0.units, "mV");
  EXPECT_EQ(s0.initial_value_adu, 995);
  EXPECT_EQ(s0.checksum, -22131);
  EXPECT_EQ(s0.description, "MLII");
  EXPECT_EQ(header.signals.at(1).initial_value_adu, 1011);
  EXPECT_EQ(header.signals.at(1).checksum, 20052);
  EXPECT_EQ(header.signals.at(1).description, "V5");
  ASSERT_EQ(header.comments.size(), 2U);
  EXPECT_EQ(header.comments.at(0), "69 M 1085 1629 x1");
  EXPECT_EQ(header.comments.at(1), "Aldomet, Inderal");
}

TEST(WfdbHeader, AGainOfZeroOrNoGainMeans200) {
  for (const std::string_view gain : {"0", "0.0", "000"}) {
    WfdbHeader header;
    std::string line = "100.dat 212 ";
    line.append(gain).append(" 12 0 -61 -6457 0 noise1");
    ASSERT_TRUE(parse(signal_header(line), header).ok()) << gain;
    EXPECT_EQ(header.signals.at(0).gain_adu_per_mv, 200.0);
    EXPECT_EQ(header.signals.at(0).gain_text, "200");
    EXPECT_EQ(header.signals.at(0).description, "noise1");
  }
  WfdbHeader header;
  ASSERT_TRUE(parse(signal_header("100.dat 16"), header).ok());
  const auto& s0 = header.signals.at(0);
  EXPECT_EQ(s0.format, WfdbFormat::kFormat16);
  EXPECT_EQ(s0.gain_adu_per_mv, 200.0);
  EXPECT_EQ(s0.gain_text, "200");
  EXPECT_EQ(s0.units, "mV");
  EXPECT_EQ(s0.baseline_adu, 0);
  EXPECT_EQ(s0.adc_zero_adu, 0);
  EXPECT_FALSE(s0.initial_value_adu.has_value());
  EXPECT_FALSE(s0.checksum.has_value());
  EXPECT_EQ(s0.description, "");
  EXPECT_TRUE(header.base_time.empty());
  EXPECT_TRUE(header.base_date.empty());
}

TEST(WfdbHeader, GainBaselineAndUnitsAsWritten) {
  WfdbHeader header;
  ASSERT_TRUE(
      parse(signal_header("100.dat 16 1000.50(-12)/mV 16 3 -5 7 0 ECG lead II"), header).ok());
  const auto& s0 = header.signals.at(0);
  EXPECT_EQ(s0.gain_adu_per_mv, 1000.5);
  EXPECT_EQ(s0.gain_text, "1000.50");
  EXPECT_EQ(s0.baseline_adu, -12);
  EXPECT_EQ(s0.adc_zero_adu, 3);
  EXPECT_EQ(s0.initial_value_adu, -5);
  EXPECT_EQ(s0.checksum, 7);
  EXPECT_EQ(s0.description, "ECG lead II");
  // Units without a baseline, and a baseline without units.
  ASSERT_TRUE(parse(signal_header("100.dat 16 200/mV 12 9"), header).ok());
  EXPECT_EQ(header.signals.at(0).baseline_adu, 9);
  ASSERT_TRUE(parse(signal_header("100.dat 16 200(+4) 12 9"), header).ok());
  EXPECT_EQ(header.signals.at(0).baseline_adu, 4);
  EXPECT_EQ(header.signals.at(0).adc_zero_adu, 9);
  EXPECT_EQ(header.signals.at(0).units, "mV");
}

TEST(WfdbHeader, UnitsOfLaterSignalsAreKeptAsWritten) {
  WfdbHeader header;
  const std::string text = "100 2 360 10\n100.dat 16 200/mV\n100.dat 16 1000/\xC2\xB5V 0 0 0 0 0\n";
  ASSERT_TRUE(parse(text, header).ok());
  EXPECT_EQ(header.signals.at(1).units, "\xC2\xB5V");
}

TEST(WfdbHeader, Signal0UnitsMustBeMv) {
  expect_failure(signal_header("100.dat 16 200/uV"), WfdbStatus::kUnsupportedUnits,
                 {"signal units 'uV' are not mV"});
  expect_failure(signal_header("100.dat 16 1000(0)/\xC2\xB5V"), WfdbStatus::kUnsupportedUnits,
                 {"'\xC2\xB5V'"});
  expect_failure(signal_header("100.dat 16 200/mv"), WfdbStatus::kUnsupportedUnits, {"'mv'"});
}

TEST(WfdbHeader, LineEndsBlanksCommentsAndBlankLines) {
  const std::string text =
      "#  leading comment  \r\n"
      "\r\n"
      "  \t \n"
      "\t100\t 1  360.0 \t 20\r\n"
      "   # between\n"
      "#\n"
      "100.dat\t16 \t200\r\n"
      "# last";
  WfdbHeader header;
  const WfdbResult result = parse(text, header);
  ASSERT_TRUE(result.ok()) << result.message;
  EXPECT_EQ(header.fs_millihertz, 360000U);
  EXPECT_EQ(header.sample_count, 20U);
  ASSERT_EQ(header.comments.size(), 4U);
  EXPECT_EQ(header.comments.at(0), "leading comment  ");
  EXPECT_EQ(header.comments.at(1), "between");
  EXPECT_EQ(header.comments.at(2), "");
  EXPECT_EQ(header.comments.at(3), "last");
}

TEST(WfdbHeader, SamplingFrequencyInMillihertz) {
  WfdbHeader header;
  ASSERT_TRUE(parse(header_of("1 128.5 10", "100.dat 16"), header).ok());
  EXPECT_EQ(header.fs_millihertz, 128500U);
  EXPECT_EQ(header.fs_hz, 128.5);
  ASSERT_TRUE(parse(header_of("1 250.0010000 10", "100.dat 16"), header).ok());
  EXPECT_EQ(header.fs_millihertz, 250001U);
  EXPECT_EQ(header.fs_hz, 250.001);
  double value = 0.0;
  ASSERT_TRUE(parse_wfdb_decimal("250.0010000", value));
  EXPECT_EQ(header.fs_hz, value);
  ASSERT_TRUE(parse(header_of("1 125 10", "100.dat 16"), header).ok());
  EXPECT_EQ(header.fs_millihertz, 125000U);
  ASSERT_TRUE(parse(header_of("1 1000.000 10", "100.dat 16"), header).ok());
  EXPECT_EQ(header.fs_millihertz, 1000000U);
}

TEST(WfdbHeader, SamplingFrequencyOutsideTheSubset) {
  expect_failure(header_of("1 100 10", "100.dat 16"), WfdbStatus::kUnsupportedRecord,
                 {"sampling frequency 100 Hz (125 Hz to 1000 Hz only) is not supported"});
  expect_failure(header_of("1 124.999 10", "100.dat 16"), WfdbStatus::kUnsupportedRecord,
                 {"124.999 Hz"});
  expect_failure(header_of("1 1000.001 10", "100.dat 16"), WfdbStatus::kUnsupportedRecord,
                 {"1000.001 Hz"});
  expect_failure(header_of("1 0 10", "100.dat 16"), WfdbStatus::kUnsupportedRecord, {"0 Hz"});
  expect_failure(header_of("1 360.0005 10", "100.dat 16"), WfdbStatus::kUnsupportedRecord,
                 {"360.0005 Hz (a whole number of mHz only)"});
  expect_failure(header_of("1 360/2 10", "100.dat 16"), WfdbStatus::kUnsupportedRecord,
                 {"'360/2'", "is not supported"});
  expect_failure(header_of("1 360/2(5) 10", "100.dat 16"), WfdbStatus::kUnsupportedRecord, {});
  expect_failure(header_of("1 3.6e2 10", "100.dat 16"), WfdbStatus::kMalformedHeader,
                 {"header line 1 is not valid WFDB", "'3.6e2'"});
  expect_failure(header_of("1 -360 10", "100.dat 16"), WfdbStatus::kMalformedHeader, {"'-360'"});
  expect_failure("100 1\n100.dat 16\n", WfdbStatus::kMalformedHeader,
                 {"header line 1", "sampling frequency is missing"});
}

TEST(WfdbHeader, SampleCount) {
  WfdbHeader header;
  ASSERT_TRUE(parse(header_of("1 360 +5", "100.dat 16"), header).ok());
  EXPECT_EQ(header.sample_count, 5U);
  // 24 h exactly, at 360 Hz and at 128.5 Hz.
  ASSERT_TRUE(parse(header_of("1 360 31104000", "100.dat 16"), header).ok());
  ASSERT_TRUE(parse(header_of("1 128.5 11102400", "100.dat 16"), header).ok());
  expect_failure(header_of("1 360 31104001", "100.dat 16"), WfdbStatus::kTooLong,
                 {"100: the record is longer than 24 h"});
  expect_failure(header_of("1 128.5 11102401", "100.dat 16"), WfdbStatus::kTooLong, {});
  expect_failure(header_of("1 360 9223372036854775807", "100.dat 16"), WfdbStatus::kTooLong, {});
  expect_failure(header_of("1 360 0", "100.dat 16"), WfdbStatus::kEmptyRecord,
                 {"100: the record has 0 samples"});
  expect_failure(header_of("1 360 -0", "100.dat 16"), WfdbStatus::kEmptyRecord, {});
  expect_failure(header_of("1 360 -1", "100.dat 16"), WfdbStatus::kMalformedHeader, {"'-1'"});
  expect_failure(header_of("1 360 9223372036854775808", "100.dat 16"), WfdbStatus::kMalformedHeader,
                 {});
  expect_failure(header_of("1 360 99999999999999999999999", "100.dat 16"),
                 WfdbStatus::kMalformedHeader, {});
  expect_failure(header_of("1 360 1.5", "100.dat 16"), WfdbStatus::kMalformedHeader, {"'1.5'"});
  expect_failure("100 1 360\n100.dat 16\n", WfdbStatus::kMalformedHeader,
                 {"number of samples is missing"});
}

TEST(WfdbHeader, RecordNameAndSegments) {
  expect_failure(header_of("1 360 10", "100.dat 16").replace(0, 3, "101"),
                 WfdbStatus::kUnsupportedRecord,
                 {"record name '101' in the header is not supported"});
  expect_failure(header_of("1 360 10", "100.dat 16").replace(0, 3, "100/2"),
                 WfdbStatus::kUnsupportedRecord, {"multi-segment records is not supported"});
  WfdbHeader header;
  EXPECT_EQ(parse_wfdb_header("x 1 360 1\nx.dat 16\n", "100", header).status,
            WfdbStatus::kUnsupportedRecord);
}

TEST(WfdbHeader, NumberOfSignals) {
  expect_failure(header_of("0 360 10", "100.dat 16"), WfdbStatus::kMalformedHeader,
                 {"'0' is not an integer from 1 to 64"});
  expect_failure(header_of("65 360 10", "100.dat 16"), WfdbStatus::kMalformedHeader, {"'65'"});
  expect_failure(header_of("-1 360 10", "100.dat 16"), WfdbStatus::kMalformedHeader, {});
  expect_failure(header_of("x 360 10", "100.dat 16"), WfdbStatus::kMalformedHeader, {});
  expect_failure("100\n", WfdbStatus::kMalformedHeader, {"number of signals is missing"});
  std::string text = "100 64 360 10\n";
  for (int k = 0; k < 64; ++k) {
    text.append("100.dat 16 200 12 0 0 0 0 s").append(std::to_string(k)).append("\n");
  }
  WfdbHeader header;
  ASSERT_TRUE(parse(text, header).ok());
  ASSERT_EQ(header.signals.size(), 64U);
  EXPECT_EQ(header.signals.at(63).description, "s63");
}

TEST(WfdbHeader, ExactlyNsigSignalLines) {
  expect_failure("100 2 360 10\n100.dat 16\n# c\n", WfdbStatus::kMalformedHeader,
                 {"header line 4 is not valid WFDB", "2 signal lines are needed, 1 are given"});
  expect_failure("100 2 360 10\n100.dat 16\n# c", WfdbStatus::kMalformedHeader,
                 {"header line 4 is not valid WFDB"});
  expect_failure("100 1 360 10\n100.dat 16\n\n100.dat 16\n", WfdbStatus::kMalformedHeader,
                 {"header line 4 is not valid WFDB", "more signal lines than the 1"});
}

TEST(WfdbHeader, NoRecordLine) {
  expect_failure("", WfdbStatus::kMalformedHeader,
                 {"header line 1 is not valid WFDB: there is no record line"});
  expect_failure("# only\n\n", WfdbStatus::kMalformedHeader, {"header line 3", "no record line"});
}

TEST(WfdbHeader, ExtraFieldOnTheRecordLine) {
  expect_failure(header_of("1 360 10 0:0:0 0/0/0 x", "100.dat 16"), WfdbStatus::kMalformedHeader,
                 {"header line 1", "'x'"});
  WfdbHeader header;
  ASSERT_TRUE(parse(header_of("1 360 10 10:20:30", "100.dat 16"), header).ok());
  EXPECT_EQ(header.base_time, "10:20:30");
  EXPECT_TRUE(header.base_date.empty());
}

TEST(WfdbHeader, SignalFileName) {
  for (const std::string_view name :
       {"../100.dat", "dir/100.dat", "dir\\100.dat", "-", ".100.dat", "100 dat", "C:100.dat"}) {
    std::string line(name);
    line.append(" 16");
    WfdbHeader header;
    const WfdbResult result = parse(signal_header(line), header);
    // "100 dat" splits into the file "100" and the format "dat".
    EXPECT_EQ(result.status, WfdbStatus::kMalformedHeader) << name << ": " << result.message;
  }
  WfdbHeader header;
  ASSERT_TRUE(parse(signal_header("a_b-c+d.e 16"), header).ok());
  EXPECT_EQ(header.signals.at(0).file_name, "a_b-c+d.e");
  expect_failure("100 2 360 10\n100.dat 16\n101.dat 16\n", WfdbStatus::kUnsupportedRecord,
                 {"signals in several files is not supported"});
}

TEST(WfdbHeader, SignalFormat) {
  expect_failure(signal_header("100.dat 80"), WfdbStatus::kUnsupportedFormat,
                 {"100: signal format 80 is not supported (formats 16 and 212 only)"});
  expect_failure(signal_header("100.dat 016"), WfdbStatus::kUnsupportedFormat, {"format 016"});
  expect_failure(signal_header("100.dat 310"), WfdbStatus::kUnsupportedFormat, {"310"});
  for (const std::string_view format : {"212x2", "16:1", "16+24", "212x2:1+3"}) {
    std::string line = "100.dat ";
    line.append(format);
    expect_failure(signal_header(line), WfdbStatus::kUnsupportedRecord, {"is not supported"});
  }
  for (const std::string_view format : {"x16", "16a", "-16", "+16"}) {
    std::string line = "100.dat ";
    line.append(format);
    expect_failure(signal_header(line), WfdbStatus::kMalformedHeader, {"header line 2"});
  }
  expect_failure("100 1 360 10\n100.dat\n", WfdbStatus::kMalformedHeader,
                 {"header line 2", "signal format is missing"});
  expect_failure("100 2 360 10\n100.dat 16\n100.dat 212\n", WfdbStatus::kUnsupportedRecord,
                 {"signals in several formats"});
}

TEST(WfdbHeader, MalformedGainField) {
  for (const std::string_view gain :
       {"-200", "+200", "2e2", "200(", "200(abc)", "200(1", "200)", "200/", "200(0)x", "(0)", "/mV",
        "200(0)(1)", "200(1.5)", "200(2147483648)", ".5", "200.", "200(0)/"}) {
    std::string line = "100.dat 16 ";
    line.append(gain);
    expect_failure(signal_header(line), WfdbStatus::kMalformedHeader, {"header line 2"});
  }
  WfdbHeader header;
  ASSERT_TRUE(parse(signal_header("100.dat 16 200(-2147483648)"), header).ok());
  EXPECT_EQ(header.signals.at(0).baseline_adu, -2147483648LL);
}

TEST(WfdbHeader, IntegerFieldsOfTheSignalLine) {
  for (const std::string_view fields :
       {"x", "11 1.5", "11 0 2147483648", "11 0 0 -2147483649", "11 0 0 0 x", "11 0 0 0 +"}) {
    std::string line = "100.dat 16 200 ";
    line.append(fields);
    expect_failure(signal_header(line), WfdbStatus::kMalformedHeader, {"header line 2"});
  }
  WfdbHeader header;
  ASSERT_TRUE(parse(signal_header("100.dat 16 200 11 0 2147483647 -2147483648 -0"), header).ok());
  EXPECT_EQ(header.signals.at(0).initial_value_adu, 2147483647);
  EXPECT_EQ(header.signals.at(0).checksum, -2147483648LL);
  expect_failure(signal_header("100.dat 16 200 11 0 0 0 512"), WfdbStatus::kUnsupportedRecord,
                 {"block size 512 is not supported"});
  expect_failure(signal_header("100.dat 16 200 11 0 0 0 1 MLII"), WfdbStatus::kUnsupportedRecord,
                 {});
}

TEST(WfdbHeader, NulByteAndSize) {
  std::string text(kRecord100);
  text.replace(text.find("MLII"), 1, std::string(1, '\0'));
  expect_failure(text, WfdbStatus::kMalformedHeader, {"header line 2", "NUL"});
  // The largest text accepted, then one byte more.
  std::string large = signal_header("100.dat 16");
  large.append("#");
  large.append(kWfdbHeaderMaxBytes - large.size(), 'c');
  ASSERT_EQ(large.size(), kWfdbHeaderMaxBytes);
  WfdbHeader header;
  ASSERT_TRUE(parse(large, header).ok());
  large.push_back('c');
  expect_failure(large, WfdbStatus::kMalformedHeader, {"header line 1", "1 MiB"});
}

TEST(WfdbHeader, OtherBytesAreAcceptedInDescriptionsAndComments) {
  WfdbHeader header;
  const std::string text = "100 1 360 10\n100.dat 16 200 12 0 0 0 0 d\xE9riv\xC3\xA9\n# \xFF\x01\n";
  ASSERT_TRUE(parse(text, header).ok());
  EXPECT_EQ(header.signals.at(0).description, "d\xE9riv\xC3\xA9");
  EXPECT_EQ(header.comments.at(0), "\xFF\x01");
}

}  // namespace
