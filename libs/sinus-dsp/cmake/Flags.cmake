# Compiler options (architecture-m2.md 14.2, 14.3; OP-057).
foreach(forbidden -ffast-math -Ofast -funsafe-math-optimizations -ffinite-math-only
                  -fassociative-math)
  string(FIND "${CMAKE_CXX_FLAGS} ${CMAKE_CXX_FLAGS_DEBUG} ${CMAKE_CXX_FLAGS_RELEASE}"
         "${forbidden}" at)
  if(NOT at EQUAL -1)
    message(FATAL_ERROR "CMAKE_CXX_FLAGS contains ${forbidden}: not allowed (OP-057)")
  endif()
endforeach()

# MinGW: link the C++ runtime and unwinder statically, so that the executables run without the
# toolchain's bin folder on PATH (otherwise Windows shows a modal "libc++.dll not found" dialog).
if(MINGW)
  add_link_options(-static)
endif()

# Library, verification code and harness. They build with -fno-rtti (ADR 0007) while the tests use
# RTTI, so the asan-ubsan preset (CMakePresets.json) passes -fno-sanitize=vptr: GCC's vptr check
# needs typeinfo of polymorphic classes (ByteSource) that no-RTTI objects do not emit. All other
# UBSan checks and ASan stay on for every target.
function(sinus_dsp_apply_flags target)
  target_compile_options(${target} PRIVATE
    -fno-exceptions -fno-rtti -ffp-contract=off
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wdouble-promotion
    -Wfloat-conversion -Wshadow -Wcast-align -Wold-style-cast -Wnon-virtual-dtor
    -Woverloaded-virtual -Wnull-dereference -Wimplicit-fallthrough -Wundef -Werror)
  if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(${target} PRIVATE -Wduplicated-cond -Wlogical-op -Wuseless-cast)
  endif()
endfunction()

# Tests.
function(sinus_dsp_apply_test_flags target)
  target_compile_options(${target} PRIVATE -ffp-contract=off -Wall -Wextra -Werror)
endfunction()
