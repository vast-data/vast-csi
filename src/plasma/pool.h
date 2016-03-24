/* Copyright (C) Vast Data, Inc - All Rights Reserved
 * Unauthorized copying of this file, via any medium is strictly
 * prohibited proprietary and confidential.
 */

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
 * 3. Consider supporting multiple allocations at once.
 */
#pragma once

#include <stdint.h>
#include "defs.h"

typedef struct p_pool p_pool;

/*!
 * p_pool__init initializes a pool.
 * In order to destroy the pool and release resources call p_pool__destroy().
 *
 * \param blocks the number of blocks the pool is expected to hold.
 * \param block_size the size of each block in bytes (minimum of 4 bytes).
 * \return a pointer to a pool.
 */
p_pool *p_pool__init(p_index blocks, size_t block_size);

/*!
 * p_pool__alloc allocates a block from the pool and returns its index.
 * Note that the memory is not cleared (zeroed).
 *
 * \return the index of the free block or -1 if no free blocks exist.
 */
p_index p_pool__alloc(p_pool *pool);

/*!
 * p_pool__alloc_address allocates a block from the pool and returns its address.
 * Note that the memory is not cleared (zeroed).
 *
 * \return the address of the free block or -1 if no free blocks exist.
 */
void *p_pool__alloc_address(p_pool *pool);

/*!
 * p_pool__free returns a block to the pool using its index.
 */
void p_pool__free(p_pool *pool, p_index index);

/*!
 * p_pool__free_address returns a block to the pool using its address.
 */
void p_pool__free_address(p_pool *pool, void *address);

/*!
 * p_pool__index_to_address translates a relative index to an absolute memory address.
 */
void *p_pool__index_to_address(p_pool *pool, p_index index);

/*!
 * p_pool__address_to_index translates an absolute address to a relative index.
 */
p_index p_pool__address_to_index(p_pool *pool, void *block);

/*!
 * p_pool__destroy should be called when work with the pool is finished.
 * The p_pool object will be released along with the underlying memory region.
 */
void p_pool__destroy(p_pool *pool);
