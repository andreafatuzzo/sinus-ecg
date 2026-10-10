# The verification code of the library (architecture-m2.md 14.12): the reader of the golden
# vectors, the expected set, the equivalence check and its results. It is not part of the library
# (no digest, not linked into the firmware).
add_library(sinus_dsp_verification STATIC
  src/golden_reader.cpp src/golden_set.cpp src/equivalence.cpp src/equivalence_folder.cpp
  src/equivalence_report.cpp src/sha256.cpp src/golden_pack.cpp)
add_library(sinus::dsp_verification ALIAS sinus_dsp_verification)
target_include_directories(sinus_dsp_verification PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(sinus_dsp_verification PUBLIC sinus::dsp)
sinus_dsp_apply_flags(sinus_dsp_verification)

# sinus_dsp_equivalence --vectors <folder> --results <file>
add_executable(sinus_dsp_equivalence tools/equivalence_main.cpp)
target_link_libraries(sinus_dsp_equivalence PRIVATE sinus::dsp_verification)
target_compile_definitions(sinus_dsp_equivalence PRIVATE
  "SINUS_DSP_BUILD_TARGET=\"computer (${CMAKE_SYSTEM_PROCESSOR}, ${CMAKE_SYSTEM_NAME}, ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION})\"")
sinus_dsp_apply_flags(sinus_dsp_equivalence)

# sinus_dsp_golden_pack --vectors <folder> --output <file>: the binary pack of the ESP32-S3 test app
# (architecture-m2.md 14.13, SRS-036)
add_executable(sinus_dsp_golden_pack tools/golden_pack_main.cpp)
target_link_libraries(sinus_dsp_golden_pack PRIVATE sinus::dsp_verification)
sinus_dsp_apply_flags(sinus_dsp_golden_pack)

if(SINUS_DSP_TIDY)
  set_target_properties(sinus_dsp_verification sinus_dsp_equivalence sinus_dsp_golden_pack
                        PROPERTIES CXX_CLANG_TIDY "${_tidy_command}")
endif()
