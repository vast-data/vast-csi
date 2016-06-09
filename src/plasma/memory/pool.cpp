/* Copyright (C) Vast Data Ltd. */
#include "pool.hpp"

#include "plasma/utils/assert.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/memory/alloc.hpp"

#define INDEX_TO_VALUE(index) (*((Index*) index_to_address(index)))

namespace P {

void Pool::partitioned_init(size_t block_size, Index num_partitions, Index partitions[])
{
    // validate block_size is larger than the index it will contain.
    ASSERT_OP(block_size, >=, sizeof(Index), "invalid block size");

    _partitions = (Index *) p_safe_malloc((size_t) num_partitions * sizeof(Index));
    _block_size = block_size;
    _blocks = 0;
    LOOP((size_t) num_partitions, i) {
        _partitions[i] = partitions[i];
        _blocks += partitions[i];
    }

    size_t mem_size = (size_t) _blocks * block_size;
    // allocate a cache aligned buffer and expand it to the nearest cache line (required by aligned_alloc)
    _mem = p_safe_cache_aligned_malloc(mem_size + mem_size % CACHE_LINE_BYTES);
    _free_head = 0;
    _num_partitions = num_partitions;

    // every free node contains the index of the next free node.
    // the end of the list is marked with index == INVALID_INDEX.
    for (Index i = 0; i < _blocks - 1; i++) {
        INDEX_TO_VALUE(i) = i + 1;
    }
    INDEX_TO_VALUE(_blocks - 1) = INVALID_INDEX;
}

void Pool::init(Index blocks, size_t block_size)
{
    Index partitions[1] = {blocks};
    return partitioned_init(block_size, 1, partitions);
}

Index Pool::partitioned_alloc(Index partition)
{
    ASSERT_OP(partition, <, _num_partitions, "invalid partition");
    if (_partitions[partition] == 0)
        return INVALID_INDEX;

    _partitions[partition]--;

    Index free = _free_head;
    ASSERT_OP(free, !=, INVALID_INDEX, "free list should have an avaliable block");
    _free_head = INDEX_TO_VALUE(free);
    return free;
}

Index Pool::alloc()
{
    return partitioned_alloc(0);
}

void *Pool::partitioned_alloc_address(Index partition)
{
    return index_to_address(partitioned_alloc(partition));
}

void *Pool::alloc_address()
{
    Index index = alloc();
    if (index == INVALID_INDEX) {
        return NULL;
    }

    return index_to_address(index);
}

void Pool::partitioned_free(Index index, Index partition)
{
    ASSERT_OP(partition, <, _num_partitions, "invalid partition");
    ASSERT_OP(index, <, _blocks, "invalid index");
    _partitions[partition]++;
    INDEX_TO_VALUE(index) = _free_head;
    _free_head = index;
}

void Pool::free(Index index)
{
    partitioned_free(index, 0);
}

void Pool::partitioned_free_address(void *address, Index partition)
{
    partitioned_free(address_to_index(address), partition);
}

void Pool::free_address(void *address)
{
    free(address_to_index(address));
}

Index Pool::address_to_index(void *block)
{
    return (Index) (((uintptr_t) block - (uintptr_t) _mem) / _block_size);
}

void *Pool::index_to_address(Index index)
{
    ASSERT_OP(index, !=, INVALID_INDEX, "invalid index");
    return (void *) (((uintptr_t) _mem) + (size_t) index * _block_size);
}

Index Pool::get_initial_n_blocks()
{
    return _blocks;
}

void Pool::destroy()
{
    p_free(_partitions);
    p_free(_mem);
}

}
