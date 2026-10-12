// Developer's unit tests of the recording writer (architecture-m3.md 17.6), and the C++ half of
// the cross-check with the offline loader (17.8, check 4: WfdbRecordingWriterCrossCheck).

#include <gtest/gtest.h>

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#include "core/mains.hpp"
#include "core/recording_metadata.hpp"
#include "core/wfdb_reader.hpp"
#include "core/wfdb_status.hpp"
#include "core/wfdb_writer.hpp"
#include "temp_folder.hpp"

namespace {

using sinus::desktop::core::kMaxMissingSamples;
using sinus::desktop::core::kMaxRecordingEvents;
using sinus::desktop::core::MainsFrequency;
using sinus::desktop::core::parse_recording_comments;
using sinus::desktop::core::read_wfdb_record;
using sinus::desktop::core::RecordingEvent;
using sinus::desktop::core::RecordingEventKind;
using sinus::desktop::core::RecordingFormat;
using sinus::desktop::core::RecordingMetadata;
using sinus::desktop::core::RecordingSource;
using sinus::desktop::core::WfdbRecord;
using sinus::desktop::core::WfdbRecordingWriter;
using sinus::desktop::core::WfdbResult;
using sinus::desktop::core::WfdbStatus;
using sinus::desktop::test::TempFolder;

const std::filesystem::path kFixtures =
    std::filesystem::path(SINUS_DESKTOP_TEST_REPO_ROOT) / "desktop" / "tests" / "fixtures" / "wfdb";

RecordingFormat test_format(std::uint32_t fs_millihertz = 360000) {
  RecordingFormat format;
  format.fs_millihertz = fs_millihertz;
  format.gain_text = "1000";
  format.gain_adu_per_mv = 1000.0;
  format.baseline_adu = 0;
  return format;
}

RecordingMetadata test_metadata() {
  RecordingMetadata metadata;
  metadata.start_utc = "2026-10-11T10:20:30.123Z";
  metadata.source = RecordingSource::kTest;
  metadata.source_name = "127.0.0.1:45000";
  metadata.mains = MainsFrequency::k60Hz;
  metadata.desktop_version = "0.3.0.dev0";
  metadata.desktop_source_sha256 =
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
  metadata.library_version = "0.3.0.dev0";
  metadata.library_source_sha256 =
      "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210";
  return metadata;
}

std::string file_bytes(const std::filesystem::path& path) {
  std::ifstream file(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

bool file_exists(const std::filesystem::path& path) {
  std::error_code error;
  return std::filesystem::exists(path, error);
}

WfdbRecord read_back(const std::filesystem::path& record_path) {
  WfdbRecord record;
  const WfdbResult result = read_wfdb_record(record_path, record);
  EXPECT_TRUE(result.ok()) << result.message;
  return record;
}

TEST(WfdbRecordingWriter, WritesARecordThatTheReaderReads) {
  const TempFolder folder;
  WfdbRecordingWriter writer;
  ASSERT_TRUE(writer.open(folder.path(), "rec_1", test_format(), test_metadata()).ok());
  EXPECT_TRUE(file_exists(folder.path() / "rec_1.dat.partial"));
  const std::vector<float> samples{0.0F, 1.5F, -1.5F, 32.767F, -32.767F, 0.0004F, 0.0005F};
  ASSERT_TRUE(writer.append(samples.data(), 3).ok());
  ASSERT_TRUE(writer.add_event(RecordingEventKind::kGap, 12, 99).ok());
  ASSERT_TRUE(writer.append(samples.data() + 3, 4).ok());
  EXPECT_EQ(writer.sample_count(), 7U);
  ASSERT_TRUE(writer.finish().ok());
  EXPECT_FALSE(file_exists(folder.path() / "rec_1.dat.partial"));
  EXPECT_FALSE(file_exists(folder.path() / "rec_1.hea.partial"));

  const WfdbRecord record = read_back(folder.path() / "rec_1");
  const std::vector<std::int16_t> expected{0, 1500, -1500, 32767, -32767, 0, 1};
  EXPECT_EQ(record.signal0_adu, expected);
  EXPECT_EQ(record.header.fs_millihertz, 360000U);
  EXPECT_EQ(record.header.signals.front().gain_text, "1000");
  bool has_recording = false;
  RecordingMetadata metadata;
  std::vector<RecordingEvent> events;
  ASSERT_TRUE(parse_recording_comments(record.header, has_recording, metadata, events).ok());
  EXPECT_TRUE(has_recording);
  EXPECT_EQ(metadata.mains, MainsFrequency::k60Hz);
  ASSERT_EQ(events.size(), 1U);
  EXPECT_EQ(events.front().at_sample, 3U);
  EXPECT_EQ(events.front().missing_samples, 12U);
  EXPECT_EQ(events.front().duration_ms, 0U);  // kept for interruptions only
}

TEST(WfdbRecordingWriter, WritesTheHeaderOf17_6) {
  const TempFolder folder;
  WfdbRecordingWriter writer;
  RecordingFormat format = test_format(128500);
  format.gain_text = "200.5";
  format.gain_adu_per_mv = 200.5;
  format.baseline_adu = -7;
  ASSERT_TRUE(writer.open(folder.path(), "h", format, test_metadata()).ok());
  const std::vector<float> samples{1.0F, 2.0F, 3.0F};
  ASSERT_TRUE(writer.append(samples.data(), samples.size()).ok());
  ASSERT_TRUE(writer.add_event(RecordingEventKind::kInterruption, 0, 1500).ok());
  ASSERT_TRUE(writer.finish().ok());
  // round(200.5) - 7, round(401) - 7, round(601.5) - 7 = 194, 394, 595; sum 1183.
  const std::string text = file_bytes(folder.path() / "h.hea");
  const std::string start =
      "h 1 128.5 3\nh.dat 16 200.5(-7)/mV 16 0 194 1183 0 ECG\n# sinus_recording=1\n";
  EXPECT_EQ(text.substr(0, start.size()), start);
  // The event at the last sample count has no sample after it: it is not written.
  EXPECT_EQ(text.find("event="), std::string::npos);
  EXPECT_EQ(text.find('\r'), std::string::npos);
  EXPECT_EQ(text.back(), '\n');
}

TEST(WfdbRecordingWriter, RoundsHalfAwayFromZeroAndKeepsTheChecksumSigned) {
  const TempFolder folder;
  WfdbRecordingWriter writer;
  RecordingFormat format = test_format();
  format.gain_text = "2";
  format.gain_adu_per_mv = 2.0;
  ASSERT_TRUE(writer.open(folder.path(), "r", format, test_metadata()).ok());
  // Exact ties, then 17 values of 2000 adu: the sum 34000 is stated as 34000 - 65536.
  std::vector<float> samples{0.25F, -0.25F, 0.75F, -0.75F};
  samples.insert(samples.end(), 17, 1000.0F);
  ASSERT_TRUE(writer.append(samples.data(), samples.size()).ok());
  ASSERT_TRUE(writer.finish().ok());
  const WfdbRecord record = read_back(folder.path() / "r");
  std::vector<std::int16_t> expected{1, -1, 2, -2};
  expected.insert(expected.end(), 17, 2000);
  EXPECT_EQ(record.signal0_adu, expected);
  EXPECT_NE(file_bytes(folder.path() / "r.hea").find(" 1 -31536 0 ECG"), std::string::npos);
}

TEST(WfdbRecordingWriter, WritesFsWithUpToThreeDecimals) {
  for (const auto& [millihertz, text] :
       std::vector<std::pair<std::uint32_t, std::string>>{{125000, "h 1 125 1\n"},
                                                          {360001, "h 1 360.001 1\n"},
                                                          {360010, "h 1 360.01 1\n"},
                                                          {1000000, "h 1 1000 1\n"}}) {
    const TempFolder folder;
    WfdbRecordingWriter writer;
    ASSERT_TRUE(writer.open(folder.path(), "h", test_format(millihertz), test_metadata()).ok());
    const float sample = 0.0F;
    ASSERT_TRUE(writer.append(&sample, 1).ok());
    ASSERT_TRUE(writer.finish().ok());
    EXPECT_EQ(file_bytes(folder.path() / "h.hea").substr(0, text.size()), text);
  }
}

TEST(WfdbRecordingWriter, RejectsInvalidNames) {
  const TempFolder folder;
  for (const std::string& name :
       {std::string(), std::string(65, 'a'), std::string("a.b"), std::string("a b"),
        std::string("../a"), std::string("caf\xc3\xa9")}) {
    WfdbRecordingWriter writer;
    const WfdbResult result = writer.open(folder.path(), name, test_format(), test_metadata());
    EXPECT_EQ(result.status, WfdbStatus::kInvalidName) << name;
    EXPECT_EQ(result.message.rfind("Recording " + name + ": ", 0), 0U) << result.message;
  }
  WfdbRecordingWriter writer;
  EXPECT_TRUE(
      writer.open(folder.path(), std::string(64, 'Z'), test_format(), test_metadata()).ok());
  writer.abandon();
  EXPECT_TRUE(file_exists(folder.path() / (std::string(64, 'Z') + ".dat.partial")));
}

TEST(WfdbRecordingWriter, RejectsInvalidFormatsAndMetadata) {
  const TempFolder folder;
  std::vector<RecordingFormat> formats(6, test_format());
  formats.at(0).fs_millihertz = 124999;
  formats.at(1).fs_millihertz = 1000001;
  formats.at(2).gain_text = "0";
  formats.at(2).gain_adu_per_mv = 0.0;
  formats.at(3).gain_text = "1000";
  formats.at(3).gain_adu_per_mv = 999.0;
  formats.at(4).gain_text = "1e3";
  formats.at(5).gain_text = "";
  for (const RecordingFormat& format : formats) {
    WfdbRecordingWriter writer;
    EXPECT_EQ(writer.open(folder.path(), "r", format, test_metadata()).status,
              WfdbStatus::kInvalidMetadata)
        << format.fs_millihertz << " " << format.gain_text;
  }
  RecordingMetadata metadata = test_metadata();
  metadata.library_source_sha256 = "x";
  WfdbRecordingWriter writer;
  const WfdbResult result = writer.open(folder.path(), "r", test_format(), metadata);
  EXPECT_EQ(result.status, WfdbStatus::kInvalidMetadata);
  EXPECT_NE(result.message.find("library_source_sha256"), std::string::npos);
  EXPECT_TRUE(std::filesystem::is_empty(folder.path()));
}

TEST(WfdbRecordingWriter, NeverOverwritesAFile) {
  for (const char* suffix : {".hea", ".dat", ".hea.partial", ".dat.partial"}) {
    const TempFolder folder;
    folder.write(std::string("r") + suffix, "keep");
    WfdbRecordingWriter writer;
    const WfdbResult result = writer.open(folder.path(), "r", test_format(), test_metadata());
    EXPECT_EQ(result.status, WfdbStatus::kAlreadyExists) << suffix;
    EXPECT_NE(result.message.find(std::string("r") + suffix), std::string::npos);
    EXPECT_EQ(file_bytes(folder.path() / (std::string("r") + suffix)), "keep");
  }
}

TEST(WfdbRecordingWriter, FailsToCreateInAMissingFolder) {
  const TempFolder folder;
  WfdbRecordingWriter writer;
  EXPECT_EQ(writer.open(folder.path() / "missing", "r", test_format(), test_metadata()).status,
            WfdbStatus::kWriteFailed);
}

TEST(WfdbRecordingWriter, RejectsSamplesOutsideFormat16) {
  const float nan = std::numeric_limits<float>::quiet_NaN();
  const float infinity = std::numeric_limits<float>::infinity();
  // 32.7675 rounds to 32768 at gain 1000; with baseline 1, 32.767 gives 32768.
  for (const auto& [sample, baseline] : std::vector<std::pair<float, std::int32_t>>{
           {nan, 0}, {infinity, 0}, {-infinity, 0}, {32.768F, 0}, {-32.768F, 0}, {32.767F, 1}}) {
    const TempFolder folder;
    RecordingFormat format = test_format();
    format.baseline_adu = baseline;
    WfdbRecordingWriter writer;
    ASSERT_TRUE(writer.open(folder.path(), "r", format, test_metadata()).ok());
    const std::vector<float> samples{0.0F, sample};
    const WfdbResult result = writer.append(samples.data(), samples.size());
    EXPECT_EQ(result.status, WfdbStatus::kSampleOutOfFormat) << sample;
    EXPECT_NE(result.message.find("sample 1 "), std::string::npos) << result.message;
    // After a failure every call is kWriterFailed and the partial file stays.
    EXPECT_EQ(writer.append(samples.data(), 1).status, WfdbStatus::kWriterFailed);
    EXPECT_EQ(writer.add_event(RecordingEventKind::kGap, 0, 0).status, WfdbStatus::kWriterFailed);
    EXPECT_EQ(writer.finish().status, WfdbStatus::kWriterFailed);
    EXPECT_TRUE(file_exists(folder.path() / "r.dat.partial"));
    EXPECT_FALSE(file_exists(folder.path() / "r.dat"));
    EXPECT_FALSE(file_exists(folder.path() / "r.hea"));
  }
}

TEST(WfdbRecordingWriter, EmptyRecordingFails) {
  const TempFolder folder;
  WfdbRecordingWriter writer;
  ASSERT_TRUE(writer.open(folder.path(), "r", test_format(), test_metadata()).ok());
  ASSERT_TRUE(writer.append(nullptr, 0).ok());
  EXPECT_EQ(writer.finish().status, WfdbStatus::kEmptyRecording);
  EXPECT_TRUE(file_exists(folder.path() / "r.dat.partial"));
  EXPECT_FALSE(file_exists(folder.path() / "r.hea"));
  EXPECT_EQ(writer.finish().status, WfdbStatus::kWriterFailed);
}

TEST(WfdbRecordingWriter, CallsOutsideAnOpenRecordingFail) {
  const TempFolder folder;
  const float sample = 1.0F;
  WfdbRecordingWriter idle;
  EXPECT_EQ(idle.append(&sample, 1).status, WfdbStatus::kWriterFailed);
  EXPECT_EQ(idle.finish().status, WfdbStatus::kWriterFailed);

  WfdbRecordingWriter finished;
  ASSERT_TRUE(finished.open(folder.path(), "a", test_format(), test_metadata()).ok());
  ASSERT_TRUE(finished.append(&sample, 1).ok());
  ASSERT_TRUE(finished.finish().ok());
  EXPECT_EQ(finished.append(&sample, 1).status, WfdbStatus::kWriterFailed);
  EXPECT_EQ(finished.open(folder.path(), "b", test_format(), test_metadata()).status,
            WfdbStatus::kWriterFailed);

  WfdbRecordingWriter abandoned;
  ASSERT_TRUE(abandoned.open(folder.path(), "c", test_format(), test_metadata()).ok());
  ASSERT_TRUE(abandoned.append(&sample, 1).ok());
  abandoned.abandon();
  EXPECT_EQ(abandoned.finish().status, WfdbStatus::kWriterFailed);
  EXPECT_TRUE(file_exists(folder.path() / "c.dat.partial"));
  EXPECT_FALSE(file_exists(folder.path() / "c.hea"));
  EXPECT_FALSE(file_exists(folder.path() / "c.hea.partial"));
}

TEST(WfdbRecordingWriter, DestructorAbandonsAnOpenRecording) {
  const TempFolder folder;
  {
    WfdbRecordingWriter writer;
    ASSERT_TRUE(writer.open(folder.path(), "r", test_format(), test_metadata()).ok());
    const float sample = 1.0F;
    ASSERT_TRUE(writer.append(&sample, 1).ok());
  }
  EXPECT_TRUE(file_exists(folder.path() / "r.dat.partial"));
  EXPECT_FALSE(file_exists(folder.path() / "r.dat"));
  EXPECT_FALSE(file_exists(folder.path() / "r.hea"));
}

TEST(WfdbRecordingWriter, StoresEventsByTheRulesOf17_6) {
  const TempFolder folder;
  WfdbRecordingWriter writer;
  ASSERT_TRUE(writer.open(folder.path(), "r", test_format(), test_metadata()).ok());
  const float sample = 0.5F;
  ASSERT_TRUE(writer.add_event(RecordingEventKind::kGap, 5, 0).ok());  // at 0: not stored
  ASSERT_TRUE(writer.append(&sample, 1).ok());
  ASSERT_TRUE(writer.add_event(RecordingEventKind::kGap, 5, 0).ok());
  ASSERT_TRUE(writer.add_event(RecordingEventKind::kInterruption, 0, 7).ok());  // same position
  ASSERT_TRUE(writer.append(&sample, 1).ok());
  EXPECT_EQ(writer.add_event(RecordingEventKind::kGap, kMaxMissingSamples + 1, 0).status,
            WfdbStatus::kInvalidMetadata);
  WfdbRecordingWriter second;
  ASSERT_TRUE(second.open(folder.path(), "s", test_format(), test_metadata()).ok());
  for (std::size_t i = 0; i < kMaxRecordingEvents; ++i) {
    ASSERT_TRUE(second.append(&sample, 1).ok());
    ASSERT_TRUE(second.add_event(RecordingEventKind::kGap, kMaxMissingSamples, 0).ok());
  }
  ASSERT_TRUE(second.append(&sample, 1).ok());
  EXPECT_EQ(second.add_event(RecordingEventKind::kGap, 0, 0).status, WfdbStatus::kTooManyEvents);

  WfdbRecordingWriter third;
  ASSERT_TRUE(third.open(folder.path(), "t", test_format(), test_metadata()).ok());
  ASSERT_TRUE(third.append(&sample, 1).ok());
  ASSERT_TRUE(third.add_event(RecordingEventKind::kGap, 5, 0).ok());
  ASSERT_TRUE(third.add_event(RecordingEventKind::kInterruption, 0, 7).ok());
  ASSERT_TRUE(third.append(&sample, 1).ok());
  ASSERT_TRUE(third.finish().ok());
  const WfdbRecord record = read_back(folder.path() / "t");
  bool has_recording = false;
  RecordingMetadata metadata;
  std::vector<RecordingEvent> events;
  ASSERT_TRUE(parse_recording_comments(record.header, has_recording, metadata, events).ok());
  ASSERT_EQ(events.size(), 1U);
  EXPECT_EQ(events.front().kind, RecordingEventKind::kGap);
  EXPECT_EQ(events.front().at_sample, 1U);
}

TEST(WfdbRecordingWriter, LargeRecordingsCrossTheBuffer) {
  const TempFolder folder;
  WfdbRecordingWriter writer;
  ASSERT_TRUE(writer.open(folder.path(), "big", test_format(), test_metadata()).ok());
  std::vector<float> samples(100003);
  for (std::size_t i = 0; i < samples.size(); ++i) {
    samples.at(i) = static_cast<float>(static_cast<int>(i % 2001) - 1000) / 1000.0F;
  }
  ASSERT_TRUE(writer.append(samples.data(), 70000).ok());
  ASSERT_TRUE(writer.append(samples.data() + 70000, samples.size() - 70000).ok());
  ASSERT_TRUE(writer.finish().ok());
  const WfdbRecord record = read_back(folder.path() / "big");
  ASSERT_EQ(record.signal0_adu.size(), samples.size());
  for (std::size_t i = 0; i < samples.size(); ++i) {
    ASSERT_EQ(record.signal0_adu.at(i), static_cast<int>(i % 2001) - 1000) << i;
  }
}

// The fixture session_gap is the recording the writer makes of 20 s of replay16 at gain 1000.
TEST(WfdbRecordingWriter, WritesTheBytesOfTheSessionFixture) {
  const WfdbRecord replay = read_back(kFixtures / "replay16");
  const TempFolder folder;
  WfdbRecordingWriter writer;
  ASSERT_TRUE(writer.open(folder.path(), "session_gap", test_format(), test_metadata()).ok());
  for (std::size_t i = 0; i < 7200; ++i) {
    if (i == 3600) {
      ASSERT_TRUE(writer.add_event(RecordingEventKind::kGap, 1080, 0).ok());
    } else if (i == 5400) {
      ASSERT_TRUE(writer.add_event(RecordingEventKind::kInterruption, 0, 1500).ok());
    }
    const float sample = replay.sample_mv(i);
    ASSERT_TRUE(writer.append(&sample, 1).ok());
  }
  ASSERT_TRUE(writer.finish().ok());
  for (const char* suffix : {".hea", ".dat"}) {
    const std::string name = std::string("session_gap") + suffix;
    EXPECT_EQ(file_bytes(folder.path() / name), file_bytes(kFixtures / name)) << name;
  }
}

// Writes `name` and `<name>.source` (fs_millihertz, then the binary32 values in hex) for the
// Python check test_cpp_recordings_load_in_offline_loader.
void write_cross_check(const std::filesystem::path& folder, const std::string& name,
                       const RecordingFormat& format, const RecordingMetadata& metadata,
                       const std::vector<float>& samples,
                       const std::vector<std::pair<std::size_t, RecordingEvent>>& events) {
  for (const char* suffix : {".hea", ".dat", ".hea.partial", ".dat.partial", ".source"}) {
    std::error_code error;
    std::filesystem::remove(folder / (name + suffix), error);
  }
  WfdbRecordingWriter writer;
  ASSERT_TRUE(writer.open(folder, name, format, metadata).ok());
  std::size_t next = 0;
  for (std::size_t i = 0; i < samples.size(); ++i) {
    for (const auto& [position, event] : events) {
      if (position == i) {
        ASSERT_TRUE(writer.add_event(event.kind, event.missing_samples, event.duration_ms).ok());
      }
    }
    ASSERT_TRUE(writer.append(&samples.at(i), 1).ok());
    ++next;
  }
  ASSERT_TRUE(writer.finish().ok());
  std::string source = "fs_millihertz=" + std::to_string(format.fs_millihertz) + "\n";
  for (const float sample : samples) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &sample, sizeof(bits));
    std::array<char, 9> text{};
    std::snprintf(text.data(), text.size(), "%08x", static_cast<unsigned>(bits));
    source.append(text.data()).append("\n");
  }
  std::ofstream file(folder / (name + ".source"), std::ios::binary);
  file.write(source.data(), static_cast<std::streamsize>(source.size()));
  ASSERT_TRUE(file.good());
  EXPECT_EQ(next, samples.size());
}

RecordingMetadata cross_check_metadata() {
  RecordingMetadata metadata;
  metadata.desktop_version = "0.3.0.dev0";
  for (int i = 0; i < 32; ++i) {
    metadata.desktop_source_sha256.append("ab");
  }
  metadata.library_version = "0.3.0.dev0";
  for (int i = 0; i < 32; ++i) {
    metadata.library_source_sha256.append("cd");
  }
  return metadata;
}

// Writes into SINUS_DESKTOP_WFDB_DIR when it is set (the desktop CI job), else into a temporary
// folder; the C++ reader reads each record back.
TEST(WfdbRecordingWriterCrossCheck, WritesRecords) {
  const TempFolder temporary;
  const char* variable = std::getenv("SINUS_DESKTOP_WFDB_DIR");  // NOLINT(concurrency-mt-unsafe)
  std::filesystem::path folder = temporary.path();
  if (variable != nullptr && *variable != '\0') {
    folder = std::filesystem::u8path(variable);
    std::error_code error;
    std::filesystem::create_directories(folder, error);
    ASSERT_FALSE(error) << error.message();
  }

  RecordingMetadata metadata = cross_check_metadata();
  metadata.start_utc = "2026-10-12T08:00:00.000Z";
  metadata.source = RecordingSource::kTest;
  metadata.source_name = "127.0.0.1:45000";
  metadata.mains = MainsFrequency::k60Hz;
  const std::vector<float> test_samples{0.0F,    32.767F, -32.767F, 0.0005F,  -0.0005F, 1.2345F,
                                        -7.654F, 0.1F,    -0.1F,    12.3456F, 0.333F,   -0.333F};
  RecordingEvent gap;
  gap.kind = RecordingEventKind::kGap;
  gap.missing_samples = 36;
  RecordingEvent interruption;
  interruption.kind = RecordingEventKind::kInterruption;
  interruption.duration_ms = 2500;
  write_cross_check(folder, "xc_test", test_format(), metadata, test_samples,
                    {{4, gap}, {9, interruption}});

  const WfdbRecord source = read_back(kFixtures / "f212_even");
  std::vector<float> replay_samples(source.signal0_adu.size());
  for (std::size_t i = 0; i < replay_samples.size(); ++i) {
    replay_samples.at(i) = source.sample_mv(i);
  }
  RecordingFormat replay_format;
  replay_format.fs_millihertz = source.header.fs_millihertz;
  replay_format.gain_text = source.header.signals.front().gain_text;
  replay_format.gain_adu_per_mv = source.header.signals.front().gain_adu_per_mv;
  replay_format.baseline_adu = source.header.signals.front().baseline_adu;
  metadata.start_utc = "2026-10-12T08:00:01.500Z";
  metadata.source = RecordingSource::kReplayed;
  metadata.source_name = "f212_even";
  metadata.mains = MainsFrequency::k50Hz;
  write_cross_check(folder, "xc_replay", replay_format, metadata, replay_samples, {});

  const WfdbRecord replay = read_back(folder / "xc_replay");
  EXPECT_EQ(replay.signal0_adu, source.signal0_adu);
  const WfdbRecord test = read_back(folder / "xc_test");
  ASSERT_EQ(test.signal0_adu.size(), test_samples.size());
  EXPECT_EQ(test.signal0_adu.at(1), 32767);
  EXPECT_EQ(test.signal0_adu.at(2), -32767);
}

}  // namespace
