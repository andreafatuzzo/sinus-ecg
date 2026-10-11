// Equivalence of the real-time library with the reference on the ESP32-S3 (architecture-m2.md
// 14.13). The golden vectors are in the partition "golden" as a binary pack. app_main checks the
// contraction setting, the SHA-256 of the pack, then every vector of the pack, and prints the
// results between SINUS-EQUIVALENCE-BEGIN and SINUS-EQUIVALENCE-END <pass|fail> on the console,
// which the emulator writes to a file. It then restarts, which ends the emulator (-no-reboot).
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>

#include "esp_partition.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/equivalence_report.hpp"
#include "sinus/dsp/verification/golden_pack.hpp"

#if __has_include("sinus_build_target.h")
#include "sinus_build_target.h"  // written by main/CMakeLists.txt: IDF version and compiler
#endif
#ifndef SINUS_DSP_BUILD_TARGET
#define SINUS_DSP_BUILD_TARGET "ESP32-S3 (emulator)"
#endif

namespace {

using sinus::dsp::Chain;
using sinus::dsp::SampleOutput;
using sinus::dsp::verification::ByteSource;

constexpr std::size_t kChunkBytes = 4096;
constexpr auto kGoldenSubtype = static_cast<esp_partition_subtype_t>(0x40);

// The Chain and its output in static storage (architecture-m2.md 14.13), not on the task stack.
Chain g_chain;
SampleOutput g_output;

// The bytes of the partition, read in chunks.
class PartitionSource final : public ByteSource {
 public:
  explicit PartitionSource(const esp_partition_t* partition) noexcept : partition_(partition) {}

  [[nodiscard]] bool read(std::uint8_t* out, std::size_t count) override {
    std::size_t done = 0;
    while (done < count) {
      if (used_ == filled_ && !refill()) {
        return false;
      }
      const std::size_t step = std::min(count - done, filled_ - used_);
      for (std::size_t i = 0; i < step; ++i) {
        out[done + i] = buffer_[used_ + i];
      }
      used_ += step;
      done += step;
    }
    return true;
  }

 private:
  bool refill() {
    const std::size_t left = partition_->size - next_;
    if (left == 0) {
      return false;
    }
    const std::size_t step = std::min(left, buffer_.size());
    if (esp_partition_read(partition_, next_, buffer_.data(), step) != ESP_OK) {
      return false;
    }
    next_ += step;
    filled_ = step;
    used_ = 0;
    return true;
  }

  const esp_partition_t* partition_;
  std::array<std::uint8_t, kChunkBytes> buffer_{};
  std::size_t next_ = 0;
  std::size_t filled_ = 0;
  std::size_t used_ = 0;
};

// Compilers may fuse a * b + c into one rounding; the library is built so that they do not
// (architecture-m2.md 14.3). With a = b = 1 + 2^-12 and c = -(1 + 2^-11), the product is
// 1 + 2^-11 + 2^-24: rounded alone it is 1 + 2^-11 (a tie, to even) and the sum is 0, fused the
// sum is 2^-24.
bool contraction_is_off() {
  volatile float a = 1.0F + 1.0F / 4096.0F;
  volatile float b = 1.0F + 1.0F / 4096.0F;
  volatile float c = -(1.0F + 1.0F / 2048.0F);
  const float result = a * b + c;
  return result == 0.0F;
}

void print_block(const std::string& text) {
  std::fwrite(text.data(), 1, text.size(), stdout);
  if (text.empty() || text.back() != '\n') {
    std::fputc('\n', stdout);
  }
}

// The marker lines start a line of their own, whatever the console printed before.
[[noreturn]] void finish(bool passed, const std::string& body) {
  std::printf("\nSINUS-EQUIVALENCE-BEGIN\n");
  print_block(body);
  std::printf("SINUS-EQUIVALENCE-END %s\n", passed ? "pass" : "fail");
  std::fflush(stdout);
  vTaskDelay(pdMS_TO_TICKS(1000));  // let the console drain
  esp_restart();
}

}  // namespace

extern "C" void app_main() {
  if (!contraction_is_off()) {
    finish(false, "self-check failed: the compiler fuses a * b + c (contraction is on)");
  }
  const esp_partition_t* partition =
      esp_partition_find_first(ESP_PARTITION_TYPE_DATA, kGoldenSubtype, "golden");
  if (partition == nullptr) {
    finish(false, "the partition golden was not found");
  }
  {
    PartitionSource source(partition);
    const auto sealed = sinus::dsp::verification::verify_pack(source);
    if (!sealed.ok) {
      finish(false, "the golden pack is damaged: " + sealed.error);
    }
  }
  PartitionSource source(partition);
  const auto checked = sinus::dsp::verification::check_pack(source, g_chain, g_output);
  if (!checked.outcome.ok) {
    finish(false, "the golden pack cannot be read: " + checked.outcome.error);
  }
  const std::string report = sinus::dsp::verification::render_equivalence_report(
      checked.set, sinus::dsp::verification::make_report_info(SINUS_DSP_BUILD_TARGET));
  finish(sinus::dsp::verification::set_passed(checked.set), report);
}
