#pragma once

// Reference records: a record in a folder whose SHA256SUMS.txt is the pinned checksum list of a
// reference database, checked file by file (architecture-m3.md 17.7, rules of
// architecture-m1.md 8.3).

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string_view>

#include "core/mains.hpp"
#include "core/wfdb_status.hpp"

namespace sinus::desktop::core {

struct ReferenceDatabase {
  std::string_view slug;
  std::string_view version;
  std::string_view title;
  std::string_view checksum_list_sha256;  // pinned, 64 lowercase hexadecimal digits
  MainsFrequency mains;
};

// MIT-BIH Arrhythmia Database 1.0.0 and MIT-BIH Noise Stress Test Database 1.0.0: the digests
// and titles of sinus_dsp.data.physionet (checked by a Python test), 60 Hz mains for both.
extern const std::array<ReferenceDatabase, 2> kReferenceDatabases;

// The name of the checksum list in the folder of a record.
inline constexpr std::string_view kChecksumListName = "SHA256SUMS.txt";
// A larger checksum list is not read; it cannot be a reference list (the pinned ones are 70 kB
// and 10 kB).
inline constexpr std::uintmax_t kChecksumListMaxBytes = std::uintmax_t{16} << 20U;

enum class ReferenceCheck : std::uint8_t { kNotReference, kVerified };

// record_path: the record without extension. Looks for SHA256SUMS.txt in the folder of the
// record. kNotReference when it is absent, larger than kChecksumListMaxBytes, its digest is
// none of `databases`, or it lists no file of the record; otherwise every listed file of the
// record must match (kVerified, `database` set) or the result is kReferenceMismatch. A list that
// exists but cannot be read is kCannotRead. `database` is null unless kVerified.
[[nodiscard]] WfdbResult check_reference_record(const std::filesystem::path& record_path,
                                                const ReferenceDatabase* databases,
                                                std::size_t count, ReferenceCheck& check,
                                                const ReferenceDatabase*& database);

}  // namespace sinus::desktop::core
