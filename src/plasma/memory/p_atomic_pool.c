/* Copyright (C) Vast Data Ltd. */
#include "p_atomic_pool.h"

struct PAtomicPool {
    PSem idle_elements;
    PPool *pool;
};

// Note: init fcn is useless when using p_pool since the element is being rewritten when not allocated.
//typedef void (*element_initializer) (void *element);

PAtomicPool *p_atomic_pool_init(PIndex element_count, size_t element_size) //, element_initializer init_fn)
{
    PAtomicPool *pool_ret = (PAtomicPool*)p_safe_cache_aligned_malloc(sizeof(PAtomicPool));
    pool_ret->pool = p_pool_init(element_count, element_size);
    p_sem_init(&pool_ret->idle_elements, (uint32_t)element_count);
    return pool_ret;
}

inline PIndex  p_atomic_pool_element_to_index(PAtomicPool *apool, void *element)
{
    return p_pool_address_to_index(apool->pool, element);
}

inline void *p_atomic_pool_index_to_element(PAtomicPool *apool, PIndex index)
{
    return p_pool_index_to_address(apool->pool, index);
}

void p_atomic_pool_alloc_multiple(PAtomicPool *apool, PIndex idle_elements[] OUT, uint32_t element_count)
{
    p_sem_dec(&apool->idle_elements, element_count);

    LOOP_TYPE(uint32_t, element_count, element_index) {
        idle_elements[element_index] =  p_pool_alloc(apool->pool);
        P_ASSERT(idle_elements[element_index] != P_INVALID_INDEX);
    }
}

void p_atomic_pool_free_multiple(PAtomicPool *apool, PIndex returned_elements[], uint32_t element_count)
{
    LOOP_TYPE(uint32_t, element_count, element_index) {
        p_pool_free(apool->pool, returned_elements[element_index]);
    }

    p_sem_inc(&apool->idle_elements, element_count);
}

void *p_atomic_pool_alloc(PAtomicPool *apool)
{
    PIndex index;
    p_atomic_pool_alloc_multiple(apool, &index, 1);
    return p_atomic_pool_index_to_element(apool, index);
}

void p_atomic_pool_free(PAtomicPool *apool, void *element)
{
    PIndex index = p_atomic_pool_element_to_index(apool, element);
    p_atomic_pool_free_multiple(apool, &index, 1);
}

void p_atomic_pool_destroy(PAtomicPool *apool)
{
    p_sem_destroy(&apool->idle_elements);
    p_pool_destroy(apool->pool);
    free(apool);
}
