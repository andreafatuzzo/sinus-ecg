cmake_minimum_required(VERSION 3.25)

# VERSION: one line, the version of the milestone register (architecture-m3.md 15.12).
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/VERSION" SINUS_DESKTOP_VERSION_TEXT LIMIT_COUNT 1)
string(STRIP "${SINUS_DESKTOP_VERSION_TEXT}" SINUS_DESKTOP_VERSION_TEXT)
string(REGEX MATCH "^[0-9]+(\\.[0-9]+)*" SINUS_DESKTOP_VERSION_NUMERIC
       "${SINUS_DESKTOP_VERSION_TEXT}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
             "${CMAKE_CURRENT_SOURCE_DIR}/VERSION")

project(sinus_desktop VERSION ${SINUS_DESKTOP_VERSION_NUMERIC} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(SINUS_DESKTOP_BUILD_TESTS "Build the tests" ON)
option(SINUS_DESKTOP_TIDY "Run the pinned clang-tidy on the desktop application" OFF)
option(SINUS_DESKTOP_ALLOW_OTHER_QT
       "Accept a Qt version other than qt/version.txt (local exploration only; stated in the identity)"
       OFF)

# Included by path, not through CMAKE_MODULE_PATH: the library has its own Flags.cmake.
include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/Flags.cmake")

# The library, linked and never copied (architecture-m3.md 15.3). It is not the top-level project,
# so its tests are off; EXCLUDE_FROM_ALL builds only what the desktop links. It keeps its own flags.
add_subdirectory(../libs/sinus-dsp sinus-dsp EXCLUDE_FROM_ALL)

# Qt: the modules of Milestone 3 (ADR 0009), at the version of qt/version.txt.
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network)
include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/QtPin.cmake")
qt_standard_project_setup()
# AUTOMOC only on the io and ui targets (architecture-m3.md 15.3); no .ui files.
set(CMAKE_AUTOMOC OFF)
set(CMAKE_AUTOUIC OFF)

