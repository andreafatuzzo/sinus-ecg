#include "io/qt_versions.hpp"

#include <qtversion.h>
#include <string>

namespace sinus::desktop::io {

std::string qt_runtime_version() { return std::string{qVersion()}; }

}  // namespace sinus::desktop::io
