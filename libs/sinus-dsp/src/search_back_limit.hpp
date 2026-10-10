#pragma once

// The search-back interval limit in integers (architecture-m2.md 14.3, step 9; architecture-m1.md
// 8.7.3). Integer arithmetic only, so it may be inline.

#include <cstdint>

namespace sinus::dsp {

// floor(1.66 * total / count + 0.5) of the reference, for count from 1 to 8 stored intervals with
// the given total (in samples): (166 * total + 50 * count) / (100 * count). Equal to the binary64
// expression for every total up to 200 000 (the totals stay below 8 * G <= 64 000).
[[nodiscard]] inline std::uint64_t search_back_limit(std::uint64_t total,
                                                     std::uint64_t count) noexcept {
  return ((166U * total) + (50U * count)) / (100U * count);
}

}  // namespace sinus::dsp
