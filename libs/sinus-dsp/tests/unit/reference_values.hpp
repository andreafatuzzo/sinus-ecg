#pragma once

// Values of the Python reference (dsp/sinus_dsp/filters.py), written as exact hexadecimal
// floating-point literals. Developer's unit tests: they check the C++ against the reference on
// a few cases; the equivalence on the golden vectors is SRS-034.

#include <array>

namespace sinus::dsp::reference {

struct DesignCase {
  double fs_hz;
  std::array<double, 5> baseline, notch50, notch60, highpass5, lowpass15;  // b0 b1 b2 a1 a2
};

inline const std::array<DesignCase, 3> kDesigns = {{
    {
        125.0,
        {0x1.f6fb396512868p-1, -0x1.f6fb396512868p+0, 0x1.f6fb396512868p-1, -0x1.f6e6e37a433d7p+0,
         0x1.ee1f1e9fc39f2p-1},
        {0x1.eb6770f470ee7p-1, 0x1.8d8de2c644d0ap+0, 0x1.eb6770f470ee7p-1, 0x1.8d8de2c644d0ap+0,
         0x1.d6cee1e8e1dcep-1},
        {0x1.e779e30008e65p-1, 0x1.e3a1d9828e419p+0, 0x1.e779e30008e65p-1, 0x1.e3a1d9828e419p+0,
         0x1.cef3c60011ccap-1},
        {0x1.ac96f452a2978p-1, -0x1.ac96f452a2978p+0, 0x1.ac96f452a2978p-1, -0x1.a5bfeff431c3bp+0,
         0x1.66dbf16226d6bp-1},
        {0x1.76069cf0267acp-4, 0x1.76069cf0267acp-3, 0x1.76069cf0267acp-4, -0x1.f6fde4619a5e2p-1,
         0x1.640265b35b374p-2},
    },
    {
        360.0,
        {0x1.fcd9b028b7905p-1, -0x1.fcd9b028b7905p+0, 0x1.fcd9b028b7905p-1, -0x1.fcd7354077c6dp+0,
         0x1.f9b85621eeb39p-1},
        {0x1.f8a8d579de02ap-1, -0x1.44638d89e404ep+0, 0x1.f8a8d579de02ap-1, -0x1.44638d89e404ep+0,
         0x1.f151aaf3bc054p-1},
        {0x1.f7376129e9231p-1, -0x1.f7376129e9233p-1, 0x1.f7376129e9231p-1, -0x1.f7376129e9233p-1,
         0x1.ee6ec253d2462p-1},
        {0x1.e15c40ea14f3ap-1, -0x1.e15c40ea14f3ap+0, 0x1.e15c40ea14f3ap-1, -0x1.e07158a536e27p+0,
         0x1.c48e525de609bp-1},
        {0x1.d7e809a6db12ap-7, 0x1.d7e809a6db12ap-6, 0x1.d7e809a6db12ap-7, -0x1.a20bd700c2c3ep+0,
         0x1.61962e9bf338fp-1},
    },
    {
        1000.0,
        {0x1.fedd27862edb9p-1, -0x1.fedd27862edb9p+0, 0x1.fedd27862edb9p-1, -0x1.fedcd4ea5d6eap+0,
         0x1.fdbaf44400912p-1},
        {0x1.fd5546f030539p-1, -0x1.e467925737bf4p+0, 0x1.fd5546f030539p-1, -0x1.e467925737bf4p+0,
         0x1.faaa8de060a72p-1},
        {0x1.fccd94f35c9c4p-1, -0x1.d912b7b460474p+0, 0x1.fccd94f35c9c4p-1, -0x1.d912b7b460474p+0,
         0x1.f99b29e6b9388p-1},
        {0x1.f4c069355de44p-1, -0x1.f4c069355de44p+0, 0x1.f4c069355de44p-1, -0x1.f4a0c68aec1c4p+0,
         0x1.e9c017bf9f588p-1},
        {0x1.10b43f9baf4c7p-9, 0x1.10b43f9baf4c7p-8, 0x1.10b43f9baf4c7p-9, -0x1.ddeca70684467p+0,
         0x1.c01c1f0b7749fp-1},
    },
}};

struct RunCase {
  double fs_hz;
  int mains_hz;
  std::array<float, 12> input, baseline, conditioned;
};

// input, baseline_mv and conditioned_mv, rounded to binary32
inline const std::array<RunCase, 2> kRuns = {{
    {
        360.0,
        50,
        {{0x1.99999a0000000p-2, 0x1.580ea20000000p-1, 0x1.8f0ec80000000p-1, 0x1.599ba80000000p-1,
          0x1.d977d80000000p-2, 0x1.495c0a0000000p-2, 0x1.85cc7c0000000p-2, 0x1.3f34aa0000000p-1,
          0x1.cd8c720000000p-1, 0x1.0a26280000000p+0, 0x1.ec40860000000p-1, 0x1.7ca3ee0000000p-1}},
        {{0x0.0p+0, 0x1.14cd0e0000000p-2, 0x1.7eb59c0000000p-2, 0x1.0fb93c0000000p-2,
          0x1.9f4b720000000p-5, -0x1.7015ea0000000p-4, -0x1.ee48940000000p-6, 0x1.b1023e0000000p-3,
          0x1.f0b3ac0000000p-2, 0x1.3b8f3a0000000p-1, 0x1.0fce4c0000000p-1, 0x1.3ae2c80000000p-2}},
        {{0x0.0p+0, 0x1.10d5200000000p-2, 0x1.7431a40000000p-2, 0x1.06538e0000000p-2,
          0x1.b7afd60000000p-5, -0x1.2742bc0000000p-4, -0x1.331c840000000p-7, 0x1.bac33e0000000p-3,
          0x1.daa1fa0000000p-2, 0x1.283c840000000p-1, 0x1.01b3de0000000p-1, 0x1.41374c0000000p-2}},
    },
    {
        250.0,
        60,
        {{0x1.99999a0000000p-2, 0x1.8523e80000000p-1, 0x1.1d90340000000p-1, 0x1.2195e80000000p-2,
          0x1.1d44a00000000p-1, 0x1.ef6e660000000p-1, 0x1.ada5b80000000p-1, 0x1.ff5bb20000000p-2,
          0x1.5419d40000000p-1, 0x1.18a9320000000p+0, 0x1.0cf12c0000000p+0, 0x1.5813380000000p-1}},
        {{0x0.0p+0, 0x1.6d6b440000000p-2, 0x1.3335200000000p-3, -0x1.0077900000000p-3,
          0x1.30dbc60000000p-3, 0x1.1b22340000000p-1, 0x1.a9b7120000000p-2, 0x1.24785c0000000p-4,
          0x1.dddb0a0000000p-3, 0x1.507a9e0000000p-1, 0x1.331fde0000000p-1, 0x1.b57fbc0000000p-3}},
        {{0x0.0p+0, 0x1.6475560000000p-2, 0x1.297a9a0000000p-3, -0x1.b0cfee0000000p-4,
          0x1.3f133a0000000p-3, 0x1.0987a20000000p-1, 0x1.97f0e60000000p-2, 0x1.d20e420000000p-4,
          0x1.09ba060000000p-2, 0x1.3621c20000000p-1, 0x1.1e8d8a0000000p-1, 0x1.12f50e0000000p-2}},
    },
}};

}  // namespace sinus::dsp::reference
