#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/defs/estore_defs.hpp"
#include "base_block.hpp"

namespace EStore {

struct NameRange {
    uint16_t len;
    LAddress bitmap_addr;
    char name[0];
} PACKED;

class NameRangeBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    EStoreRes WARN_UNUSED add_range(const char *name, LAddress addr);
    // get the address relevant to the given name
    LAddress get_address(const char *name);
    bool has_ranges();

    void trace();

private:
    NameRange *find_range(const char *name);
};

}

