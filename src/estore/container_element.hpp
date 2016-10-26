/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "element.hpp"
#include "estore/metadata/name_range_block.hpp"
#include "estore/metadata/name_bitmap_block.hpp"
#include "estore/metadata/name_content_block.hpp"

namespace EStore {

class ContainerElement : public Element {
public:
    void init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table, BuffersGuard *buffers_guard) override;

    EStoreRes WARN_UNUSED read_name_blocks(const char *name, EHandle *handle);
    EStoreRes WARN_UNUSED add_child(const char *name, LAddress content_addr);

    EStoreRes WARN_UNUSED list_elements(uint64_t offset, uint64_t element_version, ListCallback list_cb, void *list_ctx,
                                        const char *prefix, char delimiter, uint64_t *current_element_version);

    // internal callbacks
    EStoreRes name_range_traverse(Layout::LAddress addr, uint16_t idx, void *ctx);
    EStoreRes name_bitmap_traverse(Layout::LAddress addr, void *ctx);

private:
    NameRangeBlock _range_block;
    NameBitmapBlock _bitmap_block;
    NameContentBlock _content_block;
};

}

