#include "core/recording_metadata.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <iterator>
#include <limits>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "core/mains.hpp"
#include "core/wfdb_header.hpp"
#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

namespace {

// The metadata keys, in the order of their lines (17.6).
constexpr std::size_t kMetadataKeyCount = 9;
constexpr std::array<std::string_view, kMetadataKeyCount> kMetadataKeys{
    "sinus_recording",       "start_utc",       "source",
    "source_name",           "mains_hz",        "desktop_version",
    "desktop_source_sha256", "library_version", "library_source_sha256"};
constexpr std::string_view kEventKey = "event";
constexpr std::string_view kRecordingPrefix = "sinus_recording=";
constexpr std::string_view kVersionText = "1";
constexpr std::size_t kDigestDigits = 64;

constexpr bool is_digit(char c) noexcept { return c >= '0' && c <= '9'; }
constexpr bool is_lower_hex(char c) noexcept { return is_digit(c) || (c >= 'a' && c <= 'f'); }
constexpr bool is_key_char(char c) noexcept {
  return is_digit(c) || (c >= 'a' && c <= 'z') || c == '_';
}
// Printable ASCII without space and '='.
constexpr bool is_value_char(char c) noexcept { return c > ' ' && c <= '~' && c != '='; }

bool is_key(std::string_view text) noexcept {
  return !text.empty() && std::all_of(text.begin(), text.end(), is_key_char);
}

bool is_value(std::string_view text) noexcept {
  return !text.empty() && std::all_of(text.begin(), text.end(), is_value_char);
}

bool is_digest(std::string_view text) noexcept {
  return text.size() == kDigestDigits && std::all_of(text.begin(), text.end(), is_lower_hex);
}

bool is_metadata_key(std::string_view key) noexcept {
  return std::find(kMetadataKeys.begin(), kMetadataKeys.end(), key) != kMetadataKeys.end();
}

// Two decimal digits at `at` of `text`, which holds them (checked by the caller).
int two_digits(std::string_view text, std::size_t at) noexcept {
  return ((text.at(at) - '0') * 10) + (text.at(at + 1) - '0');
}

bool is_leap_year(int year) noexcept {
  return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
}

int days_in_month(int year, int month) noexcept {
  constexpr std::array<int, 12> days{31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  if (month == 2 && is_leap_year(year)) {
    return 29;
  }
  return days.at(static_cast<std::size_t>(month - 1));
}

// YYYY-MM-DDTHH:MM:SS.mmmZ, a date of the Gregorian calendar and a time from 00:00:00.000 to
// 23:59:59.999.
bool is_start_utc(std::string_view text) noexcept {
  constexpr std::string_view pattern = "dddd-dd-ddTdd:dd:dd.dddZ";
  if (text.size() != pattern.size()) {
    return false;
  }
  for (std::size_t i = 0; i < pattern.size(); ++i) {
    const bool ok = pattern.at(i) == 'd' ? is_digit(text.at(i)) : text.at(i) == pattern.at(i);
    if (!ok) {
      return false;
    }
  }
  const int year = (two_digits(text, 0) * 100) + two_digits(text, 2);
  const int month = two_digits(text, 5);
  const int day = two_digits(text, 8);
  if (month < 1 || month > 12 || day < 1 || day > days_in_month(year, month)) {
    return false;
  }
  return two_digits(text, 11) <= 23 && two_digits(text, 14) <= 59 && two_digits(text, 17) <= 59;
}

// A whole number without sign and without leading zero (except "0"), within std::uint64_t.
bool parse_count(std::string_view text, std::uint64_t& value) noexcept {
  if (text.empty() || !std::all_of(text.begin(), text.end(), is_digit) ||
      (text.size() > 1 && text.front() == '0')) {
    return false;
  }
  constexpr std::uint64_t max = std::numeric_limits<std::uint64_t>::max();
  std::uint64_t result = 0;
  for (const char c : text) {
    const auto digit = static_cast<std::uint64_t>(c - '0');
    if (result > (max - digit) / 10U) {
      return false;
    }
    result = (result * 10U) + digit;
  }
  value = result;
  return true;
}

std::string quoted(std::string_view text) {
  std::string out = "'";
  out.append(text).append("'");
  return out;
}

const char* source_text(RecordingSource source) noexcept {
  return source == RecordingSource::kReplayed ? "replayed" : "test";
}

// The metadata rules shared by the writer's check and the parser; empty when they hold.
std::string metadata_problem(const RecordingMetadata& metadata) {
  if (!is_start_utc(metadata.start_utc)) {
    return "start_utc " + quoted(metadata.start_utc) +
           " is not a UTC time of the form 2026-10-11T10:20:30.123Z";
  }
  if (metadata.source != RecordingSource::kTest && metadata.source != RecordingSource::kReplayed) {
    return "source must be test or replayed";
  }
  if (!is_value(metadata.source_name)) {
    return "source_name " + quoted(metadata.source_name) +
           " is not printable ASCII without space or '='";
  }
  if (metadata.mains != MainsFrequency::k50Hz && metadata.mains != MainsFrequency::k60Hz) {
    return "mains_hz must be 50 or 60";
  }
  if (!is_value(metadata.desktop_version)) {
    return "desktop_version " + quoted(metadata.desktop_version) +
           " is not printable ASCII without space or '='";
  }
  if (!is_digest(metadata.desktop_source_sha256)) {
    return "desktop_source_sha256 is not 64 lowercase hexadecimal digits";
  }
  if (!is_value(metadata.library_version)) {
    return "library_version " + quoted(metadata.library_version) +
           " is not printable ASCII without space or '='";
  }
  if (!is_digest(metadata.library_source_sha256)) {
    return "library_source_sha256 is not 64 lowercase hexadecimal digits";
  }
  return {};
}

struct Pair {
  std::string_view key;
  std::string_view value;
};

// The parser of the comments of one header.
class CommentParser {
 public:
  CommentParser(const WfdbHeader& header, RecordingMetadata& metadata,
                std::vector<RecordingEvent>& events)
      : header_(&header), metadata_(&metadata), events_(&events) {}

  WfdbResult parse(std::size_t first);

 private:
  bool split_pairs(std::string_view line, std::size_t number);
  bool metadata_line(std::size_t number);
  bool store_metadata(std::size_t key_index, std::string_view value, std::size_t number);
  bool event_line(std::size_t number);
  bool event_number(std::size_t index, std::string_view key, std::uint64_t& value,
                    std::size_t number);

  bool malformed(std::size_t number, std::string_view what) {
    result_.status = WfdbStatus::kMalformedRecording;
    result_.message.assign(header_->record_name).append(": header comment ");
    result_.message.append(std::to_string(number)).append(" is not a valid Sinus recording line: ");
    result_.message.append(what);
    return false;
  }

  const WfdbHeader* header_;             // never null
  RecordingMetadata* metadata_;          // the caller's metadata, never null
  std::vector<RecordingEvent>* events_;  // the caller's events, never null
  WfdbResult result_;
  std::vector<Pair> pairs_;
  std::size_t next_key_ = 0;  // index in kMetadataKeys of the next metadata line
};

WfdbResult CommentParser::parse(std::size_t first) {
  const std::vector<std::string>& comments = header_->comments;
  // Comments before the sinus_recording line may be anything but a Sinus line.
  for (std::size_t i = 0; i < first; ++i) {
    const std::string_view line = comments.at(i);
    const std::string_view key = line.substr(0, line.find('='));
    if (key.size() < line.size() && (is_metadata_key(key) || key == kEventKey)) {
      malformed(i + 1, "the key " + quoted(key) + " comes before sinus_recording");
      return result_;
    }
  }
  for (std::size_t i = first; i < comments.size(); ++i) {
    const std::size_t number = i + 1;
    if (!split_pairs(comments.at(i), number)) {
      return result_;
    }
    const bool ok = next_key_ < kMetadataKeyCount ? metadata_line(number) : event_line(number);
    if (!ok) {
      return result_;
    }
  }
  if (next_key_ < kMetadataKeyCount) {
    malformed(comments.size() + 1,
              "the key " + quoted(kMetadataKeys.at(next_key_)) + " is missing");
  }
  return result_;
}

bool CommentParser::split_pairs(std::string_view line, std::size_t number) {
  pairs_.clear();
  std::string_view rest = line;
  while (true) {
    const std::size_t end = rest.find(' ');
    const std::string_view token = rest.substr(0, end);
    const std::size_t equals = token.find('=');
    if (equals == std::string_view::npos) {
      return malformed(number, "the field " + quoted(token) + " is not key=value");
    }
    const Pair pair{token.substr(0, equals), token.substr(equals + 1)};
    if (!is_key(pair.key)) {
      return malformed(number, "the key " + quoted(pair.key) + " is not [a-z0-9_]+");
    }
    if (!is_value(pair.value)) {
      return malformed(number, "the value of " + quoted(pair.key) +
                                   " is not printable ASCII without space or '='");
    }
    pairs_.push_back(pair);
    if (end == std::string_view::npos) {
      return true;
    }
    rest.remove_prefix(end + 1);
  }
}

bool CommentParser::metadata_line(std::size_t number) {
  const std::string_view key = pairs_.front().key;
  const std::string_view expected = kMetadataKeys.at(next_key_);
  if (key != expected) {
    const auto* const found = std::find(kMetadataKeys.begin(), kMetadataKeys.end(), key);
    const auto position = static_cast<std::size_t>(std::distance(kMetadataKeys.begin(), found));
    if (position < next_key_) {  // a key already read
      return malformed(number, "the key " + quoted(key) + " is repeated");
    }
    if (is_metadata_key(key) || key == kEventKey) {
      return malformed(number, "the key " + quoted(expected) + " is missing");
    }
    return malformed(number, "the key " + quoted(key) + " is unknown");
  }
  if (pairs_.size() != 1) {
    return malformed(number, "a metadata line holds one key=value pair");
  }
  if (!store_metadata(next_key_, pairs_.front().value, number)) {
    return false;
  }
  ++next_key_;
  return true;
}

bool CommentParser::store_metadata(std::size_t key_index, std::string_view value,
                                   std::size_t number) {
  RecordingMetadata& metadata = *metadata_;
  switch (key_index) {
    case 0:
      if (value != kVersionText) {
        return malformed(number, "the version " + quoted(value) + " is not 1");
      }
      return true;
    case 1:
      if (!is_start_utc(value)) {
        return malformed(number, "start_utc " + quoted(value) +
                                     " is not a UTC time of the form 2026-10-11T10:20:30.123Z");
      }
      metadata.start_utc.assign(value);
      return true;
    case 2:
      if (value == "test") {
        metadata.source = RecordingSource::kTest;
      } else if (value == "replayed") {
        metadata.source = RecordingSource::kReplayed;
      } else {
        return malformed(number, "source " + quoted(value) + " is not test or replayed");
      }
      return true;
    case 3:
      metadata.source_name.assign(value);
      return true;
    case 4:
      if (value == "50") {
        metadata.mains = MainsFrequency::k50Hz;
      } else if (value == "60") {
        metadata.mains = MainsFrequency::k60Hz;
      } else {
        return malformed(number, "mains_hz " + quoted(value) + " is not 50 or 60");
      }
      return true;
    case 5:
      metadata.desktop_version.assign(value);
      return true;
    case 7:
      metadata.library_version.assign(value);
      return true;
    default:
      break;
  }
  // 6 and 8: the source digests.
  if (!is_digest(value)) {
    return malformed(number, std::string(kMetadataKeys.at(key_index)) +
                                 " is not 64 lowercase hexadecimal digits");
  }
  (key_index == 6 ? metadata.desktop_source_sha256 : metadata.library_source_sha256).assign(value);
  return true;
}

bool CommentParser::event_number(std::size_t index, std::string_view key, std::uint64_t& value,
                                 std::size_t number) {
  const Pair& pair = pairs_.at(index);
  if (pair.key != key) {
    return malformed(number, "field " + std::to_string(index + 1) + " of an event is " +
                                 quoted(pair.key) + ", not " + quoted(key));
  }
  if (!parse_count(pair.value, value)) {
    return malformed(number, std::string(key) + " " + quoted(pair.value) +
                                 " is not a whole number without leading zero");
  }
  return true;
}

bool CommentParser::event_line(std::size_t number) {
  const Pair& first = pairs_.front();
  if (first.key != kEventKey) {
    if (is_metadata_key(first.key)) {
      return malformed(number, "the key " + quoted(first.key) + " is repeated");
    }
    return malformed(number, "the key " + quoted(first.key) + " is unknown");
  }
  RecordingEvent event;
  std::size_t fields = 3;
  if (first.value == "gap") {
    event.kind = RecordingEventKind::kGap;
  } else if (first.value == "interruption") {
    event.kind = RecordingEventKind::kInterruption;
    fields = 4;
  } else {
    return malformed(number, "the event " + quoted(first.value) + " is not gap or interruption");
  }
  if (pairs_.size() != fields) {
    return malformed(number, "a " + std::string(first.value) + " event holds " +
                                 std::to_string(fields) + " key=value pairs");
  }
  if (!event_number(1, "at_sample", event.at_sample, number) ||
      !event_number(2, "missing_samples", event.missing_samples, number)) {
    return false;
  }
  if (fields == 4 && !event_number(3, "duration_ms", event.duration_ms, number)) {
    return false;
  }
  if (events_->size() >= kMaxRecordingEvents) {
    return malformed(number,
                     "there are more than " + std::to_string(kMaxRecordingEvents) + " events");
  }
  const std::uint64_t samples = header_->sample_count;
  if (event.at_sample < 1 || event.at_sample >= samples) {
    return malformed(number, "at_sample " + std::to_string(event.at_sample) + " is not from 1 to " +
                                 std::to_string(samples == 0 ? 0 : samples - 1));
  }
  if (!events_->empty() && event.at_sample <= events_->back().at_sample) {
    return malformed(number, "at_sample " + std::to_string(event.at_sample) +
                                 " does not follow the previous event's " +
                                 std::to_string(events_->back().at_sample));
  }
  if (event.missing_samples > kMaxMissingSamples) {
    return malformed(number, "missing_samples " + std::to_string(event.missing_samples) +
                                 " is above " + std::to_string(kMaxMissingSamples));
  }
  events_->push_back(event);
  return true;
}

}  // namespace

std::vector<std::string> recording_comment_lines(const RecordingMetadata& metadata,
                                                 const std::vector<RecordingEvent>& events) {
  const std::array<std::string, kMetadataKeyCount> values{
      std::string(kVersionText),
      metadata.start_utc,
      source_text(metadata.source),
      metadata.source_name,
      std::to_string(static_cast<unsigned>(metadata.mains)),
      metadata.desktop_version,
      metadata.desktop_source_sha256,
      metadata.library_version,
      metadata.library_source_sha256};
  std::vector<std::string> lines;
  lines.reserve(kMetadataKeyCount + events.size());
  for (std::size_t i = 0; i < kMetadataKeyCount; ++i) {
    std::string line(kMetadataKeys.at(i));
    line.append("=").append(values.at(i));
    lines.push_back(std::move(line));
  }
  for (const RecordingEvent& event : events) {
    const bool interruption = event.kind == RecordingEventKind::kInterruption;
    std::string line = "event=";
    line.append(interruption ? "interruption" : "gap");
    line.append(" at_sample=").append(std::to_string(event.at_sample));
    line.append(" missing_samples=").append(std::to_string(event.missing_samples));
    if (interruption) {
      line.append(" duration_ms=").append(std::to_string(event.duration_ms));
    }
    lines.push_back(std::move(line));
  }
  return lines;
}

bool check_recording_metadata(const RecordingMetadata& metadata, std::string& what) {
  what = metadata_problem(metadata);
  return what.empty();
}

WfdbResult parse_recording_comments(const WfdbHeader& header, bool& has_recording,
                                    RecordingMetadata& metadata,
                                    std::vector<RecordingEvent>& events) {
  metadata = RecordingMetadata{};
  events.clear();
  const std::vector<std::string>& comments = header.comments;
  const auto found = std::find_if(comments.begin(), comments.end(), [](const std::string& line) {
    return std::string_view(line).substr(0, kRecordingPrefix.size()) == kRecordingPrefix;
  });
  has_recording = found != comments.end();
  if (!has_recording) {
    return {};
  }
  CommentParser parser(header, metadata, events);
  return parser.parse(static_cast<std::size_t>(found - comments.begin()));
}

}  // namespace sinus::desktop::core
