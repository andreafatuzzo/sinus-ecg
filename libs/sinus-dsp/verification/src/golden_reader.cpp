// SRS-034: reader of the golden-vector files (architecture.md 7.3, architecture-m2.md 13.8, 14.12).
// It follows dsp/sinus_dsp/golden.py (parse_golden_vector, read_golden_vector) rule by rule and in
// the same order, so that both readers reject the same texts at the same line.
#include "sinus/dsp/verification/golden_reader.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <ios>
#include <iterator>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

#include "sinus/dsp/heart_rate.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/signal_quality.hpp"

namespace sinus::dsp::verification {

namespace {

constexpr std::size_t kHeaderKeyCount = 15;
constexpr std::array<std::string_view, kHeaderKeyCount> kHeaderKeys{"format",
                                                                    "format_version",
                                                                    "input_id",
                                                                    "input_source",
                                                                    "input_parameters",
                                                                    "sampling_frequency_hz",
                                                                    "mains_frequency_hz",
                                                                    "software_version",
                                                                    "source_sha256",
                                                                    "stages",
                                                                    "n_samples",
                                                                    "n_beats",
                                                                    "n_reference_beats",
                                                                    "n_heart_rates",
                                                                    "n_quality_windows"};
constexpr std::size_t kKeyFormat = 0;
constexpr std::size_t kKeyVersion = 1;
constexpr std::size_t kKeyInputId = 2;
constexpr std::size_t kKeySamplingFrequency = 5;
constexpr std::size_t kKeyMains = 6;
constexpr std::size_t kKeySha256 = 8;
constexpr std::size_t kKeyStages = 9;
constexpr std::size_t kKeySamples = 10;
constexpr std::size_t kKeyBeats = 11;
constexpr std::size_t kKeyReferenceBeats = 12;
constexpr std::size_t kKeyHeartRates = 13;
constexpr std::size_t kKeyWindows = 14;

constexpr std::string_view kFormatName = "sinus-golden-vector";
constexpr std::string_view kCoefficients = "[coefficients]";
constexpr std::string_view kCoefficientColumns = "stage,section,b0,b1,b2,a1,a2";
constexpr std::string_view kSignals = "[signals]";
constexpr std::string_view kBeats = "[beats]";
constexpr std::string_view kBeatColumns = "sample_index,mark,reported_at";
constexpr std::string_view kReferenceBeats = "[reference_beats]";
constexpr std::string_view kIndexColumn = "sample_index";
constexpr std::string_view kHeartRates = "[heart_rates]";
constexpr std::string_view kHeartRateColumns = "sample_index,beat_index,status,heart_rate_bpm";
constexpr std::string_view kWindows = "[quality_windows]";
constexpr std::string_view kWindowColumns =
    "first_sample,last_sample,reported_at,quality_index,usable";
constexpr std::string_view kEnd = "[end]";
constexpr std::string_view kByteOrderMark = "\xEF\xBB\xBF";
constexpr std::string_view kIntegerMaxText = "9223372036854775807";  // 2^63 - 1
constexpr std::size_t kCoefficientFields = 7;
constexpr std::size_t kShownLength = 40;
constexpr std::size_t kSha256Digits = 64;

using Fields = std::vector<std::string_view>;

bool is_digit(char c) noexcept { return c >= '0' && c <= '9'; }

bool all_digits(std::string_view text) noexcept {
  return !text.empty() && std::all_of(text.begin(), text.end(), is_digit);
}

bool starts_with(std::string_view text, std::string_view prefix) noexcept {
  return text.substr(0, prefix.size()) == prefix;
}

// The end of a text as a pointer, for std::from_chars.
const char* end_of(std::string_view text) noexcept {
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): the one past-the-end pointer.
  return text.data() + text.size();
}

// A piece of text as an error shows it: at most 40 characters.
std::string shown(std::string_view text) {
  std::string out(text.substr(0, kShownLength));
  if (text.size() > kShownLength) {
    out += "...";
  }
  return out;
}

// Python's str.split(sep): empty pieces are kept.
Fields split(std::string_view text, char separator) {
  Fields pieces;
  std::size_t start = 0;
  while (true) {
    const std::size_t at = text.find(separator, start);
    if (at == std::string_view::npos) {
      pieces.push_back(text.substr(start));
      return pieces;
    }
    pieces.push_back(text.substr(start, at - start));
    start = at + 1;
  }
}

// --- UTF-8 ------------------------------------------------------------------------------------

unsigned byte_at(std::string_view text, std::size_t i) noexcept {
  return static_cast<unsigned char>(text.at(i));
}

bool in_range(unsigned value, unsigned low, unsigned high) noexcept {
  return value >= low && value <= high;
}

// The length of the well-formed UTF-8 sequence that starts at i (Unicode table 3-7), or 0.
std::size_t sequence_length(std::string_view text, std::size_t i) noexcept {
  const unsigned lead = byte_at(text, i);
  if (lead < 0x80U) {
    return 1;
  }
  std::size_t length = 0;
  unsigned second_low = 0x80U;
  unsigned second_high = 0xBFU;
  if (in_range(lead, 0xC2U, 0xDFU)) {
    length = 2;
  } else if (in_range(lead, 0xE0U, 0xEFU)) {
    length = 3;
    second_low = lead == 0xE0U ? 0xA0U : second_low;
    second_high = lead == 0xEDU ? 0x9FU : second_high;
  } else if (in_range(lead, 0xF0U, 0xF4U)) {
    length = 4;
    second_low = lead == 0xF0U ? 0x90U : second_low;
    second_high = lead == 0xF4U ? 0x8FU : second_high;
  } else {
    return 0;
  }
  if (i + length > text.size() || !in_range(byte_at(text, i + 1), second_low, second_high)) {
    return 0;
  }
  for (std::size_t k = 2; k < length; ++k) {
    if (!in_range(byte_at(text, i + k), 0x80U, 0xBFU)) {
      return 0;
    }
  }
  return length;
}

bool is_utf8(std::string_view text) noexcept {
  std::size_t i = 0;
  while (i < text.size()) {
    const std::size_t length = sequence_length(text, i);
    if (length == 0) {
      return false;
    }
    i += length;
  }
  return true;
}

// --- numbers (architecture.md 7.3, "Numbers") ---------------------------------------------------

// -?[0-9]+(\.[0-9]+)?(e[+-][0-9]+)?
bool float_syntax(std::string_view text) noexcept {
  std::size_t i = (!text.empty() && text.front() == '-') ? 1U : 0U;
  const auto skip_digits = [&text, &i]() {
    const std::size_t start = i;
    while (i < text.size() && is_digit(text.at(i))) {
      ++i;
    }
    return i > start;
  };
  if (!skip_digits()) {
    return false;
  }
  if (i < text.size() && text.at(i) == '.') {
    ++i;
    if (!skip_digits()) {
      return false;
    }
  }
  if (i < text.size() && text.at(i) == 'e') {
    ++i;
    if (i >= text.size() || (text.at(i) != '+' && text.at(i) != '-')) {
      return false;
    }
    ++i;
    if (!skip_digits()) {
      return false;
    }
  }
  return i == text.size();
}

// Why a text is not a float of the format, or "". The value is converted after the syntax check and
// must be finite and not zero unless every digit of its significand is zero: the two rules on the
// converted value give the same outcome whether the library returns infinity or zero or reports
// the value as out of range (architecture.md 7.3).
std::string float_problem(std::string_view text, double& value) {
  if (!float_syntax(text)) {
    return "not a float: " + shown(text);
  }
  const bool significand_not_zero =
      text.substr(0, text.find('e')).find_first_of("123456789") != std::string_view::npos;
  double parsed = 0.0;
  // NOLINTNEXTLINE(bugprone-suspicious-stringview-data-usage): the end is given by end_of.
  const auto result = std::from_chars(text.data(), end_of(text), parsed);
  if (result.ec == std::errc::result_out_of_range) {
    if (significand_not_zero) {
      return "not a finite float, or converts to zero: " + shown(text);
    }
    parsed = (text.front() == '-') ? -0.0 : 0.0;
  } else if (result.ec != std::errc() || result.ptr != end_of(text)) {
    return "not a float: " + shown(text);
  }
  if (!std::isfinite(parsed)) {
    return "not a finite float: " + shown(text);
  }
  if (parsed == 0.0 && significand_not_zero) {
    return "float that converts to zero although its significand is not zero: " + shown(text);
  }
  value = parsed;
  return {};
}

// 0|[1-9][0-9]*, not greater than 2^63 - 1 (checked on the text, before any conversion).
std::string integer_problem(std::string_view text, std::uint64_t& value) {
  if (!all_digits(text) || (text.front() == '0' && text.size() > 1)) {
    return "not an integer: " + shown(text);
  }
  if (text.size() > kIntegerMaxText.size() ||
      (text.size() == kIntegerMaxText.size() && text > kIntegerMaxText)) {
    return "integer greater than " + std::string(kIntegerMaxText) + ": " + shown(text);
  }
  // NOLINTNEXTLINE(bugprone-suspicious-stringview-data-usage): the end is given by end_of.
  const auto result = std::from_chars(text.data(), end_of(text), value);
  if (result.ec != std::errc()) {
    return "not an integer: " + shown(text);
  }
  return {};
}

// --- header values ------------------------------------------------------------------------------

bool is_input_id(std::string_view text) noexcept {
  return !text.empty() && std::all_of(text.begin(), text.end(), [](char c) {
    return is_digit(c) || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || c == '-';
  });
}

bool is_sha256(std::string_view text) noexcept {
  return text.size() == kSha256Digits && std::all_of(text.begin(), text.end(), [](char c) {
           return is_digit(c) || (c >= 'a' && c <= 'f');
         });
}

// [a-z][a-z0-9_]*
bool is_stage_name(std::string_view text) noexcept {
  if (text.empty() || text.front() < 'a' || text.front() > 'z') {
    return false;
  }
  return std::all_of(text.begin(), text.end(),
                     [](char c) { return is_digit(c) || (c >= 'a' && c <= 'z') || c == '_'; });
}

std::string stages_problem(const Fields& stages) {
  if (stages.empty()) {
    return "no stage given";
  }
  for (std::size_t i = 0; i < stages.size(); ++i) {
    if (!is_stage_name(stages.at(i))) {
      return "invalid stage name " + shown(stages.at(i));
    }
    if (std::find(stages.begin(), stages.begin() + static_cast<std::ptrdiff_t>(i), stages.at(i)) !=
        stages.begin() + static_cast<std::ptrdiff_t>(i)) {
      return "stage " + shown(stages.at(i)) + " given twice";
    }
  }
  return {};
}

std::string sampling_frequency_problem(std::string_view value) {
  double fs = 0.0;
  const std::string problem = float_problem(value, fs);
  if (!problem.empty()) {
    return "sampling_frequency_hz: " + problem;
  }
  return fs > 0.0 ? std::string() : "sampling_frequency_hz is not positive: " + shown(value);
}

std::string count_problem(std::size_t key, std::string_view value) {
  std::uint64_t count = 0;
  const std::string problem = integer_problem(value, count);
  if (!problem.empty()) {
    return std::string(kHeaderKeys.at(key)) + ": " + problem;
  }
  if (key == kKeySamples && count < 1) {
    return "n_samples is not at least 1";
  }
  return {};
}

// Why a header value breaks the rules of its key, or "".
std::string header_value_problem(std::size_t key, std::string_view value) {
  switch (key) {
    case kKeyFormat:
      return value == kFormatName ? std::string() : "unknown format " + shown(value);
    case kKeyVersion:
      return value == "2" ? std::string() : "unknown format version " + shown(value);
    case kKeyInputId:
      return is_input_id(value) ? std::string() : "input_id does not match [A-Za-z0-9_-]+";
    case kKeySamplingFrequency:
      return sampling_frequency_problem(value);
    case kKeyMains:
      return (value == "50" || value == "60") ? std::string()
                                              : "mains_frequency_hz is not 50 or 60";
    case kKeySha256:
      return is_sha256(value) ? std::string()
                              : "source_sha256 is not 64 lowercase hexadecimal digits";
    case kKeyStages: {
      const std::string problem = stages_problem(value.empty() ? Fields() : split(value, ','));
      return problem.empty() ? problem : "stages: " + problem;
    }
    case kKeySamples:
    case kKeyBeats:
    case kKeyReferenceBeats:
    case kKeyHeartRates:
    case kKeyWindows:
      return count_problem(key, value);
    default:  // input_source, input_parameters, software_version
      return value.empty() ? std::string(kHeaderKeys.at(key)) + " is empty" : std::string();
  }
}

// --- the parser ---------------------------------------------------------------------------------

class Parser {
 public:
  explicit Parser(std::string_view text) {
    std::size_t start = 0;
    while (true) {
      const std::size_t at = text.find('\n', start);
      if (at == std::string_view::npos) {
        if (start < text.size()) {
          lines_.push_back(text.substr(start));
        }
        break;
      }
      lines_.push_back(text.substr(start, at - start));
      ++complete_;
      start = at + 1;
    }
  }

