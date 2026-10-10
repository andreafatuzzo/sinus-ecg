#pragma once

// Helpers of the requirement tests of SRS-034 and SRS-037 (QA): an own reader of the golden-vector
// files (architecture.md 7.3, architecture-m2.md 13.8), an own run of the library on a vector, an
// own comparison with the approved tolerances (architecture-m2.md 14.11), an own SHA-256 and the
// source digest of architecture-m2.md 14.15, and small helpers to build folders of vectors. Nothing
// here uses the verification code of the library (reader, check, results).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <system_error>
#include <vector>

#include "sinus/dsp/chain.hpp"

#ifndef _WIN32
#include <sys/wait.h>
#endif

namespace sinus_qa {

namespace fs = std::filesystem;

// The 32 inputs of the set, written out by QA from architecture.md 7.2 and architecture-m2.md 13.9.
inline std::vector<std::string> expected_ids() {
  std::vector<std::string> ids;
  for (const char* rate : {"fs250", "fs360"}) {
    for (const char* hr : {"hr040", "hr075", "hr180"}) {
      for (const char* kind : {"clean", "bw-mains50", "bw-mains60"}) {
        ids.push_back(std::string("syn-") + rate + "-" + hr + "-" + kind);
      }
    }
    for (const char* event : {"artefact", "held", "rate-change", "small-beat"}) {
      ids.push_back(std::string("syn-") + rate + "-event-" + event);
    }
  }
  for (const char* record : {"100", "105", "108", "119", "203", "207"}) {
    ids.push_back(std::string("mitdb-") + record + "-first60s");
  }
  std::sort(ids.begin(), ids.end());
  return ids;
}

// The folder of the golden vectors of the same commit, or empty when not set.
inline std::string golden_dir() {
  const char* value = std::getenv("SINUS_GOLDEN_DIR");
  return value == nullptr ? std::string() : std::string(value);
}

inline constexpr const char* kSkipMessage =
    "SINUS_GOLDEN_DIR is not set: the golden vectors of the same commit are a precondition of "
    "this test (architecture-m2.md 14.12, 14.17); CI sets it";

inline std::string path_of(const std::string& dir, const std::string& id) {
  return (fs::path(dir) / (id + ".golden.txt")).string();
}

inline std::string read_text(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  std::ostringstream buffer;
  buffer << in.rdbuf();
  return buffer.str();
}

inline void write_text(const std::string& path, const std::string& text) {
  std::ofstream out(path, std::ios::binary);
  out << text;
}

inline std::vector<std::string> split(const std::string& text, char separator) {
  std::vector<std::string> parts;
  std::string current;
  for (const char c : text) {
    if (c == separator) {
      parts.push_back(current);
      current.clear();
    } else {
      current.push_back(c);
    }
  }
  parts.push_back(current);
  return parts;
}

// ---------------------------------------------------------------------------------------------
// The vector as QA reads it.

struct QBeat {
  std::uint64_t index = 0;
  bool reliable = false;
  std::uint64_t reported = 0;
};
struct QRate {
  std::uint64_t sample = 0;
  bool has_beat = false;
  std::uint64_t beat = 0;
  std::string status;
  bool has_bpm = false;
  double bpm = 0.0;
};
struct QWindow {
  std::uint64_t first = 0, last = 0, reported = 0;
  double index = 0.0;
  bool usable = false;
};
struct QVector {
  std::string id, version, digest;
  double fs = 0.0;
  int mains = 0;
  std::vector<double> input, baseline, mains_out;
  std::vector<QBeat> beats;
  std::vector<QRate> rates;
  std::vector<QWindow> windows;
};

inline QVector parse_vector(const std::string& text) {
  QVector v;
  std::string section = "header";
  bool header_line = false;
  std::istringstream in(text);
  std::string line;
  while (std::getline(in, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    if (!line.empty() && line[0] == '[') {
      section = line;
      header_line = true;
      continue;
    }
    if (section == "header") {
      const auto eq = line.find('=');
      if (eq == std::string::npos) {
        continue;
      }
      const std::string key = line.substr(0, eq);
      const std::string value = line.substr(eq + 1);
      if (key == "input_id") {
        v.id = value;
      } else if (key == "software_version") {
        v.version = value;
      } else if (key == "source_sha256") {
        v.digest = value;
      } else if (key == "sampling_frequency_hz") {
        v.fs = std::strtod(value.c_str(), nullptr);
      } else if (key == "mains_frequency_hz") {
        v.mains = std::atoi(value.c_str());
      }
      continue;
    }
    if (header_line) {  // the column names of the section
      header_line = false;
      continue;
    }
    const auto f = split(line, ',');
    if (section == "[signals]") {
      v.input.push_back(std::strtod(f[0].c_str(), nullptr));
      v.baseline.push_back(std::strtod(f[1].c_str(), nullptr));
      v.mains_out.push_back(std::strtod(f[2].c_str(), nullptr));
    } else if (section == "[beats]") {
      v.beats.push_back({std::strtoull(f[0].c_str(), nullptr, 10), f[1] == "reliable",
                         std::strtoull(f[2].c_str(), nullptr, 10)});
    } else if (section == "[heart_rates]") {
      QRate r;
      r.sample = std::strtoull(f[0].c_str(), nullptr, 10);
      r.has_beat = !f[1].empty();
      r.beat = r.has_beat ? std::strtoull(f[1].c_str(), nullptr, 10) : 0;
      r.status = f[2];
      r.has_bpm = !f[3].empty();
      r.bpm = r.has_bpm ? std::strtod(f[3].c_str(), nullptr) : 0.0;
      v.rates.push_back(r);
    } else if (section == "[quality_windows]") {
      v.windows.push_back({std::strtoull(f[0].c_str(), nullptr, 10),
                           std::strtoull(f[1].c_str(), nullptr, 10),
                           std::strtoull(f[2].c_str(), nullptr, 10),
                           std::strtod(f[3].c_str(), nullptr), f[4] == "usable"});
    }
  }
  return v;
}

// ---------------------------------------------------------------------------------------------
// The library's own run, sample by sample.

inline const char* status_text(sinus::dsp::HeartRateStatus s) {
  switch (s) {
    case sinus::dsp::HeartRateStatus::kValid:
      return "valid";
    case sinus::dsp::HeartRateStatus::kNotEnoughBeats:
      return "not_enough_beats";
    case sinus::dsp::HeartRateStatus::kNoRecentBeat:
      return "no_recent_beat";
    case sinus::dsp::HeartRateStatus::kOutOfRange:
      return "out_of_range";
  }
  return "?";
}

struct QRun {
  bool ok = false;
  std::vector<double> baseline, mains_out;
  std::vector<QBeat> beats;
  std::vector<std::uint64_t> beat_call;  // the call (sample) at which each detection came out
  std::vector<QRate> rates;
  std::vector<std::uint64_t> rate_call;
  std::vector<QWindow> windows;
  std::vector<std::uint64_t> window_call;
};

inline QRun run_library_on(const QVector& v) {
  using namespace sinus::dsp;
  QRun run;
  Chain chain;
  Config config;
  config.sampling_frequency_hz = v.fs;
  config.mains_frequency_hz = v.mains;
  if (chain.configure(config) != Status::kOk) {
    return run;
  }
  SampleOutput out;
  for (std::size_t i = 0; i < v.input.size(); ++i) {
    if (chain.process(static_cast<float>(v.input[i]), out) != Status::kOk) {
      return run;
    }
    run.baseline.push_back(static_cast<double>(out.baseline_mv));
    run.mains_out.push_back(static_cast<double>(out.conditioned_mv));
    for (std::size_t k = 0; k < out.detection_count; ++k) {
      const Detection& d = out.detections[k];
      run.beats.push_back({d.index, d.mark == Mark::kReliable, d.reported_at});
      run.beat_call.push_back(i);
    }
    for (std::size_t k = 0; k < out.heart_rate_count; ++k) {
      const HeartRateEvent& e = out.heart_rates[k];
      QRate r;
      r.sample = e.sample;
      r.has_beat = e.has_beat;
      r.beat = e.has_beat ? e.beat_index : 0;
      r.status = status_text(e.status);
      r.has_bpm = e.status == HeartRateStatus::kValid || e.status == HeartRateStatus::kOutOfRange;
      r.bpm = r.has_bpm ? static_cast<double>(e.bpm) : 0.0;
      run.rates.push_back(r);
      run.rate_call.push_back(i);
    }
    if (out.has_window) {
      const QualityWindow& w = out.window;
      run.windows.push_back(
          {w.first_sample, w.last_sample, w.reported_at, static_cast<double>(w.index), w.usable});
      run.window_call.push_back(i);
    }
  }
  run.ok = true;
  return run;
}

// ---------------------------------------------------------------------------------------------
// The comparison, with the approved tolerances (architecture-m2.md 14.11).

inline constexpr double kTolConditioning = 2e-5;
inline constexpr double kTolRate = 1e-4;
inline constexpr double kTolQuality = 0.01;

struct QDiff {
  std::string output;
  std::string structural;  // empty when the output is structurally the same
  double largest = 0.0;
  std::uint64_t sample = 0;
};

inline QDiff compare_series(const char* name, const std::vector<double>& lib,
                            const std::vector<double>& file) {
  QDiff d;
  d.output = name;
  if (lib.size() != file.size()) {
    d.structural = "count";
    return d;
  }
  for (std::size_t i = 0; i < lib.size(); ++i) {
    const double diff = std::fabs(lib[i] - file[i]);
    if (diff > d.largest) {
      d.largest = diff;
      d.sample = i;
    }
  }
  return d;
}

// The six outputs in the order of the report.
inline std::vector<QDiff> compare_run(const QVector& v, const QRun& run) {
  std::vector<QDiff> all;
  all.push_back(compare_series("baseline_mv", run.baseline, v.baseline));
  all.push_back(compare_series("mains_mv", run.mains_out, v.mains_out));

  QDiff beats;
  beats.output = "beats";
  QDiff reported;
  reported.output = "beat_reported_at";
  if (run.beats.size() != v.beats.size()) {
    beats.structural = "count";
    reported.structural = "count";
  } else {
    for (std::size_t i = 0; i < v.beats.size(); ++i) {
      if (run.beats[i].reliable != v.beats[i].reliable && beats.structural.empty()) {
        beats.structural = "mark";
      }
      const auto a = run.beats[i].index;
      const auto b = v.beats[i].index;
      const double d = static_cast<double>(a > b ? a - b : b - a);
      if (d > beats.largest) {
        beats.largest = d;
        beats.sample = b;
      }
      const auto ra = run.beats[i].reported;
      const auto rb = v.beats[i].reported;
      const double rd = static_cast<double>(ra > rb ? ra - rb : rb - ra);
      if (rd > reported.largest) {
        reported.largest = rd;
        reported.sample = rb;
      }
    }
  }
  all.push_back(beats);
  all.push_back(reported);

  QDiff rates;
  rates.output = "heart_rates";
  if (run.rates.size() != v.rates.size()) {
    rates.structural = "count";
  } else {
    for (std::size_t i = 0; i < v.rates.size(); ++i) {
      const QRate& a = run.rates[i];
      const QRate& b = v.rates[i];
      if ((a.sample != b.sample || a.has_beat != b.has_beat || (a.has_beat && a.beat != b.beat) ||
           a.status != b.status || a.has_bpm != b.has_bpm) &&
          rates.structural.empty()) {
        rates.structural = "event";
      }
      if (a.has_bpm && b.has_bpm) {
        const double d = std::fabs(a.bpm - b.bpm);
        if (d > rates.largest) {
          rates.largest = d;
          rates.sample = b.sample;
        }
      }
    }
  }
  all.push_back(rates);

  QDiff windows;
  windows.output = "quality_windows";
  if (run.windows.size() != v.windows.size()) {
    windows.structural = "count";
  } else {
    for (std::size_t i = 0; i < v.windows.size(); ++i) {
      const QWindow& a = run.windows[i];
      const QWindow& b = v.windows[i];
      if ((a.first != b.first || a.last != b.last || a.reported != b.reported ||
           a.usable != b.usable) &&
          windows.structural.empty()) {
        windows.structural = "window";
      }
      const double d = std::fabs(a.index - b.index);
      if (d > windows.largest) {
        windows.largest = d;
        windows.sample = b.first;
      }
    }
  }
  all.push_back(windows);
  return all;
}

inline double tolerance_of(const std::string& output) {
  if (output == "baseline_mv" || output == "mains_mv") {
    return kTolConditioning;
  }
  if (output == "heart_rates") {
    return kTolRate;
  }
  if (output == "quality_windows") {
    return kTolQuality;
  }
  return 0.0;  // beats, beat_reported_at
}

// ---------------------------------------------------------------------------------------------
// SHA-256 (FIPS 180-4), written by QA for the source digest of architecture-m2.md 14.15.

inline std::string sha256_hex(const std::string& message) {
  static const std::array<std::uint32_t, 64> k = {
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
      0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
      0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
      0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
      0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
      0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
      0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
      0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
      0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
      0xc67178f2};
  std::array<std::uint32_t, 8> h = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  std::string data = message;
  const std::uint64_t bits = static_cast<std::uint64_t>(message.size()) * 8U;
  data.push_back(static_cast<char>(0x80));
  while (data.size() % 64U != 56U) {
    data.push_back('\0');
  }
  for (int shift = 56; shift >= 0; shift -= 8) {
    data.push_back(static_cast<char>((bits >> shift) & 0xFFU));
  }
  const auto rotr = [](std::uint32_t x, unsigned n) { return (x >> n) | (x << (32U - n)); };
  for (std::size_t block = 0; block < data.size(); block += 64) {
    std::array<std::uint32_t, 64> w{};
    for (std::size_t i = 0; i < 16; ++i) {
      std::uint32_t word = 0;
      for (std::size_t b = 0; b < 4; ++b) {
        word = (word << 8U) | static_cast<std::uint8_t>(data[block + 4 * i + b]);
      }
      w[i] = word;
    }
    for (std::size_t i = 16; i < 64; ++i) {
      const std::uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3U);
      const std::uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10U);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    auto a = h;
    for (std::size_t i = 0; i < 64; ++i) {
      const std::uint32_t s1 = rotr(a[4], 6) ^ rotr(a[4], 11) ^ rotr(a[4], 25);
      const std::uint32_t ch = (a[4] & a[5]) ^ (~a[4] & a[6]);
      const std::uint32_t t1 = a[7] + s1 + ch + k[i] + w[i];
      const std::uint32_t s0 = rotr(a[0], 2) ^ rotr(a[0], 13) ^ rotr(a[0], 22);
      const std::uint32_t maj = (a[0] & a[1]) ^ (a[0] & a[2]) ^ (a[1] & a[2]);
      const std::uint32_t t2 = s0 + maj;
      a[7] = a[6];
      a[6] = a[5];
      a[5] = a[4];
      a[4] = a[3] + t1;
      a[3] = a[2];
      a[2] = a[1];
      a[1] = a[0];
      a[0] = t1 + t2;
    }
    for (std::size_t i = 0; i < 8; ++i) {
      h[i] += a[i];
    }
  }
  std::string hex;
  for (const std::uint32_t word : h) {
    char buffer[9];
    std::snprintf(buffer, sizeof buffer, "%08x", word);
    hex += buffer;
  }
  return hex;
}

// The source digest of the library by the method of architecture-m2.md 14.15, computed by QA:
// every regular file under include/ and src/ whose path has no component starting with '.', named
// relative to libs/ ("sinus-dsp/src/..."), sorted in code-point order, CR LF replaced by LF, one
// line "<sha256>  <name>" per file, then the SHA-256 of the manifest.
inline std::string library_source_digest(const fs::path& library_dir) {
  std::vector<std::pair<std::string, std::string>> files;  // name, content
  for (const char* sub : {"include", "src"}) {
    for (auto it = fs::recursive_directory_iterator(library_dir / sub);
         it != fs::recursive_directory_iterator(); ++it) {
      if (!it->is_regular_file()) {
        continue;
      }
      const fs::path relative = fs::relative(it->path(), library_dir);
      bool hidden = false;
      for (const auto& part : relative) {
        if (!part.empty() && part.string()[0] == '.') {
          hidden = true;
        }
      }
      if (hidden) {
        continue;
      }
      std::string content = read_text(it->path().string());
      std::string normalised;
      for (std::size_t i = 0; i < content.size(); ++i) {
        if (content[i] == '\r' && i + 1 < content.size() && content[i + 1] == '\n') {
          continue;
        }
        normalised.push_back(content[i]);
      }
      files.emplace_back("sinus-dsp/" + relative.generic_string(), normalised);
    }
  }
  std::sort(files.begin(), files.end());
  std::string manifest;
  for (const auto& [name, content] : files) {
    manifest += sha256_hex(content) + "  " + name + "\n";
  }
  return sha256_hex(manifest);
}

// ---------------------------------------------------------------------------------------------
// Folders of vectors and edits of a vector's text.

class TempFolder {
 public:
  TempFolder() {
    static int counter = 0;
    path_ = fs::temp_directory_path() /
            ("sinus_qa_equiv_" + std::to_string(static_cast<long long>(std::rand())) + "_" +
             std::to_string(counter++));
    fs::create_directories(path_);
  }
  TempFolder(const TempFolder&) = delete;
  TempFolder& operator=(const TempFolder&) = delete;
  ~TempFolder() {
    std::error_code ignored;
    fs::remove_all(path_, ignored);
  }
  [[nodiscard]] std::string str() const { return path_.string(); }
  [[nodiscard]] fs::path file(const std::string& name) const { return path_ / name; }

