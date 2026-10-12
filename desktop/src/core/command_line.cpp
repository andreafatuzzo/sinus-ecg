#include "core/command_line.hpp"

#include <algorithm>
#include <iterator>
#include <string>
#include <vector>

namespace sinus::desktop::core {

Command command_from_arguments(const std::vector<std::string>& arguments) {
  if (arguments.empty()) {
    return Command::kRun;
  }
  const bool version = std::any_of(std::next(arguments.begin()), arguments.end(),
                                   [](const std::string& a) { return a == "--version"; });
  return version ? Command::kPrintVersion : Command::kRun;
}

}  // namespace sinus::desktop::core
