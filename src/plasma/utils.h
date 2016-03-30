#pragma once

#define LOOP(until, i) for (size_t i = 0; i < until; i++)

#define P_CACHE_LINE_BYTES 64
#define P_CACHE_ALIGNED __attribute__ ((aligned(P_CACHE_LINE_BYTES)))
#define P_PACKED __attribute__ ((packed)))

inline int is_power_of_two (uintmax_t x)
{
    return ((x != 0) && ((x & (~x + 1)) == x));
}
