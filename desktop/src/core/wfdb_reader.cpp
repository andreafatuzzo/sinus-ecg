#include "core/wfdb_reader.hpp"

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

#include "core/wfdb_header.hpp"
#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

namespace {

// Files are read in blocks of 1 MiB.
constexpr std::size_t kReadBlockBytes = std::size_t{1} << 20U;
// The WFDB invalid-sample codes (17.4).
constexpr std::int32_t kInvalidSample16 = -32768;
constexpr std::int32_t kInvalidSample212 = -2048;

WfdbResult failure(WfdbStatus status, const std::string& record_name, std::string_view what) {
  WfdbResult result;
  result.status = status;
  result.message.assign(record_name).append(": ").append(what);
  return result;
}

WfdbResult cannot_read(const std::string& record_name, const std::filesystem::path& file) {
  std::string what = "cannot read ";
  what.append(file.filename().u8string());
  return failure(WfdbStatus::kCannotRead, record_name, what);
}

// The size of a regular file; false when it is not one or cannot be examined.
bool regular_file_size(const std::filesystem::path& path, std::size_t& size) {
  std::error_code error;
  if (!std::filesystem::is_regular_file(path, error) || error) {
    return false;
  }
  size = std::filesystem::file_size(path, error);
  return !error;
}

// The header text: at most kWfdbHeaderMaxBytes + 1 bytes, so that the parser sees a larger file.
bool read_header_text(const std::filesystem::path& path, std::string& text) {
  std::size_t size = 0;
  if (!regular_file_size(path, size)) {
    return false;
  }
  std::ifstream file(path, std::ios::binary);
  if (!file.is_open()) {
    return false;
  }
  text.resize(std::min(size, kWfdbHeaderMaxBytes + 1U));
  file.read(text.data(), static_cast<std::streamsize>(text.size()));
  return !file.bad() && static_cast<std::size_t>(file.gcount()) == text.size();
}

// Decodes the stored values byte by byte and keeps those of signal 0 (17.4). Value j belongs to
// sample t = j / nsig of signal s = j % nsig.
class Signal0Decoder {
 public:
  Signal0Decoder(WfdbFormat format, std::size_t signal_count, std::vector<std::int16_t>& samples)
      : format_(format), signal_count_(signal_count), samples_(&samples) {}

  void add(std::uint8_t byte) noexcept {
    if (format_ == WfdbFormat::kFormat16) {
      add_format16(byte);
    } else {
      add_format212(byte);
    }
  }

 private:
  // Little-endian two's-complement 16-bit values.
  void add_format16(std::uint8_t byte) noexcept {
    if (phase_ == 0) {
      first_ = byte;
      phase_ = 1;
      return;
    }
    const std::int32_t value = static_cast<std::int32_t>(first_) | (std::int32_t{byte} << 8U);
    emit(value >= 32768 ? value - 65536 : value);
    phase_ = 0;
  }

  // Pairs of 12-bit values in 3 bytes: even = b0 | (b1 & 0x0F) << 8, odd = b2 | (b1 & 0xF0) << 4.
  void add_format212(std::uint8_t byte) noexcept {
    if (phase_ == 0) {
      first_ = byte;
      phase_ = 1;
    } else if (phase_ == 1) {
      second_ = byte;
      emit(twelve_bit(static_cast<std::int32_t>(first_) |
                      (static_cast<std::int32_t>(second_ & 0x0FU) << 8U)));
      phase_ = 2;
    } else {
      emit(twelve_bit(static_cast<std::int32_t>(byte) |
                      (static_cast<std::int32_t>(second_ & 0xF0U) << 4U)));
      phase_ = 0;
    }
  }

  static std::int32_t twelve_bit(std::int32_t value) noexcept {
    return value >= 2048 ? value - 4096 : value;
  }

  void emit(std::int32_t value) noexcept {
    if (signal_ == 0) {
      samples_->at(sample_) = static_cast<std::int16_t>(value);
      ++sample_;
    }
    ++signal_;
    if (signal_ == signal_count_) {
      signal_ = 0;
    }
  }

  WfdbFormat format_;
  std::size_t signal_count_;
  std::vector<std::int16_t>* samples_;  // the caller's samples, never null
  unsigned phase_ = 0;
  std::uint8_t first_ = 0;
  std::uint8_t second_ = 0;
  std::size_t signal_ = 0;
  std::size_t sample_ = 0;
};

// Reads the first `needed` bytes of the signal file and decodes signal 0.
bool read_signal0(const std::filesystem::path& path, std::size_t needed, WfdbFormat format,
                  std::size_t signal_count, std::vector<std::int16_t>& samples) {
  std::ifstream file(path, std::ios::binary);
  if (!file.is_open()) {
    return false;
  }
  Signal0Decoder decoder(format, signal_count, samples);
  std::vector<char> buffer(std::min(needed, kReadBlockBytes));
  std::size_t left = needed;
  while (left > 0) {
    const std::size_t count = std::min(left, buffer.size());
    file.read(buffer.data(), static_cast<std::streamsize>(count));
    if (file.bad() || static_cast<std::size_t>(file.gcount()) != count) {
      return false;
    }
    for (std::size_t k = 0; k < count; ++k) {
      decoder.add(static_cast<std::uint8_t>(buffer.at(k)));
    }
    left -= count;
  }
  return true;
}

std::string float_text(float value) {
  std::array<char, 32> text{};
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): the end of the array.
  const std::to_chars_result result = std::to_chars(text.data(), text.data() + text.size(), value);
  return {text.data(), result.ptr};
}

