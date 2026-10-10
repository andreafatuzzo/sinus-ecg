// Probe for the test no_heap_symbols_probe: it calls malloc, which the check must report.
#include <cstdlib>

void* sinus_dsp_heap_probe(std::size_t n) { return std::malloc(n); }
