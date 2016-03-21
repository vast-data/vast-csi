/* Copyright (C) Vast Data, Inc - All Rights Reserved
 * Unauthorized copying of this file, via any medium is strictly
 * prohibited proprietary and confidential.
 */
#include <stdlib.h>
#include <stdint.h>
#include <assert.h>
#include "pool.h"

#define INDEX_TO_ADDRESS(pool, index) ((void*) (((uint8_t*) pool->mem) + index * pool->block_size))
#define INDEX_TO_VALUE(pool, index) (*((uint32_t*) INDEX_TO_ADDRESS(pool, index)))

struct p_pool {
    void *mem;
    size_t block_size;
    uint32_t blocks;
    uint32_t free_head;
};

p_pool *p_pool__init(uint32_t blocks, size_t block_size)
{
    // Validate each block is larger than the index it will contain.
    assert(block_size >= sizeof(uint32_t));

    p_pool *pool = malloc(sizeof(p_pool));
    pool->mem = malloc(blocks * block_size);
    pool->free_head = 0;
    pool->blocks = blocks;
    pool->block_size = block_size;

    // Every free node contains the index of the next free node.
    // The end of the list is marked with index == blocks.
    for (uint32_t i = 0; i < blocks; i++)
        INDEX_TO_VALUE(pool, i) = i + 1;
    return pool;
}

void *p_pool__alloc(p_pool *pool)
{
    uint32_t free = pool->free_head;
    if (free == pool->blocks)
        return NULL;
    pool->free_head = INDEX_TO_VALUE(pool, free);
    return INDEX_TO_ADDRESS(pool, free);
}

void p_pool__free(p_pool *pool, void *block)
{
    uint32_t index = (uint32_t) ((uintptr_t) block - (uintptr_t) pool->mem) / pool->block_size;
    INDEX_TO_VALUE(pool, index) = pool->free_head;
    pool->free_head = index;
}

void p_pool__destroy(p_pool *pool) {
    free(pool->mem);
    free(pool);
}
