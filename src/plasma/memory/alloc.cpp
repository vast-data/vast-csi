/* Copyright (C) Vast Data Ltd. */
#include "alloc.hpp"
#include "../utils/assert.hpp"
#include "../utils/compiler.hpp"

namespace P {

void *p_malloc(size_t size)
{
    return malloc(size);
}

void *p_safe_malloc(size_t size)
{
    void *buffer = p_malloc(size);
    ASSERT_NOT_NULL(buffer);
    return buffer;
}

void *p_cache_aligned_malloc(size_t size)
{
    return aligned_alloc(CACHE_LINE_BYTES, size);
}

void *p_safe_cache_aligned_malloc(size_t size)
{
    void *buffer = p_cache_aligned_malloc(size);
    ASSERT_NOT_NULL(buffer);
    return buffer;
}

void p_fill_zeroes(void *buffer, size_t size)
{
    memset(buffer, 0, size);
}

void p_free(void *buffer)
{
    free(buffer);
}

}
