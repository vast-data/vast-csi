/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/utils/extent.hpp"
#include "base_block.hpp"

namespace EStore {

class BitmapExtent : public P::Extent<uint32_t> {
public:
    // TODO optimize by keeping each content address only once in the block
    LAddress _content_addr;
} PACKED;
ASSERT_NO_VTABLE(BitmapExtent);

struct BitmapExtents {
    uint16_t n_extents;
    BitmapExtent extents[0];
} PACKED;

struct DataBitmapInfo {
    uint64_t base_offset;
    BitmapExtents extents;
} PACKED;

// the DataBitmapBlock store the addresses of the content blocks that contain relevant data for the extents it manages
class DataBitmapBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    void set_base_offset(uint64_t base_offset);
    EStoreRes WARN_UNUSED add_extent(uint64_t offset, uint32_t len, LAddress addr);
    EStoreRes WARN_UNUSED get_content_addrs(uint64_t offset, uint32_t len, uint16_t *n_addrs INOUT,
                                            LAddress *content_addrs OUT);
    void trace();
};

}


