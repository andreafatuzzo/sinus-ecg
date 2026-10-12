# SBOM of the desktop application (architecture-m3.md 15.12; OP-075), run in script mode:
#   cmake -DDIGEST_FILE=<desktop_digest.txt> -DLIBRARY_IDENTITY=<sinus_dsp_identity.cpp>
#         -DTEMPLATE=<sbom.cdx.json.in> -DBUILD_TARGET=<text> -DCOMPILER_ID=<id>
#         -DCOMPILER_VERSION=<version> -DQT_VERSION=<version> -DOUTPUT=<sbom-desktop.cdx.json>
#         -P Sbom.cmake
# CycloneDX 1.6 JSON, no timestamp and no serial number (deterministic), like the library's
# (architecture-m2.md 14.16). The digests are those the application and the library state.
foreach(required DIGEST_FILE LIBRARY_IDENTITY TEMPLATE BUILD_TARGET COMPILER_ID COMPILER_VERSION
                 QT_VERSION OUTPUT)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "Sbom.cmake: ${required} is not defined")
  endif()
endforeach()

file(STRINGS "${DIGEST_FILE}" digest_line LIMIT_COUNT 1)
if(NOT digest_line MATCHES "^([^ ]+) ([0-9a-f]+)$")
  message(FATAL_ERROR "Sbom.cmake: no version and digest in ${DIGEST_FILE}")
endif()
set(SBOM_VERSION "${CMAKE_MATCH_1}")
set(SBOM_SOURCE_SHA256 "${CMAKE_MATCH_2}")

file(READ "${LIBRARY_IDENTITY}" library_text)
if(NOT library_text MATCHES "LibraryIdentity{\"([^\"]*)\", \"([0-9a-f]+)\"}")
  message(FATAL_ERROR "Sbom.cmake: no library identity in ${LIBRARY_IDENTITY}")
endif()
set(SBOM_LIBRARY_VERSION "${CMAKE_MATCH_1}")
set(SBOM_LIBRARY_SHA256 "${CMAKE_MATCH_2}")

set(SBOM_BUILD_TARGET "${BUILD_TARGET}")
set(SBOM_COMPILER_VERSION "${COMPILER_VERSION}")
set(SBOM_QT_VERSION "${QT_VERSION}")
if(COMPILER_ID STREQUAL "GNU")
  set(SBOM_RUNTIME_NAME "GNU ${COMPILER_VERSION}: libstdc++, libgcc, glibc")
else()
  set(SBOM_RUNTIME_NAME "${COMPILER_ID} ${COMPILER_VERSION}: C++ standard library and C library of the toolchain")
endif()

configure_file("${TEMPLATE}" "${OUTPUT}" @ONLY NEWLINE_STYLE UNIX)
