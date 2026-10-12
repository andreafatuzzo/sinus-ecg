#include "core/wfdb_writer.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <ios>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include "core/recording_metadata.hpp"
#include "core/wfdb_header.hpp"
#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

namespace {

// The sampling frequencies accepted (17.6), in mHz.
constexpr std::uint32_t kMinFsMillihertz = 125000;
constexpr std::uint32_t kMaxFsMillihertz = 1000000;
// Format 16 without its invalid-sample code -32768 (OP-082 (a)).
constexpr double kMaxStoredAdu = 32767.0;

bool is_name_char(char c) noexcept {
  return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
}

bool is_record_name(std::string_view name) noexcept {
  return !name.empty() && name.size() <= kMaxRecordingNameLength &&
         std::all_of(name.begin(), name.end(), is_name_char);
}

std::filesystem::path file_in(const std::filesystem::path& folder, const std::string& name,
                              std::string_view suffix) {
  std::string file_name = name;
  file_name.append(suffix);
  return folder / file_name;
}

enum class Presence : std::uint8_t { kAbsent, kPresent, kUnknown };

// Whether a file (of any type, also a dangling link) exists at `path`.
Presence presence_of(const std::filesystem::path& path) {
  std::error_code error;
  const std::filesystem::file_status status = std::filesystem::symlink_status(path, error);
  if (status.type() == std::filesystem::file_type::not_found) {
    return Presence::kAbsent;
  }
  if (error || status.type() == std::filesystem::file_type::none) {
    return Presence::kUnknown;
  }
  return Presence::kPresent;
}

// The size of a regular file, or false.
bool size_is(const std::filesystem::path& path, std::uintmax_t expected) {
  std::error_code error;
  const std::uintmax_t size = std::filesystem::file_size(path, error);
  return !error && size == expected;
}

std::string float_text(float value) {
  std::array<char, 32> text{};
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): the end of the array.
  const std::to_chars_result result = std::to_chars(text.data(), text.data() + text.size(), value);
  return {text.data(), result.ptr};
}

// The sampling frequency with its integer part and up to three decimals, trailing zeros and
// point removed (360, 128.5).
std::string fs_text(std::uint32_t fs_millihertz) {
  std::string text = std::to_string(fs_millihertz / 1000U);
  std::uint32_t fraction = fs_millihertz % 1000U;
  if (fraction == 0) {
    return text;
  }
  std::string digits = std::to_string(fraction);
  digits.insert(0, 3 - digits.size(), '0');
  while (digits.back() == '0') {
    digits.pop_back();
  }
  text.append(".").append(digits);
  return text;
}

// The sum modulo 2^16 as a signed 16-bit number.
std::int32_t signed16(std::uint32_t sum) noexcept {
  return sum >= 32768U ? static_cast<std::int32_t>(sum) - 65536 : static_cast<std::int32_t>(sum);
}

}  // namespace

WfdbRecordingWriter::WfdbRecordingWriter() noexcept = default;

WfdbRecordingWriter::~WfdbRecordingWriter() {
  if (state_ == State::kOpen) {
    abandon();
  }
}

WfdbResult WfdbRecordingWriter::fail(WfdbStatus status, std::string_view cause) {
  if (dat_file_.is_open()) {
    dat_file_.close();
  }
  state_ = State::kFailed;
  WfdbResult result;
  result.status = status;
  result.message.assign("Recording ").append(name_).append(": ").append(cause);
  return result;
}

WfdbResult WfdbRecordingWriter::not_usable() {
  WfdbResult result;
  result.status = WfdbStatus::kWriterFailed;
  result.message.assign("Recording ").append(name_).append(": ");
  switch (state_) {
    case State::kIdle:
      result.message.append("the recording is not open");
      break;
    case State::kFinished:
      result.message.append("the recording is already complete");
      break;
    case State::kClosed:
      result.message.append("the recording was abandoned");
      break;
    case State::kOpen:
    case State::kFailed:
      result.message.append("the recording failed earlier");
      break;
  }
  return result;
}

