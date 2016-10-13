/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/defs/estore_defs.hpp"
#include "estore/io/buffers_guard.hpp"
#include "estore/metadata/composite_block.hpp"
#include "estore/metadata/handles_table.hpp"
#include "estore/metadata/handle_block.hpp"

namespace EStore {

class Element {
public:
    virtual void init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table, BuffersGuard *buffers_guard);

    EStoreRes WARN_UNUSED create_root();
    EStoreRes WARN_UNUSED read_block(LAddress addr, EHandle owner, BaseBlock *block);
    EStoreRes WARN_UNUSED read_handle_block(EHandle handle);
    EStoreRes WARN_UNUSED write_new_handle(const char *name, SettableAttr *sattr, CreateFlags create_flags,
                                           LAddress *content_addr, EHandle parent_handle, EHandle *new_handle,
                                           SystemAttr *element_attr);

    void update_mc_times();
    bool is_container() { return _handle_block.is_container_element(); }
    void copy_attr(SystemAttr *attr);
    SystemAttr *get_attr() { return _handle_block.get_attr(); }
    EHandle get_handle() { return _handle_block.get_handle(); }


private:
    void set_default_attr(SystemAttr *attr, EHandle parent, EHandle handle, bool is_container);
    void set_handle_attr(SettableAttr *sattr, SystemAttr *handle_attr);

protected:
    CompositeBlock _composite_block;
    HandleBlock _handle_block;

    EStoreIO *_eio;
    ShardMd *_shard_md;
    HandlesTable *_handles_table;
    BuffersGuard *_buffers_guard;
};

}

