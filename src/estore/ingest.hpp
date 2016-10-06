#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/utils/compiler.hpp"
#include "phys/layout/address.hpp"
#include "estore/io/estore_io.hpp"
#include "estore/metadata/shard_md.hpp"
#include "estore/metadata/handles_table.hpp"
#include "estore/metadata/handle_block.hpp"
#include "estore/metadata/composite_block.hpp"
#include "estore/metadata/name_range_block.hpp"
#include "estore/metadata/data_range_block.hpp"
#include "estore/metadata/name_bitmap_block.hpp"
#include "estore/metadata/data_bitmap_block.hpp"

namespace EStore {

class Ingest {
public:
    void init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table);
    void destroy();

    void alloc_data_buffers(P::IO::IOVecs *iovecs INOUT);
    void free_data_buffers(P::IO::IOVecs *iovecs);

    EStoreRes create_root();

    EStoreRes WARN_UNUSED create(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, CreateFlags create_flags,
                                 uint64_t verifier, SettableAttr *sattr, ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr,
                                 EHandle *element_handle OUT, SystemAttr *element_attr OUT,
                                 SystemAttr *pre_pattr OUT, SystemAttr *post_pattr OUT);

    EStoreRes WARN_UNUSED lookup(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool case_sensitive,
                                 EHandle *element OUT, SystemAttr *element_attr OUT, SystemAttr *parent_attr OUT);
    EStoreRes WARN_UNUSED list_elements(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset,
                                        uint64_t element_version, ListCallback rd_cb, void *rd_ctx, const char *prefix,
                                        char delimiter, uint64_t *current_element_version, SystemAttr *post_attr OUT);


    EStoreRes WARN_UNUSED write(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, P::IO::IOVecs *io_vecs,
                                SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);
    EStoreRes WARN_UNUSED read(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint32_t len,
                               P::IO::IOVecs *res_vecs INOUT, P::IO::IOVecs *alloc_vecs OUT, uint32_t *bytes_read OUT,
                               bool *eof OUT, SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);

    EStoreRes WARN_UNUSED get_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SystemAttr *attr OUT,
                                   ExtendedAttrs *user_xattr OUT, ExtendedAttrs *proto_xattr OUT);

private:
    EStoreRes WARN_UNUSED read_block(CompositeBlock *composite_block, LAddress addr, EHandle owner, BaseBlock *block);
    EStoreRes WARN_UNUSED write_new_handle(BuffersGuard *buffers_guard, const char *name, SettableAttr *sattr,
                                           CreateFlags create_flags, LAddress *content_addr, EHandle *new_handle,
                                           SystemAttr *element_attr);
    EStoreRes WARN_UNUSED update_parent(BuffersGuard *buffers_guard, LAddress range_addr, NameRangeBlock *range_block,
                                        bool range_updated, NameBitmapBlock *bitmap_block, EHandle parent,
                                        CompositeBlock *parent_composite_block, const char *name, LAddress content_addr);
    EStoreRes WARN_UNUSED get_attr_internal(EHandle handle, SystemAttr *attr, BuffersGuard *buffers_guard);
    EStoreRes WARN_UNUSED read_handle_block(EHandle handle, CompositeBlock *composite_block, HandleBlock *handle_block,
                                            BuffersGuard *buffers_guard);
    EStoreRes WARN_UNUSED read_parent_blocks(EHandle parent, const char *name, BuffersGuard *buffers_guard,
                                             CompositeBlock *composite_block, HandleBlock *handle_block,
                                             NameRangeBlock *range_block, NameBitmapBlock *bitmap_block,
                                             bool *range_updated);
    EStoreRes WARN_UNUSED io_start(EHandle handle, uint64_t offset, BuffersGuard *buffers_guard, CompositeBlock *composite_block,
                                   HandleBlock *handle_block, DataRangeBlock *range_block, DataBitmapBlock *bitmap_block);

    void set_default_attr(SystemAttr *attr, EHandle handle, bool is_container);
    void set_handle_attr(SettableAttr *sattr, SystemAttr *handle_attr);
    void update_mc_times(HandleBlock *handle_block);
    void copy_attr(HandleBlock *handle_block, SystemAttr *attr);
    uint32_t alloc_read_buffers(uint32_t len, P::IO::IOVecs *io_vecs);
    P::ShardId resolve_shard_id(EHandle handle, uint64_t offset) const;
    uint32_t fill_hole(uint64_t prev_offset, uint64_t extent_offset, P::IO::IOVecs *res_vecs, P::IO::IOVecs *alloc_vecs,
                       uint32_t n_buffers, uint16_t *curr_buffer, uint32_t *buffer_offset);

private:
    EStoreIO *_eio;
    ShardMd *_shard_md;
    HandlesTable *_handles_table;

};

}