WfdbResult WfdbRecordingWriter::open(const std::filesystem::path& folder,
                                     std::string_view record_name, const RecordingFormat& format,
                                     const RecordingMetadata& metadata) {
  if (state_ != State::kIdle) {
    return not_usable();
  }
  name_.assign(record_name);
  if (!is_record_name(record_name)) {
    return fail(WfdbStatus::kInvalidName,
                "the name must be 1 to 64 letters, digits or underscores");
  }
  if (format.fs_millihertz < kMinFsMillihertz || format.fs_millihertz > kMaxFsMillihertz) {
    return fail(WfdbStatus::kInvalidMetadata, "the sampling frequency " +
                                                  fs_text(format.fs_millihertz) +
                                                  " Hz is not from 125 Hz to 1000 Hz");
  }
  double gain = 0.0;
  if (!parse_wfdb_decimal(format.gain_text, gain) || gain != format.gain_adu_per_mv ||
      !(gain > 0.0)) {
    return fail(WfdbStatus::kInvalidMetadata, "the gain '" + format.gain_text +
                                                  "' is not a decimal above 0 equal to " +
                                                  std::to_string(format.gain_adu_per_mv));
  }
  std::string what;
  if (!check_recording_metadata(metadata, what)) {
    return fail(WfdbStatus::kInvalidMetadata, what);
  }
  for (const std::string_view suffix : {".hea", ".dat", ".hea.partial", ".dat.partial"}) {
    const std::filesystem::path path = file_in(folder, name_, suffix);
    const Presence presence = presence_of(path);
    if (presence == Presence::kPresent) {
      return fail(WfdbStatus::kAlreadyExists,
                  path.filename().u8string() + " already exists in the folder");
    }
    if (presence == Presence::kUnknown) {
      return fail(WfdbStatus::kWriteFailed, "cannot examine " + path.filename().u8string());
    }
  }
  format_ = format;
  metadata_ = metadata;
  folder_ = folder;
  buffer_.assign(kRecordingBufferBytes, '\0');
  events_.reserve(kMaxRecordingEvents);
  dat_file_.open(file_in(folder_, name_, ".dat.partial"), std::ios::binary | std::ios::out);
  if (!dat_file_.is_open() || !dat_file_.good()) {
    return fail(WfdbStatus::kWriteFailed, "cannot create " + name_ + ".dat.partial");
  }
  state_ = State::kOpen;
  return {};
}

bool WfdbRecordingWriter::flush_buffer() {
  if (buffer_used_ > 0) {
    dat_file_.write(buffer_.data(), static_cast<std::streamsize>(buffer_used_));
    buffer_used_ = 0;
  }
  return dat_file_.good();
}

WfdbResult WfdbRecordingWriter::append(const float* samples_mv, std::size_t count) {
  if (state_ != State::kOpen) {
    return not_usable();
  }
  for (std::size_t k = 0; k < count; ++k) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): count values (precondition).
    const float sample = samples_mv[k];
    const std::uint64_t index = sample_count_;
    if (!std::isfinite(sample)) {
      return fail(WfdbStatus::kSampleOutOfFormat,
                  "sample " + std::to_string(index) + " is not a finite number");
    }
    // Half away from zero; baseline + round(x * gain) is exact in binary64.
    const double value = std::round(static_cast<double>(sample) * format_.gain_adu_per_mv) +
                         static_cast<double>(format_.baseline_adu);
    // value is finite here (checked above).
    if (value < -kMaxStoredAdu || value > kMaxStoredAdu) {
      return fail(WfdbStatus::kSampleOutOfFormat,
                  "sample " + std::to_string(index) + " (" + float_text(sample) +
                      " mV) cannot be stored in format 16 at gain " + format_.gain_text +
                      " and baseline " + std::to_string(format_.baseline_adu));
    }
    const auto adu = static_cast<std::int32_t>(value);
    const auto word = static_cast<std::uint16_t>(static_cast<std::uint32_t>(adu + 65536) & 0xFFFFU);
    if (sample_count_ == 0) {
      first_adu_ = adu;
    }
    sum_ = (sum_ + word) & 0xFFFFU;
    if (buffer_used_ + 2 > buffer_.size() && !flush_buffer()) {
      return fail(WfdbStatus::kWriteFailed, "cannot write " + name_ + ".dat.partial");
    }
    buffer_.at(buffer_used_) = static_cast<char>(word & 0xFFU);
    buffer_.at(buffer_used_ + 1) = static_cast<char>(word >> 8U);
    buffer_used_ += 2;
    ++sample_count_;
  }
  return {};
}

