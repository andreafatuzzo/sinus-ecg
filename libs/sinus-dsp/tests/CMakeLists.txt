# GoogleTest 1.18.0, fetched by URL and checked by SHA-256 (architecture-m2.md 14.2). A computer
# without network access sets FETCHCONTENT_SOURCE_DIR_GOOGLETEST to a copy. A test tool, not SOUP.
include(FetchContent)
FetchContent_Declare(
  googletest
  URL https://github.com/google/googletest/releases/download/v1.18.0/googletest-1.18.0.tar.gz
  URL_HASH SHA256=6e3191c1455468b3fc35a417fb565c1c5071aee1b7e7f85e30cf48a98d37d8b5
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)
include(GoogleTest)

# Developer's unit tests: label "unit". The requirement and system tests (QA, test engineer)
# are added by the groups that bring them.
add_executable(sinus_dsp_unit_tests
  unit/test_identity.cpp unit/test_arithmetic.cpp unit/test_config.cpp unit/test_biquad.cpp
  unit/test_conditioner.cpp unit/test_chain.cpp unit/test_detector_math.cpp
  unit/test_qrs_detector.cpp unit/test_interval_estimate.cpp unit/test_heart_rate.cpp
  unit/test_signal_quality.cpp unit/test_harness.cpp)
target_link_libraries(sinus_dsp_unit_tests PRIVATE sinus::dsp sinus_dsp_harness_static
                      GTest::gtest_main)
# The private helpers of src/ (compensated sum, search-back limit) are tested directly.
target_include_directories(sinus_dsp_unit_tests PRIVATE "${PROJECT_SOURCE_DIR}/src")
target_compile_definitions(sinus_dsp_unit_tests PRIVATE
  SINUS_DSP_TEST_VERSION="${SINUS_DSP_VERSION_TEXT}")
sinus_dsp_apply_test_flags(sinus_dsp_unit_tests)
gtest_discover_tests(sinus_dsp_unit_tests PROPERTIES LABELS unit DISCOVERY_MODE PRE_TEST)

# Unit tests of the verification code (reader, equivalence check, results), label "unit".
add_executable(sinus_dsp_verification_unit_tests
  unit/test_golden_reader.cpp unit/test_equivalence.cpp unit/test_equivalence_report.cpp
  unit/test_sha256.cpp unit/test_golden_pack.cpp)
target_link_libraries(sinus_dsp_verification_unit_tests PRIVATE sinus::dsp_verification
                      GTest::gtest_main)
sinus_dsp_apply_test_flags(sinus_dsp_verification_unit_tests)
gtest_discover_tests(sinus_dsp_verification_unit_tests PROPERTIES LABELS unit
                     DISCOVERY_MODE PRE_TEST)

# Requirement tests (QA): every requirements/*.cpp goes into one executable, label "requirement".
file(GLOB SINUS_DSP_REQUIREMENT_SOURCES CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/requirements/*.cpp")
if(SINUS_DSP_REQUIREMENT_SOURCES)
  add_executable(sinus_dsp_requirement_tests ${SINUS_DSP_REQUIREMENT_SOURCES})
  # SRS-034, SRS-037: the tests also verify the verification code and run its tool; SINUS_GOLDEN_DIR
  # names the folder of the golden vectors of the same commit (the tests skip without it).
  target_link_libraries(sinus_dsp_requirement_tests PRIVATE sinus::dsp sinus::dsp_verification
                        GTest::gtest_main)
  add_dependencies(sinus_dsp_requirement_tests sinus_dsp_equivalence)
  target_compile_definitions(sinus_dsp_requirement_tests PRIVATE
    "SINUS_QA_EQUIVALENCE_TOOL=\"$<TARGET_FILE:sinus_dsp_equivalence>\""
    "SINUS_QA_LIBRARY_DIR=\"${PROJECT_SOURCE_DIR}\"")
  sinus_dsp_apply_test_flags(sinus_dsp_requirement_tests)
  gtest_discover_tests(sinus_dsp_requirement_tests PROPERTIES LABELS requirement
                       DISCOVERY_MODE PRE_TEST)
endif()

# SRS-032 (QA): counts every dynamic memory request, so it replaces operator new and delete and is
# its own executable (architecture-m2.md 14.10). On Linux without sanitizers it also wraps malloc,
# calloc, realloc and free.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/requirements/alloc/test_srs_032_fixed_memory.cpp")
  add_executable(sinus_dsp_requirement_alloc_tests
    requirements/alloc/test_srs_032_fixed_memory.cpp)
  target_link_libraries(sinus_dsp_requirement_alloc_tests PRIVATE sinus::dsp GTest::gtest_main)
  sinus_dsp_apply_test_flags(sinus_dsp_requirement_alloc_tests)
  if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND NOT CMAKE_CXX_FLAGS MATCHES "sanitize")
    target_compile_definitions(sinus_dsp_requirement_alloc_tests PRIVATE SINUS_QA_WRAP_MALLOC)
    target_link_options(sinus_dsp_requirement_alloc_tests PRIVATE
      -Wl,--wrap=malloc -Wl,--wrap=calloc -Wl,--wrap=realloc -Wl,--wrap=free)
  endif()
  gtest_discover_tests(sinus_dsp_requirement_alloc_tests PROPERTIES LABELS requirement
                       DISCOVERY_MODE PRE_TEST)
endif()

# No allocation and no exception anywhere in the library (architecture-m2.md 14.17).
find_program(SINUS_DSP_NM NAMES llvm-nm nm REQUIRED)
add_test(NAME no_heap_symbols
  COMMAND ${CMAKE_COMMAND} -DNM=${SINUS_DSP_NM} -DARCHIVE=$<TARGET_FILE:sinus_dsp>
          -P ${CMAKE_CURRENT_SOURCE_DIR}/no_heap_symbols.cmake)
# The check must detect what it looks for: the same script on a probe that calls malloc.
add_library(sinus_dsp_heap_probe STATIC unit/heap_probe.cpp)
sinus_dsp_apply_test_flags(sinus_dsp_heap_probe)
add_test(NAME no_heap_symbols_probe
  COMMAND ${CMAKE_COMMAND} -DNM=${SINUS_DSP_NM} -DARCHIVE=$<TARGET_FILE:sinus_dsp_heap_probe>
          -P ${CMAKE_CURRENT_SOURCE_DIR}/no_heap_symbols.cmake)
set_tests_properties(no_heap_symbols_probe PROPERTIES PASS_REGULAR_EXPRESSION "forbidden symbol")

# The digest script on a fixture tree (architecture-m2.md 14.15).
add_test(NAME source_digest
  COMMAND ${CMAKE_COMMAND} -DSCRIPT=${PROJECT_SOURCE_DIR}/cmake/SourceDigest.cmake
          -DWORK=${CMAKE_CURRENT_BINARY_DIR}/source_digest
          -P ${CMAKE_CURRENT_SOURCE_DIR}/source_digest_test.cmake)
set_tests_properties(no_heap_symbols no_heap_symbols_probe source_digest PROPERTIES LABELS unit)
