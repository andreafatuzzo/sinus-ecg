#pragma once

// The Qt version loaded at run time (architecture-m3.md 15.12): the LGPL lets the user replace
// the Qt libraries, so it may differ from the version the application was built with.

#include <string>

namespace sinus::desktop::io {

[[nodiscard]] std::string qt_runtime_version();

}  // namespace sinus::desktop::io
