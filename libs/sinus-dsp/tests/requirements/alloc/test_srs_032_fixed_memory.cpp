// Requirement tests of SRS-032: fixed memory of the real-time library.
// This file is its own executable (sinus_dsp_requirement_alloc_tests): it replaces the global
// operator new and operator delete (every form) with counting versions and, on Linux without
// sanitizers, wraps malloc, calloc, realloc and free (-Wl,--wrap), so that every dynamic memory
// request of the process is counted while a counter is armed (architecture-m2.md 14.10).
// Each test states the part of the requirement it covers, its inputs and its expected result.

#include <gtest/gtest.h>

#include <atomic>
#include <cstddef>
#include <cstdlib>
#include <limits>
#include <new>
#include <vector>

#if defined(_WIN32)
#include <malloc.h>
#endif

#include "../support.hpp"
#include "sinus/dsp/chain.hpp"
#include "sinus/dsp/limits.hpp"

namespace {

std::atomic<bool> g_armed{false};
std::atomic<unsigned long> g_requests{0};

void count_request() {
  if (g_armed.load(std::memory_order_relaxed)) {
    g_requests.fetch_add(1, std::memory_order_relaxed);
  }
}

void* allocate(std::size_t n) {
  count_request();
  void* p = std::malloc(n == 0 ? 1 : n);
  if (p == nullptr) {
    throw std::bad_alloc();
  }
  return p;
}

void* allocate_aligned(std::size_t n, std::align_val_t align) {
  count_request();
  const std::size_t a = static_cast<std::size_t>(align);
  const std::size_t size = ((n == 0 ? 1 : n) + a - 1) / a * a;
#if defined(_WIN32)
  void* p = _aligned_malloc(size, a);
#else
  void* p = std::aligned_alloc(a, size);
#endif
  if (p == nullptr) {
    throw std::bad_alloc();
  }
  return p;
}

void release(void* p) noexcept {
  if (p != nullptr) {
    count_request();
  }
  std::free(p);
}

void release_aligned(void* p) noexcept {
  if (p != nullptr) {
    count_request();
  }
#if defined(_WIN32)
  _aligned_free(p);
#else
  std::free(p);
#endif
}

// Arms the counter for the lifetime of the object. Nothing in the armed region may use GoogleTest
// (it allocates), so the checks are made after the scope ends.
class Counting {
 public:
  Counting() {
    g_requests.store(0);
    g_armed.store(true);
  }
  ~Counting() { g_armed.store(false); }
  Counting(const Counting&) = delete;
  Counting& operator=(const Counting&) = delete;
  [[nodiscard]] static unsigned long requests() { return g_requests.load(); }
};

// Makes a pointer escape, so that the compiler cannot prove an allocation unused and elide it
// (allowed since C++14). Without it the self-check below could count nothing under optimisation.
inline void escape(const void* p) {
#if defined(__GNUC__) || defined(__clang__)
  asm volatile("" : : "g"(p) : "memory");
#else
  static const void* volatile sink;
  sink = p;
#endif
}

}  // namespace

