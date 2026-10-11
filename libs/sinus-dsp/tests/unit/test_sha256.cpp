#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <string>

#include "sinus/dsp/verification/sha256.hpp"

namespace {

using sinus::dsp::verification::Sha256;
using sinus::dsp::verification::Sha256Digest;

std::string hex(const Sha256Digest& digest) {
  static constexpr char kDigits[] = "0123456789abcdef";
  std::string text;
  for (const std::uint8_t byte : digest) {
    text.push_back(kDigits[byte >> 4U]);
    text.push_back(kDigits[byte & 0xFU]);
  }
  return text;
}

std::string hash_of(const std::string& text) {
  Sha256 hash;
  hash.update(reinterpret_cast<const std::uint8_t*>(text.data()), text.size());
  return hex(hash.finish());
}

// The vectors of FIPS 180-4 and NIST's examples.
TEST(Sha256, EmptyMessage) {
  EXPECT_EQ(hash_of(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
}

TEST(Sha256, Abc) {
  EXPECT_EQ(hash_of("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
}

TEST(Sha256, TwoBlockMessage) {
  EXPECT_EQ(hash_of("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
}

TEST(Sha256, OneMillionA) {
  EXPECT_EQ(hash_of(std::string(1000000, 'a')),
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
}

TEST(Sha256, LengthsAroundTheBlockAndPaddingBoundaries) {
  // The padding crosses into a further block at 56 bytes; the same text in pieces gives the same
  // digest as in one call.
  for (std::size_t length = 54; length <= 66; ++length) {
    const std::string text(length, 'x');
    Sha256 pieces;
    for (std::size_t i = 0; i < length; ++i) {
      pieces.update(reinterpret_cast<const std::uint8_t*>(text.data()) + i, 1);
    }
    EXPECT_EQ(hex(pieces.finish()), hash_of(text)) << length;
  }
  EXPECT_NE(hash_of(std::string(55, 'x')), hash_of(std::string(56, 'x')));
}

}  // namespace
