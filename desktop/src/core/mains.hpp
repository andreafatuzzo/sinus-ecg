#pragma once

// Mains frequency: of a recording (architecture-m3.md 17.6), of a reference database (17.7) and
// of the processing (17.12). No other value exists.

#include <cstdint>

namespace sinus::desktop::core {

enum class MainsFrequency : std::uint8_t { k50Hz = 50, k60Hz = 60 };

}  // namespace sinus::desktop::core
