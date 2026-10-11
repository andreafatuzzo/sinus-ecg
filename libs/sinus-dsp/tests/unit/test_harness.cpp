#include <gtest/gtest.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/config.hpp"
#include "sinus/dsp/status.hpp"
#include "sinus/dsp/version.hpp"
#include "sinus_dsp_harness.h"
#include "synthetic_beats.hpp"

namespace {

using sinus::dsp::Status;

constexpr double kFs = 360.0;

std::int64_t error_code(Status status) { return -1 - static_cast<std::int64_t>(status); }

std::vector<float> test_signal() {
  return sinus_test::synthetic_beats(kFs, 40.0, sinus_test::regular_beats(0.4, 0.85, 39.5));
}

struct Reference {
  std::vector<std::uint64_t> indices, reported_at;
  std::vector<std::uint8_t> startup;
};

// The detections of a Chain driven directly, the same way the harness drives it.
Reference run_chain(const std::vector<float>& signal) {
  sinus::dsp::Chain chain;
  EXPECT_EQ(chain.configure(sinus::dsp::Config{kFs, 60}), Status::kOk);
  Reference ref;
  sinus::dsp::SampleOutput out;
  for (const float sample : signal) {
    EXPECT_EQ(chain.process(sample, out), Status::kOk);
    for (std::size_t k = 0; k < out.detection_count; ++k) {
      ref.indices.push_back(out.detections.at(k).index);
      ref.reported_at.push_back(out.detections.at(k).reported_at);
      ref.startup.push_back(out.detections.at(k).mark == sinus::dsp::Mark::kStartUp ? 1U : 0U);
    }
  }
  return ref;
}

}  // namespace

TEST(Harness, ReturnsTheDetectionsOfTheChain) {
  const std::vector<float> signal = test_signal();
  const Reference ref = run_chain(signal);
  ASSERT_GT(ref.indices.size(), 20U);
  const std::uint64_t capacity = ref.indices.size() + 5;
  std::vector<std::uint64_t> indices(capacity, 7), reported_at(capacity, 7);
  std::vector<std::uint8_t> startup(capacity, 7);
  const std::int64_t total =
      sinus_dsp_harness_detect(kFs, 60, signal.data(), signal.size(), indices.data(),
                               startup.data(), reported_at.data(), capacity);
  ASSERT_EQ(total, static_cast<std::int64_t>(ref.indices.size()));
  for (std::size_t i = 0; i < ref.indices.size(); ++i) {
    EXPECT_EQ(indices.at(i), ref.indices.at(i)) << i;
    EXPECT_EQ(reported_at.at(i), ref.reported_at.at(i)) << i;
    EXPECT_EQ(startup.at(i), ref.startup.at(i)) << i;
  }
  // Both marks occur: the first beats are start-up detections, the later ones reliable.
  EXPECT_EQ(startup.front(), 1U);
  EXPECT_EQ(startup.at(ref.indices.size() - 1), 0U);
  // Nothing is written past the detections.
  EXPECT_EQ(indices.at(ref.indices.size()), 7U);
  EXPECT_EQ(startup.at(ref.indices.size()), 7U);
}

TEST(Harness, SmallCapacityWritesThatManyAndReturnsTheTotal) {
  const std::vector<float> signal = test_signal();
  const Reference ref = run_chain(signal);
  constexpr std::uint64_t kCapacity = 3;
  std::vector<std::uint64_t> indices(kCapacity + 1, 7), reported_at(kCapacity + 1, 7);
  std::vector<std::uint8_t> startup(kCapacity + 1, 7);
  const std::int64_t total =
      sinus_dsp_harness_detect(kFs, 60, signal.data(), signal.size(), indices.data(),
                               startup.data(), reported_at.data(), kCapacity);
  EXPECT_EQ(total, static_cast<std::int64_t>(ref.indices.size()));
  for (std::size_t i = 0; i < kCapacity; ++i) {
    EXPECT_EQ(indices.at(i), ref.indices.at(i));
  }
  EXPECT_EQ(indices.at(kCapacity), 7U);
  EXPECT_EQ(reported_at.at(kCapacity), 7U);
  EXPECT_EQ(startup.at(kCapacity), 7U);
}

