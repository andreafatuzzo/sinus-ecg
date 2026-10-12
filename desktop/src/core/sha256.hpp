#pragma once

// SHA-256 (FIPS 180-4) of core, without Qt (architecture-m3.md 17.7): the digest of the checksum
// lists and of the files of a reference record.

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>

namespace sinus::desktop::core {

inline constexpr std::size_t kSha256Bytes = 32;
using Sha256Digest = std::array<std::uint8_t, kSha256Bytes>;

class Sha256 {
 public:
  Sha256() noexcept;
  void update(const std::uint8_t* data, std::size_t size) noexcept;
  // The digest of everything given so far. Then the object is spent: a later update is ignored
  // and a later finish returns the same digest.
  [[nodiscard]] Sha256Digest finish() noexcept;

 private:
  static constexpr std::size_t kBlockBytes = 64;
  using Block = std::array<std::uint8_t, kBlockBytes>;
  void compress(const Block& block) noexcept;
  void absorb(std::uint8_t byte) noexcept;

  std::array<std::uint32_t, 8> state_{};
  Block block_{};
  std::size_t block_used_ = 0;
  std::uint64_t total_bytes_ = 0;
  bool spent_ = false;
  Sha256Digest digest_{};
};

// 64 lowercase hexadecimal digits.
[[nodiscard]] std::string to_hex(const Sha256Digest& digest);

// The digest of a regular file, read in blocks of 1 MiB. false: the file cannot be read (missing,
// not a regular file, or a read error); `out` is then unspecified.
[[nodiscard]] bool sha256_file(const std::filesystem::path& path, Sha256Digest& out);

}  // namespace sinus::desktop::core
