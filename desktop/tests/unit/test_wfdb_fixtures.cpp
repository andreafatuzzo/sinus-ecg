// Developer's unit tests of the WFDB reader on the fixtures written with Python wfdb
// (architecture-m3.md 17.8): each readable record equals its .expected file exactly, and each
// rejection record has the status of rejections.txt.

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "core/mains.hpp"
#include "core/recording_metadata.hpp"
#include "core/sha256.hpp"
#include "core/wfdb_reader.hpp"
#include "core/wfdb_status.hpp"
#include "wfdb_status_name.hpp"

namespace {

using sinus::desktop::core::MainsFrequency;
using sinus::desktop::core::parse_recording_comments;
using sinus::desktop::core::read_wfdb_record;
using sinus::desktop::core::RecordingEvent;
using sinus::desktop::core::RecordingEventKind;
using sinus::desktop::core::RecordingMetadata;
using sinus::desktop::core::RecordingSource;
using sinus::desktop::core::Sha256;
using sinus::desktop::core::to_hex;
using sinus::desktop::core::WfdbRecord;
using sinus::desktop::core::WfdbResult;
using sinus::desktop::core::WfdbStatus;
using sinus::desktop::test::wfdb_status_name;

const std::filesystem::path kFixtures =
    std::filesystem::path(SINUS_DESKTOP_TEST_REPO_ROOT) / "desktop" / "tests" / "fixtures" / "wfdb";

std::vector<std::string> lines_of(const std::filesystem::path& path) {
  std::ifstream file(path, std::ios::binary);
  std::vector<std::string> lines;
  std::string line;
  while (std::getline(file, line)) {
    lines.push_back(line);
  }
  return lines;
}

std::string value_of(const std::string& line, const std::string& key) {
  EXPECT_EQ(line.rfind(key + "=", 0), 0U) << line;
  return line.substr(key.size() + 1);
}

std::string hex_bits(std::uint64_t bits, int digits) {
  std::string text(static_cast<std::size_t>(digits), '0');
  for (int k = digits - 1; k >= 0; --k) {
    text.at(static_cast<std::size_t>(k)) = "0123456789abcdef"[bits & 0xFU];
    bits >>= 4U;
  }
  return text;
}

std::string sha256_binary32(const WfdbRecord& record) {
  Sha256 hash;
  for (std::size_t i = 0; i < record.signal0_adu.size(); ++i) {
    const float value = record.sample_mv(i);
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    for (unsigned k = 0; k < 4; ++k) {
      const auto byte = static_cast<std::uint8_t>((bits >> (8U * k)) & 0xFFU);
      hash.update(&byte, 1);
    }
  }
  return to_hex(hash.finish());
}

void check_expected(const std::filesystem::path& expected_path) {
  const std::vector<std::string> lines = lines_of(expected_path);
  ASSERT_GE(lines.size(), 5U) << expected_path;
  const std::string name = value_of(lines.at(0), "record");
  SCOPED_TRACE(name);
  WfdbRecord record;
  const WfdbResult result = read_wfdb_record(kFixtures / name, record);
  ASSERT_TRUE(result.ok()) << result.message;
  EXPECT_EQ(std::to_string(record.header.fs_millihertz), value_of(lines.at(1), "fs_millihertz"));
  EXPECT_EQ(std::to_string(record.signal0_adu.size()), value_of(lines.at(2), "sample_count"));
  EXPECT_EQ(sha256_binary32(record), value_of(lines.at(3), "sha256_binary32"));
  const std::size_t rows = std::stoul(value_of(lines.at(4), "rows"));
  ASSERT_EQ(lines.size(), 5U + rows);
  for (std::size_t i = 0; i < rows; ++i) {
    std::istringstream row(lines.at(5 + i));
    int adu = 0;
    std::string bits64;
    std::string bits32;
    row >> adu >> bits64 >> bits32;
    EXPECT_EQ(record.signal0_adu.at(i), adu) << i;
    const double physical = record.physical_mv(i);
    const float sample = record.sample_mv(i);
    std::uint64_t physical_bits = 0;
    std::uint32_t sample_bits = 0;
    std::memcpy(&physical_bits, &physical, sizeof(physical_bits));
    std::memcpy(&sample_bits, &sample, sizeof(sample_bits));
    EXPECT_EQ(hex_bits(physical_bits, 16), bits64) << i;
    EXPECT_EQ(hex_bits(sample_bits, 8), bits32) << i;
  }
}

TEST(WfdbFixtures, ReadableRecordsEqualTheirExpectedFiles) {
  std::size_t count = 0;
  for (const auto& entry : std::filesystem::directory_iterator(kFixtures)) {
    if (entry.path().extension() == ".expected") {
      check_expected(entry.path());
      ++count;
    }
  }
  EXPECT_EQ(count, 11U);
}

TEST(WfdbFixtures, RejectionRecordsHaveTheirStatus) {
  const std::vector<std::string> lines = lines_of(kFixtures / "rejections.txt");
  EXPECT_EQ(lines.size(), 16U);
  for (const std::string& line : lines) {
    const std::size_t space = line.find(' ');
    ASSERT_NE(space, std::string::npos) << line;
    const std::string name = line.substr(0, space);
    WfdbRecord record;
    WfdbResult result = read_wfdb_record(kFixtures / name, record);
    if (result.ok()) {
      bool has_recording = false;
      RecordingMetadata metadata;
      std::vector<RecordingEvent> events;
      result = parse_recording_comments(record.header, has_recording, metadata, events);
    }
    EXPECT_EQ(wfdb_status_name(result.status), line.substr(space + 1)) << result.message;
    EXPECT_EQ(result.message.rfind(name + ": ", 0), 0U) << result.message;
  }
}

TEST(WfdbFixtures, SessionGapIsARecordingWithItsEvents) {
  WfdbRecord record;
  ASSERT_TRUE(read_wfdb_record(kFixtures / "session_gap", record).ok());
  bool has_recording = false;
  RecordingMetadata metadata;
  std::vector<RecordingEvent> events;
  ASSERT_TRUE(parse_recording_comments(record.header, has_recording, metadata, events).ok());
  EXPECT_TRUE(has_recording);
  EXPECT_EQ(metadata.source, RecordingSource::kTest);
  EXPECT_EQ(metadata.mains, MainsFrequency::k60Hz);
  ASSERT_EQ(events.size(), 2U);
  EXPECT_EQ(events.at(0).kind, RecordingEventKind::kGap);
  EXPECT_EQ(events.at(0).at_sample, 3600U);
  EXPECT_EQ(events.at(0).missing_samples, 1080U);
  EXPECT_EQ(events.at(1).kind, RecordingEventKind::kInterruption);
  EXPECT_EQ(events.at(1).at_sample, 5400U);
  EXPECT_EQ(events.at(1).duration_ms, 1500U);
  // The other records are no recordings.
  ASSERT_TRUE(read_wfdb_record(kFixtures / "replay16", record).ok());
  ASSERT_TRUE(parse_recording_comments(record.header, has_recording, metadata, events).ok());
  EXPECT_FALSE(has_recording);
}

}  // namespace
