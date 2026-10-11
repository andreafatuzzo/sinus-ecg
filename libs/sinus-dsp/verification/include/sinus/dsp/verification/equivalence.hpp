#pragma once

// SRS-034: the equivalence of the real-time library with the reference on the golden vectors
// (architecture-m2.md 14.11, 14.12). A newly configured Chain is given the input of a vector one
// sample at a time, and its outputs are compared with the file's, each with its largest difference,
// the sample where it occurs and its tolerance.

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/status.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"

namespace sinus::dsp::verification {

// Tolerances of architecture-m2.md 14.11 (approved 2026-10-08, OP-005).
inline constexpr double kConditioningToleranceMv = 2e-5;
inline constexpr double kDetectionIndexToleranceSamples = 0.0;
inline constexpr double kReportSampleToleranceSamples = 0.0;
inline constexpr double kHeartRateToleranceBpm = 1e-4;
inline constexpr double kQualityIndexTolerance = 0.01;

// What the library produced for the input of a vector.
struct LibraryOutputs {
  Status status = Status::kOk;  // the first status other than kOk, from configure or process
  std::uint64_t failed_at = 0;  // the sample where process failed
  std::vector<double> baseline_mv;
  std::vector<double> conditioned_mv;
  std::vector<BeatRow> beats;
  std::vector<HeartRateRow> heart_rates;
  std::vector<WindowRow> windows;
};

// Appends the detections, heart-rate events and quality window that the chain reported at one
// sample (not the two signals).
void collect_events(const SampleOutput& out, LibraryOutputs& result);

// Configures a new Chain with the sampling frequency and the mains setting of the vector and runs
// its input, each value as a binary32 (static_cast<float>). The vector's stages must be
// baseline, mains.
[[nodiscard]] LibraryOutputs run_library(const GoldenVector& vector);

// One compared output of one file.
struct OutputResult {
  std::string output;      // baseline_mv, mains_mv, beats, beat_reported_at, heart_rates,
                           // quality_windows
  std::string difference;  // a structural difference ("count 74, file 73", "mark"); else empty
  double largest = 0.0;    // the largest difference, when `difference` is empty
  bool has_sample = false;
  std::uint64_t sample = 0;  // the first sample where the largest difference or the structural
                             // difference occurs
  double tolerance = 0.0;
  bool pass = false;
};

// The six outputs, in the order of the report. A structural difference fails its output and is
// reported at the first sample where it occurs, in place of a largest difference.
[[nodiscard]] std::vector<OutputResult> compare_outputs(const GoldenVector& vector,
                                                        const LibraryOutputs& library);

enum class FileStatus : std::uint8_t {
  kCompared,       // read, run and compared
  kMissing,        // expected, not in the folder
  kUnexpected,     // in the folder, not expected
  kRejected,       // the reader rejected it (or it cannot be read)
  kNotComparable,  // read, but the library cannot run it
};

struct FileResult {
  std::string input_id;
  FileStatus status = FileStatus::kCompared;
  std::string detail;  // why, for a status other than kCompared
  std::vector<OutputResult> outputs;
  bool has_identity = false;  // the reference software, from the file
  std::string software_version;
  std::string source_sha256;

  [[nodiscard]] bool passed() const;
};

struct SetResult {
  bool folder_listed = false;
  std::vector<FileResult> files;  // the expected inputs in order, then the unexpected files

  [[nodiscard]] std::size_t expected_present() const;
};

// The result for the vector of one file.
[[nodiscard]] FileResult check_vector(const std::string& input_id, const GoldenVector& vector);

// Reads, runs and compares one file.
[[nodiscard]] FileResult check_file(const std::string& input_id, const std::string& path);

// The whole folder: every expected input (golden_set.hpp), a missing or unexpected file named.
// Other files (NOTICE.md) are ignored.
[[nodiscard]] SetResult check_folder(const std::string& folder);

enum class ReferenceState : std::uint8_t { kNone, kSame, kMixed };

struct ReferenceIdentity {
  ReferenceState state = ReferenceState::kNone;
  std::string software_version;
  std::string source_sha256;
};

// The software that wrote the files: the version and the source digest they state, if all agree.
[[nodiscard]] ReferenceIdentity reference_identity(const SetResult& set);

// Every file passes and the reference software is the same in all of them.
[[nodiscard]] bool set_passed(const SetResult& set);

}  // namespace sinus::dsp::verification
