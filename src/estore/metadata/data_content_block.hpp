/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/data/ilist.hpp"
#include "plasma/utils/extent.hpp"
#include "base_block.hpp"

namespace EStore {

class ExtentsAggregator;

// TODO optimize by keeping relative offsets
// TODO optimize by keeping each handle only once in the block
class ContentExtent : public P::Extent<uint64_t> {
public:
    EHandle _handle;
    LAddress _data_addr;
} PACKED;
ASSERT_NO_VTABLE(ContentExtent);

struct ContentExtents {
    uint16_t n_extents;
    ContentExtent extents[0];
};

class DataContentBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;
    // add an extent to the end of the block
    EStoreRes WARN_UNUSED add_extent(EHandle handle, uint64_t offset, uint32_t len, LAddress data_addr);
    EStoreRes WARN_UNUSED alloc_extent(uint16_t *extent_index);
    EStoreRes WARN_UNUSED export_extents(EHandle handle, uint64_t offset, uint32_t len,
                                         ExtentsAggregator *aggregator);
    EStoreRes WARN_UNUSED export_all(ExtentsAggregator *aggregator);
    void set_extent(uint16_t extent_index, EHandle handle, uint64_t offset, uint32_t len, LAddress data_addr);
    void trace();
};

}
