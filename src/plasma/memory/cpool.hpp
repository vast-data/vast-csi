/* Copyright (C) Vast Data Ltd. */

/*!
 * \file cpool.hpp
 * \brief A fixed-block concurrent pool for efficient memory management.
 *
 * Note that the cpool must be initialized after the Env is initialized.
 * Uses a per thread cache in order to reduce locking. In case the thread cache is empty a spinlock is taken.
 */
#pragma once

#include <stdint.h>
#include "pool.hpp"
#include "../sync/spin_lock.hpp"

namespace P {

class CPool {
public:
    /*!
     * Initialize a concurrent pool.
     * In order to release the pool resources call destroy().
     *
     * \param num_caches the number of per the thread caches to use
     * \param max_buffers_per_cache the maximal number of buffers that can be placed in the per cache.
     * \param n_buffers the total number of buffers in the pool.
     * \param buffer_size the size of each buffer in bytes (minimum of 4 bytes).
     */
    void init(uint32_t num_caches, uint32_t max_buffers_per_cache, uint32_t n_buffers, uint32_t buffer_size);

    /*!
     * Frees the pool resources.
     */
    void destroy(bool leak_check);

    /*!
    * Allocate a buffer from the pool and returns its address.
    * Note that the memory is not cleared (zeroed).
    * \param cache_index index to the thread cache to use, must be lower than num_caches passed at init time.
    *   Or P::INVALID_INDEX of the current thread does not have a cache.
    *   It is expected that 2 different threads will not use the same index.
    *
    * \return a pointer to the buffer or nullptr if no buffer is available
    */
    void *alloc(Index cache_index);

    /*!
     * Return a buffer to the pool.
     *
     * \param cache_index index to the thread cache to use, must be lower than num_caches passed at init time.
     *   Or P::INVALID_INDEX of the current thread does not have a cache.
     *   It is expected that 2 different threads will not use the same index.
     * \param buffer the buffer to return to the pool
     */
    void free_address(Index cache_index, void *buffer);

    /*!
     * Return a buffer to the pool.
     *
     * \param cache_index index to the thread cache to use, must be lower than num_caches passed at init time.
     *   Or P::INVALID_INDEX of the current thread does not have a cache.
     *   It is expected that 2 different threads will not use the same index.
     * \param buffer_index the index of the buffer to return to the pool
     */
    void free(Index cache_index, Index buffer_index);

    /*!
     * Print the pool internal counters to stdout (used for debugging)
     */
    void print_counters();

    /*!
    * Translate a relative index to an absolute memory address.
    */
    void *index_to_address(Index index) { return _shared_pool.index_to_address(index); }

    /*!
    * Translates an absolute address to a relative index.
    */
    Index address_to_index(void *buffer) { return _shared_pool.address_to_index(buffer); }

    /*!
     * Returns the number of buffers currently residing in the shared pool
     */
    uint32_t get_shared_count() const;

    /*!
    * Returns a pointer to the start of the pool memory
    */
    void *get_mem_ptr() { return _shared_pool.get_mem_ptr(); }

    /*!
    * Returns the amount of memory used by the pool
    */
    size_t get_mem_size() { return _shared_pool.get_mem_size(); }

private:
    mutable Sync::SpinLock _lock;
    uint32_t _n_caches;
    uint32_t _max_buffers_per_cache;

    Index *_cache_heads;
    uint32_t *_cache_counts;
    uint32_t _shared_count;
    Pool _shared_pool;
};

};
