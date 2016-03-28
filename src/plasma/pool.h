/* Copyright (C) Vast Data Ltd. */

/*!
 * \file pool.h
 * \brief A fixed-block pool for efficient memory management.
 *
 * Constraints:
 * 1. The minimum size of a block is 4 bytes.
 * 2. The maximum number of blocks in the pool is 2**32.
 *
 * Future considerations:
 * 1. The pool currently doesn't support multiple threads.
 * 2. Consider adding a magic to each block for identifying overflows.
 * 3. Consider supporting multiple allocations at once (to prevent deadlocks).
 */
#pragma once

#include <stdint.h>
#include "defs.h"

typedef struct p_pool p_pool;

/*!
 * Initialize a pool.
 * In order to destroy the pool and release resources call p_pool__destroy().
 *
 * \param blocks the number of blocks the pool is expected to hold.
 * \param block_size the size of each block in bytes (minimum of 4 bytes).
 * \return a pointer to a pool.
 */
p_pool *p_pool__init(p_index blocks, size_t block_size);

/*!
 * Allocate a block from the pool and returns its index.
 * Note that the memory is not cleared (zeroed).
 *
 * \return the index of the free block or -1 if no free blocks exist.
 */
p_index p_pool__alloc(p_pool *pool);

/*!
 * Allocate a block from the pool and returns its address.
 * Note that the memory is not cleared (zeroed).
 *
 * \return the address of the free block or -1 if no free blocks exist.
 */
void *p_pool__alloc_address(p_pool *pool);

/*!
 * Return a block to the pool using its index.
 */
void p_pool__free(p_pool *pool, p_index index);

/*!
 * Return a block to the pool using its address.
 */
void p_pool__free_address(p_pool *pool, void *address);

/*!
 * Translate a relative index to an absolute memory address.
 */
void *p_pool__index_to_address(p_pool *pool, p_index index);

/*!
 * Translates an absolute address to a relative index.
 */
p_index p_pool__address_to_index(p_pool *pool, void *block);

/*!
 * Destroy a pool in order to free its resources.
 * The p_pool object will be released along with the underlying memory region.
 */
void p_pool__destroy(p_pool *pool);
