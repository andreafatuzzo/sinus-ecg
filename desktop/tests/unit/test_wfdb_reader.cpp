// Developer's unit tests of the WFDB record reader: formats 16 and 212, the checks of signal 0 and
// the physical values (architecture-m3.md 17.4, 17.5).

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <initializer_list>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include "core/wfdb_header.hpp"
#include "core/wfdb_reader.hpp"
#include "core/wfdb_status.hpp"
#include "temp_folder.hpp"

namespace {

using sinus::desktop::core::kWfdbHeaderMaxBytes;
using sinus::desktop::core::read_wfdb_record;
using sinus::desktop::core::WfdbRecord;
using sinus::desktop::core::WfdbResult;
using sinus::desktop::core::WfdbStatus;
using sinus::desktop::test::TempFolder;

// Format 16: little-endian two's complement.
std::vector<std::uint8_t> format16(const std::vector<int>& values) {
  std::vector<std::uint8_t> bytes;
  for (const int value : values) {
    const auto word = static_cast<std::uint16_t>(value);
    bytes.push_back(static_cast<std::uint8_t>(word & 0xFFU));
    bytes.push_back(static_cast<std::uint8_t>(word >> 8U));
  }
  return bytes;
}

// Format 212: pairs of 12-bit values in 3 bytes; an odd last value takes 2 bytes.
std::vector<std::uint8_t> format212(const std::vector<int>& values) {
  std::vector<std::uint8_t> bytes;
  for (std::size_t j = 0; j < values.size(); j += 2) {
    const auto even = static_cast<unsigned>(values.at(j)) & 0xFFFU;
    bytes.push_back(static_cast<std::uint8_t>(even & 0xFFU));
    if (j + 1 == values.size()) {
      bytes.push_back(static_cast<std::uint8_t>(even >> 8U));
      break;
    }
    const auto odd = static_cast<unsigned>(values.at(j + 1)) & 0xFFFU;
    bytes.push_back(static_cast<std::uint8_t>((even >> 8U) | ((odd >> 8U) << 4U)));
    bytes.push_back(static_cast<std::uint8_t>(odd & 0xFFU));
  }
  return bytes;
}

// The WFDB checksum: the sum modulo 2^16 as a signed 16-bit number.
int checksum_of(const std::vector<int>& values) {
  int sum = 0;
  for (const int value : values) {
    sum = (sum + value + 65536) % 65536;
  }
  return sum >= 32768 ? sum - 65536 : sum;
}

// Values of signal 0 in an interleaved list of nsig signals.
std::vector<int> signal0_of(const std::vector<int>& values, std::size_t nsig) {
  std::vector<int> out;
  for (std::size_t j = 0; j < values.size(); j += nsig) {
    out.push_back(values.at(j));
  }
  return out;
}

std::string header_text(std::size_t nsig, std::size_t nsamp, std::string_view format,
                        std::string_view gain_field, const std::vector<int>& signal0) {
  std::string text = "100 ";
  text.append(std::to_string(nsig)).append(" 360 ").append(std::to_string(nsamp)).append("\n");
  for (std::size_t s = 0; s < nsig; ++s) {
    text.append("100.dat ").append(format).append(" ").append(gain_field).append(" 12 0");
    if (s == 0) {
      text.append(" ").append(std::to_string(signal0.front()));
      text.append(" ").append(std::to_string(checksum_of(signal0)));
    } else {
      text.append(" 0 0");
    }
    text.append(" 0 sig").append(std::to_string(s)).append("\n");
  }
  return text;
}

struct Written {
  std::vector<int> signal0;
};

// Writes record 100 with `values` stored interleaved for nsig signals, with a valid initial value
// and checksum of signal 0.
Written write_record(const TempFolder& folder, std::size_t nsig, std::string_view format,
                     std::string_view gain_field, const std::vector<int>& values) {
  Written written{signal0_of(values, nsig)};
  folder.write("100.hea",
               header_text(nsig, values.size() / nsig, format, gain_field, written.signal0));
  folder.write("100.dat", format == "16" ? format16(values) : format212(values));
  return written;
}

WfdbResult read(const TempFolder& folder, WfdbRecord& record) {
  return read_wfdb_record(folder.path() / "100", record);
}

void expect_failure(const WfdbResult& result, WfdbStatus status,
                    std::initializer_list<std::string_view> fragments) {
  EXPECT_EQ(result.status, status) << result.message;
  EXPECT_EQ(result.message.rfind("100: ", 0), 0U) << result.message;
  for (const std::string_view fragment : fragments) {
    EXPECT_NE(result.message.find(fragment), std::string::npos)
        << "'" << fragment << "' not in: " << result.message;
  }
}

void expect_signal0(const WfdbRecord& record, const std::vector<int>& expected) {
  ASSERT_EQ(record.signal0_adu.size(), expected.size());
  for (std::size_t i = 0; i < expected.size(); ++i) {
    ASSERT_EQ(record.signal0_adu.at(i), expected.at(i)) << i;
  }
}

std::vector<int> pattern(std::size_t count, int low, int high) {
  std::vector<int> values(count);
  std::uint32_t state = 7U;
  const auto span = static_cast<std::uint32_t>(high - low + 1);
  for (int& value : values) {
    state = (state * 1664525U) + 1013904223U;
    value = low + static_cast<int>((state >> 8U) % span);
  }
  return values;
}

TEST(WfdbReader, Format16OneSignal) {
  const TempFolder folder;
  const std::vector<int> values{0, 1, -1, 32767, -32767, 100, -200};
  write_record(folder, 1, "16", "200", values);
  WfdbRecord record;
  const WfdbResult result = read(folder, record);
  ASSERT_TRUE(result.ok()) << result.message;
  EXPECT_TRUE(result.message.empty());
  EXPECT_EQ(record.header.record_name, "100");
  EXPECT_EQ(record.header.sample_count, values.size());
  expect_signal0(record, values);
  EXPECT_EQ(record.physical_mv(5), 0.5);
  EXPECT_EQ(record.physical_mv(6), -1.0);
  EXPECT_EQ(record.sample_mv(3), static_cast<float>(32767.0 / 200.0));
}

// The bytes that wfdb 4.3.1 writes for -2047, 5, 2047 (architecture-m3.md 17.4).
TEST(WfdbReader, Format212OddCountFromWfdb) {
  const TempFolder folder;
  folder.write("100.hea", std::string_view("100 1 360 3\n100.dat 212 200 12 0 -2047 5 0 x\n"));
  folder.write("100.dat", std::vector<std::uint8_t>{0x01, 0x08, 0x05, 0xFF, 0x07});
  WfdbRecord record;
  const WfdbResult result = read(folder, record);
  ASSERT_TRUE(result.ok()) << result.message;
  expect_signal0(record, {-2047, 5, 2047});
}

TEST(WfdbReader, OnlySignal0IsKeptForEveryFormatAndSignalCount) {
  for (const std::string_view format : {"16", "212"}) {
    for (const std::size_t nsig : {1U, 2U, 3U, 5U}) {
      for (const std::size_t nsamp : {1U, 2U, 3U, 7U}) {
        const TempFolder folder;
        const std::vector<int> values = pattern(nsig * nsamp, -2047, 2047);
        const Written written = write_record(folder, nsig, format, "200", values);
        WfdbRecord record;
        const WfdbResult result = read(folder, record);
        ASSERT_TRUE(result.ok()) << format << " " << nsig << " " << nsamp << ": " << result.message;
        expect_signal0(record, written.signal0);
        EXPECT_EQ(record.header.signals.size(), nsig);
      }
    }
  }
}

// Records larger than the read block of 1 MiB.
TEST(WfdbReader, RecordsLargerThanOneBlock) {
  {
    const TempFolder folder;
    const std::vector<int> values = pattern(1'000'001, -2047, 2047);  // 1.5 MB, T odd
    const Written written = write_record(folder, 1, "212", "200", values);
    WfdbRecord record;
    const WfdbResult result = read(folder, record);
    ASSERT_TRUE(result.ok()) << result.message;
    expect_signal0(record, written.signal0);
  }
  {
    const TempFolder folder;
    const std::vector<int> values = pattern(600'002, -32767, 32767);  // 1.2 MB, 2 signals
    const Written written = write_record(folder, 2, "16", "1000", values);
    WfdbRecord record;
    const WfdbResult result = read(folder, record);
    ASSERT_TRUE(result.ok()) << result.message;
    expect_signal0(record, written.signal0);
  }
}

TEST(WfdbReader, PhysicalValuesUseBaselineAndGain) {
  const TempFolder folder;
  const std::vector<int> values{-12, 0, 1000, -1013, 7};
  folder.write("100.hea", "100 1 360 5\n100.dat 16 1000.5(-12)/mV 16 3 -12 " +
                              std::to_string(checksum_of(values)) + " 0 ECG\n");
  folder.write("100.dat", format16(values));
  WfdbRecord record;
  const WfdbResult result = read(folder, record);
  ASSERT_TRUE(result.ok()) << result.message;
  for (std::size_t i = 0; i < values.size(); ++i) {
    const double expected = (static_cast<double>(values.at(i)) + 12.0) / 1000.5;
    EXPECT_EQ(record.physical_mv(i), expected) << i;
    EXPECT_EQ(record.sample_mv(i), static_cast<float>(expected)) << i;
  }
  EXPECT_EQ(record.physical_mv(0), 0.0);
}

TEST(WfdbReader, BaselineDefaultsToAdcZeroAndGainZeroTo200) {
  const TempFolder folder;
  const std::vector<int> values{1024, 1224, 824};
  folder.write("100.hea", "100 1 360 3\n100.dat 212 0 12 1024 1024 " +
                              std::to_string(checksum_of(values)) + " 0 noise\n");
  folder.write("100.dat", format212(values));
  WfdbRecord record;
  ASSERT_TRUE(read(folder, record).ok());
  EXPECT_EQ(record.physical_mv(0), 0.0);
  EXPECT_EQ(record.physical_mv(1), 1.0);
  EXPECT_EQ(record.physical_mv(2), -1.0);
}

TEST(WfdbReader, FurtherBytesAreIgnored) {
  const TempFolder folder;
  const std::vector<int> values{1, 2, 3};
  write_record(folder, 1, "16", "200", values);
  std::vector<std::uint8_t> bytes = format16(values);
  bytes.push_back(0x80);
  bytes.push_back(0x00);
  bytes.push_back(0x7F);
  folder.write("100.dat", bytes);
  WfdbRecord record;
  ASSERT_TRUE(read(folder, record).ok());
  expect_signal0(record, values);
}

TEST(WfdbReader, TruncatedSignalFile) {
  {
    const TempFolder folder;
    write_record(folder, 1, "16", "200", {1, 2, 3});
    folder.write("100.dat", format16({1, 2}));
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kTruncatedSignal,
                   {"100: the signal file 100.dat has 4 bytes, 6 are needed"});
  }
  {
    const TempFolder folder;
    write_record(folder, 1, "212", "200", {1, 2, 3});
    folder.write("100.dat", std::vector<std::uint8_t>{0x01, 0x20, 0x00, 0x03});
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kTruncatedSignal,
                   {"has 4 bytes, 5 are needed"});
  }
  {
    // Two signals of 2 samples in format 212: 4 values, 6 bytes.
    const TempFolder folder;
    write_record(folder, 2, "212", "200", {1, 2, 3, 4});
    folder.write("100.dat", std::string_view("\x01\x20\x00\x03\x40", 5));
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kTruncatedSignal,
                   {"has 5 bytes, 6 are needed"});
  }
}

