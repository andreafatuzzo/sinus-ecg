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
  unit/test_conditioner.cpp unit/test_chain.cpp)
target_link_libraries(sinus_dsp_unit_tests PRIVATE sinus::dsp GTest::gtest_main)
target_compile_definitions(sinus_dsp_unit_tests PRIVATE
  SINUS_DSP_TEST_VERSION="${SINUS_DSP_VERSION_TEXT}")
sinus_dsp_apply_test_flags(sinus_dsp_unit_tests)
gtest_discover_tests(sinus_dsp_unit_tests PROPERTIES LABELS unit DISCOVERY_MODE PRE_TEST)

# Requirement tests (QA): every requirements/*.cpp goes into one executable, label "requirement".
file(GLOB SINUS_DSP_REQUIREMENT_SOURCES CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/requirements/*.cpp")
if(SINUS_DSP_REQUIREMENT_SOURCES)
  add_executable(sinus_dsp_requirement_tests ${SINUS_DSP_REQUIREMENT_SOURCES})
  target_link_libraries(sinus_dsp_requirement_tests PRIVATE sinus::dsp GTest::gtest_main)
  sinus_dsp_apply_test_flags(sinus_dsp_requirement_tests)
  gtest_discover_tests(sinus_dsp_requirement_tests PROPERTIES LABELS requirement
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
