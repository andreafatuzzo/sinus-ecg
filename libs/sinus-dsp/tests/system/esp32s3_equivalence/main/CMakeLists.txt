idf_component_register(SRCS "app_main.cpp"
                       INCLUDE_DIRS "."
                       REQUIRES sinus_dsp sinus_dsp_verification esp_partition esp_system)

# Not in the early expansion pass of ESP-IDF, which runs this file in script mode.
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
  idf_build_get_property(sinus_idf_version IDF_VER)
  include("${CMAKE_CURRENT_LIST_DIR}/../../../../cmake/Flags.cmake")
  target_compile_options(${COMPONENT_LIB} PRIVATE -std=c++17)
  sinus_dsp_apply_test_flags(${COMPONENT_LIB})

  # The build target text goes in a generated header, not in a quoted definition: a definition with
  # quotes and spaces ends up in ESP-IDF's generated property files, where it is a syntax warning.
  set(sinus_target_dir "${CMAKE_CURRENT_BINARY_DIR}/generated")
  file(WRITE "${sinus_target_dir}/sinus_build_target.h.tmp"
       "#define SINUS_DSP_BUILD_TARGET \"ESP32-S3 (emulator, ESP-IDF ${sinus_idf_version}, ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION})\"\n")
  file(COPY_FILE "${sinus_target_dir}/sinus_build_target.h.tmp"
       "${sinus_target_dir}/sinus_build_target.h" ONLY_IF_DIFFERENT)
  target_include_directories(${COMPONENT_LIB} PRIVATE "${sinus_target_dir}")
endif()
