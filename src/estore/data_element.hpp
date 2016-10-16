/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/metadata/data_content_block.hpp"
#include "estore/metadata/data_bitmap_block.hpp"
#include "estore/metadata/data_range_block.hpp"
#include "element.hpp"

namespace EStore {

class DataElement : public Element {
public:
    void init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table, BuffersGuard *buffers_guard) override;

    EStoreRes WARN_UNUSED io_start(EHandle handle, uint64_t offset);
    EStoreRes WARN_UNUSED write(EHandle handle, uint64_t offset, P::IO::IOVecs *io_vecs, uint64_t data_len);
    EStoreRes WARN_UNUSED read(uint64_t offset, uint32_t len, P::IO::IOVecs *res_vecs INOUT,
                               P::IO::IOVecs *alloc_vecs OUT, uint32_t *bytes_read OUT, bool *eof OUT);
    EStoreRes WARN_UNUSED truncate(uint64_t size);

    // internal callback
    EStoreRes truncate_cb(Layout::Address addr, uint64_t offset, void *ctx);

private:
    EStoreRes add_data_bitmap_block(WriteBuffer *write_buffer, LAddress range_addr, LAddress *bitmap_addr,
                                    uint64_t offset, bool *range_updated);
    EStoreRes write_data(WriteBuffer *write_buffer, uint64_t data_len, uint64_t offset, P::IO::IOVecs *io_vecs,
                         LAddress bitmap_addr);
    uint32_t fill_hole(uint64_t prev_offset, uint64_t extent_offset, P::IO::IOVecs *res_vecs, P::IO::IOVecs *alloc_vecs,
                       uint32_t n_buffers, uint16_t *curr_buffer, uint32_t *buffer_offset);
    EStoreRes read_content_addrs(uint64_t offset, uint32_t len);
    EStoreRes read_extents(uint64_t offset, uint32_t len);

    EStoreRes read_data(uint64_t offset, uint32_t len, P::IO::IOVecs *res_vecs INOUT,
                        P::IO::IOVecs *alloc_vecs OUT, uint32_t *bytes_read OUT, bool *eof OUT);

    P::ShardId resolve_shard_id(EHandle handle, uint64_t offset) const;
    void update_element_size(uint64_t offset, uint64_t len);

private:
    DataRangeBlock _range_block;
    DataBitmapBlock _bitmap_block;
    DataContentBlock _content_block;

    static const uint64_t MAX_ADDR_PER_READ = 64;
    uint16_t _n_content_addrs;
    LAddress _content_addrs[MAX_ADDR_PER_READ];
    ExtentsContainer _extents_container;

};

}