TEST(Harness, ZeroCapacityCountsWithNullArrays) {
  const std::vector<float> signal = test_signal();
  const Reference ref = run_chain(signal);
  EXPECT_EQ(
      sinus_dsp_harness_detect(kFs, 60, signal.data(), signal.size(), nullptr, nullptr, nullptr, 0),
      static_cast<std::int64_t>(ref.indices.size()));
}

TEST(Harness, EmptySignalHasNoDetection) {
  EXPECT_EQ(sinus_dsp_harness_detect(kFs, 50, nullptr, 0, nullptr, nullptr, nullptr, 0), 0);
}

TEST(Harness, EveryCallStartsANewStream) {
  const std::vector<float> signal = test_signal();
  const std::int64_t first =
      sinus_dsp_harness_detect(kFs, 60, signal.data(), signal.size(), nullptr, nullptr, nullptr, 0);
  const std::int64_t second =
      sinus_dsp_harness_detect(kFs, 60, signal.data(), signal.size(), nullptr, nullptr, nullptr, 0);
  EXPECT_EQ(first, second);
}

TEST(Harness, ConfigurationErrorsAreReportedAsStatusCodes) {
  const std::vector<float> signal(100, 0.0F);
  EXPECT_EQ(sinus_dsp_harness_detect(100.0, 60, signal.data(), signal.size(), nullptr, nullptr,
                                     nullptr, 0),
            error_code(Status::kInvalidSamplingFrequency));
  EXPECT_EQ(sinus_dsp_harness_detect(std::numeric_limits<double>::quiet_NaN(), 60, signal.data(),
                                     signal.size(), nullptr, nullptr, nullptr, 0),
            error_code(Status::kInvalidSamplingFrequency));
  EXPECT_EQ(
      sinus_dsp_harness_detect(kFs, 55, signal.data(), signal.size(), nullptr, nullptr, nullptr, 0),
      error_code(Status::kInvalidMainsFrequency));
}

TEST(Harness, InvalidSampleIsReportedAsStatusCode) {
  std::vector<float> signal = test_signal();
  signal.at(500) = std::numeric_limits<float>::infinity();
  EXPECT_EQ(
      sinus_dsp_harness_detect(kFs, 60, signal.data(), signal.size(), nullptr, nullptr, nullptr, 0),
      error_code(Status::kInvalidSample));
  signal.at(500) = 1001.0F;
  EXPECT_EQ(
      sinus_dsp_harness_detect(kFs, 60, signal.data(), signal.size(), nullptr, nullptr, nullptr, 0),
      error_code(Status::kInvalidSample));
}

TEST(Harness, NullArraysAreAnInvalidArgument) {
  const std::vector<float> signal(100, 0.0F);
  std::vector<std::uint64_t> indices(4);
  std::vector<std::uint8_t> startup(4);
  EXPECT_EQ(sinus_dsp_harness_detect(kFs, 60, nullptr, 100, nullptr, nullptr, nullptr, 0),
            error_code(Status::kInvalidArgument));
  EXPECT_EQ(sinus_dsp_harness_detect(kFs, 60, signal.data(), signal.size(), indices.data(),
                                     startup.data(), nullptr, 4),
            error_code(Status::kInvalidArgument));
}

TEST(Harness, IdentityIsTheVersionAndTheDigestOfTheLibrary) {
  const sinus::dsp::LibraryIdentity id = sinus::dsp::library_identity();
  const std::string expected = std::string(id.version) + ";" + id.source_sha256;
  EXPECT_EQ(std::string(sinus_dsp_harness_identity()), expected);
  EXPECT_EQ(sinus_dsp_harness_identity(), sinus_dsp_harness_identity());
}
