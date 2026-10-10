// SRS-034: equivalence of the real-time library with the reference on the golden vectors
// (architecture-m2.md 14.11, 14.12).
#include "sinus/dsp/verification/equivalence.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/heart_rate.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/signal_quality.hpp"
#include "sinus/dsp/status.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"

namespace sinus::dsp::verification {

namespace {

constexpr std::string_view kBaseline = "baseline";
constexpr std::string_view kMains = "mains";

void collect_detections(const SampleOutput& out, LibraryOutputs& result) {
  for (std::size_t k = 0; k < out.detection_count; ++k) {
    const Detection& d = out.detections.at(k);
    result.beats.push_back(BeatRow{d.index, d.mark, d.reported_at});
  }
}

void collect_heart_rates(const SampleOutput& out, LibraryOutputs& result) {
  for (std::size_t k = 0; k < out.heart_rate_count; ++k) {
    const HeartRateEvent& e = out.heart_rates.at(k);
    const bool has_rate =
        e.status == HeartRateStatus::kValid || e.status == HeartRateStatus::kOutOfRange;
    result.heart_rates.push_back(HeartRateRow{e.sample, e.has_beat, e.has_beat ? e.beat_index : 0U,
                                              e.status, has_rate,
                                              has_rate ? static_cast<double>(e.bpm) : 0.0});
  }
}

void collect_window(const SampleOutput& out, LibraryOutputs& result) {
  if (out.has_window) {
    const QualityWindow& w = out.window;
    result.windows.push_back(WindowRow{w.first_sample, w.last_sample, w.reported_at,
                                       static_cast<double>(w.index), w.usable});
  }
}

// --- comparison ---------------------------------------------------------------------------------

double absolute_difference(std::uint64_t a, std::uint64_t b) noexcept {
  return static_cast<double>(a > b ? a - b : b - a);
}

// The largest difference of an output, and the first sample where it occurs.
struct Largest {
  double value = 0.0;
  bool has = false;
  std::uint64_t sample = 0;

