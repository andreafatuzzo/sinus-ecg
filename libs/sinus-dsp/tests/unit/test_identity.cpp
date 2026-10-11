#include <gtest/gtest.h>

#include <string>

#include "sinus/dsp/version.hpp"

TEST(Identity, VersionIsTheContentOfTheVersionFile) {
  const sinus::dsp::LibraryIdentity id = sinus::dsp::library_identity();
  EXPECT_STREQ(id.version, SINUS_DSP_TEST_VERSION);
}

TEST(Identity, SourceDigestIsSixtyFourLowercaseHexDigits) {
  const std::string digest = sinus::dsp::library_identity().source_sha256;
  ASSERT_EQ(digest.size(), 64U);
  EXPECT_EQ(digest.find_first_not_of("0123456789abcdef"), std::string::npos) << digest;
}
