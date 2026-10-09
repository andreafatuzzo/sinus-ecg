cmake_minimum_required(VERSION 3.25)

# VERSION: one line, the version of the milestone register (architecture-m2.md 14.15).
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/VERSION" SINUS_DSP_VERSION_TEXT LIMIT_COUNT 1)
string(STRIP "${SINUS_DSP_VERSION_TEXT}" SINUS_DSP_VERSION_TEXT)
string(REGEX MATCH "^[0-9]+(\\.[0-9]+)*" SINUS_DSP_VERSION_NUMERIC "${SINUS_DSP_VERSION_TEXT}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
             "${CMAKE_CURRENT_SOURCE_DIR}/VERSION")

project(sinus_dsp VERSION ${SINUS_DSP_VERSION_NUMERIC} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
  set(_top_level ON)
else()
  set(_top_level OFF)
endif()
option(SINUS_DSP_BUILD_TESTS "Build the tests" ${_top_level})
option(SINUS_DSP_TIDY "Run the pinned clang-tidy on the library" OFF)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(Flags)
set(SINUS_DSP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
include(SinusDspSources)

# Identity (SourceDigest.cmake), regenerated when a source or VERSION changes.
get_filename_component(SINUS_DSP_LIBS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
get_filename_component(SINUS_DSP_DIR_NAME "${CMAKE_CURRENT_SOURCE_DIR}" NAME)
set(SINUS_DSP_IDENTITY "${CMAKE_CURRENT_BINARY_DIR}/generated/sinus_dsp_identity.cpp")
add_custom_command(
  OUTPUT "${SINUS_DSP_IDENTITY}"
  COMMAND ${CMAKE_COMMAND} -DLIBS_ROOT=${SINUS_DSP_LIBS_ROOT} -DITEM=${SINUS_DSP_DIR_NAME}
          -DVERSION_FILE=${CMAKE_CURRENT_SOURCE_DIR}/VERSION -DOUTPUT=${SINUS_DSP_IDENTITY}
          -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/SourceDigest.cmake"
  DEPENDS ${SINUS_DSP_SOURCES} ${SINUS_DSP_HEADERS} "${CMAKE_CURRENT_SOURCE_DIR}/VERSION"
          "${CMAKE_CURRENT_SOURCE_DIR}/cmake/SourceDigest.cmake"
  COMMENT "Generating the identity of the library"
  VERBATIM)

# The library: the only code linked into the firmware and the desktop application.
add_library(sinus_dsp STATIC ${SINUS_DSP_SOURCES} "${SINUS_DSP_IDENTITY}")
add_library(sinus::dsp ALIAS sinus_dsp)
target_include_directories(sinus_dsp PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
sinus_dsp_apply_flags(sinus_dsp)
if(SINUS_DSP_TIDY)
  # The tools project of tools/ puts the pinned clang-tidy first on PATH (uv run).
  find_program(SINUS_DSP_CLANG_TIDY NAMES clang-tidy REQUIRED)
  # -Wno-unknown-warning-option: the GCC-only warnings of Flags.cmake are unknown to clang-tidy.
  set(_tidy_command "${SINUS_DSP_CLANG_TIDY};--config-file=${CMAKE_CURRENT_SOURCE_DIR}/.clang-tidy"
      "--extra-arg=-Wno-unknown-warning-option")
  if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    # The pinned clang-tidy is not the compiler's own tool: on Windows it assumes the MSVC target
    # and finds neither the standard library nor the headers of the MinGW compiler. It is given
    # the target and the compiler's include directories (not its resource directory, which
    # belongs to the compiler's version).
    execute_process(COMMAND ${CMAKE_CXX_COMPILER} -dumpmachine OUTPUT_VARIABLE _tidy_target
                    OUTPUT_STRIP_TRAILING_WHITESPACE)
    if(_tidy_target)
      list(APPEND _tidy_command "--extra-arg=--target=${_tidy_target}")
    endif()
    execute_process(COMMAND ${CMAKE_CXX_COMPILER} -std=c++17 -E -v -x c++ -
                    INPUT_FILE "${CMAKE_CURRENT_SOURCE_DIR}/VERSION"
                    OUTPUT_QUIET ERROR_VARIABLE _tidy_search)
    string(REPLACE "\r" "" _tidy_search "${_tidy_search}")
    string(REGEX REPLACE "^.*#include <[.][.][.]> search starts here:\n" "" _tidy_search
           "${_tidy_search}")
    string(REGEX REPLACE "\nEnd of search list[.].*$" "" _tidy_search "${_tidy_search}")
    string(REPLACE "\n" ";" _tidy_search "${_tidy_search}")
    foreach(_dir IN LISTS _tidy_search)
      string(STRIP "${_dir}" _dir)
      if(_dir AND NOT _dir MATCHES "/lib/clang/")
        list(APPEND _tidy_command "--extra-arg=-isystem${_dir}")
      endif()
    endforeach()
  endif()
  set_target_properties(sinus_dsp PROPERTIES CXX_CLANG_TIDY "${_tidy_command}")
endif()

if(SINUS_DSP_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()
