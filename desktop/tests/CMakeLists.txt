# Tests of the desktop application (architecture-m3.md 15.16). GoogleTest 1.18.0, fetched by URL
# and checked by SHA-256 as for the library (architecture-m2.md 14.2). A computer without network
# access sets FETCHCONTENT_SOURCE_DIR_GOOGLETEST to a copy. A test tool, not SOUP.
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

find_package(Qt6 REQUIRED COMPONENTS Test)

# The test main of the Qt executables: a QApplication on the offscreen platform. An object
# library, so that an executable without tests of its own still has a source.
add_library(sinus_desktop_test_main OBJECT support/qt_test_main.cpp)
target_link_libraries(sinus_desktop_test_main PUBLIC GTest::gtest Qt6::Widgets Qt6::Test)
sinus_desktop_apply_test_flags(sinus_desktop_test_main)

# Test environment: LeakSanitizer suppressions for leaks inside Qt and its system libraries, when
# the build uses the sanitizers (preset asan-ubsan).
set(SINUS_DESKTOP_TEST_ENVIRONMENT "")
if(CMAKE_CXX_FLAGS MATCHES "sanitize=address")
  list(APPEND SINUS_DESKTOP_TEST_ENVIRONMENT
       "LSAN_OPTIONS=suppressions=${CMAKE_CURRENT_SOURCE_DIR}/sanitizers/lsan.supp:print_suppressions=0")
endif()

function(sinus_desktop_discover target label)
  gtest_discover_tests(${target} PROPERTIES LABELS ${label}
                       ENVIRONMENT "${SINUS_DESKTOP_TEST_ENVIRONMENT}" DISCOVERY_MODE PRE_TEST)
endfunction()

file(STRINGS "${SINUS_DESKTOP_REPO_ROOT}/libs/sinus-dsp/VERSION" _library_version LIMIT_COUNT 1)
string(STRIP "${_library_version}" _library_version)

# Developer's unit tests of core, without Qt: the executable also proves that core needs no Qt.
add_executable(sinus_desktop_core_unit_tests
  unit/test_identity.cpp unit/test_command_line.cpp unit/test_source_digest.cpp)
# The SHA-256 of the library's verification code computes the expected digest independently.
target_link_libraries(sinus_desktop_core_unit_tests PRIVATE sinus_desktop_core
                      sinus::dsp_verification GTest::gtest_main)
target_compile_definitions(sinus_desktop_core_unit_tests PRIVATE
  "SINUS_DESKTOP_TEST_VERSION=\"${SINUS_DESKTOP_VERSION_TEXT}\""
  "SINUS_DESKTOP_TEST_LIBRARY_VERSION=\"${_library_version}\""
  "SINUS_DESKTOP_TEST_QT_VERSION=\"${Qt6_VERSION}\""
  "SINUS_DESKTOP_TEST_REPO_ROOT=\"${SINUS_DESKTOP_REPO_ROOT}\""
  "SINUS_DESKTOP_TEST_OTHER_QT=${_other_qt}")
sinus_desktop_apply_test_flags(sinus_desktop_core_unit_tests)
sinus_desktop_discover(sinus_desktop_core_unit_tests unit)

# Developer's unit tests of io and ui.
add_executable(sinus_desktop_unit_tests unit/test_qt_versions.cpp unit/test_main_window.cpp
  $<TARGET_OBJECTS:sinus_desktop_test_main>)
target_link_libraries(sinus_desktop_unit_tests PRIVATE sinus_desktop_ui sinus_desktop_io
                      GTest::gtest Qt6::Widgets Qt6::Test)
sinus_desktop_apply_test_flags(sinus_desktop_unit_tests)
sinus_desktop_discover(sinus_desktop_unit_tests unit)

# `sinus-desktop --version` prints the identity text and exits.
add_test(NAME sinus_desktop_version COMMAND sinus-desktop --version)
string(REPLACE "." "[.]" _version_regex "${SINUS_DESKTOP_VERSION_TEXT}")
set_tests_properties(sinus_desktop_version PROPERTIES LABELS unit
  ENVIRONMENT "${SINUS_DESKTOP_TEST_ENVIRONMENT}"
  PASS_REGULAR_EXPRESSION "^sinus-desktop ${_version_regex}, source SHA-256 [0-9a-f]+\nsinus-dsp ")

# Requirement tests (QA) and system tests (test engineer): every requirements/*.cpp and
# system/*.cpp goes into one executable each, with the Qt test main; they build without tests.
foreach(kind requirement system)
  if(kind STREQUAL "requirement")
    set(folder requirements)
  else()
    set(folder system)
  endif()
  file(GLOB _sources CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/${folder}/*.cpp")
  add_executable(sinus_desktop_${kind}_tests ${_sources} $<TARGET_OBJECTS:sinus_desktop_test_main>)
  target_link_libraries(sinus_desktop_${kind}_tests PRIVATE sinus_desktop_ui sinus_desktop_io
                        sinus_desktop_core GTest::gtest Qt6::Widgets Qt6::Test)
  sinus_desktop_apply_test_flags(sinus_desktop_${kind}_tests)
  sinus_desktop_discover(sinus_desktop_${kind}_tests ${kind})
endforeach()
# The subset run of the replay and the WFDB cross-checks of the writer come with their groups
# (architecture-m3.md 15.16, 15.18).
