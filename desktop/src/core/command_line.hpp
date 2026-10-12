#pragma once

// Command line of sinus-desktop (architecture-m3.md 15.2, 15.12).

#include <cstdint>
#include <string>
#include <vector>

namespace sinus::desktop::core {

enum class Command : std::uint8_t {
  kRun,           // start the application
  kPrintVersion,  // print the identity text and exit
};

// The command for the arguments (the first one is the program name): `--version` anywhere
// prints the identity; every other argument is left to Qt.
[[nodiscard]] Command command_from_arguments(const std::vector<std::string>& arguments);

}  // namespace sinus::desktop::core
