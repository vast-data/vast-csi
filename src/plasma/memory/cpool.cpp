/* Copyright (C) Vast Data Ltd. */
#include "cpool.hpp"

#include <stdint.h>
#include "../utils/assert.hpp"
#include "../execution/p_silo.h"

namespace P {

void CPool::init(uint32_t n_silos, uint32_t max_buffers_per_silo, uint32_t n_buffers, uint32_t buffer_size) {
    ASSERT_OP(buffer_size, >=, sizeof(Index), "invalid buffer_size");
    ASSERT_OP(n_buffers, >, max_buffers_per_silo * n_silos, "the number of buffers must be larger than the silo caches");

    _shared_pool.init(n_buffers, buffer_size);

    _n_silos = n_silos;
    _max_buffers_per_silo = max_buffers_per_silo;

    // TODO add p_new and p_delete
    _silo_heads = new Index[n_silos];
    ASSERT_OP(_silo_heads, !=, nullptr, "allocation failed");
    _silo_counts = new uint32_t[n_silos];
    ASSERT_OP(_silo_counts, !=, nullptr, "allocation failed");

    for (uint32_t j = 0; j < _n_silos; ++j) {
        _silo_heads[j] = INVALID_INDEX;
        _silo_counts[j] = 0;
    }
    _shared_count = n_buffers;
}

void CPool::destroy() {
    // verify that there are no leaks
    Index pool_buffers = _shared_count;
    for (uint32_t i = 0; i < _n_silos; ++i) {
        pool_buffers += _silo_counts[i];
    }
    ASSERT_OP(pool_buffers, ==, _shared_pool.get_initial_n_blocks(), "leak detected");

    delete[] _silo_heads;
    delete[] _silo_counts;
    _shared_pool.destroy();
}

void *CPool::alloc() {
    void *buffer = nullptr;
    PSiloId silo_id = p_silo_get_id();
    // check if there is a buffer available in the silo pool
    if (silo_id != P_INVALID_SILO_ID && _silo_heads[silo_id] != INVALID_INDEX) {
        DEBUG_ASSERT_OP(_silo_counts[silo_id], >, 0, "free list isn't empty though count equals 0");
        buffer = _shared_pool.index_to_address(_silo_heads[silo_id]);
        _silo_heads[silo_id] = *(Index *) buffer;
        _silo_counts[silo_id]--;
        return buffer;
    }
    // no buffer available in the silo pool, go to the shared pool
    _lock.lock();
    buffer = _shared_pool.alloc_address();
    if (buffer != NULL) {
        _shared_count--;
    }
    _lock.unlock();
    return buffer;
}

void CPool::free(void *buffer) {
    PSiloId silo_id = p_silo_get_id();
    if (silo_id != P_INVALID_SILO_ID && _silo_counts[silo_id] < _max_buffers_per_silo) {
        DEBUG_ASSERT_OP(silo_id, <=, _n_silos, "invalid silo id from p_silo_get_id()");
        // return the buffer to the silo pool
        *(Index *) buffer = _silo_heads[silo_id];
        _silo_heads[silo_id] = _shared_pool.address_to_index(buffer);
        _silo_counts[silo_id]++;
        return;
    }
    // return the buffer to the shared pool
    _lock.lock();
    _shared_count++;
    _shared_pool.free_address(buffer);
    _lock.unlock();
}

void CPool::print_counters() {
    std::cout << "shared_count=" << _shared_count << std::endl;
    for (uint32_t j = 0; j < _n_silos; ++j) {
        std::cout << "silo[" << j << "]=" << _silo_counts[j] << std::endl;
    }
}

}