  bool parse();
  [[nodiscard]] ReadError take_error() { return std::move(error_); }
  [[nodiscard]] GoldenVector take_vector() { return std::move(v_); }

 private:
  using RowFunction = bool (Parser::*)(std::uint64_t, const Fields&);

  bool fail(std::uint64_t line, std::string reason);
  bool take(std::string_view expected, std::uint64_t& number, std::string_view& line);
  bool expect(std::string_view expected);
  bool finish();
  [[nodiscard]] std::uint64_t last_number() const { return std::max<std::uint64_t>(next_, 1); }

  bool get_uint(std::uint64_t number, std::string_view text, std::uint64_t& value);
  bool get_real(std::uint64_t number, std::string_view text, double& value);
  bool read_rows(std::string_view section, std::uint64_t count, std::size_t width, RowFunction row);

  bool read_header();
  void store_header();
  bool read_coefficients();
  bool read_coefficient_row(std::uint64_t number, const Fields& fields, std::size_t& current);
  bool read_signals();
  bool read_signal_row(std::uint64_t number, const Fields& fields);
  bool read_beat_row(std::uint64_t number, const Fields& fields);
  bool read_reference_row(std::uint64_t number, const Fields& fields);
  bool read_heart_rates();
  bool read_heart_rate_row(std::uint64_t number, const Fields& fields);
  bool name_reliable(std::uint64_t number, std::string_view text, HeartRateRow& row);
  bool read_status_and_rate(std::uint64_t number, const Fields& fields, HeartRateRow& row);
  bool read_window_row(std::uint64_t number, const Fields& fields);
  [[nodiscard]] std::string signal_columns() const;