TEST(WfdbReader, FilesThatCannotBeRead) {
  {
    const TempFolder folder;
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kCannotRead, {"100: cannot read 100.hea"});
  }
  {
    const TempFolder folder;
    write_record(folder, 1, "16", "200", {1, 2, 3});
    std::error_code error;
    std::filesystem::remove(folder.path() / "100.dat", error);
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kCannotRead, {"100: cannot read 100.dat"});
  }
  {
    const TempFolder folder;
    std::error_code error;
    std::filesystem::create_directory(folder.path() / "100.hea", error);
    ASSERT_FALSE(error);
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kCannotRead, {"cannot read 100.hea"});
  }
}

TEST(WfdbReader, HeaderFailuresArePassedOn) {
  const TempFolder folder;
  folder.write("100.hea", std::string_view("100 1 360 3\n100.dat 80\n"));
  WfdbRecord record;
  expect_failure(read(folder, record), WfdbStatus::kUnsupportedFormat, {"format 80"});
  folder.write("100.hea", std::string_view("101 1 360 3\n100.dat 16\n"));
  expect_failure(read(folder, record), WfdbStatus::kUnsupportedRecord, {"'101'"});
  std::string large = "100 1 360 3\n100.dat 16\n#";
  large.append(kWfdbHeaderMaxBytes, 'c');
  folder.write("100.hea", large);
  expect_failure(read(folder, record), WfdbStatus::kMalformedHeader, {"1 MiB"});
}

