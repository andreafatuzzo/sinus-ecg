# Compiler options (architecture-m2.md 14.2, 14.3; OP-057).
foreach(forbidden -ffast-math -Ofast -funsafe-math-optimizations -ffinite-math-only
                  -fassociative-math)
  string(FIND "${CMAKE_CXX_FLAGS} ${CMAKE_CXX_FLAGS_DEBUG} ${CMAKE_CXX_FLAGS_RELEASE}"
         "${forbidden}" at)
  if(NOT at EQUAL -1)
    message(FATAL_ERROR "CMAKE_CXX_FLAGS contains ${forbidden}: not allowed (OP-057)")
  endif()
endforeach()

# Library, verification code and harness.
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
