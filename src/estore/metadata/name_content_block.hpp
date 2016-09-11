#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/defs/estore_defs.hpp"
#include "base_block.hpp"

namespace EStore {

struct NameHandle {
    EHandle handle;
    uint16_t len;
    char name[0];
} PACKED;

class NameContentBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    EStoreRes add_handle(const char *name, EHandle handle);
    EStoreRes get_handle(const char *name, EHandle *handle);
    void trace_handles();
};

}



