/* Copyright (C) Vast Data Ltd. */
#include <p.h>

bool p_is_power_of_two (uintmax_t x)
{
    return ((x != 0) && ((x & (~x + 1)) == x));
}
