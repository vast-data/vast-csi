/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/utils/io.hpp"
#include "base_block.hpp"

namespace EStore {

struct Range {
    LAddress data_bitmap_addr;
    uint64_t offset;
} PACKED;

struct Ranges {
    uint16_t n_ranges;
    Range ranges[];
} PACKED;

class DataRangeBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    EStoreRes WARN_UNUSED add_range(uint64_t offset, LAddress addr);
    // if len is passed it will be set to the part, the returned range applies to
    LAddress get_range(uint64_t offset, uint64_t *len = nullptr INOUT);

    typedef EStoreRes (*TraverseCallback)(Layout::Address addr, uint64_t offset, void *ctx);
    EStoreRes traverse(uint64_t start_offset, TraverseCallback cb, void *cb_ctx);

    void trace();

private:
    uint16_t find_range_index(uint64_t offset);
    void set_output_len(uint16_t found_index, uint64_t offset, uint64_t *len);
};

}
