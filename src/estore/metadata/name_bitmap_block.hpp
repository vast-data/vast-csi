/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/utils/io.hpp"
#include "estore/defs/estore_defs.hpp"
#include "base_block.hpp"

namespace EStore {

struct NameHash {
    uint8_t len;
    char hash[0];
} PACKED;

struct ContentHashes {
    uint16_t len;
    LAddress content_addr;
    NameHash hashes[0];
} PACKED;

class NameBitmapBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    EStoreRes WARN_UNUSED add_name(const char *name, LAddress addr);
    EStoreRes WARN_UNUSED get_addr(const char *name, LAddress *addr);

    // TODO support variable size hashes
    typedef EStoreRes (*TraverseCallback)(Layout::Address addr, void *ctx);
    // traverse the content blocks refereed by this bitmap, callback will be called ONCE per content block
    EStoreRes traverse(uint32_t start_hash, TraverseCallback cb, void *cb_ctx);
    // TODO move somewhere generic
    static uint32_t name_hash(const char *name);

    void trace();
};

}
