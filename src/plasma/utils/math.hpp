/* Copyright (C) Vast Data Ltd. */

/*!
 * \file math.hpp
 * \brief A collection of useful math utilities
 */
#pragma once

#include <stdint.h>
#include "compiler.hpp"

namespace P {

inline bool WARN_UNUSED is_power_of_two(uintmax_t x)
{
    return ((x != 0) && ((x & (x - 1)) == 0));
}

inline uintmax_t WARN_UNUSED round_to_next_power_of_two(uintmax_t x)
{
    uint8_t bit = 0;
    while (x > 0) {
        bit++;
        x >>= 1;
    }
    return 1 << bit;
}

inline uint64_t WARN_UNUSED unit_consumption(uint64_t x, uint64_t unit)
{
    return (x + unit - 1) / unit;
}

inline uint64_t WARN_UNUSED round_to(uint64_t x, uint64_t unit)
{
    return unit * unit_consumption(x, unit);
}

}
