#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/utils/io.hpp"
#include "estore/defs/estore_defs.hpp"
#include "base_block.hpp"

namespace EStore {

struct NameHash {
    uint8_t len;
    LAddress content_addr;
    char hash[0];
} PACKED;

class NameBitmapBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    EStoreRes WARN_UNUSED add_name(const char *name, LAddress addr);
    EStoreRes WARN_UNUSED get_addr(const char *name, LAddress *addr);
    void trace_hashes();
};

}
