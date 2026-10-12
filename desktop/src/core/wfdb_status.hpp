#pragma once

// Status and message of the WFDB reader and writer (architecture-m3.md 17.5).

#include <cstdint>
#include <string>

namespace sinus::desktop::core {

enum class WfdbStatus : std::uint8_t {
  // Reading and replay.
  kOk,
  kCannotRead,
  kMalformedHeader,
  kUnsupportedRecord,
  kUnsupportedFormat,
  kUnsupportedUnits,
  kEmptyRecord,
  kTooLong,
  kTruncatedSignal,
  kChecksumMismatch,
  kInvalidSampleValue,
  kSampleOutOfRange,
  kMalformedRecording,
  kReferenceMismatch,
  kStartBeyondEnd,
  // Writing.
  kInvalidName,
  kInvalidMetadata,
  kAlreadyExists,
  kWriteFailed,
  kSampleOutOfFormat,
  kTooManyEvents,
  kEmptyRecording,
  kWriterFailed,
};

struct WfdbResult {
  WfdbStatus status = WfdbStatus::kOk;
  std::string message;  // empty for kOk; otherwise one sentence for the user (17.5)
  [[nodiscard]] bool ok() const noexcept { return status == WfdbStatus::kOk; }
};

}  // namespace sinus::desktop::core
