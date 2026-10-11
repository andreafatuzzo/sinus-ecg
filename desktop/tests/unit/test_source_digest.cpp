// The source digest of the desktop application (architecture-m3.md 15.12), computed again here
// without CMake: a walk of desktop/src with std::filesystem and the SHA-256 of the library's
// verification code. The method is first checked on a fixture tree whose digest was computed
// with the shell command of 15.12.

#include <gtest/gtest.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <system_error>
#include <vector>

#include "core/identity.hpp"
#include "sinus/dsp/verification/sha256.hpp"

namespace fs = std::filesystem;

namespace {

std::string sha256_hex(const std::string& data) {
  sinus::dsp::verification::Sha256 sha;
  std::vector<std::uint8_t> bytes(data.begin(), data.end());
  sha.update(bytes.data(), bytes.size());
  const sinus::dsp::verification::Sha256Digest digest = sha.finish();
  static constexpr char kHex[] = "0123456789abcdef";
  std::string text;
  for (const std::uint8_t byte : digest) {
    text.push_back(kHex[byte >> 4U]);
    text.push_back(kHex[byte & 0x0FU]);
  }
  return text;
}

std::string read_lf(const fs::path& path) {
  std::ifstream in(path, std::ios::binary);
  std::string content((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  std::string out;
  out.reserve(content.size());
  for (std::size_t i = 0; i < content.size(); ++i) {
    if (content[i] == '\r' && i + 1 < content.size() && content[i + 1] == '\n') {
      continue;
    }
    out.push_back(content[i]);
  }
  return out;
}

bool has_hidden_component(const fs::path& relative) {
  return std::any_of(relative.begin(), relative.end(), [](const fs::path& part) {
    const std::string name = part.generic_string();
    return !name.empty() && name.front() == '.';
  });
}

// SHA-256 of the manifest of every regular file under root/desktop/src, named relative to root.
std::string desktop_digest(const fs::path& root) {
  std::vector<std::string> names;
  for (const fs::directory_entry& entry :
       fs::recursive_directory_iterator(root / "desktop" / "src")) {
    const fs::path relative = fs::relative(entry.path(), root);
    if (entry.is_regular_file() && !has_hidden_component(relative)) {
      names.push_back(relative.generic_string());
    }
  }
  std::sort(names.begin(), names.end());
  std::string manifest;
  for (const std::string& name : names) {
    manifest += sha256_hex(read_lf(root / name)) + "  " + name + "\n";
  }
  return sha256_hex(manifest);
}

void write_file(const fs::path& path, const std::string& content) {
  fs::create_directories(path.parent_path());
  std::ofstream out(path, std::ios::binary);
  out << content;
}

}  // namespace

TEST(SourceDigest, MethodMatchesTheShellCommandOnAFixtureTree) {
  const fs::path root = fs::temp_directory_path() / "sinus_desktop_digest_fixture";
  std::error_code error;
  fs::remove_all(root, error);
  write_file(root / "desktop/src/a.cpp", "int b;\r\nint c;\r\n");
  write_file(root / "desktop/src/Z/z.hpp", "int B;\n");
  write_file(root / "desktop/src/.hidden/x.cpp", "int h;\n");
  write_file(root / "desktop/src/.i.cpp", "int i;\n");
  write_file(root / "desktop/tests/t.cpp", "int t;\n");
  // find desktop/src -type f -not -path '*/.*' -print0 | LC_ALL=C sort -z \
  //   | xargs -0 sha256sum --text | sha256sum --text   (a.cpp in its LF form)
  EXPECT_EQ(desktop_digest(root),
            "3ccc2f158b9b27997e27786f05cb4d20aeadea762add14b95fadcabad3c86fc7");
  fs::remove_all(root, error);
}

TEST(SourceDigest, BuiltDigestIsTheDigestOfDesktopSrc) {
  EXPECT_EQ(sinus::desktop::core::desktop_identity().source_sha256,
            desktop_digest(SINUS_DESKTOP_TEST_REPO_ROOT));
}
