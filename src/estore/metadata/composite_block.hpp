/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "base_block.hpp"

namespace EStore {

struct ContainedBlock {
    uint16_t len;
    EHandle owner;
    BlockType type;
    MIOBuffer buffer;
} PACKED;

class CompositeBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    EStoreRes WARN_UNUSED add_contained_block(EHandle owner, const BaseBlock *block);
    EStoreRes WARN_UNUSED remove_contained_block(EHandle owner, BlockType type);
    EStoreRes WARN_UNUSED replace_contained_block(EHandle owner, const BaseBlock *block);
    EStoreRes WARN_UNUSED export_contained_block(EHandle owner, BlockType type, BaseBlock *block);
    void trace_contained_blocks(const char *msg);
};

}



