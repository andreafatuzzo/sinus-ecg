#pragma once

// WFDB record reader: signal formats 16 and 212, the checks of signal 0 and its physical values
// (architecture-m3.md 17.4).

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <vector>

#include "core/wfdb_header.hpp"
#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

struct WfdbRecord {
  WfdbHeader header;
  std::vector<std::int16_t> signal0_adu;  // the first stored signal, header.sample_count values
  // (d - baseline) / gain, binary64. Precondition: i < signal0_adu.size().
  [[nodiscard]] double physical_mv(std::size_t i) const noexcept;
  // physical_mv(i) rounded once to binary32.
  [[nodiscard]] float sample_mv(std::size_t i) const noexcept;
};

// The largest magnitude of a sample of signal 0, in mV (the test of the library).
inline constexpr float kWfdbMaxSampleMagnitudeMv = 1000.0F;

// record_path: the record without extension, e.g. data/mitdb/100 (as the offline loader). Reads
// <record_path>.hea with the stem of record_path as the record name, then the signal file in the
// folder of the header. When the result is not ok, `out` is unspecified and must not be used.
[[nodiscard]] WfdbResult read_wfdb_record(const std::filesystem::path& record_path,
                                          WfdbRecord& out);

}  // namespace sinus::desktop::core
