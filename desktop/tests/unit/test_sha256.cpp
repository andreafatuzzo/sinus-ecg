// Developer's unit tests of the SHA-256 of core (architecture-m3.md 17.7).

#include <gtest/gtest.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <string>
#include <string_view>
#include <vector>

#include "core/sha256.hpp"
#include "sinus/dsp/verification/sha256.hpp"
#include "temp_folder.hpp"

namespace {

using sinus::desktop::core::Sha256;
using sinus::desktop::core::sha256_file;
using sinus::desktop::core::Sha256Digest;
using sinus::desktop::core::to_hex;
using sinus::desktop::test::TempFolder;

std::vector<std::uint8_t> bytes_of(std::string_view text) {
  std::vector<std::uint8_t> bytes;
  bytes.reserve(text.size());
  for (const char c : text) {
    bytes.push_back(static_cast<std::uint8_t>(c));
  }
  return bytes;
}

std::string hex_of(const std::vector<std::uint8_t>& bytes) {
  Sha256 sha;
  sha.update(bytes.data(), bytes.size());
  return to_hex(sha.finish());
}

// A deterministic byte pattern that is not periodic in 64 bytes.
std::vector<std::uint8_t> pattern(std::size_t size) {
  std::vector<std::uint8_t> bytes(size);
  std::uint32_t state = 12345U;
  for (std::uint8_t& byte : bytes) {
    state = (state * 1103515245U) + 12345U;
    byte = static_cast<std::uint8_t>(state >> 24U);
  }
  return bytes;
}

std::string independent_hex(const std::vector<std::uint8_t>& bytes) {
  sinus::dsp::verification::Sha256 sha;
  sha.update(bytes.data(), bytes.size());
  const sinus::dsp::verification::Sha256Digest digest = sha.finish();
  Sha256Digest copy{};
  for (std::size_t k = 0; k < digest.size(); ++k) {
    copy.at(k) = digest.at(k);
  }
  return to_hex(copy);
}

// FIPS 180-4 examples (NIST CSRC example values).
TEST(Sha256, FipsExamples) {
  EXPECT_EQ(hex_of({}), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  EXPECT_EQ(hex_of(bytes_of("abc")),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  EXPECT_EQ(hex_of(bytes_of("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
  EXPECT_EQ(hex_of(bytes_of("abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijkl"
                            "mnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu")),
            "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1");
}

TEST(Sha256, OneMillionA) {
  const std::vector<std::uint8_t> bytes(1'000'000, static_cast<std::uint8_t>('a'));
  EXPECT_EQ(hex_of(bytes), "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
}

// Every length around the padding boundaries (55, 56, 63, 64 bytes, ...) against the library's
// verification SHA-256, written independently.
TEST(Sha256, EveryLengthUpTo300MatchesAnIndependentImplementation) {
  for (std::size_t size = 0; size <= 300; ++size) {
    const std::vector<std::uint8_t> bytes = pattern(size);
    EXPECT_EQ(hex_of(bytes), independent_hex(bytes)) << size;
  }
}

TEST(Sha256, TheDigestDoesNotDependOnHowTheBytesAreSplit) {
  const std::vector<std::uint8_t> bytes = pattern(1000);
  const std::string whole = hex_of(bytes);
  for (const std::size_t chunk : {std::size_t{1}, std::size_t{7}, std::size_t{63}, std::size_t{64},
                                  std::size_t{65}, std::size_t{999}}) {
    Sha256 sha;
    for (std::size_t at = 0; at < bytes.size(); at += chunk) {
      const std::size_t count = std::min(chunk, bytes.size() - at);
      sha.update(&bytes.at(at), count);
    }
    EXPECT_EQ(to_hex(sha.finish()), whole) << chunk;
  }
}

TEST(Sha256, AnEmptyOrNullUpdateChangesNothing) {
  const std::vector<std::uint8_t> bytes = bytes_of("abc");
  Sha256 sha;
  sha.update(nullptr, 0);
  sha.update(bytes.data(), 0);
  sha.update(bytes.data(), bytes.size());
  sha.update(nullptr, 5);
  EXPECT_EQ(to_hex(sha.finish()), hex_of(bytes));
}

TEST(Sha256, TheObjectIsSpentAfterFinish) {
  const std::vector<std::uint8_t> bytes = bytes_of("abc");
  Sha256 sha;
  sha.update(bytes.data(), bytes.size());
  const Sha256Digest first = sha.finish();
  sha.update(bytes.data(), bytes.size());
  EXPECT_EQ(sha.finish(), first);
}

TEST(Sha256, HexIsLowercaseAndInByteOrder) {
  Sha256Digest digest{};
  for (std::size_t k = 0; k < digest.size(); ++k) {
    digest.at(k) = static_cast<std::uint8_t>((k * 8U) + 7U);
  }
  digest.at(31) = 0xFFU;
  EXPECT_EQ(to_hex(digest), "070f171f272f373f474f575f676f777f878f979fa7afb7bfc7cfd7dfe7eff7ff");
}

TEST(Sha256File, ReadsAFileOfSeveralBlocks) {
  const TempFolder folder;
  // 2.5 MiB and 3 bytes: two whole blocks of 1 MiB and a partial one.
  const std::vector<std::uint8_t> bytes = pattern((5U * 1024U * 1024U / 2U) + 3U);
  folder.write("data.bin", bytes);
  Sha256Digest digest{};
  ASSERT_TRUE(sha256_file(folder.path() / "data.bin", digest));
  EXPECT_EQ(to_hex(digest), independent_hex(bytes));
}

TEST(Sha256File, ReadsAFileOfExactlyOneBlock) {
  const TempFolder folder;
  const std::vector<std::uint8_t> bytes = pattern(1024U * 1024U);
  folder.write("data.bin", bytes);
  Sha256Digest digest{};
  ASSERT_TRUE(sha256_file(folder.path() / "data.bin", digest));
  EXPECT_EQ(to_hex(digest), independent_hex(bytes));
}

TEST(Sha256File, AnEmptyFileHasTheDigestOfNothing) {
  const TempFolder folder;
  folder.write("empty.bin", std::string_view{});
  Sha256Digest digest{};
  ASSERT_TRUE(sha256_file(folder.path() / "empty.bin", digest));
  EXPECT_EQ(to_hex(digest), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
}

TEST(Sha256File, AMissingFileOrAFolderCannotBeRead) {
  const TempFolder folder;
  Sha256Digest digest{};
  EXPECT_FALSE(sha256_file(folder.path() / "missing.bin", digest));
  EXPECT_FALSE(sha256_file(folder.path(), digest));
}

}  // namespace
