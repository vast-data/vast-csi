/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_alloc.h
 * \brief A collection of memory allocation functions
 */

#pragma once

#include <p.h>

void *p_malloc(size_t size);

/*!
 * p_cache_malloc calls p_malloc and aborts if the result is NULL.
 */
void *p_safe_malloc(size_t size);

/*!
 * p_cache_aligned_alloc allocates a memory region aligned on a cache line.
 * \param size should be a multiple of a cache line (64 bytes on 64-bit systems).
 */
void *p_cache_aligned_alloc(size_t size);

/*!
 * p_safe_cache_aligned_alloc calls p_cache_aligned_alloc() and aborts if the result is NULL
 */
void *p_safe_cache_aligned_alloc(size_t size);

void p_fill_zeroes(void *buffer, size_t size);

void p_free(void *buffer);
