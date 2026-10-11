#include <gtest/gtest.h>

#include <string>

#include "core/identity.hpp"
#include "sinus/dsp/version.hpp"

namespace core = sinus::desktop::core;

namespace {

bool is_sha256_hex(const std::string& text) {
  return text.size() == 64U && text.find_first_not_of("0123456789abcdef") == std::string::npos;
}

}  // namespace

TEST(Identity, TextStatesEveryInputOnItsLine) {
  const core::IdentityInputs inputs{
      core::ItemIdentity{"1.2.3.dev0", "aa11"}, core::ItemIdentity{"1.2.3.dev0", "bb22"},
      core::BuildInfo{"6.12.0", "GNU 14.2.0", "Release", false}, "6.12.1"};
  EXPECT_EQ(core::identity_text(inputs),
            "sinus-desktop 1.2.3.dev0, source SHA-256 aa11\n"
            "sinus-dsp 1.2.3.dev0, source SHA-256 bb22\n"
            "Qt 6.12.0 at build, 6.12.1 at run time\n"
            "Compiler GNU 14.2.0, build type Release\n"
            "Qt version check: on\n");
}

TEST(Identity, TextStatesThatTheQtVersionCheckWasOff) {
  const core::IdentityInputs inputs{core::ItemIdentity{"v", "d"}, core::ItemIdentity{"w", "e"},
                                    core::BuildInfo{"6.11.0", "Clang 18.1.3", "Debug", true},
                                    "6.11.0"};
  const std::string text = core::identity_text(inputs);
  EXPECT_NE(text.find("\nQt version check: off (SINUS_DESKTOP_ALLOW_OTHER_QT)\n"),
            std::string::npos)
      << text;
}

TEST(Identity, DesktopVersionIsTheContentOfTheVersionFile) {
  EXPECT_STREQ(core::desktop_identity().version, SINUS_DESKTOP_TEST_VERSION);
}

TEST(Identity, DesktopDigestIsSixtyFourLowercaseHexDigits) {
  const std::string digest = core::desktop_identity().source_sha256;
  EXPECT_TRUE(is_sha256_hex(digest)) << digest;
}

TEST(Identity, BuildInfoComesFromTheBuild) {
  const core::BuildInfo build = core::build_info();
  EXPECT_STREQ(build.qt_build_version, SINUS_DESKTOP_TEST_QT_VERSION);
  EXPECT_EQ(build.other_qt_allowed, SINUS_DESKTOP_TEST_OTHER_QT != 0);
  EXPECT_FALSE(std::string(build.compiler).empty());
  EXPECT_FALSE(std::string(build.build_type).empty());
}

TEST(Identity, CurrentTextUsesTheIdentitiesOfThisBuild) {
  const sinus::dsp::LibraryIdentity library = sinus::dsp::library_identity();
  const core::ItemIdentity desktop = core::desktop_identity();
  const core::BuildInfo build = core::build_info();
  const std::string expected = core::identity_text(core::IdentityInputs{
      desktop, core::ItemIdentity{library.version, library.source_sha256}, build, "9.9.9"});
  EXPECT_EQ(core::current_identity_text("9.9.9"), expected);
  EXPECT_STREQ(library.version, SINUS_DESKTOP_TEST_LIBRARY_VERSION);
}
