/* Copyright (C) Vast Data Ltd. */
#include "cpool.hpp"

#include <stdint.h>
#include "../utils/assert.hpp"
#include "../sync/lock_guard.hpp"

namespace P {

void CPool::init(uint32_t num_caches, uint32_t max_buffers_per_cache, uint32_t n_buffers, uint32_t buffer_size)
{
    ASSERT_OP(buffer_size, >=, sizeof(Index), "invalid buffer_size");
    ASSERT_OP(n_buffers, >, 0, "invalid n_buffers");

    _shared_pool.init(n_buffers, buffer_size);
    _lock.init();

    _n_caches = num_caches;
    _max_buffers_per_cache = max_buffers_per_cache;
    _cache_heads = new Index[_n_caches];
    ASSERT_NOT_NULL(_cache_heads);
    _cache_counts = new uint32_t[_n_caches];
    ASSERT_NOT_NULL(_cache_counts);

    for (uint32_t j = 0; j < _n_caches; ++j) {
        _cache_heads[j] = INVALID_INDEX;
        _cache_counts[j] = 0;
    }
    _shared_count = n_buffers;
}

void CPool::destroy(bool leak_check) {
    // verify that there are no leaks
    if (leak_check) {
        Index pool_buffers = _shared_count;
        for (uint32_t i = 0; i < _n_caches; ++i) {
            pool_buffers += _cache_counts[i];
        }
        ASSERT_OP(pool_buffers, ==, _shared_pool.get_initial_n_blocks(), "leak detected");
    }

    delete[] _cache_heads;
    delete[] _cache_counts;
    _shared_pool.destroy();
    _lock.destroy();
}

void *CPool::alloc(Index cache_index)
{
    void *buffer = nullptr;
    // check if there is a buffer available in the cache
    DEBUG_ASSERT((cache_index == INVALID_INDEX) || ((uint32_t)cache_index < _n_caches), "invalid cache index " << cache_index);
    if (cache_index != INVALID_INDEX && _cache_heads[cache_index] != INVALID_INDEX) {
        DEBUG_ASSERT_OP(_cache_counts[cache_index], >, 0, "free list isn't empty though count equals 0");
        buffer = index_to_address(_cache_heads[cache_index]);
        _cache_heads[cache_index] = *(Index *) buffer;
        _cache_counts[cache_index]--;
        return buffer;
    }
    // no buffer available in the cache, go to the shared pool
    {
        Sync::LockGuard<Sync::SpinLock> guard(&_lock);
        buffer = _shared_pool.alloc_address();
        if (buffer != nullptr) {
            _shared_count--;
        }
    }
    return buffer;
}

void CPool::free_address(Index cache_index, void *buffer)
{
    free(cache_index, address_to_index(buffer));
}

void CPool::free(Index cache_index, Index buffer_index)
{
    DEBUG_ASSERT((cache_index == INVALID_INDEX) || ((uint32_t)cache_index < _n_caches), "invalid cache index " << cache_index);
    if (cache_index != INVALID_INDEX && _cache_counts[cache_index] < _max_buffers_per_cache) {
        // return the buffer to the cache
        void *buffer = index_to_address(buffer_index);
        *(Index *) buffer = _cache_heads[cache_index];
        _cache_heads[cache_index] = buffer_index;
        _cache_counts[cache_index]++;
        return;
    }
    // return the buffer to the shared pool
    {
        Sync::LockGuard<Sync::SpinLock> guard(&_lock);
        _shared_count++;
        _shared_pool.free(buffer_index);
    }
}

void CPool::print_counters()
{
    Sync::LockGuard<Sync::SpinLock> guard(&_lock);
    std::cout << "shared_count=" << _shared_count << std::endl;
    for (uint32_t j = 0; j < _n_caches; ++j) {
        std::cout << "cache[" << j << "]=" << _cache_counts[j] << std::endl;
    }
}

uint32_t CPool::get_shared_count()
{
    return __sync_fetch_and_add(&_shared_count, 0);
}

}
