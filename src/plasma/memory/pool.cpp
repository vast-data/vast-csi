/* Copyright (C) Vast Data Ltd. */
#include "pool.hpp"

#include "plasma/utils.h"
#include "plasma/utils/assert.hpp"
#include "plasma/memory/p_alloc.h"

#define INDEX_TO_VALUE(index) (*((PIndex*) index_to_address(index)))

namespace P {

void Pool::partitioned_init(size_t block_size, PIndex num_partitions, PIndex partitions[])
{
    // validate block_size is larger than the index it will contain.
    ASSERT(block_size >= sizeof(PIndex), "invalid block size");

    _partitions = (PIndex *) p_safe_malloc((size_t) num_partitions * sizeof(PIndex));
    _block_size = block_size;
    _blocks = 0;
    LOOP((size_t) num_partitions, i) {
        _partitions[i] = partitions[i];
        _blocks += partitions[i];
    }

    size_t mem_size = (size_t) _blocks * block_size;
    // allocate a cache aligned buffer and expand it to the nearest cache line (required by aligned_alloc)
    _mem = p_safe_cache_aligned_malloc(mem_size + mem_size % P_CACHE_LINE_BYTES);
    _free_head = 0;
    _num_partitions = num_partitions;

    // every free node contains the index of the next free node.
    // the end of the list is marked with index == P_INVALID_INDEX.
    for (PIndex i = 0; i < _blocks - 1; i++) {
        INDEX_TO_VALUE(i) = i + 1;
    }
    INDEX_TO_VALUE(_blocks - 1) = P_INVALID_INDEX;
}

void Pool::init(PIndex blocks, size_t block_size)
{
    PIndex partitions[1] = {blocks};
    return partitioned_init(block_size, 1, partitions);
}

PIndex Pool::partitioned_alloc(PIndex partition)
{
    ASSERT(partition < _num_partitions, "invalid partition");
    if (_partitions[partition] == 0)
        return P_INVALID_INDEX;

    _partitions[partition]--;

    PIndex free = _free_head;
    ASSERT(free != P_INVALID_INDEX, "free list should have an avaliable block");
    _free_head = INDEX_TO_VALUE(free);
    return free;
}

PIndex Pool::alloc()
{
    return partitioned_alloc(0);
}

void *Pool::partitioned_alloc_address(PIndex partition)
{
    return index_to_address(partitioned_alloc(partition));
}

void *Pool::alloc_address()
{
    PIndex index = alloc();
    if (index == P_INVALID_INDEX) {
        return NULL;
    }

    return index_to_address(index);
}

void Pool::partitioned_free(PIndex index, PIndex partition)
{
    ASSERT(partition < _num_partitions, "invalid partition");
    ASSERT(index < _blocks, "invalid index");
    _partitions[partition]++;
    INDEX_TO_VALUE(index) = _free_head;
    _free_head = index;
}

void Pool::free(PIndex index)
{
    partitioned_free(index, 0);
}

void Pool::partitioned_free_address(void *address, PIndex partition)
{
    partitioned_free(address_to_index(address), partition);
}

void Pool::free_address(void *address)
{
    free(address_to_index(address));
}

PIndex Pool::address_to_index(void *block)
{
    return (PIndex) (((uintptr_t) block - (uintptr_t) _mem) / _block_size);
}

void *Pool::index_to_address(PIndex index)
{
    ASSERT(index != P_INVALID_INDEX, "invalid index");
    return (void *) (((uintptr_t) _mem) + (size_t) index * _block_size);
}

PIndex Pool::get_initial_n_blocks()
{
    return _blocks;
}

void Pool::destroy()
{
    p_free(_partitions);
    p_free(_mem);
}

}