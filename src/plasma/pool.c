/* Copyright (C) Vast Data Ltd. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "pool.h"
#include "defs.h"
#include "alloc.h"
#include "assert.h"

#define INDEX_TO_VALUE(pool, index) (*((p_index*) p_pool__index_to_address(pool, index)))

struct p_pool {
    void *mem;
    size_t block_size;
    p_index blocks;
    p_index free_head;
};

p_pool *p_pool__init(p_index blocks, size_t block_size)
{
    // Validate each block is larger than the index it will contain.
    P_ASSERT(block_size >= sizeof(p_index));

    p_pool *pool = p_safe_malloc(sizeof(p_pool));
    // Allocate a cache aligned buffer and expand it to the nearest cache line (required by aligned_alloc)
    pool->mem = p_safe_cache_aligned_alloc((size_t) blocks * block_size + ((size_t) blocks * block_size % P_CACHE_LINE_BYTES));
    pool->free_head = 0;
    pool->blocks = blocks;
    pool->block_size = block_size;

    // Every free node contains the index of the next free node.
    // The end of the list is marked with index == blocks.
    for (p_index i = 0; i < blocks - 1; i++)
        INDEX_TO_VALUE(pool, i) = i + 1;
    INDEX_TO_VALUE(pool, blocks - 1) = P_INVALID_INDEX;
    return pool;
}

p_index p_pool__alloc(p_pool *pool)
{
    p_index free = pool->free_head;
    if (free == P_INVALID_INDEX)
        return P_INVALID_INDEX;
    pool->free_head = INDEX_TO_VALUE(pool, free);
    return free;
}

void *p_pool__alloc_address(p_pool *pool)
{
    return p_pool__index_to_address(pool, p_pool__alloc(pool));
}

void p_pool__free(p_pool *pool, p_index index)
{
    INDEX_TO_VALUE(pool, index) = pool->free_head;
    pool->free_head = index;
}

void p_pool__free_address(p_pool *pool, void *address)
{
    p_pool__free(pool, p_pool__address_to_index(pool, address));
}

p_index p_pool__address_to_index(p_pool *pool, void *block)
{
    return (p_index) (((uintptr_t) block - (uintptr_t) pool->mem) / pool->block_size);
}

void *p_pool__index_to_address(p_pool *pool, p_index index)
{
    P_ASSERT(index != P_INVALID_INDEX);
    return (void*) (((uintptr_t) pool->mem) + (size_t) index * pool->block_size);
}

void p_pool__destroy(p_pool *pool) {
    free(pool->mem);
    free(pool);
}
