// architecture-m2.md 14.3: no contraction into a fused multiply-add (OP-057).
#include <gtest/gtest.h>

TEST(Arithmetic, MultiplyAddIsNotContracted) {
  // a * b = 1 + 2^-12 + 2^-26 exactly; in binary32 the product rounds to 1 + 2^-12. Fused, the
  // sum with c keeps 2^-26; unfused, it is exactly 0.
  volatile float a = 1.0F + 0x1.0p-13F;
  volatile float b = 1.0F + 0x1.0p-13F;
  volatile float c = -(1.0F + 0x1.0p-12F);
  const float result = a * b + c;
  EXPECT_EQ(result, 0.0F);
}
