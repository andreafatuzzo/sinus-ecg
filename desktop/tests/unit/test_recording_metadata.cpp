// Developer's unit tests of the recording metadata and its comment lines (architecture-m3.md
// 17.6).

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "core/mains.hpp"
#include "core/recording_metadata.hpp"
#include "core/wfdb_header.hpp"
#include "core/wfdb_status.hpp"

namespace {

using sinus::desktop::core::check_recording_metadata;
using sinus::desktop::core::kMaxMissingSamples;
using sinus::desktop::core::kMaxRecordingEvents;
using sinus::desktop::core::MainsFrequency;
using sinus::desktop::core::parse_recording_comments;
using sinus::desktop::core::recording_comment_lines;
using sinus::desktop::core::RecordingEvent;
using sinus::desktop::core::RecordingEventKind;
using sinus::desktop::core::RecordingMetadata;
using sinus::desktop::core::RecordingSource;
using sinus::desktop::core::WfdbHeader;
using sinus::desktop::core::WfdbResult;
using sinus::desktop::core::WfdbStatus;

const std::string kDigestA(64, 'a');
const std::string kDigestB = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

RecordingMetadata metadata() {
  RecordingMetadata out;
  out.start_utc = "2026-10-11T10:20:30.123Z";
  out.source = RecordingSource::kTest;
  out.source_name = "127.0.0.1:45000";
  out.mains = MainsFrequency::k50Hz;
  out.desktop_version = "0.3.0.dev0";
  out.desktop_source_sha256 = kDigestA;
  out.library_version = "0.3.0.dev0";
  out.library_source_sha256 = kDigestB;
  return out;
}

std::vector<std::string> metadata_lines() {
  return {"sinus_recording=1",
          "start_utc=2026-10-11T10:20:30.123Z",
          "source=test",
          "source_name=127.0.0.1:45000",
          "mains_hz=50",
          "desktop_version=0.3.0.dev0",
          "desktop_source_sha256=" + kDigestA,
          "library_version=0.3.0.dev0",
          "library_source_sha256=" + kDigestB};
}

WfdbHeader header_with(const std::vector<std::string>& comments, std::uint64_t samples = 7200) {
  WfdbHeader header;
  header.record_name = "rec";
  header.sample_count = samples;
  header.comments = comments;
  return header;
}

struct Parsed {
  WfdbResult result;
  bool has_recording = false;
  RecordingMetadata metadata;
  std::vector<RecordingEvent> events;
};

Parsed parse(const std::vector<std::string>& comments, std::uint64_t samples = 7200) {
  Parsed parsed;
  parsed.result = parse_recording_comments(header_with(comments, samples), parsed.has_recording,
                                           parsed.metadata, parsed.events);
  return parsed;
}

// The metadata lines with line `index` replaced.
std::vector<std::string> with_line(std::size_t index, const std::string& line) {
  std::vector<std::string> lines = metadata_lines();
  lines.at(index) = line;
  return lines;
}

void expect_malformed(const std::vector<std::string>& comments, const std::string& part,
                      std::uint64_t samples = 7200) {
  const Parsed parsed = parse(comments, samples);
  EXPECT_EQ(parsed.result.status, WfdbStatus::kMalformedRecording) << part;
  EXPECT_TRUE(parsed.has_recording);
  EXPECT_EQ(parsed.result.message.rfind("rec: header comment ", 0), 0U) << parsed.result.message;
  EXPECT_NE(parsed.result.message.find(part), std::string::npos) << parsed.result.message;
}

TEST(RecordingCommentLines, AreTheMetadataThenTheEvents) {
  std::vector<RecordingEvent> events(2);
  events.at(0) = {RecordingEventKind::kGap, 3600, 1080, 99};
  events.at(1) = {RecordingEventKind::kInterruption, 5400, 0, 1500};
  RecordingMetadata data = metadata();
  data.source = RecordingSource::kReplayed;
  data.mains = MainsFrequency::k60Hz;
  std::vector<std::string> expected = metadata_lines();
  expected.at(2) = "source=replayed";
  expected.at(4) = "mains_hz=60";
  expected.emplace_back("event=gap at_sample=3600 missing_samples=1080");
  expected.emplace_back("event=interruption at_sample=5400 missing_samples=0 duration_ms=1500");
  EXPECT_EQ(recording_comment_lines(data, events), expected);
}

TEST(ParseRecordingComments, ReadsTheLinesItWrites) {
  std::vector<RecordingEvent> events(2);
  events.at(0) = {RecordingEventKind::kGap, 1, kMaxMissingSamples, 0};
  events.at(1) = {RecordingEventKind::kInterruption, 7199, 0, 18446744073709551615ULL};
  const Parsed parsed = parse(recording_comment_lines(metadata(), events));
  ASSERT_TRUE(parsed.result.ok()) << parsed.result.message;
  EXPECT_TRUE(parsed.result.message.empty());
  EXPECT_TRUE(parsed.has_recording);
  EXPECT_EQ(parsed.metadata.start_utc, "2026-10-11T10:20:30.123Z");
  EXPECT_EQ(parsed.metadata.source, RecordingSource::kTest);
  EXPECT_EQ(parsed.metadata.source_name, "127.0.0.1:45000");
  EXPECT_EQ(parsed.metadata.mains, MainsFrequency::k50Hz);
  EXPECT_EQ(parsed.metadata.desktop_version, "0.3.0.dev0");
  EXPECT_EQ(parsed.metadata.desktop_source_sha256, kDigestA);
  EXPECT_EQ(parsed.metadata.library_version, "0.3.0.dev0");
  EXPECT_EQ(parsed.metadata.library_source_sha256, kDigestB);
  ASSERT_EQ(parsed.events.size(), 2U);
  EXPECT_EQ(parsed.events.at(0).kind, RecordingEventKind::kGap);
  EXPECT_EQ(parsed.events.at(0).at_sample, 1U);
  EXPECT_EQ(parsed.events.at(0).missing_samples, kMaxMissingSamples);
  EXPECT_EQ(parsed.events.at(1).kind, RecordingEventKind::kInterruption);
  EXPECT_EQ(parsed.events.at(1).at_sample, 7199U);
  EXPECT_EQ(parsed.events.at(1).duration_ms, 18446744073709551615ULL);
}

TEST(ParseRecordingComments, WithoutSinusRecordingIsNoRecording) {
  for (const std::vector<std::string>& comments :
       {std::vector<std::string>{}, std::vector<std::string>{"MLII", "start_utc=x", "event=gap"},
        std::vector<std::string>{"sinus_recording 1", "sinus_recordingx=1"}}) {
    const Parsed parsed = parse(comments);
    EXPECT_TRUE(parsed.result.ok());
    EXPECT_FALSE(parsed.has_recording);
  }
}

TEST(ParseRecordingComments, AcceptsForeignCommentsBeforeTheRecording) {
  std::vector<std::string> comments = metadata_lines();
  comments.insert(comments.begin(), {"69 M 1085 1629 x1", "Aldomet, Inderal", "x=1"});
  const Parsed parsed = parse(comments);
  EXPECT_TRUE(parsed.result.ok()) << parsed.result.message;
  EXPECT_TRUE(parsed.has_recording);
}

TEST(ParseRecordingComments, RejectsASinusKeyBeforeTheRecording) {
  std::vector<std::string> comments = metadata_lines();
  comments.insert(comments.begin(), "mains_hz=60");
  expect_malformed(comments, "header comment 1 ");
  comments.at(0) = "event=gap at_sample=1 missing_samples=0";
  expect_malformed(comments, "comes before sinus_recording");
}

TEST(ParseRecordingComments, RejectsAnotherVersion) {
  expect_malformed(with_line(0, "sinus_recording=2"), "header comment 1 ");
  expect_malformed(with_line(0, "sinus_recording=01"), "the version");
}

TEST(ParseRecordingComments, RejectsMissingRepeatedAndUnknownKeys) {
  std::vector<std::string> lines = metadata_lines();
  lines.erase(lines.begin() + 4);
  expect_malformed(lines, "'mains_hz' is missing");
  lines = metadata_lines();
  lines.pop_back();
  expect_malformed(lines, "header comment 9 ");
  lines = metadata_lines();
  lines.insert(lines.begin() + 3, "source=test");
  expect_malformed(lines, "'source' is repeated");
  lines = metadata_lines();
  lines.emplace_back("source=test");
  expect_malformed(lines, "header comment 10 ");
  lines = metadata_lines();
  lines.emplace_back("sinus_recording=1");
  expect_malformed(lines, "is repeated");
  expect_malformed(with_line(3, "colour=red"), "'colour' is unknown");
  lines = metadata_lines();
  lines.emplace_back("colour=red");
  expect_malformed(lines, "'colour' is unknown");
  lines = metadata_lines();
  lines.insert(lines.begin() + 2, "event=gap at_sample=1 missing_samples=0");
  expect_malformed(lines, "'source' is missing");
}

TEST(ParseRecordingComments, RejectsValuesOutsideTheirRules) {
  expect_malformed(with_line(1, "start_utc=2026-10-11T10:20:30Z"), "start_utc");
  expect_malformed(with_line(1, "start_utc=2026-02-29T10:20:30.123Z"), "start_utc");
  expect_malformed(with_line(1, "start_utc=2026-10-11T24:00:00.000Z"), "start_utc");
  expect_malformed(with_line(2, "source=live"), "source 'live'");
  expect_malformed(with_line(4, "mains_hz=55"), "mains_hz '55'");
  expect_malformed(with_line(6, "desktop_source_sha256=" + std::string(64, 'A')), "64 lowercase");
  expect_malformed(with_line(8, "library_source_sha256=" + std::string(63, 'a')), "64 lowercase");
  expect_malformed(with_line(3, "source_name="), "the value of 'source_name'");
  expect_malformed(with_line(3, "source_name=a=b"), "the value of 'source_name'");
  expect_malformed(with_line(3, "source_name=a b"), "is not key=value");
  expect_malformed(with_line(3, "source_name=a  "), "header comment 4 ");
  expect_malformed(with_line(3, "source_name=caf\xc3\xa9"), "printable ASCII");
  expect_malformed(with_line(3, "Source_name=x"), "is not [a-z0-9_]+");
  expect_malformed(with_line(3, "source_name=x extra=1"), "one key=value pair");
  // A leap day of a leap year is a date.
  EXPECT_TRUE(parse(with_line(1, "start_utc=2028-02-29T23:59:59.999Z")).result.ok());
}

TEST(ParseRecordingComments, RejectsEventsOutsideTheirRules) {
  const auto with_events = [](const std::vector<std::string>& events) {
    std::vector<std::string> lines = metadata_lines();
    lines.insert(lines.end(), events.begin(), events.end());
    return lines;
  };
  expect_malformed(with_events({"event=gap at_sample=0 missing_samples=0"}), "at_sample 0");
  expect_malformed(with_events({"event=gap at_sample=7200 missing_samples=0"}), "7199");
  expect_malformed(with_events({"event=gap at_sample=1 missing_samples=0"}), "from 1 to 0", 1);
  expect_malformed(with_events({"event=gap at_sample=5 missing_samples=0",
                                "event=gap at_sample=5 missing_samples=0"}),
                   "header comment 11 ");
  expect_malformed(with_events({"event=gap at_sample=6 missing_samples=0",
                                "event=gap at_sample=5 missing_samples=0"}),
                   "does not follow");
  expect_malformed(with_events({"event=gap at_sample=5 missing_samples=86400001"}), "is above");
  expect_malformed(with_events({"event=gap at_sample=05 missing_samples=0"}), "leading zero");
  expect_malformed(with_events({"event=gap at_sample=+5 missing_samples=0"}), "at_sample");
  expect_malformed(with_events({"event=gap at_sample=18446744073709551616 missing_samples=0"}),
                   "at_sample");
  expect_malformed(with_events({"event=gap missing_samples=0 at_sample=5"}), "not 'at_sample'");
  expect_malformed(with_events({"event=gap at_sample=5 missing_samples=0 duration_ms=1"}),
                   "3 key=value pairs");
  expect_malformed(with_events({"event=interruption at_sample=5 missing_samples=0"}),
                   "4 key=value pairs");
  expect_malformed(with_events({"event=stop at_sample=5 missing_samples=0"}), "'stop'");
}

TEST(ParseRecordingComments, AcceptsAtMostTheLargestNumberOfEvents) {
  std::vector<RecordingEvent> events(kMaxRecordingEvents);
  for (std::size_t i = 0; i < events.size(); ++i) {
    events.at(i).at_sample = i + 1;
  }
  std::vector<std::string> lines = recording_comment_lines(metadata(), events);
  EXPECT_TRUE(parse(lines, 20000).result.ok());
  lines.emplace_back("event=gap at_sample=10001 missing_samples=0");
  expect_malformed(lines, "more than 10000 events", 20000);
}

TEST(CheckRecordingMetadata, AppliesTheValueRules) {
  std::string what;
  EXPECT_TRUE(check_recording_metadata(metadata(), what));
  EXPECT_TRUE(what.empty());
  RecordingMetadata data = metadata();
  data.start_utc = "2026-10-11 10:20:30.123Z";
  EXPECT_FALSE(check_recording_metadata(data, what));
  EXPECT_NE(what.find("start_utc"), std::string::npos);
  data = metadata();
  data.source_name = "a b";
  EXPECT_FALSE(check_recording_metadata(data, what));
  data = metadata();
  data.mains = static_cast<MainsFrequency>(55);
  EXPECT_FALSE(check_recording_metadata(data, what));
  data = metadata();
  data.source = static_cast<RecordingSource>(2);
  EXPECT_FALSE(check_recording_metadata(data, what));
  data = metadata();
  data.desktop_version.clear();
  EXPECT_FALSE(check_recording_metadata(data, what));
  data = metadata();
  data.library_version = "1=2";
  EXPECT_FALSE(check_recording_metadata(data, what));
  data = metadata();
  data.desktop_source_sha256 = kDigestA.substr(1);
  EXPECT_FALSE(check_recording_metadata(data, what));
  data = metadata();
  data.library_source_sha256 = std::string(64, 'g');
  EXPECT_FALSE(check_recording_metadata(data, what));
}

}  // namespace
