# Source lists of the library. Also read by the ESP-IDF components, so that no source file is
# listed twice and none is copied (architecture-m2.md 5.3, 14.2). The caller sets SINUS_DSP_ROOT.
# The generated identity source is not listed here: each build system adds it.
file(GLOB_RECURSE SINUS_DSP_SOURCES CONFIGURE_DEPENDS "${SINUS_DSP_ROOT}/src/*.cpp")
file(GLOB_RECURSE SINUS_DSP_HEADERS CONFIGURE_DEPENDS
     "${SINUS_DSP_ROOT}/include/*.hpp" "${SINUS_DSP_ROOT}/src/*.hpp")
