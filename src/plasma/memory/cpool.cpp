#include "cpool.hpp"

#include <stdint.h>
#include "plasma/utils/assert.hpp"

namespace P {

void CPool::init(uint32_t n_silos, uint32_t max_buffers_per_silo, uint32_t n_buffers, uint32_t buffer_size) {
    ASSERT(buffer_size >= sizeof(PIndex), "invalid buffer_size");
    ASSERT(n_buffers > max_buffers_per_silo * n_silos, "the number of buffers must be larger than the silo caches");

    _shared_pool.init(n_buffers, buffer_size);

    _n_silos = n_silos;
    _max_buffers_per_silo = max_buffers_per_silo;

    // TODO add p_new and p_delete
    _silo_heads = new PIndex[n_silos];
    ASSERT(_silo_heads != nullptr, "allocation failed");
    _silo_counts = new uint32_t[n_silos];
    ASSERT(_silo_counts != nullptr, "allocation failed");

    for (uint32_t j = 0; j < _n_silos; ++j) {
        _silo_heads[j] = P_INVALID_INDEX;
        _silo_counts[j] = 0;
    }
    _shared_count = n_buffers;
    p_spin_lock_init(&_lock);
}

void CPool::destroy() {
    // verify that there are no leaks
    PIndex pool_buffers = _shared_count;
    for (uint32_t i = 0; i < _n_silos; ++i) {
        pool_buffers += _silo_counts[i];
    }
    ASSERT(pool_buffers == _shared_pool.get_initial_n_blocks(), "leak detected");

    p_spin_lock_destroy(&_lock);
    delete[] _silo_heads;
    delete[] _silo_counts;
    _shared_pool.destroy();
}

void *CPool::alloc() {
    void *buffer = nullptr;
    PSiloId silo_id = p_silo_get_id();
    // check if there is a buffer available in the silo pool
    if (silo_id != P_INVALID_SILO_ID && _silo_heads[silo_id] != P_INVALID_INDEX) {
        P_DEBUG_ASSERT(_silo_counts[silo_id] > 0);
        buffer = _shared_pool.index_to_address(_silo_heads[silo_id]);
        _silo_heads[silo_id] = *(PIndex *) buffer;
        _silo_counts[silo_id]--;
        return buffer;
    }
    // no buffer available in the silo pool, go to the shared pool
    p_spin_lock_lock(&_lock);
    buffer = _shared_pool.alloc_address();
    if (buffer != NULL) {
        _shared_count--;
    }
    p_spin_lock_unlock(&_lock);
    return buffer;
}

void CPool::free(void *buffer) {
    PSiloId silo_id = p_silo_get_id();
    if (silo_id != P_INVALID_SILO_ID && _silo_counts[silo_id] < _max_buffers_per_silo) {
        P_DEBUG_ASSERT(silo_id <= _n_silos);
        // return the buffer to the silo pool
        *(PIndex *) buffer = _silo_heads[silo_id];
        _silo_heads[silo_id] = _shared_pool.address_to_index(buffer);
        _silo_counts[silo_id]++;
        return;
    }
    // return the buffer to the shared pool
    p_spin_lock_lock(&_lock);
    _shared_count++;
    _shared_pool.free_address(buffer);
    p_spin_lock_unlock(&_lock);
}

void CPool::print_counters() {
    printf("shared_count=%u\n", _shared_count);
    for (uint32_t j = 0; j < _n_silos; ++j) {
        printf("silo[%u]=%u\n", j, _silo_counts[j]);
    }
}

}