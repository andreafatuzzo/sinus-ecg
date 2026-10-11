// SRS-036: the binary pack of the golden vectors and the streaming equivalence check on it
// (architecture-m2.md 14.13).
#include "sinus/dsp/verification/golden_pack.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <set>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/heart_rate.hpp"
#include "sinus/dsp/qrs_detector.hpp"
#include "sinus/dsp/status.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"
#include "sinus/dsp/verification/golden_set.hpp"
#include "sinus/dsp/verification/sha256.hpp"

namespace sinus::dsp::verification {

namespace {

constexpr std::array<char, 4> kFileMagic{'G', 'V', 'F', '2'};
constexpr std::size_t kSampleBytes = 4 + 8 + 8;
constexpr std::size_t kCoefficientRowBytes = 1 + 1 + (5 * 8);
constexpr std::size_t kMaxText = 0xFFFF;
constexpr std::size_t kChunk = 4096;
constexpr auto kMaxMark = static_cast<std::uint8_t>(Mark::kReliable);
constexpr auto kMaxStatus = static_cast<std::uint8_t>(HeartRateStatus::kOutOfRange);
constexpr std::uint64_t kNoBeat = std::numeric_limits<std::uint64_t>::max();  // int64 -1

// The smaller of a byte count and a buffer size, as a size. A cast would be a useless one where
// size_t is 64 bits wide (-Wuseless-cast) and a missing one where it is 32 bits wide (the device).
std::size_t chunk_of(std::uint64_t count, std::size_t buffer_size) noexcept {
  if (count >= buffer_size) {
    return buffer_size;
  }
  if constexpr (std::is_same_v<std::size_t, std::uint64_t>) {
    return count;
  } else {
    return static_cast<std::size_t>(count);
  }
}

PackOutcome refuse(std::string error) {
  PackOutcome outcome;
  outcome.error = std::move(error);
  return outcome;
}

PackOutcome accept() {
  PackOutcome outcome;
  outcome.ok = true;
  return outcome;
}

// --- writing ------------------------------------------------------------------------------------

class Writer {
 public:
  explicit Writer(std::string& out) noexcept : out_(&out) {}

  // NOLINTNEXTLINE(bugprone-easily-swappable-parameters): the value and its width.
  void integer(std::uint64_t value, unsigned bytes) {
    for (unsigned i = 0; i < bytes; ++i) {
      out_->push_back(static_cast<char>((value >> (8U * i)) & 0xFFU));
    }
  }
  void u8(std::uint64_t value) { integer(value, 1); }
  void u16(std::uint64_t value) { integer(value, 2); }
  void u32(std::uint64_t value) { integer(value, 4); }
  void u64(std::uint64_t value) { integer(value, 8); }
  void f32(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof bits);
    u32(bits);
  }
  void f64(double value) {
    std::uint64_t bits = 0;
    std::memcpy(&bits, &value, sizeof bits);
    u64(bits);
  }
  void text(const std::string& value) {
    u16(value.size());
    *out_ += value;
  }
  void raw(const char* data, std::size_t count) { out_->append(data, count); }

 private:
  std::string* out_;
};

std::string vector_problem(const GoldenVector& v) {
  if (v.stages.size() != 2 || v.stages.at(0) != "baseline" || v.stages.at(1) != "mains" ||
      v.stage_outputs_mv.size() != 2) {
    return "the stages are not baseline,mains";
  }
  if (v.stage_outputs_mv.at(0).size() != v.input_mv.size() ||
      v.stage_outputs_mv.at(1).size() != v.input_mv.size()) {
    return "an output does not have one value per input sample";
  }
  for (const std::string* s :
       {&v.input_id, &v.input_source, &v.input_parameters, &v.software_version, &v.source_sha256}) {
    if (s->size() > kMaxText) {
      return "a text is longer than 65535 bytes";
    }
  }
  if (v.mains_hz < 0) {
    return "negative mains frequency";
  }
  return {};
}

void write_file(const GoldenVector& v, Writer& w) {
  w.raw(kFileMagic.data(), kFileMagic.size());
  for (const std::string* s :
       {&v.input_id, &v.input_source, &v.input_parameters, &v.software_version, &v.source_sha256}) {
    w.text(*s);
  }
  w.f64(v.fs_hz);
  w.u32(static_cast<std::uint64_t>(v.mains_hz));
  std::size_t rows = 0;
  for (const auto& stage : v.coefficients) {
    rows += stage.size();
  }
  w.u32(v.input_mv.size());
  w.u32(rows);
  w.u32(v.beats.size());
  w.u32(v.heart_rates.size());
  w.u32(v.windows.size());
  for (std::size_t stage = 0; stage < v.coefficients.size(); ++stage) {
    for (std::size_t section = 0; section < v.coefficients.at(stage).size(); ++section) {
      w.u8(stage);
      w.u8(section);
      for (const double c : v.coefficients.at(stage).at(section)) {
        w.f64(c);
      }
    }
  }
  for (std::size_t n = 0; n < v.input_mv.size(); ++n) {
    w.f32(static_cast<float>(v.input_mv.at(n)));
    w.f64(v.stage_outputs_mv.at(0).at(n));
    w.f64(v.stage_outputs_mv.at(1).at(n));
  }
  for (const BeatRow& b : v.beats) {
    w.u64(b.index);
    w.u8(static_cast<std::uint8_t>(b.mark));
    w.u64(b.reported_at);
  }
  for (const HeartRateRow& h : v.heart_rates) {
    w.u64(h.sample);
    w.u64(h.has_beat ? h.beat_index : kNoBeat);
    w.u8(static_cast<std::uint8_t>(h.status));
    w.f64(h.has_rate ? h.bpm : std::numeric_limits<double>::quiet_NaN());
  }
  for (const WindowRow& win : v.windows) {
    w.u64(win.first_sample);
    w.u64(win.last_sample);
    w.u64(win.reported_at);
    w.f64(win.index);
    w.u8(win.usable ? 1U : 0U);
  }
}

// --- reading ------------------------------------------------------------------------------------

std::uint64_t decode(const std::uint8_t* data, unsigned bytes) noexcept {
  std::uint64_t value = 0;
  for (unsigned i = 0; i < bytes; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): `bytes` bytes of `data`.
    value |= static_cast<std::uint64_t>(data[i]) << (8U * i);
  }
  return value;
}

