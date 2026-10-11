// Private header: a stream counter as an array index.
#pragma once

#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace sinus::dsp {

// A counter reduced below the size of an array, as std::size_t. std::size_t is std::uint64_t on a
// 64-bit Linux or Windows target (a cast there is "useless" for GCC) and 32 bits wide on the
// ESP32-S3 (the cast is needed and the value fits, since it is below the array size).
inline std::size_t array_index(std::uint64_t reduced) noexcept {
  if constexpr (std::is_same_v<std::size_t, std::uint64_t>) {
    return reduced;
  } else {
    return static_cast<std::size_t>(reduced);
  }
}

}  // namespace sinus::dsp
