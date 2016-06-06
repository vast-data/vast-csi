/* Copyright (C) Vast Data Ltd. */

/*!
 * \file cpool.h
 * \brief A fixed-block concurrent pool for efficient memory management.
 *
 * Uses a per SILO cache in order to reduce locking. In case the silo cache is empty a spinlock is taken.
 */
#pragma once

#include <stdint.h>
#include "pool.hpp"
#include "../sync/p_spin_lock.h"

namespace P {

class CPool {
public:
    /*!
     * Initialize a concurrent pool.
     * In order to release the pool resources call destroy().
     *
     * \param n_silos the number of silos in the Env using this pool
     * \param max_buffers_per_silo the maximal number of buffers that can be placed in the per silo cache.
     * \param n_buffers the total number of buffers in the pool.
     * \param buffer_size the size of each buffer in bytes (minimum of 4 bytes).
     */
    void init(uint32_t n_silos, uint32_t max_buffers_per_silo, uint32_t n_buffers, uint32_t buffer_size);

    /*!
     * Frees the pool resources.
     */
    void destroy();

    /*!
    * Allocate a buffer from the pool and returns its buffer.
    * Note that the memory is not cleared (zeroed).
    *
    * \return a pointer to the buffer or nullptr if no buffer is available
    */
    void *alloc();

    /*!
     * Return a buffer to the pool.
     */
    void free(void *buffer);

    /*!
     * Print the pool internal counters to stdout (used for debugging)
     */
    void print_counters();

private:
    uint32_t _n_silos;
    uint32_t _max_buffers_per_silo;

    PSpinLock _lock;

    PIndex *_silo_heads;
    uint32_t *_silo_counts;
    uint32_t _shared_count;
    Pool _shared_pool;
};

};
