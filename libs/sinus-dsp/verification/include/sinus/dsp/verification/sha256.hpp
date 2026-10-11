#pragma once

// SRS-036: SHA-256 (FIPS 180-4), incremental, with no dependency: the target seals the golden pack
// with it (architecture-m2.md 14.13).

#include <array>
#include <cstddef>
#include <cstdint>

namespace sinus::dsp::verification {

inline constexpr std::size_t kSha256Bytes = 32;
using Sha256Digest = std::array<std::uint8_t, kSha256Bytes>;

class Sha256 {
 public:
  Sha256() noexcept = default;
  void update(const std::uint8_t* data, std::size_t count) noexcept;
  // The digest of everything given so far; the object must not be updated afterwards.
  [[nodiscard]] Sha256Digest finish() noexcept;

 private:
  static constexpr std::size_t kBlockBytes = 64;
  void compress(const std::uint8_t* block) noexcept;

  std::array<std::uint32_t, 8> state_{0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
                                      0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U};
  std::array<std::uint8_t, kBlockBytes> block_{};
  std::size_t block_used_ = 0;
  std::uint64_t total_bytes_ = 0;
};

}  // namespace sinus::dsp::verification