  // Makes the file `name` of the folder the same as `source` (a hard link, else a copy).
  void link_or_copy(const std::string& source, const std::string& name) const {
    std::error_code ec;
    fs::create_hard_link(source, file(name), ec);
    if (ec) {
      fs::copy_file(source, file(name), fs::copy_options::overwrite_existing);
    }
  }

  // All files of `dir` that end with .golden.txt or are NOTICE.md, but those whose id is in `skip`
  // or in `replace` (the latter are written by the caller).
  void import_vectors(const std::string& dir, const std::vector<std::string>& skip) const {
    for (const auto& entry : fs::directory_iterator(dir)) {
      const std::string name = entry.path().filename().string();
      bool skipped = false;
      for (const auto& id : skip) {
        if (name == id + ".golden.txt") {
          skipped = true;
        }
      }
      if (!skipped && entry.is_regular_file()) {
        link_or_copy(entry.path().string(), name);
      }
    }
  }

 private:
  fs::path path_;
};

// The text of a vector as lines, with edits by section and row.
class VectorText {
 public:
  explicit VectorText(const std::string& text) {
    std::istringstream in(text);
    std::string line;
    while (std::getline(in, line)) {
      lines_.push_back(line);
    }
  }
  [[nodiscard]] std::string str() const {
    std::string out;
    for (const auto& l : lines_) {
      out += l + "\n";
    }
    return out;
  }
  // Index in lines_ of data row `row` of `section` (e.g. "[beats]"); row 0 follows the column
  // names.
  [[nodiscard]] std::size_t row_line(const std::string& section, std::size_t row) const {
    for (std::size_t i = 0; i < lines_.size(); ++i) {
      if (lines_[i] == section) {
        return i + 2 + row;
      }
    }
    abort_missing_section();
    return 0;
  }
  void set_field(const std::string& section, std::size_t row, std::size_t column,
                 const std::string& value) {
    auto& line = lines_[row_line(section, row)];
    auto fields = split(line, ',');
    fields[column] = value;
    line.clear();
    for (std::size_t i = 0; i < fields.size(); ++i) {
      line += (i == 0 ? "" : ",") + fields[i];
    }
  }
  [[nodiscard]] std::string get_field(const std::string& section, std::size_t row,
                                      std::size_t column) const {
    return split(lines_[row_line(section, row)], ',')[column];
  }
  void remove_row(const std::string& section, std::size_t row, const std::string& count_key) {
    lines_.erase(lines_.begin() + static_cast<std::ptrdiff_t>(row_line(section, row)));
    for (auto& l : lines_) {
      if (l.rfind(count_key + "=", 0) == 0) {
        l = count_key + "=" + std::to_string(std::stoul(l.substr(count_key.size() + 1)) - 1);
        return;
      }
    }
  }
  void replace_line_starting(const std::string& prefix, const std::string& whole) {
    for (auto& l : lines_) {
      if (l.rfind(prefix, 0) == 0) {
        l = whole;
        return;
      }
    }
  }