double to_f64(std::uint64_t bits) noexcept {
  double value = 0.0;
  std::memcpy(&value, &bits, sizeof value);
  return value;
}

float to_f32(std::uint64_t bits) noexcept {
  const auto narrow = static_cast<std::uint32_t>(bits);
  float value = 0.0F;
  std::memcpy(&value, &narrow, sizeof value);
  return value;
}

// Little-endian reads from a ByteSource; after the first failure every read gives zero.
class Reader {
 public:
  explicit Reader(ByteSource& source) noexcept : source_(&source) {}

  [[nodiscard]] bool failed() const noexcept { return failed_; }

  bool take(std::uint8_t* out, std::size_t count) {
    if (!failed_ && !source_->read(out, count)) {
      failed_ = true;
    }
    return !failed_;
  }
  std::uint64_t integer(unsigned bytes) {
    std::array<std::uint8_t, 8> buffer{};
    return take(buffer.data(), bytes) ? decode(buffer.data(), bytes) : 0U;
  }
  std::uint8_t u8() { return static_cast<std::uint8_t>(integer(1)); }
  std::uint16_t u16() { return static_cast<std::uint16_t>(integer(2)); }
  std::uint32_t u32() { return static_cast<std::uint32_t>(integer(4)); }
  std::uint64_t u64() { return integer(8); }
  double f64() { return to_f64(integer(8)); }
  std::string text() {
    const std::size_t length = u16();
    std::vector<std::uint8_t> buffer(length);
    if (length == 0 || !take(buffer.data(), length)) {
      return {};
    }
    return {buffer.begin(), buffer.end()};
  }
  void skip(std::uint64_t count) {
    std::array<std::uint8_t, kChunk> buffer{};
    while (count > 0 && !failed_) {
      const auto step = chunk_of(count, buffer.size());
      if (!take(buffer.data(), step)) {
        return;
      }
      count -= step;
    }
  }

 private:
  ByteSource* source_;
  bool failed_ = false;
};

struct Header {
  std::uint32_t file_count = 0;
  std::uint64_t payload_bytes = 0;
  Sha256Digest sha256{};
};

PackOutcome read_header(Reader& r, Header& header) {
  std::array<std::uint8_t, kPackMagic.size()> magic{};
  if (!r.take(magic.data(), magic.size())) {
    return refuse("the pack is shorter than its header");
  }
  for (std::size_t i = 0; i < magic.size(); ++i) {
    if (magic.at(i) != static_cast<std::uint8_t>(kPackMagic.at(i))) {
      return refuse("not a golden pack (bad magic)");
    }
  }
  const std::uint32_t version = r.u32();
  header.file_count = r.u32();
  header.payload_bytes = r.u64();
  if (!r.take(header.sha256.data(), header.sha256.size())) {
    return refuse("the pack is shorter than its header");
  }
  if (version != kPackVersion) {
    return refuse("unsupported pack version " + std::to_string(version));
  }
  return accept();
}

// --- the streaming comparison -------------------------------------------------------------------

// The largest difference of a signal and the first sample where it occurs (equivalence.cpp does the
// same for the vectors of the text files).
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

