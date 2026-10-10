idf_component_register(SRCS "app_main.cpp"
                       INCLUDE_DIRS "."
                       REQUIRES sinus_dsp sinus_dsp_verification esp_partition esp_system)

if(NOT CMAKE_BUILD_EARLY_EXPANSION)
  idf_build_get_property(sinus_idf_version IDF_VER)
  include("${CMAKE_CURRENT_LIST_DIR}/../../../../cmake/Flags.cmake")
  target_compile_options(${COMPONENT_LIB} PRIVATE -std=c++17)
  sinus_dsp_apply_test_flags(${COMPONENT_LIB})
  target_compile_definitions(${COMPONENT_LIB} PRIVATE
    "SINUS_DSP_BUILD_TARGET=\"ESP32-S3 (emulator, ESP-IDF ${sinus_idf_version}, ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION})\"")
endif()
