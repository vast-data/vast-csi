/* Copyright (C) Vast Data Ltd. */
#include "alloc.hpp"
#include "../utils/assert.hpp"
#include "../utils/compiler.hpp"

namespace P {

void fill_zeroes(void *buffer, size_t size)
{
    memset(buffer, 0, size);
}

}
