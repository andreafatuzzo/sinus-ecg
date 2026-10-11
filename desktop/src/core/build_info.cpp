#include "core/identity.hpp"

// The values come from CMake (desktop/CMakeLists.txt), as compile definitions of this file only.
#if !defined(SINUS_DESKTOP_QT_BUILD_VERSION) || !defined(SINUS_DESKTOP_COMPILER) || \
    !defined(SINUS_DESKTOP_BUILD_TYPE) || !defined(SINUS_DESKTOP_OTHER_QT_ALLOWED)
#error "build_info.cpp needs the compile definitions of desktop/CMakeLists.txt"
#endif

namespace sinus::desktop::core {

BuildInfo build_info() noexcept {
  return BuildInfo{SINUS_DESKTOP_QT_BUILD_VERSION, SINUS_DESKTOP_COMPILER, SINUS_DESKTOP_BUILD_TYPE,
                   SINUS_DESKTOP_OTHER_QT_ALLOWED != 0};
}

}  // namespace sinus::desktop::core
