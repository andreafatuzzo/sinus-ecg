#pragma once

// The name of a WfdbStatus as written in the source (rejections.txt, the dump tool).

#include <string_view>

#include "core/wfdb_status.hpp"

namespace sinus::desktop::test {

inline std::string_view wfdb_status_name(core::WfdbStatus status) {
  using core::WfdbStatus;
  switch (status) {
    case WfdbStatus::kOk:
      return "kOk";
    case WfdbStatus::kCannotRead:
      return "kCannotRead";
    case WfdbStatus::kMalformedHeader:
      return "kMalformedHeader";
    case WfdbStatus::kUnsupportedRecord:
      return "kUnsupportedRecord";
    case WfdbStatus::kUnsupportedFormat:
      return "kUnsupportedFormat";
    case WfdbStatus::kUnsupportedUnits:
      return "kUnsupportedUnits";
    case WfdbStatus::kEmptyRecord:
      return "kEmptyRecord";
    case WfdbStatus::kTooLong:
      return "kTooLong";
    case WfdbStatus::kTruncatedSignal:
      return "kTruncatedSignal";
    case WfdbStatus::kChecksumMismatch:
      return "kChecksumMismatch";
    case WfdbStatus::kInvalidSampleValue:
      return "kInvalidSampleValue";
    case WfdbStatus::kSampleOutOfRange:
      return "kSampleOutOfRange";
    case WfdbStatus::kMalformedRecording:
      return "kMalformedRecording";
    case WfdbStatus::kReferenceMismatch:
      return "kReferenceMismatch";
    case WfdbStatus::kStartBeyondEnd:
      return "kStartBeyondEnd";
    case WfdbStatus::kInvalidName:
      return "kInvalidName";
    case WfdbStatus::kInvalidMetadata:
      return "kInvalidMetadata";
    case WfdbStatus::kAlreadyExists:
      return "kAlreadyExists";
    case WfdbStatus::kWriteFailed:
      return "kWriteFailed";
    case WfdbStatus::kSampleOutOfFormat:
      return "kSampleOutOfFormat";
    case WfdbStatus::kTooManyEvents:
      return "kTooManyEvents";
    case WfdbStatus::kEmptyRecording:
      return "kEmptyRecording";
    case WfdbStatus::kWriterFailed:
      return "kWriterFailed";
  }
  return "unknown";
}

}  // namespace sinus::desktop::test
