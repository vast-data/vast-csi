/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/defs/estore_defs.hpp"
#include "base_block.hpp"

namespace EStore {

struct NameHandle {
    uint16_t len;
    EHandle handle;
    char name[];
} PACKED;

class NameContentBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    EStoreRes add_handle(const char *name, EHandle handle);
    EStoreRes get_handle(const char *name, EHandle *handle);

    typedef EStoreRes (*TraverseCallback)(const char *name, uint16_t name_len, uint32_t hash, EHandle handle, void *ctx);
    EStoreRes traverse(uint32_t start_hash, TraverseCallback cb, void *cb_ctx);


    void trace();
};

}
