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
 */
#pragma once

#include <stdint.h>

typedef struct p_pool p_pool;

/*!
 * p_pool__init initializes a pool.
 * In order to destroy the pool and release resources call p_pool__destroy().
 *
 * \param blocks the number of blocks the pool is expected to hold.
 * \param block_size the size of each block in bytes (minimum of 4 bytes).
 * \return a pointer to a pool.
 */
p_pool *p_pool__init(uint32_t blocks, size_t block_size);

/*!
 * p_pool__alloc allocates a block from the pool.
 * Note that the memory is not cleared (zeroed).
 *
 * \return a pointer to a block.
 */
void *p_pool__alloc(p_pool *pool);

/*!
 * p_pool__free returns a block to the pool.
 */
void p_pool__free(p_pool *pool, void *block);

/*!
 * p_pool__destroy should be called when work with the pool is finished.
 * The p_pool object will be released along with the underlying memory region.
 */
void p_pool__destroy(p_pool *pool);