// The checks of signal 0, in the order of 17.4.
WfdbResult check_signal0(const WfdbRecord& record, const std::string& record_name) {
  const WfdbSignal& signal = record.header.signals.front();
  const std::int32_t invalid =
      signal.format == WfdbFormat::kFormat16 ? kInvalidSample16 : kInvalidSample212;
  const std::vector<std::int16_t>& samples = record.signal0_adu;
  for (std::size_t i = 0; i < samples.size(); ++i) {
    if (samples.at(i) == invalid) {
      std::string what = "sample ";
      what.append(std::to_string(i)).append(" holds the WFDB invalid-sample code");
      return failure(WfdbStatus::kInvalidSampleValue, record_name, what);
    }
  }
  // The checksum: the sum of all values modulo 2^16, as a signed 16-bit number.
  std::uint32_t sum = 0;
  for (const std::int16_t value : samples) {
    sum = (sum + static_cast<std::uint32_t>(static_cast<std::int32_t>(value) + 65536)) & 0xFFFFU;
  }
  const std::int32_t checksum =
      sum >= 32768U ? static_cast<std::int32_t>(sum) - 65536 : static_cast<std::int32_t>(sum);
  const bool initial_differs =
      signal.initial_value_adu.has_value() && *signal.initial_value_adu != samples.front();
  const bool checksum_differs = signal.checksum.has_value() && *signal.checksum != checksum;
  if (initial_differs || checksum_differs) {
    return failure(WfdbStatus::kChecksumMismatch, record_name,
                   "the samples do not match the checksum (or the initial value) in the header");
  }
  for (std::size_t i = 0; i < samples.size(); ++i) {
    const float sample = record.sample_mv(i);
    if (std::fabs(sample) > kWfdbMaxSampleMagnitudeMv) {
      std::string what = "sample ";
      what.append(std::to_string(i)).append(" is ").append(float_text(sample));
      what.append(" mV, beyond 1000 mV");
      return failure(WfdbStatus::kSampleOutOfRange, record_name, what);
    }
  }
  return {};
}

}  // namespace

double WfdbRecord::physical_mv(std::size_t i) const noexcept {
  const WfdbSignal& signal = header.signals.front();
  // An exact subtraction and one correctly rounded division, as wfdb.rdrecord(..., physical=True,
  // return_res=64).
  return (static_cast<double>(signal0_adu.at(i)) - static_cast<double>(signal.baseline_adu)) /
         signal.gain_adu_per_mv;
}

float WfdbRecord::sample_mv(std::size_t i) const noexcept {
  return static_cast<float>(physical_mv(i));
}

WfdbResult read_wfdb_record(const std::filesystem::path& record_path, WfdbRecord& out) {
  out = WfdbRecord{};
  const std::string record_name = record_path.stem().u8string();
  std::filesystem::path header_path = record_path;
  header_path += ".hea";
  std::string text;
  if (!read_header_text(header_path, text)) {
    return cannot_read(record_name, header_path);
  }
  WfdbResult result = parse_wfdb_header(text, record_name, out.header);
  if (!result.ok()) {
    return result;
  }
  const WfdbSignal& signal = out.header.signals.front();
  const std::filesystem::path signal_path = record_path.parent_path() / signal.file_name;
  std::size_t size = 0;
  if (!regular_file_size(signal_path, size)) {
    return cannot_read(record_name, signal_path);
  }
  // T = nsig * nsamp values: at most 64 * 86 400 000, far within 64 bits.
  const std::size_t values = out.header.signals.size() * out.header.sample_count;
  const std::size_t needed =
      signal.format == WfdbFormat::kFormat16 ? 2U * values : ((3U * values) + 1U) / 2U;
  if (size < needed) {
    std::string what = "the signal file ";
    what.append(signal_path.filename().u8string()).append(" has ").append(std::to_string(size));
    what.append(" bytes, ").append(std::to_string(needed)).append(" are needed");
    return failure(WfdbStatus::kTruncatedSignal, record_name, what);
  }
  out.signal0_adu.resize(out.header.sample_count);
  if (!read_signal0(signal_path, needed, signal.format, out.header.signals.size(),
                    out.signal0_adu)) {
    return cannot_read(record_name, signal_path);
  }
  return check_signal0(out, record_name);
}

}  // namespace sinus::desktop::core