 private:
  static void abort_missing_section() { std::abort(); }
  std::vector<std::string> lines_;
};

inline std::string number_text(double value) {
  char buffer[40];
  std::snprintf(buffer, sizeof buffer, "%.17g", value);
  return buffer;
}

#ifdef SINUS_QA_EQUIVALENCE_TOOL
inline int command_status(std::string command) {
#ifdef _WIN32
  command = "\"" + command + "\"";
  return std::system(command.c_str());
#else
  const int raw = std::system(command.c_str());
  return (raw >= 0 && WIFEXITED(raw)) ? WEXITSTATUS(raw) : -1;
#endif
}

// Runs sinus_dsp_equivalence; returns its exit status and leaves its stderr in `error_file`.
inline int run_tool(const std::string& vectors, const std::string& results,
                    const std::string& error_file) {
  return command_status(std::string("\"") + SINUS_QA_EQUIVALENCE_TOOL + "\" --vectors \"" +
                        vectors + "\" --results \"" + results + "\" 2> \"" + error_file + "\"");
}

inline int run_tool_without_arguments(const std::string& error_file) {
  return command_status(std::string("\"") + SINUS_QA_EQUIVALENCE_TOOL + "\" 2> \"" + error_file +
                        "\"");
}
#endif

}  // namespace sinus_qa
