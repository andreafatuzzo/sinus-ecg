# ESP-IDF component of the verification code that runs on the device (architecture-m2.md 14.13):
# the equivalence check, its results, the SHA-256 and the pack reader. Not the text reader and the
# folder check (they need <filesystem>), which only the computer uses.
get_filename_component(SINUS_DSP_ROOT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
set(SINUS_DSP_VERIFICATION "${SINUS_DSP_ROOT}/verification")

idf_component_register(
  SRCS "${SINUS_DSP_VERIFICATION}/src/equivalence.cpp"
       "${SINUS_DSP_VERIFICATION}/src/equivalence_report.cpp"
       "${SINUS_DSP_VERIFICATION}/src/golden_set.cpp"
       "${SINUS_DSP_VERIFICATION}/src/golden_pack.cpp"
       "${SINUS_DSP_VERIFICATION}/src/sha256.cpp"
  INCLUDE_DIRS "${SINUS_DSP_VERIFICATION}/include"
  REQUIRES sinus_dsp)

if(NOT CMAKE_BUILD_EARLY_EXPANSION)
  include("${SINUS_DSP_ROOT}/cmake/Flags.cmake")
  target_compile_options(${COMPONENT_LIB} PRIVATE -std=c++17)
  sinus_dsp_apply_flags(${COMPONENT_LIB})
endif()
