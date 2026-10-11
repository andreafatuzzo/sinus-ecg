// SRS-036: SHA-256 (FIPS 180-4).
#include "sinus/dsp/verification/sha256.hpp"

#include <array>
#include <cstddef>
#include <cstdint>

namespace sinus::dsp::verification {

namespace {

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

constexpr std::uint32_t rotate_right(std::uint32_t value, unsigned bits) noexcept {
  return (value >> bits) | (value << (32U - bits));
}

}  // namespace

void Sha256::compress(const std::uint8_t* block) noexcept {
  std::array<std::uint32_t, 64> w{};
  for (std::size_t t = 0; t < 16; ++t) {
    const std::size_t at = 4 * t;
    // NOLINTBEGIN(cppcoreguidelines-pro-bounds-pointer-arithmetic): a 64-byte block.
    w.at(t) = (static_cast<std::uint32_t>(block[at]) << 24U) |
              (static_cast<std::uint32_t>(block[at + 1]) << 16U) |
              (static_cast<std::uint32_t>(block[at + 2]) << 8U) |
              static_cast<std::uint32_t>(block[at + 3]);
    // NOLINTEND(cppcoreguidelines-pro-bounds-pointer-arithmetic)
  }
  for (std::size_t t = 16; t < 64; ++t) {
    const std::uint32_t s0 =
        rotate_right(w.at(t - 15), 7) ^ rotate_right(w.at(t - 15), 18) ^ (w.at(t - 15) >> 3U);
    const std::uint32_t s1 =
        rotate_right(w.at(t - 2), 17) ^ rotate_right(w.at(t - 2), 19) ^ (w.at(t - 2) >> 10U);
    w.at(t) = w.at(t - 16) + s0 + w.at(t - 7) + s1;
  }
  std::uint32_t a = state_.at(0);
  std::uint32_t b = state_.at(1);
  std::uint32_t c = state_.at(2);
  std::uint32_t d = state_.at(3);
  std::uint32_t e = state_.at(4);
  std::uint32_t f = state_.at(5);
  std::uint32_t g = state_.at(6);
  std::uint32_t h = state_.at(7);
  for (std::size_t t = 0; t < 64; ++t) {
    const std::uint32_t big_s1 = rotate_right(e, 6) ^ rotate_right(e, 11) ^ rotate_right(e, 25);
    const std::uint32_t choose = (e & f) ^ (~e & g);
    const std::uint32_t temp1 = h + big_s1 + choose + kRoundConstants.at(t) + w.at(t);
    const std::uint32_t big_s0 = rotate_right(a, 2) ^ rotate_right(a, 13) ^ rotate_right(a, 22);
    const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
    const std::uint32_t temp2 = big_s0 + majority;
    h = g;
    g = f;
    f = e;
    e = d + temp1;
    d = c;
    c = b;
    b = a;
    a = temp1 + temp2;
  }
  state_.at(0) += a;
  state_.at(1) += b;
  state_.at(2) += c;
  state_.at(3) += d;
  state_.at(4) += e;
  state_.at(5) += f;
  state_.at(6) += g;
  state_.at(7) += h;
}

void Sha256::update(const std::uint8_t* data, std::size_t count) noexcept {
  total_bytes_ += count;
  for (std::size_t i = 0; i < count; ++i) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic): the caller's buffer.
    block_.at(block_used_++) = data[i];
    if (block_used_ == kBlockBytes) {
      compress(block_.data());
      block_used_ = 0;
    }
  }
}

Sha256Digest Sha256::finish() noexcept {
  const std::uint64_t bit_length = total_bytes_ * 8U;
  const std::uint8_t one = 0x80U;
  const std::uint8_t zero = 0U;
  update(&one, 1);
  while (block_used_ != kBlockBytes - 8) {
    update(&zero, 1);
  }
  for (unsigned shift = 64; shift > 0; shift -= 8) {
    const auto byte = static_cast<std::uint8_t>((bit_length >> (shift - 8U)) & 0xFFU);
    update(&byte, 1);
  }
  Sha256Digest digest{};
  for (std::size_t i = 0; i < 8; ++i) {
    for (std::size_t k = 0; k < 4; ++k) {
      digest.at((4 * i) + k) = static_cast<std::uint8_t>(
          (state_.at(i) >> (24U - (8U * static_cast<unsigned>(k)))) & 0xFFU);
    }
  }
  return digest;
}

}  // namespace sinus::dsp::verification
