# Source lists of the library. Also read by the ESP-IDF components, so that no source file is
# listed twice and none is copied (architecture-m2.md 5.3, 14.2). The caller sets SINUS_DSP_ROOT.
# The generated identity source is not listed here: each build system adds it.
# ESP-IDF runs the component CMakeLists a first time in script mode (early expansion), where
# CONFIGURE_DEPENDS is invalid; the list is the same, only the re-glob check is left out there.
if(CMAKE_SCRIPT_MODE_FILE OR CMAKE_BUILD_EARLY_EXPANSION)
  set(SINUS_DSP_GLOB_OPTION "")
else()
  set(SINUS_DSP_GLOB_OPTION CONFIGURE_DEPENDS)
endif()
file(GLOB_RECURSE SINUS_DSP_SOURCES ${SINUS_DSP_GLOB_OPTION} "${SINUS_DSP_ROOT}/src/*.cpp")
file(GLOB_RECURSE SINUS_DSP_HEADERS ${SINUS_DSP_GLOB_OPTION}
     "${SINUS_DSP_ROOT}/include/*.hpp" "${SINUS_DSP_ROOT}/src/*.hpp")
