# SourceDigest.cmake on a fixture tree. EXPECTED was computed independently with
#   find sinus-dsp/include sinus-dsp/src -type f -not -path '*/.*' -print0 | LC_ALL=C sort -z \
#     | xargs -0 sha256sum --text | sha256sum --text
# on the tree below, with the CR LF file in its LF form. Z.cpp sorts before a.cpp (code-point order).
file(REMOVE_RECURSE "${WORK}")
set(root "${WORK}/libs")
file(WRITE "${root}/sinus-dsp/include/sinus/dsp/a.hpp" "#pragma once\n")
file(WRITE "${root}/sinus-dsp/src/a.cpp" "int b;\r\nint c;\r\n")
file(WRITE "${root}/sinus-dsp/src/Z.cpp" "int B;\n")
file(WRITE "${root}/sinus-dsp/src/.hidden.cpp" "int hidden;\n")
file(WRITE "${root}/sinus-dsp/tests/t.cpp" "int outside;\n")
file(WRITE "${WORK}/VERSION" "9.8.7.dev1\n")
set(EXPECTED "9c56d42fc3dd408e94a9e945570974669f76fad6a5bff138062565b4e21b7eaa")

function(run_script)
  execute_process(COMMAND ${CMAKE_COMMAND} -DLIBS_ROOT=${root} -DITEM=sinus-dsp
                          -DVERSION_FILE=${WORK}/VERSION -DOUTPUT=${WORK}/identity.cpp
                          -P ${SCRIPT} RESULT_VARIABLE rc)
  if(NOT rc EQUAL 0)
    message(FATAL_ERROR "SourceDigest.cmake failed")
  endif()
  file(READ "${WORK}/identity.cpp" text)
  set(identity_text "${text}" PARENT_SCOPE)
endfunction()

run_script()
if(NOT identity_text MATCHES "\"9.8.7.dev1\", \"${EXPECTED}\"")
  message(FATAL_ERROR "unexpected identity:\n${identity_text}")
endif()

# Unchanged inputs: the output file is not rewritten.
file(TIMESTAMP "${WORK}/identity.cpp" before "%s")
execute_process(COMMAND ${CMAKE_COMMAND} -E sleep 1.1)
run_script()
file(TIMESTAMP "${WORK}/identity.cpp" after "%s")
if(NOT before STREQUAL after)
  message(FATAL_ERROR "identity rewritten without a change")
endif()

# A change outside include and src does not change the digest; a change inside does.
file(WRITE "${root}/sinus-dsp/tests/t.cpp" "int outside2;\n")
run_script()
if(NOT identity_text MATCHES "${EXPECTED}")
  message(FATAL_ERROR "digest depends on a file outside include and src")
endif()
file(APPEND "${root}/sinus-dsp/src/Z.cpp" "int more;\n")
run_script()
if(identity_text MATCHES "${EXPECTED}")
  message(FATAL_ERROR "digest unchanged after a change in src")
endif()
