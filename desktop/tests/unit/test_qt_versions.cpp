#include <gtest/gtest.h>

#include <QtGlobal>
#include <string>

#include "core/identity.hpp"
#include "io/qt_versions.hpp"

TEST(QtVersions, RuntimeVersionIsTheLoadedQt) {
  EXPECT_EQ(sinus::desktop::io::qt_runtime_version(), std::string(qVersion()));
}

TEST(QtVersions, BuildVersionIsTheQtOfTheHeaders) {
  EXPECT_STREQ(sinus::desktop::core::build_info().qt_build_version, QT_VERSION_STR);
}