OutputResult signal_result(const char* name, const Largest& largest) {
  OutputResult result;
  result.output = name;
  result.largest = largest.value;
  result.has_sample = largest.has;
  result.sample = largest.sample;
  result.tolerance = kConditioningToleranceMv;
  result.pass = !largest.has || largest.value <= kConditioningToleranceMv;
  return result;
}

struct FileHeader {
  std::string input_id;
  std::string software_version;
  std::string source_sha256;
  double fs_hz = 0.0;
  std::uint32_t mains = 0;
  std::uint32_t samples = 0;
  std::uint32_t coefficient_rows = 0;
  std::uint32_t beats = 0;
  std::uint32_t heart_rates = 0;
  std::uint32_t windows = 0;
};

bool read_file_header(Reader& r, FileHeader& h, std::string& error) {
  std::array<std::uint8_t, kFileMagic.size()> magic{};
  if (!r.take(magic.data(), magic.size())) {
    error = "the pack ends inside a file header";
    return false;
  }
  for (std::size_t i = 0; i < magic.size(); ++i) {
    if (magic.at(i) != static_cast<std::uint8_t>(kFileMagic.at(i))) {
      error = "bad file magic";
      return false;
    }
  }
  h.input_id = r.text();
  static_cast<void>(r.text());  // input_source
  static_cast<void>(r.text());  // input_parameters
  h.software_version = r.text();
  h.source_sha256 = r.text();
  h.fs_hz = r.f64();
  h.mains = r.u32();
  h.samples = r.u32();
  h.coefficient_rows = r.u32();
  h.beats = r.u32();
  h.heart_rates = r.u32();
  h.windows = r.u32();
  if (r.failed()) {
    error = "the pack ends inside a file header";
    return false;
  }
  return true;
}

// The events of the file, into the lists of the reference vector.
bool read_events(Reader& r, const FileHeader& h, GoldenVector& reference, std::string& error) {
  for (std::uint32_t i = 0; i < h.beats && !r.failed(); ++i) {
    BeatRow row{};
    row.index = r.u64();
    const std::uint8_t mark = r.u8();
    row.reported_at = r.u64();
    if (mark > kMaxMark) {
      error = "bad detection mark in " + h.input_id;
      return false;
    }
    row.mark = static_cast<Mark>(mark);
    reference.beats.push_back(row);
  }
  for (std::uint32_t i = 0; i < h.heart_rates && !r.failed(); ++i) {
    HeartRateRow row{};
    row.sample = r.u64();
    const std::uint64_t beat = r.u64();
    row.has_beat = beat != kNoBeat;
    row.beat_index = row.has_beat ? beat : 0U;
    const std::uint8_t status = r.u8();
    const double bpm = r.f64();
    if (status > kMaxStatus) {
      error = "bad heart-rate status in " + h.input_id;
      return false;
    }
    row.status = static_cast<HeartRateStatus>(status);
    row.has_rate = !std::isnan(bpm);
    row.bpm = row.has_rate ? bpm : 0.0;
    reference.heart_rates.push_back(row);
  }
  for (std::uint32_t i = 0; i < h.windows && !r.failed(); ++i) {
    WindowRow row{};
    row.first_sample = r.u64();
    row.last_sample = r.u64();
    row.reported_at = r.u64();
    row.index = r.f64();
    row.usable = r.u8() != 0U;
    reference.windows.push_back(row);
  }
  if (r.failed()) {
    error = "the pack ends inside the events of " + h.input_id;
    return false;
  }
  return true;
}

// Reads one file of the pack and checks it; false (with `error`) if the pack is malformed.
bool check_one(Reader& r, Chain& chain, SampleOutput& out, FileResult& result, std::string& error) {
  FileHeader h;
  if (!read_file_header(r, h, error)) {
    return false;
  }
  result.input_id = h.input_id;
  result.has_identity = true;
  result.software_version = h.software_version;
  result.source_sha256 = h.source_sha256;
  r.skip(static_cast<std::uint64_t>(h.coefficient_rows) * kCoefficientRowBytes);

  Status status = chain.configure(Config{h.fs_hz, static_cast<int>(h.mains)});
  std::uint64_t failed_at = 0;
  LibraryOutputs library;
  Largest baseline;
  Largest mains;
  for (std::uint32_t n = 0; n < h.samples && !r.failed(); ++n) {
    std::array<std::uint8_t, kSampleBytes> bytes{};
    if (!r.take(bytes.data(), bytes.size()) || status != Status::kOk) {
      continue;
    }
    status = chain.process(to_f32(decode(bytes.data(), 4)), out);
    if (status != Status::kOk) {
      failed_at = n;
      continue;
    }
    // NOLINTBEGIN(cppcoreguidelines-pro-bounds-pointer-arithmetic): the fields of one sample.
    baseline.offer(
        std::fabs(static_cast<double>(out.baseline_mv) - to_f64(decode(bytes.data() + 4, 8))), n);
    mains.offer(
        std::fabs(static_cast<double>(out.conditioned_mv) - to_f64(decode(bytes.data() + 12, 8))),
        n);
    // NOLINTEND(cppcoreguidelines-pro-bounds-pointer-arithmetic)
    collect_events(out, library);
  }
  if (r.failed()) {
    error = "the pack ends inside the samples of " + h.input_id;
    return false;
  }
  GoldenVector reference;
  if (!read_events(r, h, reference, error)) {
    return false;
  }
  if (status != Status::kOk) {
    result.status = FileStatus::kNotComparable;
    result.detail = "the library returns status " + std::to_string(static_cast<unsigned>(status)) +
                    " at sample " + std::to_string(failed_at);
    return true;
  }
  // The signals were compared above, as they were read. compare_outputs compares the events; its
  // two signal results, on empty signals, are replaced by the streamed ones.
  reference.stage_outputs_mv.resize(2);
  result.outputs = compare_outputs(reference, library);
  result.outputs.at(0) = signal_result("baseline_mv", baseline);
  result.outputs.at(1) = signal_result("mains_mv", mains);
  return true;
}

