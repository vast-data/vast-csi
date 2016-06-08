/* Copyright (C) Vast Data Ltd. */

#include <plasma/utils/assert.hpp>
#include "atomic_pool.hpp"

// Note: init fcn is useless when using p_pool since the element is being rewritten when not allocated.
//typedef void (*element_initializer) (void *element);

namespace P {

void AtomicPool::init(Index element_count, size_t element_size) //, element_initializer init_fn)
{
    _pool.init(element_count, element_size);
    _idle_elements.init((uint32_t) element_count);
}

void AtomicPool::alloc_multiple(Index idle_elements[] OUT, uint32_t element_count)
{
    _idle_elements.dec(element_count);

    LOOP_TYPE(uint32_t, element_count, element_index) {
        idle_elements[element_index] = _pool.alloc();
        ASSERT(idle_elements[element_index] != INVALID_INDEX, "invalid element index");
    }
}

void AtomicPool::free_multiple(Index returned_elements[], uint32_t element_count)
{
    LOOP_TYPE(uint32_t, element_count, element_index) {
        _pool.free(returned_elements[element_index]);
    }

    _idle_elements.inc(element_count);
}

void *AtomicPool::alloc()
{
    Index index;
    alloc_multiple(&index, 1);
    return index_to_element(index);
}

void AtomicPool::free(void *element)
{
    Index index = element_to_index(element);
    free_multiple(&index, 1);
}

void AtomicPool::destroy()
{
    _idle_elements.destroy();
    _pool.destroy();
}

}
