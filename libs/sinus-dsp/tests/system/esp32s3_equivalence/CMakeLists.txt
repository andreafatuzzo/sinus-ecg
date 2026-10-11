# Test app of the equivalence check on the ESP32-S3 in the emulator (architecture-m2.md 14.13).
cmake_minimum_required(VERSION 3.22)
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../../esp-idf")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32s3_equivalence)
