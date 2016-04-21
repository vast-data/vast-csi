/* Copyright (C) Vast Data Ltd. */
#include <p.h>

#define INDEX_TO_VALUE(pool, index) (*((PIndex*) p_pool_index_to_address(pool, index)))

struct PPool {
    void *mem;
    size_t block_size;
    PIndex num_partitions;
    PIndex *partitions;
    PIndex blocks;
    PIndex free_head;
};

PPool *p_pool_partitioned_init(size_t block_size, PIndex num_partitions, PIndex partitions[])
{
    // validate block_size is larger than the index it will contain.
    P_ASSERT(block_size >= sizeof(PIndex));

    PPool *pool = p_safe_malloc(sizeof(PPool));
    pool->partitions = p_safe_malloc((size_t) num_partitions * sizeof(PIndex));
    pool->block_size = block_size;
    pool->blocks = 0;
    LOOP((size_t) num_partitions, i) {
        pool->partitions[i] = partitions[i];
        pool->blocks += partitions[i];
    }

    size_t mem_size = (size_t) pool->blocks * block_size;
    // allocate a cache aligned buffer and expand it to the nearest cache line (required by aligned_alloc)
    pool->mem = p_safe_cache_aligned_malloc(mem_size + mem_size % P_CACHE_LINE_BYTES);
    pool->free_head = 0;
    pool->num_partitions = num_partitions;

    // every free node contains the index of the next free node.
    // the end of the list is marked with index == blocks.
    for (PIndex i = 0; i < pool->blocks - 1; i++) {
        INDEX_TO_VALUE(pool, i) = i + 1;
    }
    INDEX_TO_VALUE(pool, pool->blocks - 1) = P_INVALID_INDEX;
    return pool;
}

PPool *p_pool_init(PIndex blocks, size_t block_size)
{
    PIndex partitions[1] = {blocks};
    return p_pool_partitioned_init(block_size, 1, partitions);
}

PIndex p_pool_partitioned_alloc(PPool *pool, PIndex partition)
{
    if (pool->partitions[partition] == 0)
        return P_INVALID_INDEX;

    pool->partitions[partition]--;

    PIndex free = pool->free_head;
    P_ASSERT(free != P_INVALID_INDEX);
    pool->free_head = INDEX_TO_VALUE(pool, free);
    return free;
}

PIndex p_pool_alloc(PPool *pool)
{
    return p_pool_partitioned_alloc(pool, 0);
}

void *p_pool_partitioned_alloc_address(PPool *pool, PIndex partition)
{
    return p_pool_index_to_address(pool, p_pool_partitioned_alloc(pool, partition));
}

void *p_pool_alloc_address(PPool *pool)
{
    return p_pool_index_to_address(pool, p_pool_alloc(pool));
}

void p_pool_partitioned_free(PPool *pool, PIndex index, PIndex partition)
{
    P_ASSERT(index < pool->blocks);
    pool->partitions[partition]++;
    INDEX_TO_VALUE(pool, index) = pool->free_head;
    pool->free_head = index;
}

void p_pool_free(PPool *pool, PIndex index)
{
    p_pool_partitioned_free(pool, index, 0);
}

void p_pool_partitioned_free_address(PPool *pool, void *address, PIndex partition)
{
    p_pool_partitioned_free(pool, p_pool_address_to_index(pool, address), partition);
}

void p_pool_free_address(PPool *pool, void *address)
{
    p_pool_free(pool, p_pool_address_to_index(pool, address));
}

PIndex p_pool_address_to_index(PPool *pool, void *block)
{
    return (PIndex) (((uintptr_t) block - (uintptr_t) pool->mem) / pool->block_size);
}

void *p_pool_index_to_address(PPool *pool, PIndex index)
{
    P_ASSERT(index != P_INVALID_INDEX);
    return (void*) (((uintptr_t) pool->mem) + (size_t) index * pool->block_size);
}

void p_pool_destroy(PPool *pool) {
    p_free(pool->partitions);
    p_free(pool->mem);
    p_free(pool);
}
