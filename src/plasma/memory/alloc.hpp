/* Copyright (C) Vast Data Ltd. */

/*!
 * \file alloc.hpp
 * \brief A collection of memory allocation functions
 */

#pragma once

#include <cstdlib>

namespace P {

void *p_malloc(size_t size);

/*!
 * p_cache_malloc calls p_malloc and panics if the result is NULL.
 */
void *p_safe_malloc(size_t size);

/*!
 * p_cache_aligned_alloc allocates a memory region aligned on a cache line.
 * \param size should be a multiple of a cache line (64 bytes on 64-bit systems).
 */
void *p_cache_aligned_malloc(size_t size);

/*!
 * p_safe_cache_aligned_alloc calls p_cache_aligned_alloc() and panics if the result is NULL
 */
void *p_safe_cache_aligned_malloc(size_t size);

void p_fill_zeroes(void *buffer, size_t size);

void p_free(void *buffer);

}
