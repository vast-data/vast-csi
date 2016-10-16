/* Copyright (C) Vast Data Ltd. */

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
                                 EHandle *handle OUT, SystemAttr *element_attr OUT, SystemAttr *parent_attr OUT);
    EStoreRes WARN_UNUSED lookup_parent(OpCallback op_cb, void *cb_ctx, EHandle handle, EHandle *parent OUT,
                                        SystemAttr *element_attr OUT, SystemAttr *parent_attr OUT);
    EStoreRes WARN_UNUSED list_elements(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset,
                                        uint64_t element_version, ListCallback list_cb, void *list_ctx, const char *prefix,
                                        char delimiter, uint64_t *current_element_version, SystemAttr *post_attr OUT);


    EStoreRes WARN_UNUSED write(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, P::IO::IOVecs *io_vecs,
                                SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);
    EStoreRes WARN_UNUSED read(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint32_t len,
                               P::IO::IOVecs *res_vecs INOUT, P::IO::IOVecs *alloc_vecs OUT, uint32_t *bytes_read OUT,
                               bool *eof OUT, SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);

    EStoreRes WARN_UNUSED get_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SystemAttr *attr OUT,
                                   ExtendedAttrs *user_xattr OUT, ExtendedAttrs *proto_xattr OUT);
    EStoreRes WARN_UNUSED set_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SettableAttr *sattr, uint64_t ctime_guard,
                                   ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr,
                                   SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);


private:
    EStoreRes WARN_UNUSED get_attr_internal(EHandle handle, SystemAttr *attr, BuffersGuard *buffers_guard);


private:
    EStoreIO *_eio;
    ShardMd *_shard_md;
    HandlesTable *_handles_table;
};

}
