// Test tool: sinus_desktop_wfdb_dump <record_path>. Reads the record with read_wfdb_record and
// prints fs_millihertz=, sample_count=, sha256_binary64= and sha256_binary32= (the SHA-256 of the
// little-endian binary64 physical values and of their binary32 rounding, in order), or
// error=<status> with exit status 1 (architecture-m3.md 17.8, the cross-check on the reference
// databases).

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <string>

#include "core/sha256.hpp"
#include "core/wfdb_reader.hpp"
#include "core/wfdb_status.hpp"
#include "wfdb_status_name.hpp"

namespace {

using sinus::desktop::core::Sha256;

template <typename Bits>
void update_little_endian(Sha256& hash, Bits bits) {
  for (std::size_t k = 0; k < sizeof(Bits); ++k) {
    const auto byte = static_cast<std::uint8_t>((bits >> (8U * k)) & 0xFFU);
    hash.update(&byte, 1);
  }
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: sinus_desktop_wfdb_dump <record_path>\n";
    return 2;
  }
  sinus::desktop::core::WfdbRecord record;
  // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): argv holds argc entries.
  const std::filesystem::path path = std::filesystem::u8path(argv[1]);
  const sinus::desktop::core::WfdbResult result =
      sinus::desktop::core::read_wfdb_record(path, record);
  if (!result.ok()) {
    std::cout << "error=" << sinus::desktop::test::wfdb_status_name(result.status) << "\n";
    std::cerr << result.message << "\n";
    return 1;
  }
  Sha256 binary64;
  Sha256 binary32;
  for (std::size_t i = 0; i < record.signal0_adu.size(); ++i) {
    const double value = record.physical_mv(i);
    const float rounded = record.sample_mv(i);
    std::uint64_t bits64 = 0;
    std::uint32_t bits32 = 0;
    std::memcpy(&bits64, &value, sizeof(bits64));
    std::memcpy(&bits32, &rounded, sizeof(bits32));
    update_little_endian(binary64, bits64);
    update_little_endian(binary32, bits32);
  }
  std::cout << "fs_millihertz=" << record.header.fs_millihertz << "\n";
  std::cout << "sample_count=" << record.signal0_adu.size() << "\n";
  std::cout << "sha256_binary64=" << sinus::desktop::core::to_hex(binary64.finish()) << "\n";
  std::cout << "sha256_binary32=" << sinus::desktop::core::to_hex(binary32.finish()) << "\n";
  return 0;
}
