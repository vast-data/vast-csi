/* Copyright (C) Vast Data Ltd. */
#include <p.h>

#define INDEX_TO_VALUE(pool, index) (*((p_index*) p_pool_index_to_address(pool, index)))

struct p_pool {
    void *mem;
    size_t block_size;
    p_index num_partitions;
    p_index *partitions;
    p_index blocks;
    p_index free_head;
};

p_pool *p_pool_partitioned_init(size_t block_size, p_index num_partitions, p_index partitions[])
{
    // validate block_size is larger than the index it will contain.
    P_ASSERT(block_size >= sizeof(p_index));

    p_pool *pool = p_safe_malloc(sizeof(p_pool));
    pool->partitions = p_safe_malloc((size_t) num_partitions * sizeof(p_index));
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
    for (p_index i = 0; i < pool->blocks - 1; i++) {
        INDEX_TO_VALUE(pool, i) = i + 1;
    }
    INDEX_TO_VALUE(pool, pool->blocks - 1) = P_INVALID_INDEX;
    return pool;
}

p_pool *p_pool_init(p_index blocks, size_t block_size)
{
    p_index partitions[1] = {blocks};
    return p_pool_partitioned_init(block_size, 1, partitions);
}

p_index p_pool_partitioned_alloc(p_pool *pool, p_index partition)
{
    if (pool->partitions[partition] == 0)
        return P_INVALID_INDEX;

    pool->partitions[partition]--;

    p_index free = pool->free_head;
    P_ASSERT(free != P_INVALID_INDEX);
    pool->free_head = INDEX_TO_VALUE(pool, free);
    return free;
}

p_index p_pool_alloc(p_pool *pool)
{
    return p_pool_partitioned_alloc(pool, 0);
}

void *p_pool_partitioned_alloc_address(p_pool *pool, p_index partition)
{
    return p_pool_index_to_address(pool, p_pool_partitioned_alloc(pool, partition));
}

void *p_pool_alloc_address(p_pool *pool)
{
    return p_pool_index_to_address(pool, p_pool_alloc(pool));
}

void p_pool_partitioned_free(p_pool *pool, p_index index, p_index partition)
{
    P_ASSERT(index < pool->blocks);
    pool->partitions[partition]++;
    INDEX_TO_VALUE(pool, index) = pool->free_head;
    pool->free_head = index;
}

void p_pool_free(p_pool *pool, p_index index)
{
    p_pool_partitioned_free(pool, index, 0);
}

void p_pool_partitioned_free_address(p_pool *pool, void *address, p_index partition)
{
    p_pool_partitioned_free(pool, p_pool_address_to_index(pool, address), partition);
}

void p_pool_free_address(p_pool *pool, void *address)
{
    p_pool_free(pool, p_pool_address_to_index(pool, address));
}

p_index p_pool_address_to_index(p_pool *pool, void *block)
{
    return (p_index) (((uintptr_t) block - (uintptr_t) pool->mem) / pool->block_size);
}

void *p_pool_index_to_address(p_pool *pool, p_index index)
{
    P_ASSERT(index != P_INVALID_INDEX);
    return (void*) (((uintptr_t) pool->mem) + (size_t) index * pool->block_size);
}

void p_pool_destroy(p_pool *pool) {
    p_free(pool->partitions);
    p_free(pool->mem);
    p_free(pool);
}
