#include "estore.hpp"

namespace EStore {

using P::IO::IOVec;
using P::IO::IOVecs;

using EStoreRes::OK;

void EStore::init(P::SiloId silo_id, ModuleId module_id, FiberGroupId rpc_fiber_group_id)
{
    _eio.init(silo_id, module_id, rpc_fiber_group_id, nullptr);
    _shard_md.init(&_eio);
    _handles_table.init(&_eio, &_shard_md);
    _ingest.init(&_eio, &_shard_md, &_handles_table);
}

void EStore::destroy()
{
    _ingest.destroy();
    _shard_md.destroy();
    _handles_table.destroy();
    _eio.destroy();
}

void EStore::create_estore()
{
    _shard_md.create();
    _eio.create_block_allocator(LAddrType::MD_BLOCKS);
    EStoreRes res = _handles_table.create();
    ASSERT(res == OK);
    res = _ingest.create_root();
    ASSERT(res == OK);
}

void EStore::load()
{
    _shard_md.load();
    _handles_table.load();
}

void EStore::alloc_data_buffers(IOVecs *iovecs)
{
    _ingest.alloc_data_buffers(iovecs);
}

void EStore::free_data_buffers(IOVecs *iovecs)
{
    _ingest.free_data_buffers(iovecs);
}

EStoreRes EStore::get_root_handle(EHandle *handle)
{
    *handle = ROOT_HANDLE;
    return OK;
}

EStoreRes EStore::get_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SystemAttr *attr,
                           ExtendedAttrs *user_xattr OUT, ExtendedAttrs *proto_xattr OUT)
{
    return _ingest.get_attr(op_cb, cb_ctx, handle, attr, user_xattr, proto_xattr);
}

EStoreRes EStore::set_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SettableAttr *sattr, uint64_t ctime_guard,
                           ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr, SystemAttr *pre_attr,
                           SystemAttr *post_attr)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::lookup(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool case_sensitive,
                         EHandle *element, SystemAttr *element_attr, SystemAttr *parent_attr)
{
    return _ingest.lookup(op_cb, cb_ctx, parent, name, case_sensitive, element, element_attr, parent_attr);
}

EStoreRes EStore::lookup_parent(OpCallback op_cb, void *cb_ctx, EHandle handle, EHandle *parent,
                                SystemAttr *element_attr, SystemAttr *parent_attr)

{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::create(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, CreateFlags flags,
                         uint64_t verifier, SettableAttr *sattr, ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr,
                         EHandle *element_handle, SystemAttr *element_attr, SystemAttr *pre_pattr,
                         SystemAttr *post_pattr)
{
    return _ingest.create(op_cb, cb_ctx, parent, name, flags, verifier, sattr, user_xattr, proto_xattr,
                          element_handle, element_attr, pre_pattr, post_pattr);
}

EStoreRes EStore::write(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, P::IO::IOVecs *io_vecs,
                        SystemAttr *pre_attr, SystemAttr *post_attr)
{
    return _ingest.write(op_cb, cb_ctx, handle, offset, io_vecs, pre_attr, post_attr);
}


EStoreRes EStore::read(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint64_t len, IOVecs *io_vecs,
                       P::IO::IOVecs *alloc_vecs, uint32_t *bytes_read, bool *eof, SystemAttr *pre_attr,
                       SystemAttr *post_attr)
{
    return _ingest.read(op_cb, cb_ctx, handle, offset, len, io_vecs, alloc_vecs, bytes_read, eof, pre_attr, post_attr);
}

EStoreRes EStore::list_elements(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset,
                                uint64_t element_version, ListCallback rd_cb, void *rd_ctx, const char *prefix,
                                char delimiter, uint64_t *current_element_version, SystemAttr *post_attr)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::link(OpCallback op_cb, void *cb_ctx, EHandle link_target, EHandle parent, const char *name,
                       SystemAttr *post_link_attr, SystemAttr *pre_pattr, SystemAttr *post_pattr)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::unlink(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool verify_no_children,
                         SystemAttr *pre_pattr, SystemAttr *post_pattr)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::rename(OpCallback op_cb, void *cb_ctx, EHandle src_handle, const char *src_name, EHandle dst_handle,
                         const char *dst_name, SystemAttr *pre_src_attr, SystemAttr *post_src_attr,
                         SystemAttr *pre_dst_attr, SystemAttr *post_dst_attr)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::get_stats(OpCallback op_cb, void *cb_ctx, EHandle handle, EStoreStats *stats, SystemAttr *attr)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::lock(OpCallback op_cb, void *cb_ctx, EHandle handle, bool block, LockInfo *lock)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::unlock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes EStore::test_lock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock, LockInfo *existing_lock OUT)
{
    PANIC("not implemented");
    return OK;
}

}
