#pragma once

// Recording writer: a WFDB record with one signal in format 16 and the comment lines of its
// metadata and events (architecture-m3.md 17.6). Nothing is ever overwritten or deleted; until
// finish() succeeds, the files are named <n>.dat.partial (and <n>.hea.partial).

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>
#include <vector>

#include "core/recording_metadata.hpp"
#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

struct RecordingFormat {
  std::uint32_t fs_millihertz = 0;
  std::string gain_text;          // "1000" for the test input; the source record's for a replay
  double gain_adu_per_mv = 0.0;   // the value of gain_text (parse_wfdb_decimal)
  std::int32_t baseline_adu = 0;  // 0 for the test input; the source record's for a replay
};

// The largest record name: [A-Za-z0-9_]{1,64}.
inline constexpr std::size_t kMaxRecordingNameLength = 64;
// The bytes of samples kept before they are written to the signal file.
inline constexpr std::size_t kRecordingBufferBytes = std::size_t{64} * 1024U;

class WfdbRecordingWriter {
 public:
  WfdbRecordingWriter() noexcept;
  ~WfdbRecordingWriter();  // abandon() if not finished
  WfdbRecordingWriter(const WfdbRecordingWriter&) = delete;
  WfdbRecordingWriter& operator=(const WfdbRecordingWriter&) = delete;
  WfdbRecordingWriter(WfdbRecordingWriter&&) = delete;
  WfdbRecordingWriter& operator=(WfdbRecordingWriter&&) = delete;

  // Checks the name (kInvalidName), the format and metadata (kInvalidMetadata) and that none of
  // <n>.hea, <n>.dat, <n>.hea.partial, <n>.dat.partial exists (kAlreadyExists), then creates
  // <n>.dat.partial (kWriteFailed). Every allocation of the writer happens here.
  [[nodiscard]] WfdbResult open(const std::filesystem::path& folder, std::string_view record_name,
                                const RecordingFormat& format, const RecordingMetadata& metadata);
  // d = round(x * gain) + baseline, half away from zero; a value that is not finite or a d
  // outside -32767 to 32767 is kSampleOutOfFormat. Precondition: samples_mv holds count values.
  [[nodiscard]] WfdbResult append(const float* samples_mv, std::size_t count);
  // An event at the current sample count. Not stored at sample count 0, nor a second event at
  // the same position; the 10 001st is kTooManyEvents; missing_samples above kMaxMissingSamples
  // is kInvalidMetadata. duration_ms is kept for kInterruption only.
  [[nodiscard]] WfdbResult add_event(RecordingEventKind kind, std::uint64_t missing_samples,
                                     std::uint64_t duration_ms);
  // Header, flush, rename: the record is complete. 0 samples is kEmptyRecording.
  [[nodiscard]] WfdbResult finish();
  // Closes; leaves only the .partial files.
  void abandon() noexcept;
  [[nodiscard]] std::uint64_t sample_count() const noexcept;

 private:
  enum class State : std::uint8_t { kIdle, kOpen, kFinished, kClosed, kFailed };

  WfdbResult fail(WfdbStatus status, std::string_view cause);
  WfdbResult not_usable();
  bool flush_buffer();
  std::string header_text() const;
  bool write_header(const std::string& text);

  State state_ = State::kIdle;
  std::string name_;
  RecordingFormat format_;
  RecordingMetadata metadata_;
  std::filesystem::path folder_;
  std::ofstream dat_file_;
  std::vector<char> buffer_;
  std::size_t buffer_used_ = 0;
  std::vector<RecordingEvent> events_;
  std::uint64_t sample_count_ = 0;
  std::int32_t first_adu_ = 0;
  std::uint32_t sum_ = 0;  // the sum of the values modulo 2^16
};

}  // namespace sinus::desktop::core
