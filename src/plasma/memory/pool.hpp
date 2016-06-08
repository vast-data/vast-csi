/* Copyright (C) Vast Data Ltd. */

/*!
* \file pool.hpp
* \brief A fixed-block pool for efficient memory management.
*
* Constraints:
* 1. The minimum size of a block is 4 bytes.
* 2. The maximum number of blocks in the pool is 2**32.
*
*/

#pragma once

#include <stddef.h>

#include "../utils/types.hpp"

namespace P {

class Pool {
public:

    /*!
    * Initialize a partitioned pool.
    * In order to destroy the pool and release resources call destroy().
    *
    * \param block_size the size of each block in bytes (minimum of 4 bytes).
    * \param num_partitions the number of partitions
    * \param partitions array with the number of blocks per partition, isn't modified nor used after init is done
    */
    void partitioned_init(size_t block_size, Index num_partitions, Index partitions[]);

    /*!
    * Initialize a pool.
    * In order to destroy the pool and release resources call destroy().
    *
    * \param blocks the number of blocks the pool is expected to hold.
    * \param block_size the size of each block in bytes (minimum of 4 bytes).
    */
    void init(Index blocks, size_t block_size);

    /*!
    * Allocate a block from a partition within the pool.
    * Note that the memory is not cleared (zeroed).
    *
    * \return the index of the free block or -1 if no free blocks exist.
    */
    Index partitioned_alloc(Index partition);

    /*!
    * Allocate a block from the pool and returns its index.
    * Note that the memory is not cleared (zeroed).
    *
    * \return the index of the free block or -1 if no free blocks exist.
    */
    Index alloc();

    /*!
    * Allocate a block from a partition within the pool.
    * Note that the memory is not cleared (zeroed).
    *
    * \return the address of the free block or -1 if no free blocks exist.
    */
    void *partitioned_alloc_address(Index partition);

    /*!
    * Allocate a block from the pool.
    * Note that the memory is not cleared (zeroed).
    *
    * \return the address of the free block or -1 if no free blocks exist.
    */
    void *alloc_address();

    /*!
    * Return a block to the pool using its index and partition.
    */
    void partitioned_free(Index index, Index partition);

    /*!
    * Return a block to the pool using its index.
    */
    void free(Index index);

    /*!
    * Return a block to the pool using its address and partition.
    */
    void partitioned_free_address(void *address, Index partition);

    /*!
    * Return a block to the pool using its address.
    */
    void free_address(void *address);

    /*!
    * Translate a relative index to an absolute memory address.
    */
    void *index_to_address(Index index);

    /*!
    * Translates an absolute address to a relative index.
    */
    Index address_to_index(void *block);

    /*!
    * Return the number of initially allocated blocks in the pool
    */
    Index get_initial_n_blocks();

    /*!
    * Destroy a pool in order to free its resources.
    * The PPool object will be released along with the underlying memory region.
    */
    void destroy();

private:
    void *_mem;
    size_t _block_size;
    Index _num_partitions;
    Index *_partitions;
    Index _blocks;
    Index _free_head;
};

}
