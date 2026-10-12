#include "core/wfdb_header.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <limits>
#include <string>
#include <string_view>
#include <utility>

#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

namespace {

// The number grammar of 17.3.
constexpr std::size_t kMaxDecimalDigits = 15;
constexpr std::array<double, kMaxDecimalDigits + 1> kPowersOfTen{
    1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10, 1e11, 1e12, 1e13, 1e14, 1e15};
constexpr std::array<std::uint64_t, 4> kIntegerPowersOfTen{1, 10, 100, 1000};

// Sampling frequency range and the 24 h limit of the record length (17.3).
constexpr std::uint64_t kMinFsMillihertz = 125'000;
constexpr std::uint64_t kMaxFsMillihertz = 1'000'000;
constexpr std::uint64_t kMaxSeconds = 86'400;
constexpr std::int64_t kMaxSignals = 64;
// The gain text when the header gives 0 or nothing (the WFDB default, 200 adu/mV), and the units.
constexpr std::string_view kDefaultGainText = "200";
constexpr std::string_view kDefaultUnits = "mV";

constexpr bool is_blank(char c) noexcept { return c == ' ' || c == '\t'; }
constexpr bool is_digit(char c) noexcept { return c >= '0' && c <= '9'; }

bool all_digits(std::string_view text) noexcept {
  return std::all_of(text.begin(), text.end(), is_digit);
}

struct IntegerRange {
  std::int64_t min;
  std::int64_t max;
};

constexpr IntegerRange kInt32Range{std::numeric_limits<std::int32_t>::min(),
                                   std::numeric_limits<std::int32_t>::max()};

// `[+-]?[0-9]+` within `range`.
bool parse_integer(std::string_view text, IntegerRange range, std::int64_t& value) noexcept {
  bool negative = false;
  if (!text.empty() && (text.front() == '+' || text.front() == '-')) {
    negative = text.front() == '-';
    text.remove_prefix(1);
  }
  if (text.empty() || !all_digits(text)) {
    return false;
  }
  // The magnitude, up to 2^63 (the magnitude of the smallest int64).
  constexpr std::uint64_t limit = std::uint64_t{1} << 63U;
  std::uint64_t magnitude = 0;
  for (const char c : text) {
    const auto digit = static_cast<std::uint64_t>(c - '0');
    if (magnitude > (limit - digit) / 10U) {
      return false;
    }
    magnitude = (magnitude * 10U) + digit;
  }
  std::int64_t parsed = 0;
  if (negative) {
    parsed = magnitude == limit ? std::numeric_limits<std::int64_t>::min()
                                : -static_cast<std::int64_t>(magnitude);
  } else if (magnitude == limit) {
    return false;
  } else {
    parsed = static_cast<std::int64_t>(magnitude);
  }
  if (parsed < range.min || parsed > range.max) {
    return false;
  }
  value = parsed;
  return true;
}

bool parse_int32(std::string_view text, std::int32_t& value) noexcept {
  std::int64_t parsed = 0;
  if (!parse_integer(text, kInt32Range, parsed)) {
    return false;
  }
  value = static_cast<std::int32_t>(parsed);
  return true;
}

// A decimal as the integer m of all its digits and the number F of digits after the point.
struct DecimalParts {
  std::uint64_t digits = 0;
  std::size_t fraction_digits = 0;
};

bool parse_decimal_parts(std::string_view text, DecimalParts& parts) noexcept {
  const std::size_t point = text.find('.');
  const std::string_view whole = text.substr(0, point);
  const std::string_view fraction =
      point == std::string_view::npos ? std::string_view{} : text.substr(point + 1);
  if (whole.empty() || !all_digits(whole) ||
      (point != std::string_view::npos && fraction.empty()) || !all_digits(fraction) ||
      fraction.size() > kMaxDecimalDigits) {
    return false;
  }
  std::uint64_t m = 0;
  std::size_t significant = 0;
  for (const std::string_view part : {whole, fraction}) {
    for (const char c : part) {
      const auto digit = static_cast<std::uint64_t>(c - '0');
      if (significant > 0 || digit != 0) {
        ++significant;
      }
      if (significant > kMaxDecimalDigits) {
        return false;
      }
      m = (m * 10U) + digit;
    }
  }
  parts.digits = m;
  parts.fraction_digits = fraction.size();
  return true;
}

double decimal_value(const DecimalParts& parts) noexcept {
  // Both operands are exact in binary64 (m < 10^15 < 2^53): one correctly rounded division.
  return static_cast<double>(parts.digits) / kPowersOfTen.at(parts.fraction_digits);
}

// The decimal in mHz; false when it is not a whole number of mHz.
bool decimal_millihertz(const DecimalParts& parts, std::uint64_t& millihertz) noexcept {
  if (parts.fraction_digits <= 3) {
    millihertz = parts.digits * kIntegerPowersOfTen.at(3 - parts.fraction_digits);
    return true;
  }
  std::uint64_t divisor = 1;
  for (std::size_t k = 3; k < parts.fraction_digits; ++k) {
    divisor *= 10U;
  }
  if (parts.digits % divisor != 0) {
    return false;
  }
  millihertz = parts.digits / divisor;
  return true;
}

// `[A-Za-z0-9_][A-Za-z0-9._+-]*`: a file in the folder of the header.
bool is_plain_file_name(std::string_view name) noexcept {
  if (name.empty()) {
    return false;
  }
  const auto is_word = [](char c) noexcept {
    return is_digit(c) || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_';
  };
  if (!is_word(name.front())) {
    return false;
  }
  return std::all_of(name.begin(), name.end(), [&is_word](char c) noexcept {
    return is_word(c) || c == '.' || c == '+' || c == '-';
  });
}

// The fields of one line, separated by runs of spaces and tabs.
class Fields {
 public:
  explicit Fields(std::string_view line) noexcept : rest_(line) {}

