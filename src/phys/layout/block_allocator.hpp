/* Copyright (C) Vast Data Ltd. */

/*!
 * \file block_allocator.hpp
 * \brief
 */
#pragma once

#include "estore/defs/estore_defs.hpp"
#include "phys/mirrored_io/mio.hpp"
#include "plasma/utils/io.hpp"
#include "section_allocator.hpp"

namespace MirroredIO {
    class MIO;
}

namespace Layout {

typedef uint32_t BlockAddr;

static const size_t NVRAM_ATOMIC_BLOCK_SIZE = Layout::MirroredAddress::ATOMIC_BLOCK_SIZE;
// BLOCKS_PER_PAGE depends on number of attributes in BlocksList
static const size_t BLOCKS_PER_PAGE = (NVRAM_ATOMIC_BLOCK_SIZE - EStore::MIO_OVERHEAD - 3*4)/sizeof(BlockAddr);

struct BlocksList {
    uint32_t count;
    uint32_t total_count;
    BlockAddr next;
    BlockAddr buffers[BLOCKS_PER_PAGE];
};
static_assert(sizeof(BlocksList) <= NVRAM_ATOMIC_BLOCK_SIZE - EStore::MIO_OVERHEAD, "");

class BlockAllocator {
public:
    void init(MirroredIO::MIO *mio, SectionAllocator *section_allocator);

    bool create(P::ShardId shard_id, LAddrType type);
    EStore::EStoreRes alloc(P::ShardId shard_id, LAddrType type, LAddress *eaddr OUT);
    bool free(const LAddress *eaddr);

private:
    inline EStore::EStoreRes alloc_from_extra_space(P::ShardId shard_id, LAddrType type, BlockAddr *next_block OUT);

    MirroredIO::MIO *_mio;
    SectionAllocator *_section_allocator;
    MirroredIO::MIO::Buffer _head_mio_buf;
    MirroredIO::MIO::Buffer _next_mio_buf;
    BlocksList *_head_data;
    BlocksList *_next_data;
};

}