  GoldenVector v_;
  std::vector<std::string_view> lines_;
  std::size_t complete_ = 0;  // lines followed by a line feed
  std::size_t next_ = 0;      // lines read
  ReadError error_;
  std::array<std::string_view, kHeaderKeyCount> header_{};
  std::uint64_t n_samples_ = 0;
  std::uint64_t n_beats_ = 0;
  std::uint64_t n_reference_beats_ = 0;
  std::uint64_t n_heart_rates_ = 0;
  std::uint64_t n_windows_ = 0;
  std::vector<std::pair<std::uint64_t, std::uint64_t>> reliable_;  // index, reported_at
  std::size_t named_ = 0;
};

bool Parser::fail(std::uint64_t line, std::string reason) {
  error_.has_line = true;
  error_.line = line;
  error_.reason = std::move(reason);
  return false;
}

bool Parser::take(std::string_view expected, std::uint64_t& number, std::string_view& line) {
  if (next_ >= lines_.size()) {
    return fail(std::max<std::uint64_t>(lines_.size(), 1),
                "the file ends before " + std::string(expected));
  }
  number = next_ + 1;
  line = lines_.at(next_);
  ++next_;
  if (line.empty()) {
    return fail(number, "empty line");
  }
  if (number == 1 && starts_with(line, kByteOrderMark)) {
    return fail(number, "the file starts with a byte-order mark");
  }
  if (line.find_first_of(" \t\r") != std::string_view::npos) {
    return fail(number, "the line holds a space, a tab or a carriage return");
  }
  return true;
}

bool Parser::expect(std::string_view expected) {
  std::uint64_t number = 0;
  std::string_view line;
  if (!take(expected, number, line)) {
    return false;
  }
  if (line != expected) {
    return fail(number, "expected " + std::string(expected) + ", found " + shown(line));
  }
  return true;
}

// After [end]: a line feed, and nothing else.
bool Parser::finish() {
  if (next_ > complete_) {
    return fail(next_, "no line feed after [end]");
  }
  if (next_ < lines_.size()) {
    return fail(next_ + 1, "text after [end]");
  }
  return true;
}

bool Parser::get_uint(std::uint64_t number, std::string_view text, std::uint64_t& value) {
  const std::string problem = integer_problem(text, value);
  return problem.empty() || fail(number, problem);
}

bool Parser::get_real(std::uint64_t number, std::string_view text, double& value) {
  const std::string problem = float_problem(text, value);
  return problem.empty() || fail(number, problem);
}

// The `count` rows of a section: each line must exist, must not be a section line, and must have
// `width` fields; `row` checks and stores the fields.
bool Parser::read_rows(std::string_view section, std::uint64_t count, std::size_t width,
                       RowFunction row) {
  for (std::uint64_t index = 0; index < count; ++index) {
    std::uint64_t number = 0;
    std::string_view line;
    if (!take(section, number, line)) {
      return false;
    }
    if (starts_with(line, "[")) {
      return fail(number, std::string(section) + " has " + std::to_string(index) +
                              " rows, its count is " + std::to_string(count));
    }
    const Fields fields = split(line, ',');
    if (fields.size() != width) {
      return fail(number, "row with " + std::to_string(fields.size()) + " fields, expected " +
                              std::to_string(width));
    }
    if (!(this->*row)(number, fields)) {
      return false;
    }
  }
  return true;
}

bool Parser::read_header() {
  for (std::size_t i = 0; i < kHeaderKeyCount; ++i) {
    std::uint64_t number = 0;
    std::string_view line;
    if (!take(kHeaderKeys.at(i), number, line)) {
      return false;
    }
    const std::size_t equals = line.find('=');
    if (equals == std::string_view::npos) {
      return fail(number, "not a key=value line: expected the header key " +
                              std::string(kHeaderKeys.at(i)));
    }
    const std::string_view found = line.substr(0, equals);
    if (found != kHeaderKeys.at(i)) {
      return fail(number, "header key " + shown(found) + " where " +
                              std::string(kHeaderKeys.at(i)) + " is expected");
    }
    const std::string_view value = line.substr(equals + 1);
    const std::string problem = header_value_problem(i, value);
    if (!problem.empty()) {
      return fail(number, problem);
    }
    header_.at(i) = value;
  }
  store_header();
  return true;
}

// The header values have been checked: convert them.
void Parser::store_header() {
  const auto count = [this](std::size_t key) {
    std::uint64_t value = 0;
    const std::string problem = integer_problem(header_.at(key), value);
    return problem.empty() ? value : 0U;
  };
  v_.input_id = std::string(header_.at(kKeyInputId));
  v_.input_source = std::string(header_.at(3));
  v_.input_parameters = std::string(header_.at(4));
  double fs = 0.0;
  const std::string problem = float_problem(header_.at(kKeySamplingFrequency), fs);
  v_.fs_hz = problem.empty() ? fs : 0.0;
  v_.mains_hz = header_.at(kKeyMains) == "50" ? 50 : 60;
  v_.software_version = std::string(header_.at(7));
  v_.source_sha256 = std::string(header_.at(kKeySha256));
  for (const std::string_view stage : split(header_.at(kKeyStages), ',')) {
    v_.stages.emplace_back(stage);
  }
  n_samples_ = count(kKeySamples);
  n_beats_ = count(kKeyBeats);
  n_reference_beats_ = count(kKeyReferenceBeats);
  n_heart_rates_ = count(kKeyHeartRates);
  n_windows_ = count(kKeyWindows);
}

std::string Parser::signal_columns() const {
  std::string columns = "input_mv";
  for (const std::string& stage : v_.stages) {
    columns += "," + stage + "_mv";
  }
  return columns;
}

bool Parser::read_coefficient_row(std::uint64_t number, const Fields& fields,
                                  std::size_t& current) {
  if (fields.size() != kCoefficientFields) {
    return fail(number,
                "coefficient row with " + std::to_string(fields.size()) + " fields, expected 7");
  }
  const std::string_view stage = fields.at(0);
  if (stage != v_.stages.at(current)) {
    const bool next_stage = !v_.coefficients.at(current).empty() &&
                            current + 1 < v_.stages.size() && stage == v_.stages.at(current + 1);
    if (!next_stage) {
      return fail(number, "coefficient row of the stage " + shown(stage) + " out of order");
    }
    ++current;
  }
  std::uint64_t section = 0;
  if (!get_uint(number, fields.at(1), section)) {
    return false;
  }
  auto& rows = v_.coefficients.at(current);
  if (section != rows.size()) {
    return fail(number, "section " + std::to_string(section) + " of the stage " + shown(stage) +
                            ", expected section " + std::to_string(rows.size()));
  }
  std::array<double, 5> values{};
  for (std::size_t k = 0; k < values.size(); ++k) {
    if (!get_real(number, fields.at(2 + k), values.at(k))) {
      return false;
    }
  }
  rows.push_back(values);
  return true;
}

// The rows of [coefficients] and the line [signals] that ends them.
bool Parser::read_coefficients() {
  v_.coefficients.resize(v_.stages.size());
  std::size_t current = 0;
  while (true) {
    std::uint64_t number = 0;
    std::string_view line;
    if (!take(kSignals, number, line)) {
      return false;
    }
    if (starts_with(line, "[")) {
      if (line != kSignals) {
        return fail(number, "expected [signals], found " + shown(line));
      }
      for (std::size_t i = 0; i < v_.stages.size(); ++i) {
        if (v_.coefficients.at(i).empty()) {
          return fail(number, "no coefficient row for the stage " + v_.stages.at(i));
        }
      }
      return true;
    }
    if (!read_coefficient_row(number, split(line, ','), current)) {
      return false;
    }
  }
}

bool Parser::read_signal_row(std::uint64_t number, const Fields& fields) {
  double value = 0.0;
  if (!get_real(number, fields.at(0), value)) {
    return false;
  }
  v_.input_mv.push_back(value);
  for (std::size_t k = 1; k < fields.size(); ++k) {
    if (!get_real(number, fields.at(k), value)) {
      return false;
    }
    v_.stage_outputs_mv.at(k - 1).push_back(value);
  }
  return true;
}

bool Parser::read_signals() {
  v_.stage_outputs_mv.resize(v_.stages.size());
  return read_rows(kSignals, n_samples_, v_.stages.size() + 1, &Parser::read_signal_row);
}

bool Parser::read_beat_row(std::uint64_t number, const Fields& fields) {
  std::uint64_t index = 0;
  if (!get_uint(number, fields.at(0), index)) {
    return false;
  }
  if (index >= n_samples_) {
    return fail(number, "sample " + std::to_string(index) + " is outside the signal");
  }
  if (!v_.beats.empty() && index <= v_.beats.back().index) {
    return fail(number, "sample " + std::to_string(index) + " is not greater than the one before");
  }
  Mark mark = Mark::kReliable;
  if (fields.at(1) == "startup") {
    mark = Mark::kStartUp;
  } else if (fields.at(1) != "reliable") {
    return fail(number, "mark is not startup or reliable: " + shown(fields.at(1)));
  }
  std::uint64_t reported = 0;
  if (!get_uint(number, fields.at(2), reported)) {
    return false;
  }
  if (reported < index) {
    return fail(number, "reported_at is before the sample_index");
  }
  if (reported >= n_samples_) {
    return fail(number, "reported_at is outside the signal");
  }
  if (!v_.beats.empty() && reported < v_.beats.back().reported_at) {
    return fail(number, "reported_at is before the one above it");
  }
  v_.beats.push_back(BeatRow{index, mark, reported});
  if (mark == Mark::kReliable) {
    reliable_.emplace_back(index, reported);
  }
  return true;
}

bool Parser::read_reference_row(std::uint64_t number, const Fields& fields) {
  std::uint64_t value = 0;
  if (!get_uint(number, fields.at(0), value)) {
    return false;
  }
  if (value >= n_samples_) {
    return fail(number, "sample " + std::to_string(value) + " is outside the signal");
  }
  if (!v_.reference_beats.empty() && value < v_.reference_beats.back()) {
    return fail(number, "sample " + std::to_string(value) + " is before the one above it");
  }
  v_.reference_beats.push_back(value);
  return true;
}

// A beat_index: the sample_index of a reliable detection of [beats], the next one not yet named,
// whose reported_at is this row's sample (architecture-m2.md 13.8).
bool Parser::name_reliable(std::uint64_t number, std::string_view text, HeartRateRow& row) {
  std::uint64_t beat_index = 0;
  if (!get_uint(number, text, beat_index)) {
    return false;
  }
  const auto at =
      std::lower_bound(v_.beats.begin(), v_.beats.end(), beat_index,
                       [](const BeatRow& beat, std::uint64_t index) { return beat.index < index; });
  if (at == v_.beats.end() || at->index != beat_index) {
    return fail(number, "beat_index " + std::to_string(beat_index) + " is not in [beats]");
  }
  if (named_ >= reliable_.size() || beat_index != reliable_.at(named_).first) {
    return fail(number, "beat_index " + std::to_string(beat_index) +
                            (at->mark == Mark::kStartUp ? " names a detection marked startup"
                                                        : " is not the next reliable detection"));
  }
  if (reliable_.at(named_).second != row.sample) {
    return fail(number, "sample_index is not the reported_at of the detection");
  }
  ++named_;
  row.has_beat = true;
  row.beat_index = beat_index;
  return true;
}

bool Parser::read_status_and_rate(std::uint64_t number, const Fields& fields, HeartRateRow& row) {
  const std::string_view status = fields.at(2);
  if (status == "valid") {
    row.status = HeartRateStatus::kValid;
  } else if (status == "not_enough_beats") {
    row.status = HeartRateStatus::kNotEnoughBeats;
  } else if (status == "no_recent_beat") {
    row.status = HeartRateStatus::kNoRecentBeat;
  } else if (status == "out_of_range") {
    row.status = HeartRateStatus::kOutOfRange;
  } else {
    return fail(number, "unknown status " + shown(status));
  }
  row.has_rate =
      row.status == HeartRateStatus::kValid || row.status == HeartRateStatus::kOutOfRange;
  if (!row.has_rate) {
    return fields.at(3).empty() ||
           fail(number, "heart_rate_bpm is given for the status " + std::string(status));
  }
  if (fields.at(3).empty()) {
    return fail(number, "heart_rate_bpm is empty for the status " + std::string(status));
  }
  if (!get_real(number, fields.at(3), row.bpm)) {
    return false;
  }
  return row.bpm > 0.0 || fail(number, "heart_rate_bpm is not greater than 0");
}

bool Parser::read_heart_rate_row(std::uint64_t number, const Fields& fields) {
  HeartRateRow row{0, false, 0, HeartRateStatus::kNotEnoughBeats, false, 0.0};
  if (!get_uint(number, fields.at(0), row.sample)) {
    return false;
  }
  if (row.sample >= n_samples_) {
    return fail(number, "sample " + std::to_string(row.sample) + " is outside the signal");
  }
  if (!v_.heart_rates.empty() && row.sample < v_.heart_rates.back().sample) {
    return fail(number, "sample is before the one above it");
  }
  if (!fields.at(1).empty() && !name_reliable(number, fields.at(1), row)) {
    return false;
  }
  if (!read_status_and_rate(number, fields, row)) {
    return false;
  }
  v_.heart_rates.push_back(row);
  return true;
}

// The reliable detections are all named once the counted rows have been read, before the line after
// them is read: a missing one is named at the last line read (architecture-m2.md 13.8).
bool Parser::read_heart_rates() {
  if (!read_rows(kHeartRates, n_heart_rates_, 4, &Parser::read_heart_rate_row)) {
    return false;
  }
  if (named_ < reliable_.size()) {
    return fail(last_number(), "the reliable detection " +
                                   std::to_string(reliable_.at(named_).first) +
                                   " has no row in [heart_rates]");
  }
  return true;
}

bool Parser::read_window_row(std::uint64_t number, const Fields& fields) {
  WindowRow row{0, 0, 0, 0.0, false};
  if (!get_uint(number, fields.at(0), row.first_sample)) {
    return false;
  }
  if (!v_.windows.empty() && row.first_sample <= v_.windows.back().first_sample) {
    return fail(number, "first_sample is not greater than the one above it");
  }
  if (!get_uint(number, fields.at(1), row.last_sample)) {
    return false;
  }
  if (row.last_sample < row.first_sample) {
    return fail(number, "last_sample is before the first_sample");
  }
  if (!get_uint(number, fields.at(2), row.reported_at)) {
    return false;
  }
  if (row.reported_at < row.last_sample) {
    return fail(number, "reported_at is before the last_sample");
  }
  if (row.reported_at >= n_samples_) {
    return fail(number, "reported_at is outside the signal");
  }
  if (!get_real(number, fields.at(3), row.index)) {
    return false;
  }
  if (row.index < 0.0 || row.index > 1.0) {
    return fail(number, "quality_index is outside 0 to 1");
  }
  if (fields.at(4) != "usable" && fields.at(4) != "not_usable") {
    return fail(number, "usable is not usable or not_usable: " + shown(fields.at(4)));
  }
  row.usable = fields.at(4) == "usable";
  if (row.usable != (row.index >= static_cast<double>(kUsableThreshold))) {
    return fail(number, "usable does not match the quality_index");
  }
  v_.windows.push_back(row);
  return true;
}

bool Parser::parse() {
  return read_header() && expect(kCoefficients) && expect(kCoefficientColumns) &&
         read_coefficients() && expect(signal_columns()) && read_signals() && expect(kBeats) &&
         expect(kBeatColumns) && read_rows(kBeats, n_beats_, 3, &Parser::read_beat_row) &&
         expect(kReferenceBeats) && expect(kIndexColumn) &&
         read_rows(kReferenceBeats, n_reference_beats_, 1, &Parser::read_reference_row) &&
         expect(kHeartRates) && expect(kHeartRateColumns) && read_heart_rates() &&
         expect(kWindows) && expect(kWindowColumns) &&
         read_rows(kWindows, n_windows_, 5, &Parser::read_window_row) && expect(kEnd) && finish();
}

}  // namespace

ReadResult parse_golden_vector(std::string_view bytes) {
  ReadResult result;
  if (!is_utf8(bytes)) {
    result.error.reason = "not UTF-8 text";
    return result;
  }
  Parser parser(bytes);
  result.ok = parser.parse();
  if (result.ok) {
    result.vector = parser.take_vector();
  } else {
    result.error = parser.take_error();
  }
  return result;
}

ReadResult read_golden_vector(const std::string& path) {
  std::ifstream file(path, std::ios::binary);
  if (!file) {
    ReadResult result;
    result.error.reason = "cannot be read";
    return result;
  }
  const std::string content((std::istreambuf_iterator<char>(file)),
                            std::istreambuf_iterator<char>());
  if (file.bad()) {
    ReadResult result;
    result.error.reason = "cannot be read";
    return result;
  }
  return parse_golden_vector(content);
}

}  // namespace sinus::dsp::verification