void* operator new(std::size_t n) { return allocate(n); }
void* operator new[](std::size_t n) { return allocate(n); }
void* operator new(std::size_t n, const std::nothrow_t&) noexcept {
  try {
    return allocate(n);
  } catch (...) {
    return nullptr;
  }
}
void* operator new[](std::size_t n, const std::nothrow_t&) noexcept {
  try {
    return allocate(n);
  } catch (...) {
    return nullptr;
  }
}
void* operator new(std::size_t n, std::align_val_t a) { return allocate_aligned(n, a); }
void* operator new[](std::size_t n, std::align_val_t a) { return allocate_aligned(n, a); }
void* operator new(std::size_t n, std::align_val_t a, const std::nothrow_t&) noexcept {
  try {
    return allocate_aligned(n, a);
  } catch (...) {
    return nullptr;
  }
}
void* operator new[](std::size_t n, std::align_val_t a, const std::nothrow_t&) noexcept {
  try {
    return allocate_aligned(n, a);
  } catch (...) {
    return nullptr;
  }
}
void operator delete(void* p) noexcept { release(p); }
void operator delete[](void* p) noexcept { release(p); }
void operator delete(void* p, std::size_t) noexcept { release(p); }
void operator delete[](void* p, std::size_t) noexcept { release(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { release(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { release(p); }
void operator delete(void* p, std::align_val_t) noexcept { release_aligned(p); }
void operator delete[](void* p, std::align_val_t) noexcept { release_aligned(p); }
void operator delete(void* p, std::size_t, std::align_val_t) noexcept { release_aligned(p); }
void operator delete[](void* p, std::size_t, std::align_val_t) noexcept { release_aligned(p); }
void operator delete(void* p, std::align_val_t, const std::nothrow_t&) noexcept {
  release_aligned(p);
}
void operator delete[](void* p, std::align_val_t, const std::nothrow_t&) noexcept {
  release_aligned(p);
}

#if defined(SINUS_QA_WRAP_MALLOC)
extern "C" {
void* __real_malloc(std::size_t);
void* __real_calloc(std::size_t, std::size_t);
void* __real_realloc(void*, std::size_t);
void __real_free(void*);
void* __wrap_malloc(std::size_t n) {
  count_request();
  return __real_malloc(n);
}
void* __wrap_calloc(std::size_t n, std::size_t m) {
  count_request();
  return __real_calloc(n, m);
}
void* __wrap_realloc(void* p, std::size_t n) {
  count_request();
  return __real_realloc(p, n);
}
void __wrap_free(void* p) {
  if (p != nullptr) {
    count_request();
  }
  __real_free(p);
}
}
#endif

namespace {

using sinus::dsp::Chain;
using sinus::dsp::Config;
using sinus::dsp::SampleOutput;
using sinus::dsp::Status;

// The chain is in static storage: its size is that of the build, not a stack limit.
Chain g_chain;

// Case: the counter detects a request (a test of the test). Input: one `new` and one `delete`
// of an int, and one vector growth, inside the armed region; the pointers escape through an
// optimisation barrier so that no compiler can elide the requests.
// Expected: the count is at least 2, so a zero count elsewhere is meaningful.
// Verifies: SRS-032
TEST(Srs032FixedMemory, CounterSeesDynamicRequests) {
  unsigned long n = 0;
  {
    Counting counting;
    int* p = new int(3);
    escape(p);
    delete p;
    n = Counting::requests();
  }
  EXPECT_GE(n, 2UL);
  {
    Counting counting;
    std::vector<int> v;
    v.push_back(1);
    escape(v.data());
    n = Counting::requests();
  }
  EXPECT_GE(n, 1UL);
}

// Case: no dynamic memory request while configured, processing samples or reset.
// Input: configure at 125, 250, 360, 500 and 1000 Hz (both mains settings), 20 s of the interfered
// synthetic ECG, a limit sample, an invalid sample (NaN), the stopped samples, reset, 5 s more,
// a rejected configuration (NaN Hz, mains 49), and a final valid configuration, all counted.
// Expected: zero requests, for new, delete, and (on Linux) malloc, calloc, realloc and free.
// Verifies: SRS-032
TEST(Srs032FixedMemory, NoDynamicRequestInConfigureProcessAndReset) {
  for (const int fs : {125, 250, 360, 500, 1000}) {
    for (const int mains : {50, 60}) {
      // Prepared outside the counted region.
      const std::vector<float> ecg =
          sinus_qa::synthetic_ecg(fs, 75, static_cast<std::size_t>(20 * fs), mains);
      const std::vector<float> more =
          sinus_qa::synthetic_ecg(fs, 180, static_cast<std::size_t>(5 * fs), mains);
      SampleOutput out;
      Status last = Status::kOk;
      Status bad_status = Status::kOk;
      Status stopped_status = Status::kOk;
      Status limit_status = Status::kOk;
      bool all_ok = true;
      unsigned long n = 0;
      {
        const Counting counting;
        last = g_chain.configure(Config{static_cast<double>(fs), mains});
        for (const float x : ecg) {
          all_ok = all_ok && g_chain.process(x, out) == Status::kOk;
        }
        limit_status = g_chain.process(sinus::dsp::kMaxAbsSampleMv, out);
        bad_status = g_chain.process(std::numeric_limits<float>::quiet_NaN(), out);
        stopped_status = g_chain.process(0.1F, out);
        g_chain.reset();
        for (const float x : more) {
          all_ok = all_ok && g_chain.process(x, out) == Status::kOk;
        }
        const Status rejected =
            g_chain.configure(Config{std::numeric_limits<double>::quiet_NaN(), 49});
        all_ok = all_ok && rejected == Status::kInvalidSamplingFrequency;
        all_ok = all_ok && g_chain.configure(Config{static_cast<double>(fs), mains}) == Status::kOk;
        n = Counting::requests();
      }
      EXPECT_EQ(last, Status::kOk);
      EXPECT_EQ(limit_status, Status::kOk);
      EXPECT_EQ(bad_status, Status::kInvalidSample);
      EXPECT_EQ(stopped_status, Status::kStopped);
      EXPECT_TRUE(all_ok);
      EXPECT_EQ(n, 0UL) << "fs " << fs << " mains " << mains;
    }
  }
}

// Case: size of a complete processing chain, as given by the build.
// Input: sizeof(Chain) and the limit constant.
// Expected: the limit is 65 536 bytes (64 KiB) and sizeof(Chain) is at most the limit.
// Verifies: SRS-032
TEST(Srs032FixedMemory, ChainSizeIsAtMostTheLimit) {
  EXPECT_EQ(sinus::dsp::kChainMemoryLimitBytes, 65536UL);
  EXPECT_LE(sizeof(Chain), 65536UL);
  EXPECT_LE(sizeof(Chain), sinus::dsp::kChainMemoryLimitBytes);
}

}  // namespace