FileResult problem(const std::string& input_id, FileStatus status, const char* detail) {
  FileResult result;
  result.input_id = input_id;
  result.status = status;
  result.detail = detail;
  return result;
}

}  // namespace

bool MemorySource::read(std::uint8_t* out, std::size_t count) {
  if (count > bytes_.size() - at_) {
    return false;
  }
  if (count > 0) {
    std::memcpy(out, bytes_.substr(at_, count).data(), count);
  }
  at_ += count;
  return true;
}

PackOutcome build_pack(const std::vector<GoldenVector>& vectors, std::string& bytes) {
  std::string payload;
  Writer payload_writer(payload);
  for (const GoldenVector& v : vectors) {
    const std::string why = vector_problem(v);
    if (!why.empty()) {
      return refuse(v.input_id + ": " + why);
    }
    write_file(v, payload_writer);
  }
  Sha256 hash;
  // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): char bytes as unsigned bytes.
  hash.update(reinterpret_cast<const std::uint8_t*>(payload.data()), payload.size());
  const Sha256Digest digest = hash.finish();
  bytes.clear();
  Writer header(bytes);
  header.raw(kPackMagic.data(), kPackMagic.size());
  header.u32(kPackVersion);
  header.u32(vectors.size());
  header.u64(payload.size());
  for (const std::uint8_t byte : digest) {
    header.u8(byte);
  }
  bytes += payload;
  return accept();
}

PackOutcome verify_pack(ByteSource& source) {
  Reader r(source);
  Header header;
  PackOutcome outcome = read_header(r, header);
  if (!outcome.ok) {
    return outcome;
  }
  Sha256 hash;
  std::array<std::uint8_t, kChunk> buffer{};
  std::uint64_t left = header.payload_bytes;
  while (left > 0) {
    const auto step = chunk_of(left, buffer.size());
    if (!r.take(buffer.data(), step)) {
      return refuse("the pack is shorter than its payload length");
    }
    hash.update(buffer.data(), step);
    left -= step;
  }
  if (hash.finish() != header.sha256) {
    return refuse("the SHA-256 of the payload differs from the header's");
  }
  return outcome;
}

PackCheck check_pack(ByteSource& source, Chain& chain, SampleOutput& out) {
  PackCheck check;
  Reader r(source);
  Header header;
  check.outcome = read_header(r, header);
  if (!check.outcome.ok) {
    return check;
  }
  check.outcome.ok = false;
  std::vector<FileResult> found;
  for (std::uint32_t k = 0; k < header.file_count; ++k) {
    FileResult result;
    if (!check_one(r, chain, out, result, check.outcome.error)) {
      return check;
    }
    found.push_back(std::move(result));
  }
  check.outcome.ok = true;
  check.set.folder_listed = true;
  std::set<std::string> expected;
  for (const std::string_view id : expected_inputs()) {
    const std::string name(id);
    expected.insert(name);
    const auto at = std::find_if(found.begin(), found.end(),
                                 [&name](const FileResult& file) { return file.input_id == name; });
    check.set.files.push_back(at == found.end() ? problem(name, FileStatus::kMissing, "missing")
                                                : *at);
  }
  // The files that are not expected, and the repeats of an expected one.
  std::set<std::string> claimed;
  for (const FileResult& file : found) {
    if (expected.count(file.input_id) > 0 && claimed.insert(file.input_id).second) {
      continue;
    }
    check.set.files.push_back(problem(file.input_id, FileStatus::kUnexpected, "unexpected"));
  }
  return check;
}

}  // namespace sinus::dsp::verification
