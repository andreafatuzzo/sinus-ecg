#pragma once

// Metadata and events of a recording, as comment lines of its WFDB header (architecture-m3.md
// 17.6). Each line is "key=value" pairs separated by one space; the header holds it after "# ".

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "core/mains.hpp"
#include "core/wfdb_header.hpp"
#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

enum class RecordingSource : std::uint8_t { kTest, kReplayed };

struct RecordingMetadata {
  std::string start_utc;  // ISO 8601 UTC with milliseconds: 2026-10-11T10:20:30.123Z
  RecordingSource source = RecordingSource::kTest;
  std::string source_name;  // the record or session name, or 127.0.0.1:<port>
  MainsFrequency mains = MainsFrequency::k50Hz;
  std::string desktop_version;
  std::string desktop_source_sha256;  // 64 lowercase hexadecimal digits
  std::string library_version;
  std::string library_source_sha256;  // 64 lowercase hexadecimal digits
};

enum class RecordingEventKind : std::uint8_t { kGap, kInterruption };

struct RecordingEvent {
  RecordingEventKind kind = RecordingEventKind::kGap;
  std::uint64_t at_sample = 0;        // the first recorded sample after the event, 1 to N - 1
  std::uint64_t missing_samples = 0;  // session indices skipped before that sample
  std::uint64_t duration_ms = 0;      // kInterruption only
};

inline constexpr std::size_t kMaxRecordingEvents = 10000;
inline constexpr std::uint64_t kMaxMissingSamples = 86400000;  // 24 h at 1000 Hz

// The comment lines (without "# ") of the metadata and events, in the order of 17.6.
[[nodiscard]] std::vector<std::string> recording_comment_lines(
    const RecordingMetadata& metadata, const std::vector<RecordingEvent>& events);

// Whether the metadata satisfy the value rules of 17.6 (the rules that parse_recording_comments
// applies to the metadata lines). false: `what` names the first rule broken.
[[nodiscard]] bool check_recording_metadata(const RecordingMetadata& metadata, std::string& what);

// Reads the comments of a header. Returns kOk with has_recording false when no comment is
// "sinus_recording=..."; otherwise every rule of 17.6 must hold (kMalformedRecording, naming the
// comment). When the result is not ok, `metadata` and `events` are unspecified.
[[nodiscard]] WfdbResult parse_recording_comments(const WfdbHeader& header, bool& has_recording,
                                                  RecordingMetadata& metadata,
                                                  std::vector<RecordingEvent>& events);

}  // namespace sinus::desktop::core
