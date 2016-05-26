/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_pool.h
 * \brief A fixed-block pool for efficient memory management.
 *
 * Constraints:
 * 1. The minimum size of a block is 4 bytes.
 * 2. The maximum number of blocks in the pool is 2**32.
 *
 * Future considerations:
 * 1. Add thread safety.
 * 2. Consider adding a magic chunk to each block for identifying overflows.
 * 3. Consider supporting multiple allocations at once (to prevent deadlocks).
 */

#pragma once

#include <p.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PPool PPool;

/*!
 * Initialize a partitioned pool.
 * In order to destroy the pool and release resources call p_pool_destroy().
 *
 * \param block_size the size of each block in bytes (minimum of 4 bytes).
 * \param num_partitions the number of partitions
 * \param partitions array with the number of blocks per partition, isn't modified nor used after init is done
 * \return a pointer to a pool.
 */
PPool *p_pool_partitioned_init(size_t block_size, PIndex num_partitions, PIndex partitions[]);

/*!
 * Initialize a pool.
 * In order to destroy the pool and release resources call p_pool_destroy().
 *
 * \param blocks the number of blocks the pool is expected to hold.
 * \param block_size the size of each block in bytes (minimum of 4 bytes).
 * \return a pointer to a pool.
 */
PPool *p_pool_init(PIndex blocks, size_t block_size);

/*!
 * Allocate a block from a partition within the pool.
 * Note that the memory is not cleared (zeroed).
 *
 * \return the index of the free block or -1 if no free blocks exist.
 */
PIndex p_pool_partitioned_alloc(PPool *pool, PIndex partition);

/*!
 * Allocate a block from the pool and returns its index.
 * Note that the memory is not cleared (zeroed).
 *
 * \return the index of the free block or -1 if no free blocks exist.
 */
PIndex p_pool_alloc(PPool *pool);

/*!
 * Allocate a block from a partition within the pool.
 * Note that the memory is not cleared (zeroed).
 *
 * \return the address of the free block or -1 if no free blocks exist.
 */
void *p_pool_partitioned_alloc_address(PPool *pool, PIndex partition);

/*!
 * Allocate a block from the pool.
 * Note that the memory is not cleared (zeroed).
 *
 * \return the address of the free block or -1 if no free blocks exist.
 */
void *p_pool_alloc_address(PPool *pool);

/*!
 * Return a block to the pool using its index and partition.
 */
void p_pool_partitioned_free(PPool *pool, PIndex index, PIndex partition);

/*!
 * Return a block to the pool using its index.
 */
void p_pool_free(PPool *pool, PIndex index);

/*!
 * Return a block to the pool using its address and partition.
 */
void p_pool_partitioned_free_address(PPool *pool, void *address, PIndex partition);

/*!
 * Return a block to the pool using its address.
 */
void p_pool_free_address(PPool *pool, void *address);

/*!
 * Translate a relative index to an absolute memory address.
 */
void *p_pool_index_to_address(PPool *pool, PIndex index);

/*!
 * Translates an absolute address to a relative index.
 */
PIndex p_pool_address_to_index(PPool *pool, void *block);

/*!
 * Return the number of initially allocated blocks in the pool
 */
PIndex p_pool_get_initial_n_blocks(PPool *pool);

/*!
 * Destroy a pool in order to free its resources.
 * The PPool object will be released along with the underlying memory region.
 */
void p_pool_destroy(PPool *pool);

#ifdef __cplusplus
}
#endif
