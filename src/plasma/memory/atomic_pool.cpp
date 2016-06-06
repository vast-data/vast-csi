/* Copyright (C) Vast Data Ltd. */

#include <plasma/utils/assert.hpp>
#include "atomic_pool.hpp"
#include "../sync/p_sem.h"

// Note: init fcn is useless when using p_pool since the element is being rewritten when not allocated.
//typedef void (*element_initializer) (void *element);

namespace P {

void AtomicPool::init(PIndex element_count, size_t element_size) //, element_initializer init_fn)
{
    _pool.init(element_count, element_size);
    p_sem_init(&_idle_elements, (uint32_t) element_count);
}

inline PIndex  AtomicPool::element_to_index(void *element)
{
    return _pool.address_to_index(element);
}

inline void *AtomicPool::index_to_element(PIndex index) {
    return _pool.index_to_address(index);
}

void AtomicPool::alloc_multiple(PIndex idle_elements[] OUT, uint32_t element_count)
{
    p_sem_dec(&_idle_elements, element_count);

    LOOP_TYPE(uint32_t, element_count, element_index) {
        idle_elements[element_index] = _pool.alloc();
        ASSERT(idle_elements[element_index] != P_INVALID_INDEX, "invalid element index");
    }
}

void AtomicPool::free_multiple(PIndex returned_elements[], uint32_t element_count)
{
    LOOP_TYPE(uint32_t, element_count, element_index) {
        _pool.free(returned_elements[element_index]);
    }

    p_sem_inc(&_idle_elements, element_count);
}

void *AtomicPool::alloc()
{
    PIndex index;
    alloc_multiple(&index, 1);
    return index_to_element(index);
}

void AtomicPool::free(void *element)
{
    PIndex index = element_to_index(element);
    free_multiple(&index, 1);
}

void AtomicPool::destroy()
{
    p_sem_destroy(&_idle_elements);
    _pool.destroy();
}

}