TEST(WfdbReader, TheRecordNameIsTheStemOfThePath) {
  const TempFolder folder;
  folder.write("rec_7.hea", std::string_view("rec_7 1 360 2\nrec_7.dat 16 200\n"));
  folder.write("rec_7.dat", format16({4, 5}));
  WfdbRecord record;
  const WfdbResult result = read_wfdb_record(folder.path() / "rec_7", record);
  ASSERT_TRUE(result.ok()) << result.message;
  EXPECT_EQ(record.header.record_name, "rec_7");
  expect_signal0(record, {4, 5});
}

TEST(WfdbReader, InvalidSampleCode) {
  {
    const TempFolder folder;
    write_record(folder, 1, "16", "200", {1, 2, -32768, 3, -32768});
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kInvalidSampleValue,
                   {"100: sample 2 holds the WFDB invalid-sample code"});
  }
  {
    const TempFolder folder;
    write_record(folder, 1, "212", "200", {1, -2048, 3});
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kInvalidSampleValue, {"sample 1 holds"});
  }
  {
    // -2048 is a valid value in format 16; the invalid code of signal 1 is not checked.
    const TempFolder folder;
    write_record(folder, 2, "16", "200", {-2048, -32768, 5, -32768});
    WfdbRecord record;
    ASSERT_TRUE(read(folder, record).ok());
    expect_signal0(record, {-2048, 5});
  }
  {
    // The invalid code is reported before a checksum mismatch.
    const TempFolder folder;
    folder.write("100.hea", std::string_view("100 1 360 2\n100.dat 16 200 12 0 9 9 0\n"));
    folder.write("100.dat", format16({1, -32768}));
    WfdbRecord record;
    expect_failure(read(folder, record), WfdbStatus::kInvalidSampleValue, {"sample 1"});
  }
}

