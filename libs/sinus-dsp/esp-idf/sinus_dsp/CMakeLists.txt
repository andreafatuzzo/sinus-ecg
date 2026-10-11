# ESP-IDF component of the real-time library (architecture-m2.md 14.13, 5.3): the sources of
# cmake/SinusDspSources.cmake and the generated identity, compiled with the options of 14.2.
# The firmware of Milestone 4 uses this component too.
get_filename_component(SINUS_DSP_ROOT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
include("${SINUS_DSP_ROOT}/cmake/SinusDspSources.cmake")

idf_component_register(SRCS ${SINUS_DSP_SOURCES}
                       INCLUDE_DIRS "${SINUS_DSP_ROOT}/include")

# Not in the early expansion pass of ESP-IDF, which only reads the requirements.
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
  include("${SINUS_DSP_ROOT}/cmake/Flags.cmake")

  # Identity (cmake/SourceDigest.cmake), as in the top-level project: the same digest of the same
  # sources, so that the results name the library of the computer and of the device alike.
  get_filename_component(SINUS_DSP_LIBS_ROOT "${SINUS_DSP_ROOT}/.." ABSOLUTE)
  get_filename_component(SINUS_DSP_DIR_NAME "${SINUS_DSP_ROOT}" NAME)
  set(SINUS_DSP_IDENTITY "${CMAKE_CURRENT_BINARY_DIR}/generated/sinus_dsp_identity.cpp")
  add_custom_command(
    OUTPUT "${SINUS_DSP_IDENTITY}"
    COMMAND ${CMAKE_COMMAND} -DLIBS_ROOT=${SINUS_DSP_LIBS_ROOT} -DITEM=${SINUS_DSP_DIR_NAME}
            -DVERSION_FILE=${SINUS_DSP_ROOT}/VERSION -DOUTPUT=${SINUS_DSP_IDENTITY}
            -P "${SINUS_DSP_ROOT}/cmake/SourceDigest.cmake"
    DEPENDS ${SINUS_DSP_SOURCES} ${SINUS_DSP_HEADERS} "${SINUS_DSP_ROOT}/VERSION"
            "${SINUS_DSP_ROOT}/cmake/SourceDigest.cmake"
    COMMENT "Generating the identity of the library"
    VERBATIM)
  target_sources(${COMPONENT_LIB} PRIVATE "${SINUS_DSP_IDENTITY}")

  # ESP-IDF builds C++ with -std=gnu++2b and contraction on; these come later and win (14.3).
  target_compile_options(${COMPONENT_LIB} PRIVATE -std=c++17)
  sinus_dsp_apply_flags(${COMPONENT_LIB})
endif()