# Identity of the desktop application (architecture-m3.md 15.12): the version and the source
# digest of desktop/src, regenerated when a source or VERSION changes.
get_filename_component(SINUS_DESKTOP_REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
file(GLOB_RECURSE SINUS_DESKTOP_ALL_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/src/*")
set(SINUS_DESKTOP_DIGEST "${CMAKE_CURRENT_BINARY_DIR}/generated/desktop_digest.txt")
set(SINUS_DESKTOP_IDENTITY "${CMAKE_CURRENT_BINARY_DIR}/generated/desktop_identity.cpp")
add_custom_command(
  OUTPUT "${SINUS_DESKTOP_IDENTITY}" "${SINUS_DESKTOP_DIGEST}"
  COMMAND ${CMAKE_COMMAND} -DROOT=${SINUS_DESKTOP_REPO_ROOT} -DITEM=desktop -DFOLDERS=src
          -DVERSION_FILE=${CMAKE_CURRENT_SOURCE_DIR}/VERSION -DDIGEST_FILE=${SINUS_DESKTOP_DIGEST}
          -P "${SINUS_DESKTOP_REPO_ROOT}/libs/sinus-dsp/cmake/SourceDigest.cmake"
  COMMAND ${CMAKE_COMMAND} -DDIGEST_FILE=${SINUS_DESKTOP_DIGEST}
          -DOUTPUT=${SINUS_DESKTOP_IDENTITY}
          -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/DesktopIdentity.cmake"
  DEPENDS ${SINUS_DESKTOP_ALL_SOURCES} "${CMAKE_CURRENT_SOURCE_DIR}/VERSION"
          "${SINUS_DESKTOP_REPO_ROOT}/libs/sinus-dsp/cmake/SourceDigest.cmake"
          "${CMAKE_CURRENT_SOURCE_DIR}/cmake/DesktopIdentity.cmake"
  COMMENT "Generating the identity of the desktop application"
  VERBATIM)

# The targets are defined here, not in desktop/src, so that no CMake file enters the digest.
set(SINUS_DESKTOP_SRC "${CMAKE_CURRENT_SOURCE_DIR}/src")
if(SINUS_DESKTOP_TIDY)
  sinus_desktop_tidy_command(SINUS_DESKTOP_TIDY_COMMAND)
endif()

# core: C++17 and the library only. No Qt include folder and no Qt link, so a Qt include fails to
# compile (architecture-m3.md 15.2).
add_library(sinus_desktop_core STATIC
  src/core/command_line.cpp src/core/identity.cpp src/core/build_info.cpp
  src/core/sha256.cpp src/core/wfdb_header.cpp src/core/wfdb_reader.cpp
  "${SINUS_DESKTOP_IDENTITY}")
target_include_directories(sinus_desktop_core PUBLIC "${SINUS_DESKTOP_SRC}")
target_link_libraries(sinus_desktop_core PUBLIC sinus::dsp)
sinus_desktop_apply_core_flags(sinus_desktop_core)
if(SINUS_DESKTOP_ALLOW_OTHER_QT)
  set(_other_qt 1)
else()
  set(_other_qt 0)
endif()
set_property(SOURCE src/core/build_info.cpp APPEND PROPERTY COMPILE_DEFINITIONS
  "SINUS_DESKTOP_QT_BUILD_VERSION=\"${Qt6_VERSION}\""
  "SINUS_DESKTOP_COMPILER=\"${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}\""
  "SINUS_DESKTOP_BUILD_TYPE=\"$<IF:$<CONFIG:>,none,$<CONFIG>>\""
  "SINUS_DESKTOP_OTHER_QT_ALLOWED=${_other_qt}")

# io: Qt Core and Qt Network.
add_library(sinus_desktop_io STATIC src/io/qt_versions.cpp)
target_link_libraries(sinus_desktop_io PUBLIC sinus_desktop_core Qt6::Core Qt6::Network)
set_target_properties(sinus_desktop_io PROPERTIES AUTOMOC ON)
sinus_desktop_apply_qt_flags(sinus_desktop_io)

# ui: Qt Widgets.
add_library(sinus_desktop_ui STATIC src/ui/main_window.cpp src/ui/main_window.hpp)
target_link_libraries(sinus_desktop_ui PUBLIC sinus_desktop_core sinus_desktop_io Qt6::Gui
                                              Qt6::Widgets)
set_target_properties(sinus_desktop_ui PROPERTIES AUTOMOC ON)
sinus_desktop_apply_qt_flags(sinus_desktop_ui)

# app: the executable.
add_executable(sinus-desktop src/app/main.cpp)
target_link_libraries(sinus-desktop PRIVATE sinus_desktop_ui sinus_desktop_io sinus_desktop_core
                                            Qt6::Widgets)
sinus_desktop_apply_qt_flags(sinus-desktop)

if(SINUS_DESKTOP_TIDY)
  set_target_properties(sinus_desktop_core sinus_desktop_io sinus_desktop_ui sinus-desktop
                        PROPERTIES CXX_CLANG_TIDY "${SINUS_DESKTOP_TIDY_COMMAND}")
  # The generated identity is not the project's code.
  set_source_files_properties("${SINUS_DESKTOP_IDENTITY}" PROPERTIES SKIP_LINTING ON)
endif()

if(SINUS_DESKTOP_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()

# SBOM of the desktop application (architecture-m3.md 15.12):
#   cmake --build <dir> --target sinus_desktop_sbom
set(SINUS_DESKTOP_SBOM "${CMAKE_CURRENT_BINARY_DIR}/sbom-desktop.cdx.json")
set(SINUS_DESKTOP_LIBRARY_IDENTITY
    "${CMAKE_CURRENT_BINARY_DIR}/sinus-dsp/generated/sinus_dsp_identity.cpp")
add_custom_command(
  OUTPUT "${SINUS_DESKTOP_SBOM}"
  COMMAND ${CMAKE_COMMAND} -DDIGEST_FILE=${SINUS_DESKTOP_DIGEST}
          -DLIBRARY_IDENTITY=${SINUS_DESKTOP_LIBRARY_IDENTITY}
          -DTEMPLATE=${CMAKE_CURRENT_SOURCE_DIR}/cmake/sbom.cdx.json.in
          "-DBUILD_TARGET=computer (${CMAKE_SYSTEM_PROCESSOR}, ${CMAKE_SYSTEM_NAME}, ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION})"
          -DCOMPILER_ID=${CMAKE_CXX_COMPILER_ID} -DCOMPILER_VERSION=${CMAKE_CXX_COMPILER_VERSION}
          -DQT_VERSION=${Qt6_VERSION} -DOUTPUT=${SINUS_DESKTOP_SBOM}
          -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/Sbom.cmake"
  DEPENDS "${SINUS_DESKTOP_DIGEST}" "${SINUS_DESKTOP_IDENTITY}" sinus_dsp
          "${CMAKE_CURRENT_SOURCE_DIR}/cmake/Sbom.cmake"
          "${CMAKE_CURRENT_SOURCE_DIR}/cmake/sbom.cdx.json.in"
  COMMENT "Generating the SBOM of the desktop application"
  VERBATIM)
add_custom_target(sinus_desktop_sbom DEPENDS "${SINUS_DESKTOP_SBOM}")
