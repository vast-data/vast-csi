/* Copyright (C) Vast Data Ltd. */

/*!
 * \file alloc.hpp
 * \brief A collection of memory allocation functions
 */

#pragma once

#include "../utils/assert.hpp"

namespace P {

template <typename T, typename... Args>
inline T* aligned_new(size_t alignment, Args... args)
{
    void *ptr = aligned_alloc(alignment, sizeof(T));
    ASSERT_NOT_NULL(ptr);
    return new (ptr) T(args...);
}

template <typename T>
inline T* aligned_new_arr(size_t alignment, size_t arr_len)
{
    void *ptr = aligned_alloc(alignment, arr_len * sizeof(T));
    ASSERT_NOT_NULL(ptr);
    return new (ptr) T[arr_len](); // elements are initialized
}

template <typename T, typename... Args>
inline T* cache_aligned_new(Args... args)
{
    return aligned_new<T>(CACHE_LINE_BYTES, args...);
}

template <typename T>
inline T* cache_aligned_new_arr(size_t arr_len)
{
    return aligned_new_arr<T>(CACHE_LINE_BYTES, arr_len);
}

void
inline aligned_delete(void *ptr)
{
    free(ptr);
}

void fill_zeroes(void *buffer, size_t size);

}
