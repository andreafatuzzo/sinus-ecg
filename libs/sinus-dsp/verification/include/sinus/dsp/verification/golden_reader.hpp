#pragma once

// SRS-034: the reader of the golden-vector files of the reference (architecture.md 7.3,
// architecture-m2.md 13.8, 14.12). It reads format version 2 only and applies every reader rule of
// those sections, naming the first offending line, as the Python reader
// (dsp/sinus_dsp/golden.py, parse_golden_vector) does: the two reject the same texts at the same
// line. The reason given with the line is free text and is not compared.

#include <array>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "sinus/dsp/heart_rate.hpp"
#include "sinus/dsp/qrs_detector.hpp"

namespace sinus::dsp::verification {

inline constexpr int kGoldenFormatVersion = 2;

struct BeatRow {
  std::uint64_t index;
  Mark mark;
  std::uint64_t reported_at;
};

struct HeartRateRow {
  std::uint64_t sample;
  bool has_beat;
  std::uint64_t beat_index;  // meaningful when has_beat
  HeartRateStatus status;
  bool has_rate;  // valid and out of range
  double bpm;     // meaningful when has_rate
};

struct WindowRow {
  std::uint64_t first_sample;
  std::uint64_t last_sample;
  std::uint64_t reported_at;
  double index;
  bool usable;
};

struct GoldenVector {
  std::string input_id;
  std::string input_source;
  std::string input_parameters;
  double fs_hz = 0.0;
  int mains_hz = 0;
  std::string software_version;
  std::string source_sha256;
  std::vector<std::string> stages;
  std::vector<std::vector<std::array<double, 5>>> coefficients;  // b0 b1 b2 a1 a2, by stage
  std::vector<double> input_mv;
  std::vector<std::vector<double>> stage_outputs_mv;  // by stage
  std::vector<BeatRow> beats;
  std::vector<std::uint64_t> reference_beats;
  std::vector<HeartRateRow> heart_rates;
  std::vector<WindowRow> windows;
};

struct ReadError {
  bool has_line = false;  // false only for a file that is not UTF-8 text
  std::uint64_t line = 0;
  std::string reason;
};

struct ReadResult {
  bool ok = false;
  ReadError error;
  GoldenVector vector;
};

// The text of a file. A text that is not UTF-8 is rejected with no line (reason "not UTF-8 text").
[[nodiscard]] ReadResult parse_golden_vector(std::string_view bytes);

// Reads a file and parses it. A file that cannot be read is rejected with no line.
[[nodiscard]] ReadResult read_golden_vector(const std::string& path);

}  // namespace sinus::dsp::verification
