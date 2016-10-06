#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/utils/io.hpp"
#include "base_block.hpp"

namespace EStore {

struct Range {
    EAddress data_bitmap_addr;
    uint64_t _offset;
} PACKED;

struct Ranges {
    uint16_t n_ranges;
    Range ranges[];
} PACKED;

class DataRangeBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    EStoreRes WARN_UNUSED add_range(uint64_t offset, EAddress addr);
    // if len is passed it will be set to the part, the returned range applies to
    EAddress get_range(uint64_t offset, uint64_t *len = nullptr INOUT);
    void trace_ranges();

private:
    uint16_t find_range_index(uint64_t offset);
};

}



