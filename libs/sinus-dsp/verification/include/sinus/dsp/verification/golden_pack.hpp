#pragma once

// SRS-036: the binary pack of the golden vectors that the ESP32-S3 test app reads from a flash
// partition (architecture-m2.md 14.13), and the streaming equivalence check on it. The text of the
// vectors does not fit the largest flash image of the emulator, so the host converts it, with the
// verified reader of golden_reader.hpp, and the target compares with exactly the values that the
// computer compares with. All numbers are little-endian.
//
//   header   8 bytes "SINUSGVP", uint32 pack version (1), uint32 number of files,
//            uint64 payload length, 32 bytes SHA-256 of the payload
//   payload  the files, in the order given to build_pack; per file
//            4 bytes "GVF2"; input_id, input_source, input_parameters, software_version,
//            source_sha256 (each uint16 length + UTF-8 bytes); float64 sampling frequency;
//            uint32 mains; uint32 counts of samples, coefficient rows, beats, heart rates,
//            windows; the coefficient rows (uint8 stage, uint8 section, 5 x float64); per sample
//            float32 input, float64 baseline output, float64 mains output; per beat uint64 index,
//            uint8 mark, uint64 report sample; per heart rate uint64 sample, int64 beat index
//            (-1 if none), uint8 status, float64 rate (NaN if none); per window uint64 first,
//            last and report samples, float64 index, uint8 usable

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/verification/equivalence.hpp"
#include "sinus/dsp/verification/golden_reader.hpp"
#include "sinus/dsp/verification/sha256.hpp"

namespace sinus::dsp::verification {

inline constexpr std::array<char, 8> kPackMagic{'S', 'I', 'N', 'U', 'S', 'G', 'V', 'P'};
inline constexpr std::uint32_t kPackVersion = 1;
inline constexpr std::size_t kPackHeaderBytes = 8 + 4 + 4 + 8 + kSha256Bytes;

// Where the bytes of a pack come from: a flash partition on the target, memory on the computer.
class ByteSource {
 public:
  ByteSource() = default;
  ByteSource(const ByteSource&) = delete;
  ByteSource& operator=(const ByteSource&) = delete;
  ByteSource(ByteSource&&) = delete;
  ByteSource& operator=(ByteSource&&) = delete;
  virtual ~ByteSource() = default;

  // The next `count` bytes into `out`; false if fewer remain or they cannot be read.
  [[nodiscard]] virtual bool read(std::uint8_t* out, std::size_t count) = 0;
};

class MemorySource final : public ByteSource {
 public:
  explicit MemorySource(std::string_view bytes) noexcept : bytes_(bytes) {}
  [[nodiscard]] bool read(std::uint8_t* out, std::size_t count) override;

 private:
  std::string_view bytes_;
  std::size_t at_ = 0;
};

struct PackOutcome {
  bool ok = false;
  std::string error;  // what is wrong, when !ok
};

// The pack of the vectors, in the given order. Each vector must have the stages baseline and
// mains, one output per input sample and strings of at most 65535 bytes.
[[nodiscard]] PackOutcome build_pack(const std::vector<GoldenVector>& vectors, std::string& bytes);

// Reads the header and checks the magic, the version and the SHA-256 of the whole payload.
[[nodiscard]] PackOutcome verify_pack(ByteSource& source);

struct PackCheck {
  PackOutcome outcome;  // !ok: the pack is truncated or malformed, `set` is not meaningful
  SetResult set;        // the expected inputs in order (golden_set.hpp), then the unexpected ones
};

// Runs the equivalence check on every file of a pack, a sample at a time: the samples are compared
// as they are read, the events after them, as for a text file. `chain` and `out` are the caller's
// storage (static on the target); the chain is configured anew for each file. A file the pack
// lacks is reported missing, one it holds that is not expected, unexpected (golden_set.hpp).
[[nodiscard]] PackCheck check_pack(ByteSource& source, Chain& chain, SampleOutput& out);

}  // namespace sinus::dsp::verification