// NOLINTNEXTLINE(bugprone-easily-swappable-parameters): the interface of 17.6.
WfdbResult WfdbRecordingWriter::add_event(RecordingEventKind kind, std::uint64_t missing_samples,
                                          std::uint64_t duration_ms) {
  if (state_ != State::kOpen) {
    return not_usable();
  }
  if (sample_count_ == 0 || (!events_.empty() && events_.back().at_sample == sample_count_)) {
    return {};
  }
  if (events_.size() >= kMaxRecordingEvents) {
    return fail(WfdbStatus::kTooManyEvents,
                "more than " + std::to_string(kMaxRecordingEvents) + " events");
  }
  if (missing_samples > kMaxMissingSamples) {
    return fail(WfdbStatus::kInvalidMetadata, "an event of " + std::to_string(missing_samples) +
                                                  " missing samples is above " +
                                                  std::to_string(kMaxMissingSamples));
  }
  RecordingEvent event;
  event.kind = kind;
  event.at_sample = sample_count_;
  event.missing_samples = missing_samples;
  event.duration_ms = kind == RecordingEventKind::kInterruption ? duration_ms : 0;
  events_.push_back(event);
  return {};
}

std::string WfdbRecordingWriter::header_text() const {
  std::string text = name_;
  text.append(" 1 ").append(fs_text(format_.fs_millihertz)).append(" ");
  text.append(std::to_string(sample_count_)).append("\n");
  text.append(name_).append(".dat 16 ").append(format_.gain_text).append("(");
  text.append(std::to_string(format_.baseline_adu)).append(")/mV 16 0 ");
  text.append(std::to_string(first_adu_)).append(" ").append(std::to_string(signed16(sum_)));
  text.append(" 0 ECG\n");
  // An event at the last sample count has no sample after it (at_sample is 1 to N - 1).
  std::vector<RecordingEvent> events = events_;
  if (!events.empty() && events.back().at_sample >= sample_count_) {
    events.pop_back();
  }
  for (const std::string& line : recording_comment_lines(metadata_, events)) {
    text.append("# ").append(line).append("\n");
  }
  return text;
}

bool WfdbRecordingWriter::write_header(const std::string& text) {
  const std::filesystem::path path = file_in(folder_, name_, ".hea.partial");
  if (presence_of(path) != Presence::kAbsent) {
    return false;
  }
  std::ofstream file(path, std::ios::binary | std::ios::out);
  if (!file.is_open()) {
    return false;
  }
  file.write(text.data(), static_cast<std::streamsize>(text.size()));
  file.close();
  return !file.fail() && size_is(path, text.size());
}

WfdbResult WfdbRecordingWriter::finish() {
  if (state_ != State::kOpen) {
    return not_usable();
  }
  if (sample_count_ == 0) {
    return fail(WfdbStatus::kEmptyRecording, "the recording has 0 samples");
  }
  const bool flushed = flush_buffer();
  dat_file_.close();
  const std::filesystem::path dat_partial = file_in(folder_, name_, ".dat.partial");
  if (!flushed || dat_file_.fail() || !size_is(dat_partial, 2U * sample_count_)) {
    return fail(WfdbStatus::kWriteFailed, "cannot write " + name_ + ".dat.partial");
  }
  if (!write_header(header_text())) {
    return fail(WfdbStatus::kWriteFailed, "cannot write " + name_ + ".hea.partial");
  }
  // The signal file first: without <n>.hea nothing loads as a record (RC-020).
  const std::filesystem::path hea_partial = file_in(folder_, name_, ".hea.partial");
  const std::filesystem::path dat = file_in(folder_, name_, ".dat");
  const std::filesystem::path hea = file_in(folder_, name_, ".hea");
  std::error_code error;
  if (presence_of(dat) != Presence::kAbsent || presence_of(hea) != Presence::kAbsent) {
    return fail(WfdbStatus::kWriteFailed, "a file of the record appeared in the folder");
  }
  std::filesystem::rename(dat_partial, dat, error);
  if (error) {
    return fail(WfdbStatus::kWriteFailed, "cannot rename " + name_ + ".dat.partial");
  }
  std::filesystem::rename(hea_partial, hea, error);
  if (error) {
    return fail(WfdbStatus::kWriteFailed, "cannot rename " + name_ + ".hea.partial");
  }
  state_ = State::kFinished;
  return {};
}

void WfdbRecordingWriter::abandon() noexcept {
  if (dat_file_.is_open()) {
    dat_file_.close();
  }
  if (state_ == State::kOpen || state_ == State::kIdle) {
    state_ = State::kClosed;
  }
}

std::uint64_t WfdbRecordingWriter::sample_count() const noexcept { return sample_count_; }

}  // namespace sinus::desktop::core
