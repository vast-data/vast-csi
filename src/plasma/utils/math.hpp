/* Copyright (C) Vast Data Ltd. */

/*!
 * \file math.hpp
 * \brief A collection of useful math utilities
 */
#pragma once

#include <stdint.h>

namespace P {

inline bool is_power_of_two (uintmax_t x)
{
    return ((x != 0) && ((x & (~x + 1)) == x));
}

}