  // The next field, empty when none is left.
  std::string_view next() noexcept {
    skip_blanks();
    std::size_t length = 0;
    for (const char c : rest_) {
      if (is_blank(c)) {
        break;
      }
      ++length;
    }
    const std::string_view field = rest_.substr(0, length);
    rest_.remove_prefix(length);
    return field;
  }

  // The rest of the line after the blanks that follow the last field read.
  std::string_view rest() noexcept {
    skip_blanks();
    return rest_;
  }

 private:
  void skip_blanks() noexcept {
    while (!rest_.empty() && is_blank(rest_.front())) {
      rest_.remove_prefix(1);
    }
  }

  std::string_view rest_;
};

std::string quoted(std::string_view text) {
  std::string out = "'";
  out.append(text).append("'");
  return out;
}

class HeaderParser {
 public:
  HeaderParser(std::string_view record_name, WfdbHeader& out)
      : record_name_(record_name), out_(&out) {}

  WfdbResult parse(std::string_view text);

 private:
  enum class Stage : std::uint8_t { kRecordLine, kSignalLines, kDone };

  bool parse_line(std::string_view line, std::size_t number);
  bool parse_record_line(std::string_view line, std::size_t number);
  bool parse_sampling_frequency(std::string_view field, std::size_t number);
  bool parse_sample_count(std::string_view field, std::size_t number);
  bool parse_signal_line(std::string_view line, std::size_t number);
  bool parse_signal_file_and_format(Fields& fields, WfdbSignal& signal, std::size_t number);
  bool parse_gain_field(std::string_view field, WfdbSignal& signal, bool& baseline_given,
                        std::size_t number);
  bool parse_signal_integers(Fields& fields, WfdbSignal& signal, std::size_t number);