TEST(WfdbReader, InitialValueAndChecksum) {
  const std::vector<int> values{30000, 30000, -5, 7};
  const int checksum = checksum_of(values);
  ASSERT_EQ(checksum, -5534);  // 60002 modulo 2^16, as a signed 16-bit number
  const auto header = [](std::string_view initial, std::string_view sum) {
    std::string text = "100 1 360 4\n100.dat 16 200 16 0 ";
    text.append(initial).append(" ").append(sum).append(" 0\n");
    return text;
  };
  const TempFolder folder;
  folder.write("100.dat", format16(values));
  WfdbRecord record;
  folder.write("100.hea", header("30000", std::to_string(checksum)));
  ASSERT_TRUE(read(folder, record).ok());
  folder.write("100.hea", header("29999", std::to_string(checksum)));
  expect_failure(
      read(folder, record), WfdbStatus::kChecksumMismatch,
      {"100: the samples do not match the checksum (or the initial value) in the header"});
  folder.write("100.hea", header("30000", std::to_string(checksum + 1)));
  expect_failure(read(folder, record), WfdbStatus::kChecksumMismatch, {});
  // The unsigned form of the sum is not the WFDB checksum.
  folder.write("100.hea", header("30000", std::to_string(checksum + 65536)));
  expect_failure(read(folder, record), WfdbStatus::kChecksumMismatch, {});
  // Neither given: nothing to check.
  folder.write("100.hea", std::string_view("100 1 360 4\n100.dat 16 200\n"));
  ASSERT_TRUE(read(folder, record).ok());
  // The initial value alone.
  folder.write("100.hea", std::string_view("100 1 360 4\n100.dat 16 200 16 0 1\n"));
  expect_failure(read(folder, record), WfdbStatus::kChecksumMismatch, {});
}

TEST(WfdbReader, SampleOutOfRange) {
  const auto header = [](const std::vector<int>& values) {
    std::string text = "100 1 360 ";
    text.append(std::to_string(values.size())).append("\n100.dat 16 1 16 0 ");
    text.append(std::to_string(values.front())).append(" ");
    text.append(std::to_string(checksum_of(values))).append(" 0\n");
    return text;
  };
  const TempFolder folder;
  WfdbRecord record;
  const std::vector<int> at_limit{1000, -1000, 0};
  folder.write("100.hea", header(at_limit));
  folder.write("100.dat", format16(at_limit));
  ASSERT_TRUE(read(folder, record).ok());
  const std::vector<int> beyond{0, 1000, 1001, -1001};
  folder.write("100.hea", header(beyond));
  folder.write("100.dat", format16(beyond));
  expect_failure(read(folder, record), WfdbStatus::kSampleOutOfRange,
                 {"100: sample 2 is 1001 mV, beyond 1000 mV"});
  const std::vector<int> negative{0, -1001};
  folder.write("100.hea", header(negative));
  folder.write("100.dat", format16(negative));
  expect_failure(read(folder, record), WfdbStatus::kSampleOutOfRange, {"sample 1 is -1001 mV"});
  // A fractional value is printed in its shortest form.
  folder.write("100.hea", std::string_view("100 1 360 1\n100.dat 16 2(0) 16 0 2001 2001 0\n"));
  folder.write("100.dat", format16({2001}));
  expect_failure(read(folder, record), WfdbStatus::kSampleOutOfRange, {"is 1000.5 mV"});
  // The checksum is checked before the range.
  folder.write("100.hea", std::string_view("100 1 360 1\n100.dat 16 1 16 0 2001 0 0\n"));
  expect_failure(read(folder, record), WfdbStatus::kChecksumMismatch, {});
}

}  // namespace
