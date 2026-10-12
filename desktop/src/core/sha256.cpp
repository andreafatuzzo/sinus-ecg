#include "core/sha256.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <ios>
#include <string>
#include <system_error>
#include <vector>

namespace sinus::desktop::core {

namespace {

constexpr std::array<std::uint32_t, 8> kInitialState{0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U,
                                                     0xa54ff53aU, 0x510e527fU, 0x9b05688cU,
                                                     0x1f83d9abU, 0x5be0cd19U};

constexpr std::array<std::uint32_t, 64> kRoundConstants{
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U,
    0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU,
    0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU,
    0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
    0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
    0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
    0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U,
    0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U,
    0xc67178f2U};

// Files are read in blocks of 1 MiB (architecture-m3.md 17.7).
constexpr std::size_t kFileBlockBytes = std::size_t{1} << 20U;

constexpr std::uint32_t rotate_right(std::uint32_t value, unsigned bits) noexcept {
  return (value >> bits) | (value << (32U - bits));
}

}  // namespace

Sha256::Sha256() noexcept : state_(kInitialState) {}

void Sha256::compress(const Block& block) noexcept {
  std::array<std::uint32_t, 64> w{};
  for (std::size_t t = 0; t < 16; ++t) {
    const std::size_t at = 4 * t;
    w.at(t) = (static_cast<std::uint32_t>(block.at(at)) << 24U) |
              (static_cast<std::uint32_t>(block.at(at + 1)) << 16U) |
              (static_cast<std::uint32_t>(block.at(at + 2)) << 8U) |
              static_cast<std::uint32_t>(block.at(at + 3));
  }
  for (std::size_t t = 16; t < 64; ++t) {
    const std::uint32_t s0 =
        rotate_right(w.at(t - 15), 7) ^ rotate_right(w.at(t - 15), 18) ^ (w.at(t - 15) >> 3U);
    const std::uint32_t s1 =
        rotate_right(w.at(t - 2), 17) ^ rotate_right(w.at(t - 2), 19) ^ (w.at(t - 2) >> 10U);
    w.at(t) = w.at(t - 16) + s0 + w.at(t - 7) + s1;
  }
  std::array<std::uint32_t, 8> v = state_;  // a b c d e f g h
  for (std::size_t t = 0; t < 64; ++t) {
    const std::uint32_t e = v.at(4);
    const std::uint32_t a = v.at(0);
    const std::uint32_t big_s1 = rotate_right(e, 6) ^ rotate_right(e, 11) ^ rotate_right(e, 25);
    const std::uint32_t choose = (e & v.at(5)) ^ (~e & v.at(6));
    const std::uint32_t temp1 = v.at(7) + big_s1 + choose + kRoundConstants.at(t) + w.at(t);
    const std::uint32_t big_s0 = rotate_right(a, 2) ^ rotate_right(a, 13) ^ rotate_right(a, 22);
    const std::uint32_t majority = (a & v.at(1)) ^ (a & v.at(2)) ^ (v.at(1) & v.at(2));
    for (std::size_t k = 7; k > 0; --k) {
      v.at(k) = v.at(k - 1);
    }
    v.at(4) += temp1;
    v.at(0) = temp1 + big_s0 + majority;
  }
  for (std::size_t k = 0; k < state_.size(); ++k) {
    state_.at(k) += v.at(k);
  }
}

void Sha256::absorb(std::uint8_t byte) noexcept {
  block_.at(block_used_) = byte;
  ++block_used_;
  if (block_used_ == kBlockBytes) {
    compress(block_);
    block_used_ = 0;
  }
}

void Sha256::update(const std::uint8_t* data, std::size_t size) noexcept {
  if (spent_ || data == nullptr) {
    return;
  }
  total_bytes_ += size;
  for (std::size_t i = 0; i < size; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): the caller gives size bytes.
    absorb(data[i]);
  }
}

Sha256Digest Sha256::finish() noexcept {
  if (spent_) {
    return digest_;
  }
  const std::uint64_t bit_length = total_bytes_ * 8U;
  absorb(0x80U);
  while (block_used_ != kBlockBytes - 8) {
    absorb(0U);
  }
  for (unsigned shift = 64; shift > 0; shift -= 8) {
    absorb(static_cast<std::uint8_t>((bit_length >> (shift - 8U)) & 0xFFU));
  }
  for (std::size_t i = 0; i < state_.size(); ++i) {
    for (std::size_t k = 0; k < 4; ++k) {
      digest_.at((4 * i) + k) = static_cast<std::uint8_t>(
          (state_.at(i) >> (24U - (8U * static_cast<unsigned>(k)))) & 0xFFU);
    }
  }
  spent_ = true;
  return digest_;
}

std::string to_hex(const Sha256Digest& digest) {
  constexpr std::array<char, 16> digits{'0', '1', '2', '3', '4', '5', '6', '7',
                                        '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'};
  std::string text;
  text.reserve(2 * digest.size());
  for (const std::uint8_t byte : digest) {
    text.push_back(digits.at(static_cast<std::size_t>(byte >> 4U)));
    text.push_back(digits.at(static_cast<std::size_t>(byte & 0x0FU)));
  }
  return text;
}

bool sha256_file(const std::filesystem::path& path, Sha256Digest& out) {
  std::error_code error;
  if (!std::filesystem::is_regular_file(path, error) || error) {
    return false;
  }
  std::ifstream file(path, std::ios::binary);
  if (!file.is_open()) {
    return false;
  }
  std::vector<char> buffer(kFileBlockBytes);
  Sha256 sha;
  while (true) {
    file.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const std::streamsize count = file.gcount();
    if (file.bad()) {
      return false;
    }
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): bytes seen as unsigned bytes.
    sha.update(reinterpret_cast<const std::uint8_t*>(buffer.data()),
               static_cast<std::size_t>(count));
    if (file.eof()) {
      break;
    }
    if (file.fail()) {
      return false;
    }
  }
  out = sha.finish();
  return true;
}

}  // namespace sinus::desktop::core