  bool fail(WfdbStatus status, std::string_view what) {
    result_.status = status;
    result_.message.assign(record_name_).append(": ").append(what);
    return false;
  }
  bool malformed(std::size_t number, std::string_view what) {
    std::string text = "header line ";
    text.append(std::to_string(number)).append(" is not valid WFDB: ").append(what);
    return fail(WfdbStatus::kMalformedHeader, text);
  }
  bool unsupported(std::string_view feature) {
    std::string text(feature);
    text.append(" is not supported");
    return fail(WfdbStatus::kUnsupportedRecord, text);
  }

  std::string_view record_name_;
  WfdbHeader* out_;  // the caller's header, never null
  WfdbResult result_;
  Stage stage_ = Stage::kRecordLine;
  std::size_t signal_count_ = 0;
};

WfdbResult HeaderParser::parse(std::string_view text) {
  *out_ = WfdbHeader{};
  out_->record_name.assign(record_name_);
  if (text.size() > kWfdbHeaderMaxBytes) {
    malformed(1, "the header is larger than 1 MiB");
    return result_;
  }
  std::size_t number = 0;
  std::string_view rest = text;
  // Every line is visited; the first failure ends the parse.
  while (!rest.empty()) {
    ++number;
    const std::size_t end = rest.find('\n');
    std::string_view line = rest.substr(0, end);
    rest.remove_prefix(end == std::string_view::npos ? rest.size() : end + 1);
    if (!line.empty() && line.back() == '\r') {
      line.remove_suffix(1);
    }
    if (line.find('\0') != std::string_view::npos) {
      malformed(number, "it contains a NUL byte");
      return result_;
    }
    if (!parse_line(line, number)) {
      return result_;
    }
  }
  if (stage_ == Stage::kRecordLine) {
    malformed(number + 1, "there is no record line");
  } else if (stage_ == Stage::kSignalLines) {
    malformed(number + 1, std::to_string(signal_count_) + " signal lines are needed, " +
                              std::to_string(out_->signals.size()) + " are given");
  }
  return result_;
}

bool HeaderParser::parse_line(std::string_view line, std::size_t number) {
  Fields probe(line);
  const std::string_view first = probe.rest();
  if (first.empty()) {
    return true;  // a blank line
  }
  if (first.front() == '#') {
    Fields comment(first.substr(1));
    out_->comments.emplace_back(comment.rest());
    return true;
  }
  switch (stage_) {
    case Stage::kRecordLine:
      return parse_record_line(line, number);
    case Stage::kSignalLines:
      return parse_signal_line(line, number);
    case Stage::kDone:
      break;
  }
  return malformed(number, "more signal lines than the " + std::to_string(signal_count_) +
                               " of the record line");
}

bool HeaderParser::parse_record_line(std::string_view line, std::size_t number) {
  Fields fields(line);
  const std::string_view name = fields.next();
  if (name.find('/') != std::string_view::npos) {
    return unsupported("multi-segment records");
  }
  if (name != record_name_) {
    return unsupported("record name " + quoted(name) + " in the header");
  }
  const std::string_view nsig = fields.next();
  std::int64_t count = 0;
  if (nsig.empty()) {
    return malformed(number, "the number of signals is missing");
  }
  if (!parse_integer(nsig, IntegerRange{1, kMaxSignals}, count)) {
    return malformed(number,
                     "the number of signals " + quoted(nsig) + " is not an integer from 1 to 64");
  }
  signal_count_ = static_cast<std::size_t>(count);
  if (!parse_sampling_frequency(fields.next(), number) ||
      !parse_sample_count(fields.next(), number)) {
    return false;
  }
  out_->base_time.assign(fields.next());
  out_->base_date.assign(fields.next());
  const std::string_view extra = fields.next();
  if (!extra.empty()) {
    return malformed(number, "the field " + quoted(extra) + " follows the base date");
  }
  out_->signals.reserve(signal_count_);
  stage_ = Stage::kSignalLines;
  return true;
}

bool HeaderParser::parse_sampling_frequency(std::string_view field, std::size_t number) {
  if (field.empty()) {
    return malformed(number, "the sampling frequency is missing");
  }
  if (field.find('/') != std::string_view::npos) {
    return unsupported("a counter frequency in the sampling frequency " + quoted(field));
  }
  DecimalParts parts;
  if (!parse_decimal_parts(field, parts)) {
    return malformed(number,
                     "the sampling frequency " + quoted(field) + " is not a decimal number");
  }
  std::string described = "sampling frequency ";
  described.append(field).append(" Hz");
  std::uint64_t millihertz = 0;
  if (!decimal_millihertz(parts, millihertz)) {
    return unsupported(described + " (a whole number of mHz only)");
  }
  if (millihertz < kMinFsMillihertz || millihertz > kMaxFsMillihertz) {
    return unsupported(described + " (125 Hz to 1000 Hz only)");
  }
  out_->fs_millihertz = static_cast<std::uint32_t>(millihertz);
  out_->fs_hz = static_cast<double>(out_->fs_millihertz) / 1000.0;
  return true;
}

bool HeaderParser::parse_sample_count(std::string_view field, std::size_t number) {
  if (field.empty()) {
    return malformed(number, "the number of samples is missing");
  }
  std::int64_t count = 0;
  if (!parse_integer(field, IntegerRange{0, std::numeric_limits<std::int64_t>::max()}, count)) {
    return malformed(number,
                     "the number of samples " + quoted(field) + " is not an integer of at least 0");
  }
  if (count == 0) {
    return fail(WfdbStatus::kEmptyRecord, "the record has 0 samples");
  }
  const auto samples = static_cast<std::uint64_t>(count);
  // samples <= 86 400 * fs, in integers: 1000 * samples <= 86 400 * fs_millihertz.
  if (samples > (kMaxSeconds * out_->fs_millihertz) / 1000U) {
    return fail(WfdbStatus::kTooLong, "the record is longer than 24 h");
  }
  out_->sample_count = samples;
  return true;
}

bool HeaderParser::parse_signal_line(std::string_view line, std::size_t number) {
  Fields fields(line);
  WfdbSignal signal;
  signal.gain_text.assign(kDefaultGainText);
  signal.units.assign(kDefaultUnits);
  if (!parse_signal_file_and_format(fields, signal, number)) {
    return false;
  }
  bool baseline_given = false;
  const std::string_view gain = fields.next();
  if (!gain.empty()) {
    if (!parse_gain_field(gain, signal, baseline_given, number) ||
        !parse_signal_integers(fields, signal, number)) {
      return false;
    }
  }
  signal.description.assign(fields.rest());
  if (!baseline_given) {
    signal.baseline_adu = signal.adc_zero_adu;
  }
  out_->signals.push_back(std::move(signal));
  if (out_->signals.size() == signal_count_) {
    stage_ = Stage::kDone;
  }
  return true;
}

bool HeaderParser::parse_signal_file_and_format(Fields& fields, WfdbSignal& signal,
                                                std::size_t number) {
  const std::string_view file = fields.next();
  if (!is_plain_file_name(file)) {
    return malformed(number, "the signal file " + quoted(file) +
                                 " is not a file name in the folder of the header");
  }
  if (!out_->signals.empty() && file != out_->signals.front().file_name) {
    return unsupported("signals in several files");
  }
  signal.file_name.assign(file);
  const std::string_view format = fields.next();
  if (format.empty()) {
    return malformed(number, "the signal format is missing");
  }
  std::size_t digits = 0;
  for (const char c : format) {
    if (!is_digit(c)) {
      break;
    }
    ++digits;
  }
  const std::string_view number_text = format.substr(0, digits);
  const std::string_view modifier = format.substr(digits);
  if (number_text.empty() || (!modifier.empty() && modifier.front() != 'x' &&
                              modifier.front() != ':' && modifier.front() != '+')) {
    return malformed(number, "the signal format " + quoted(format) + " is not valid");
  }
  if (number_text == "16") {
    signal.format = WfdbFormat::kFormat16;
  } else if (number_text == "212") {
    signal.format = WfdbFormat::kFormat212;
  } else {
    std::string text = "signal format ";
    text.append(number_text).append(" is not supported (formats 16 and 212 only)");
    return fail(WfdbStatus::kUnsupportedFormat, text);
  }
  if (!modifier.empty()) {
    return unsupported("samples per frame, skew or byte offset in the signal format " +
                       quoted(format));
  }
  if (!out_->signals.empty() && signal.format != out_->signals.front().format) {
    return unsupported("signals in several formats");
  }
  return true;
}

bool HeaderParser::parse_gain_field(std::string_view field, WfdbSignal& signal,
                                    bool& baseline_given, std::size_t number) {
  const std::size_t gain_end = field.find_first_of("(/");
  const std::string_view gain = field.substr(0, gain_end);
  std::string_view rest =
      gain_end == std::string_view::npos ? std::string_view{} : field.substr(gain_end);
  DecimalParts parts;
  if (!parse_decimal_parts(gain, parts)) {
    return malformed(number, "the gain " + quoted(gain) + " is not a decimal number");
  }
  if (parts.digits != 0) {
    signal.gain_adu_per_mv = decimal_value(parts);
    signal.gain_text.assign(gain);
  }
  if (!rest.empty() && rest.front() == '(') {
    const std::size_t close = rest.find(')');
    const std::string_view baseline =
        rest.substr(1, close == std::string_view::npos ? std::string_view::npos : close - 1);
    if (close == std::string_view::npos || !parse_int32(baseline, signal.baseline_adu)) {
      return malformed(number, "the baseline in " + quoted(field) + " is not an integer");
    }
    baseline_given = true;
    rest.remove_prefix(close + 1);
  }
  if (!rest.empty()) {
    if (rest.front() != '/' || rest.size() == 1) {
      return malformed(number, "the gain field " + quoted(field) + " is not valid");
    }
    signal.units.assign(rest.substr(1));
  }
  if (out_->signals.empty() && signal.units != kDefaultUnits) {
    std::string text = "signal units ";
    text.append(quoted(signal.units)).append(" are not mV");
    return fail(WfdbStatus::kUnsupportedUnits, text);
  }
  return true;
}

bool HeaderParser::parse_signal_integers(Fields& fields, WfdbSignal& signal, std::size_t number) {
  // adcres (not used), adczero, initval, checksum, blocksize: each optional, in this order.
  constexpr std::array<std::string_view, 5> field_names{"ADC resolution", "ADC zero",
                                                        "initial value", "checksum", "block size"};
  for (std::size_t k = 0; k < field_names.size(); ++k) {
    const std::string_view field = fields.next();
    if (field.empty()) {
      return true;
    }
    std::int32_t value = 0;
    if (!parse_int32(field, value)) {
      std::string text = "the ";
      text.append(field_names.at(k)).append(" ").append(quoted(field)).append(" is not an integer");
      return malformed(number, text);
    }
    switch (k) {
      case 1:
        signal.adc_zero_adu = value;
        break;
      case 2:
        signal.initial_value_adu = value;
        break;
      case 3:
        signal.checksum = value;
        break;
      case 4:
        if (value != 0) {
          return unsupported("block size " + std::to_string(value));
        }
        break;
      default:
        break;
    }
  }
  return true;
}

}  // namespace

bool parse_wfdb_decimal(std::string_view text, double& value) noexcept {
  DecimalParts parts;
  if (!parse_decimal_parts(text, parts)) {
    return false;
  }
  value = decimal_value(parts);
  return true;
}

// NOLINTNEXTLINE(bugprone-easily-swappable-parameters): the interface of the design (17.3).
WfdbResult parse_wfdb_header(std::string_view text, std::string_view record_name, WfdbHeader& out) {
  HeaderParser parser(record_name, out);
  return parser.parse(text);
}

}  // namespace sinus::desktop::core
