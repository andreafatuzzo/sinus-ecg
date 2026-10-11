# The harness (architecture-m2.md 14.14): a C interface to the library, built as the shared
# library sinus_dsp_harness for the Python evaluation (ctypes). Computer only; not part of the
# library, so not in the digest and not linked into the firmware.
set_target_properties(sinus_dsp PROPERTIES POSITION_INDEPENDENT_CODE ON)

# The same code as a static library, so that the unit tests of the C interface link it directly.
add_library(sinus_dsp_harness_static STATIC src/sinus_dsp_harness.cpp)
target_include_directories(sinus_dsp_harness_static PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(sinus_dsp_harness_static PUBLIC sinus::dsp)
set_target_properties(sinus_dsp_harness_static PROPERTIES POSITION_INDEPENDENT_CODE ON)
sinus_dsp_apply_flags(sinus_dsp_harness_static)

# The shared library. Nothing but the two functions of the header is exported.
add_library(sinus_dsp_harness SHARED src/sinus_dsp_harness.cpp)
target_include_directories(sinus_dsp_harness PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(sinus_dsp_harness PRIVATE sinus::dsp)
set_target_properties(sinus_dsp_harness PROPERTIES CXX_VISIBILITY_PRESET hidden
                      VISIBILITY_INLINES_HIDDEN ON)
sinus_dsp_apply_flags(sinus_dsp_harness)
if(MINGW)
  # A DLL that imports only Windows system libraries (no libc++.dll, no libunwind.dll), so that
  # loading it never shows a dialog; check with llvm-readobj --coff-imports.
  target_link_options(sinus_dsp_harness PRIVATE -static)
  set_target_properties(sinus_dsp_harness PROPERTIES PREFIX "")
endif()

if(SINUS_DSP_TIDY)
  set_target_properties(sinus_dsp_harness_static sinus_dsp_harness
                        PROPERTIES CXX_CLANG_TIDY "${_tidy_command}")
endif()
