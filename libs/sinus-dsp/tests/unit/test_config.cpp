#include <gtest/gtest.h>

#include <cmath>
#include <limits>

#include "sinus/dsp/config.hpp"

namespace {

using sinus::dsp::Config;
using sinus::dsp::Status;
using sinus::dsp::validate;

constexpr double kNan = std::numeric_limits<double>::quiet_NaN();
constexpr double kInf = std::numeric_limits<double>::infinity();

TEST(Config, AcceptsTheBoundsWithEachMainsSetting) {
  for (const double fs : {125.0, 250.0, 360.0, 1000.0}) {
    for (const int mains : {50, 60}) {
      EXPECT_EQ(validate(Config{fs, mains}), Status::kOk) << fs << " " << mains;
    }
  }
}

TEST(Config, RejectsSamplingFrequenciesOutsideTheRange) {
  for (const double fs : {124.9, 1000.1, std::nextafter(125.0, 0.0), std::nextafter(1000.0, 2000.0),
                          0.0, -360.0, kNan, kInf, -kInf}) {
    EXPECT_EQ(validate(Config{fs, 50}), Status::kInvalidSamplingFrequency) << fs;
  }
}

TEST(Config, RejectsOtherMainsSettings) {
  for (const int mains : {0, 49, 51, 59, 61, 100, -50}) {
    EXPECT_EQ(validate(Config{360.0, mains}), Status::kInvalidMainsFrequency) << mains;
  }
}

TEST(Config, ReportsTheSamplingFrequencyFirst) {
  EXPECT_EQ(validate(Config{kNan, 49}), Status::kInvalidSamplingFrequency);
  EXPECT_EQ(validate(Config{}), Status::kInvalidSamplingFrequency);
}

}  // namespace
