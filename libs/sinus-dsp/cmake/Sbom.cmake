# SBOM of the library (architecture-m2.md 14.16; OP-046), run in script mode:
#   cmake -DVERSION_FILE=<VERSION> -DIDENTITY=<sinus_dsp_identity.cpp> -DTEMPLATE=<sbom.cdx.json.in>
#         -DBUILD_TARGET=<text> -DCOMPILER_ID=<id> -DCOMPILER_VERSION=<version>
#         -DOUTPUT=<sbom-libs.cdx.json> -P Sbom.cmake
# CycloneDX 1.6 JSON, no timestamp and no serial number (deterministic). The source digest is the
# one of the generated identity source, so that the SBOM and the library state the same value.
foreach(required VERSION_FILE IDENTITY TEMPLATE BUILD_TARGET COMPILER_ID COMPILER_VERSION OUTPUT)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "Sbom.cmake: ${required} is not defined")
  endif()
endforeach()

file(STRINGS "${VERSION_FILE}" version_line LIMIT_COUNT 1)
string(STRIP "${version_line}" SBOM_VERSION)

file(READ "${IDENTITY}" identity_text)
if(NOT identity_text MATCHES "LibraryIdentity{\"[^\"]*\", \"([0-9a-f]+)\"}")
  message(FATAL_ERROR "Sbom.cmake: no source digest in ${IDENTITY}")
endif()
set(SBOM_SOURCE_SHA256 "${CMAKE_MATCH_1}")

set(SBOM_BUILD_TARGET "${BUILD_TARGET}")
set(SBOM_COMPILER_VERSION "${COMPILER_VERSION}")
if(COMPILER_ID STREQUAL "GNU")
  set(SBOM_RUNTIME_NAME "GNU ${COMPILER_VERSION}: libstdc++, libgcc, glibc")
else()
  set(SBOM_RUNTIME_NAME "${COMPILER_ID} ${COMPILER_VERSION}: C++ standard library and C library of the toolchain")
endif()

configure_file("${TEMPLATE}" "${OUTPUT}" @ONLY NEWLINE_STYLE UNIX)