  // NOLINTNEXTLINE(bugprone-easily-swappable-parameters): the value and the place it is at.
  void offer(double difference, std::uint64_t at) noexcept {
    if (!(difference <= std::numeric_limits<double>::max())) {
      difference = std::numeric_limits<double>::infinity();  // NaN or infinite never passes
    }
    if (!has || difference > value) {
      value = difference;
      sample = at;
      has = true;
    }
  }
};

OutputResult numeric_result(std::string_view output, const Largest& largest, double tolerance) {
  OutputResult result;
  result.output = std::string(output);
  result.largest = largest.value;
  result.has_sample = largest.has;
  result.sample = largest.sample;
  result.tolerance = tolerance;
  result.pass = !largest.has || largest.value <= tolerance;
  return result;
}

// NOLINTBEGIN(bugprone-easily-swappable-parameters): the fields of the result, in order.
OutputResult structural_result(std::string_view output, std::string difference,
                               std::uint64_t sample, double tolerance) {
  OutputResult result;
  result.output = std::string(output);
  result.difference = std::move(difference);
  result.has_sample = true;
  result.sample = sample;
  result.tolerance = tolerance;
  result.pass = false;
  return result;
}
// NOLINTEND(bugprone-easily-swappable-parameters)

std::string count_difference(std::size_t library, std::size_t file) {
  return "count " + std::to_string(library) + ", file " + std::to_string(file);
}

OutputResult compare_signal(std::string_view output, const std::vector<double>& library,
                            const std::vector<double>& file) {
  Largest largest;
  const std::size_t n = std::min(library.size(), file.size());
  for (std::size_t i = 0; i < n; ++i) {
    largest.offer(std::fabs(library.at(i) - file.at(i)), i);
  }
  return numeric_result(output, largest, kConditioningToleranceMv);
}

// The sample of the first element that only the longer list has.
template <typename Row, typename SampleOf>
std::uint64_t extra_sample(const std::vector<Row>& library, const std::vector<Row>& file,
                           SampleOf sample_of) {
  const std::size_t n = std::min(library.size(), file.size());
  return sample_of(library.size() > file.size() ? library.at(n) : file.at(n));
}

OutputResult compare_beats(const std::vector<BeatRow>& library, const std::vector<BeatRow>& file) {
  constexpr std::string_view output_name = "beats";
  const auto index_of = [](const BeatRow& row) { return row.index; };
  if (library.size() != file.size()) {
    return structural_result(output_name, count_difference(library.size(), file.size()),
                             extra_sample(library, file, index_of),
                             kDetectionIndexToleranceSamples);
  }
  for (std::size_t i = 0; i < file.size(); ++i) {
    if (library.at(i).mark != file.at(i).mark) {
      return structural_result(output_name, "mark", file.at(i).index,
                               kDetectionIndexToleranceSamples);
    }
  }
  Largest largest;
  for (std::size_t i = 0; i < file.size(); ++i) {
    largest.offer(absolute_difference(library.at(i).index, file.at(i).index), file.at(i).index);
  }
  return numeric_result(output_name, largest, kDetectionIndexToleranceSamples);
}

OutputResult compare_report_samples(const std::vector<BeatRow>& library,
                                    const std::vector<BeatRow>& file) {
  constexpr std::string_view output_name = "beat_reported_at";
  if (library.size() != file.size()) {
    OutputResult result;
    result.output = std::string(output_name);
    result.difference = "not compared, the counts differ";
    result.tolerance = kReportSampleToleranceSamples;
    return result;
  }
  Largest largest;
  for (std::size_t i = 0; i < file.size(); ++i) {
    largest.offer(absolute_difference(library.at(i).reported_at, file.at(i).reported_at),
                  file.at(i).index);
  }
  return numeric_result(output_name, largest, kReportSampleToleranceSamples);
}

// The first difference of a heart-rate event that is not a rate, or "".
std::string heart_rate_structure(const HeartRateRow& library, const HeartRateRow& file) {
  if (library.sample != file.sample) {
    return "sample";
  }
  if (library.has_beat != file.has_beat ||
      (file.has_beat && library.beat_index != file.beat_index)) {
    return "beat index";
  }
  if (library.status != file.status) {
    return "status";
  }
  return {};
}

OutputResult compare_heart_rates(const std::vector<HeartRateRow>& library,
                                 const std::vector<HeartRateRow>& file) {
  constexpr std::string_view output_name = "heart_rates";
  if (library.size() != file.size()) {
    return structural_result(
        output_name, count_difference(library.size(), file.size()),
        extra_sample(library, file, [](const HeartRateRow& row) { return row.sample; }),
        kHeartRateToleranceBpm);
  }
  for (std::size_t i = 0; i < file.size(); ++i) {
    std::string difference = heart_rate_structure(library.at(i), file.at(i));
    if (!difference.empty()) {
      return structural_result(output_name, std::move(difference), file.at(i).sample,
                               kHeartRateToleranceBpm);
    }
  }
  Largest largest;
  for (std::size_t i = 0; i < file.size(); ++i) {
    if (file.at(i).has_rate) {
      largest.offer(std::fabs(library.at(i).bpm - file.at(i).bpm), file.at(i).sample);
    }
  }
  return numeric_result(output_name, largest, kHeartRateToleranceBpm);
}

std::string window_structure(const WindowRow& library, const WindowRow& file) {
  if (library.first_sample != file.first_sample) {
    return "first sample";
  }
  if (library.last_sample != file.last_sample) {
    return "last sample";
  }
  if (library.reported_at != file.reported_at) {
    return "report sample";
  }
  if (library.usable != file.usable) {
    return "usable mark";
  }
  return {};
}

OutputResult compare_windows(const std::vector<WindowRow>& library,
                             const std::vector<WindowRow>& file) {
  constexpr std::string_view output_name = "quality_windows";
  if (library.size() != file.size()) {
    return structural_result(
        output_name, count_difference(library.size(), file.size()),
        extra_sample(library, file, [](const WindowRow& row) { return row.first_sample; }),
        kQualityIndexTolerance);
  }
  for (std::size_t i = 0; i < file.size(); ++i) {
    std::string difference = window_structure(library.at(i), file.at(i));
    if (!difference.empty()) {
      return structural_result(output_name, std::move(difference), file.at(i).first_sample,
                               kQualityIndexTolerance);
    }
  }
  Largest largest;
  for (std::size_t i = 0; i < file.size(); ++i) {
    largest.offer(std::fabs(library.at(i).index - file.at(i).index), file.at(i).first_sample);
  }
  return numeric_result(output_name, largest, kQualityIndexTolerance);
}

bool has_stages(const GoldenVector& vector) {
  return vector.stages.size() == 2 && vector.stages.at(0) == kBaseline &&
         vector.stages.at(1) == kMains;
}

}  // namespace

void collect_events(const SampleOutput& out, LibraryOutputs& result) {
  collect_detections(out, result);
  collect_heart_rates(out, result);
  collect_window(out, result);
}

LibraryOutputs run_library(const GoldenVector& vector) {
  LibraryOutputs result;
  auto chain = std::make_unique<Chain>();
  result.status = chain->configure(Config{vector.fs_hz, vector.mains_hz});
  if (result.status != Status::kOk) {
    return result;
  }
  auto out = std::make_unique<SampleOutput>();
  result.baseline_mv.reserve(vector.input_mv.size());
  result.conditioned_mv.reserve(vector.input_mv.size());
  for (std::size_t n = 0; n < vector.input_mv.size(); ++n) {
    result.status = chain->process(static_cast<float>(vector.input_mv.at(n)), *out);
    if (result.status != Status::kOk) {
      result.failed_at = n;
      return result;
    }
    result.baseline_mv.push_back(static_cast<double>(out->baseline_mv));
    result.conditioned_mv.push_back(static_cast<double>(out->conditioned_mv));
    collect_events(*out, result);
  }
  return result;
}

std::vector<OutputResult> compare_outputs(const GoldenVector& vector,
                                          const LibraryOutputs& library) {
  std::vector<OutputResult> results;
  results.push_back(
      compare_signal("baseline_mv", library.baseline_mv, vector.stage_outputs_mv.at(0)));
  results.push_back(
      compare_signal("mains_mv", library.conditioned_mv, vector.stage_outputs_mv.at(1)));
  results.push_back(compare_beats(library.beats, vector.beats));
  results.push_back(compare_report_samples(library.beats, vector.beats));
  results.push_back(compare_heart_rates(library.heart_rates, vector.heart_rates));
  results.push_back(compare_windows(library.windows, vector.windows));
  return results;
}

bool FileResult::passed() const {
  return status == FileStatus::kCompared &&
         std::all_of(outputs.begin(), outputs.end(),
                     [](const OutputResult& output) { return output.pass; });
}

std::size_t SetResult::expected_present() const {
  return static_cast<std::size_t>(
      std::count_if(files.begin(), files.end(), [](const FileResult& file) {
        return file.status != FileStatus::kMissing && file.status != FileStatus::kUnexpected;
      }));
}

FileResult check_vector(const std::string& input_id, const GoldenVector& vector) {
  FileResult result;
  result.input_id = input_id;
  result.has_identity = true;
  result.software_version = vector.software_version;
  result.source_sha256 = vector.source_sha256;
  if (!has_stages(vector)) {
    result.status = FileStatus::kNotComparable;
    result.detail = "the stages are not baseline,mains";
    return result;
  }
  const LibraryOutputs library = run_library(vector);
  if (library.status != Status::kOk) {
    result.status = FileStatus::kNotComparable;
    result.detail = "the library returns status " +
                    std::to_string(static_cast<unsigned>(library.status)) + " at sample " +
                    std::to_string(library.failed_at);
    return result;
  }
  result.outputs = compare_outputs(vector, library);
  return result;
}

ReferenceIdentity reference_identity(const SetResult& set) {
  ReferenceIdentity identity;
  for (const FileResult& file : set.files) {
    if (!file.has_identity) {
      continue;
    }
    if (identity.state == ReferenceState::kNone) {
      identity.state = ReferenceState::kSame;
      identity.software_version = file.software_version;
      identity.source_sha256 = file.source_sha256;
    } else if (identity.software_version != file.software_version ||
               identity.source_sha256 != file.source_sha256) {
      identity.state = ReferenceState::kMixed;
    }
  }
  return identity;
}

bool set_passed(const SetResult& set) {
  return set.folder_listed && !set.files.empty() &&
         std::all_of(set.files.begin(), set.files.end(),
                     [](const FileResult& file) { return file.passed(); }) &&
         reference_identity(set).state == ReferenceState::kSame;
}

}  // namespace sinus::dsp::verification
