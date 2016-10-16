#include <estore/defs/estore_defs.hpp>
#include "plasma/trace/emitter.hpp"
#include "plasma/utils/assert.hpp"
#include "ingest.hpp"
#include "container_element.hpp"
#include "data_element.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

// TODO add locking
// TODO handle read failures that require locks

namespace EStore {

using EStoreRes::OK;
using P::IO::IOVec;
using P::IO::IOVecs;
using P::ShardId;

#define OP_CALLBACK_RETURN(OP_CB, CB_CTX, ATTR) \
        if (OP_CB) { \
            EStoreRes res = OP_CB(ATTR, CB_CTX); \
            PT_RETURN(res != OK, res, "operation callback returned with error"); \
        }

void Ingest::init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table)
{
    _eio = eio;
    _shard_md = shard_md;
    _handles_table = handles_table;
    // we use rand to pick table buckets
    srand(time(0));
}

void Ingest::destroy()
{

}

EStoreRes Ingest::create_root()
{
    BuffersGuard buffers_guard(_eio, 2);
    Element new_element;
    new_element.init(_eio, _shard_md, _handles_table, &buffers_guard);
    return new_element.create_root();
}

EStoreRes Ingest::create(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, CreateFlags create_flags,
                         uint64_t verifier, SettableAttr *sattr, ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr,
                         EHandle *element_handle, SystemAttr *element_attr, SystemAttr *pre_pattr, SystemAttr *post_pattr)
{
    PT_INFO(DATA, "create parent=0x%lx name=%s", parent, name);
    // TODO reduce the number of required buffer by returning no longer used buffers to the guard
    BuffersGuard buffers_guard(_eio, 11);
    ContainerElement parent_element;
    parent_element.init(_eio, _shard_md, _handles_table, &buffers_guard);
    Element new_element;
    new_element.init(_eio, _shard_md, _handles_table, &buffers_guard);

    EStoreRes res = parent_element.read_handle_block(parent);
    PT_RETURN(res != OK, res, "read_handle_block failed parent=0x%lx", parent);
    // Verify the parent is allowed to have children
    if (!parent_element.is_container()) {
        PT_ERROR(DATA, "element 0x%lx is not allowed to have children", parent);
        return EStoreRes::NOT_A_CONTAINER;
    }
    parent_element.copy_attr(pre_pattr);
    OP_CALLBACK_RETURN(op_cb, cb_ctx, parent_element.get_attr());

    EHandle existing_handle;
    res = parent_element.read_name_blocks(name, &existing_handle);
    PT_RETURN(res != OK && res != EStoreRes::NOENT, res, "read_new_name_blocks failed parent=0x%lx name=%s", parent, name);
    if (res == OK) {
        PTC_INFO("element already exist parent=0x%lx name=%s existing_handle=0x%lx", parent, name, existing_handle);
        // TODO support overwrite
        // TODO name hash is present in the bitmap need to check if the name is on the content block and resolve hash collisions
        // TODO if name is present check if create flag allows overwrite
        // TODO check verifier if a verifier was given
        return EStoreRes::EXIST;
    }

    // allocate a new handle and append it to the write buffer
    LAddress content_addr;
    res = new_element.write_new_handle(name, sattr, create_flags, &content_addr, parent, element_handle, element_attr);
    PT_RETURN(res != OK, res, "write_new_handle failed name=%s content_addr=0x%lx", name, content_addr.as_number());

    parent_element.update_mc_times();
    res = parent_element.add_child(name, content_addr);
    PT_RETURN(res != OK, res, "add_child failed");

    parent_element.copy_attr(post_pattr);

    PT_INFO(DATA, "created handle=0x%lx name=%s under parent=0x%lx", *element_handle, name, parent);

    return OK;
}

EStoreRes Ingest::lookup(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool case_sensitive,
                         EHandle *handle, SystemAttr *element_attr, SystemAttr *parent_attr)
{
    DEBUG_ASSERT(case_sensitive == true); // TODO case insensitive lookup
    PT_INFO(DATA, "lookup parent=0x%lx name=%s", parent, name);
    BuffersGuard buffers_guard(_eio, 7);

    ContainerElement parent_element;
    parent_element.init(_eio, _shard_md, _handles_table, &buffers_guard);
    EStoreRes res = parent_element.read_handle_block(parent);
    PT_RETURN(res != OK, res, "read_handle_block failed handle=0x%lx", parent);

    // Verify the parent is allowed to have children
    if (!parent_element.is_container()) {
        PT_ERROR(DATA, "element 0x%lx is not allowed to have children", parent);
        return EStoreRes::NOT_A_CONTAINER;
    }
    parent_element.copy_attr(parent_attr);
    OP_CALLBACK_RETURN(op_cb, cb_ctx, parent_element.get_attr());

    // get ranges block
    res = parent_element.read_name_blocks(name, handle);
    PT_RETURN(res != OK, res, "read_name_blocks failed handle=0x%lx name=%s", parent, name);

    PT_INFO(DATA, "found handle=0x%lx for parent=0x%lx name=%s", *handle, parent, name);

    res = get_attr_internal(*handle, element_attr, &buffers_guard);
    PT_RETURN(res != OK, res, "get_attr_internal for handle=0x%lx failed", *handle);

    return OK;
}

EStoreRes Ingest::lookup_parent(OpCallback op_cb, void *cb_ctx, EHandle handle, EHandle *parent,
                                SystemAttr *element_attr, SystemAttr *parent_attr)
{
    BuffersGuard buffers_guard(_eio, 4);

    SystemAttr tmp_element_attr;
    EStoreRes res = get_attr_internal(handle, &tmp_element_attr, &buffers_guard);
    PT_RETURN(res != OK, res, "get_attr_internal failed handle=0x%lx", handle);

    OP_CALLBACK_RETURN(op_cb, cb_ctx, &tmp_element_attr);
    *parent = tmp_element_attr.parent;
    if (element_attr) {
        *element_attr = tmp_element_attr;
    }
    if (parent_attr) {
        res = get_attr_internal(*parent, parent_attr, &buffers_guard);
        PT_RETURN(res != OK, res, "get_attr_internal failed handle=0x%lx", *parent);
    }
    return OK;
}

EStoreRes Ingest::list_elements(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint64_t element_version,
                                ListCallback list_cb, void *list_ctx, const char *prefix, char delimiter,
                                uint64_t *current_element_version, SystemAttr *post_attr)
{
    PTC_INFO("handle=0x%lx offset=0x%lx element_version=%lu", handle, offset, element_version);
    BuffersGuard buffers_guard(_eio, 5);
    ContainerElement element;
    element.init(_eio, _shard_md, _handles_table, &buffers_guard);

    EStoreRes res = element.read_handle_block(handle);
    PT_RETURN(res != OK, res, "read_handle_block failed handle=0x%lx", handle);

    // Verify the parent is allowed to have children
    if (!element.is_container()) {
        PTC_ERROR("element 0x%lx is not allowed to have children", handle);
        return EStoreRes::NOT_A_CONTAINER;
    }
    OP_CALLBACK_RETURN(op_cb, cb_ctx, element.get_attr());

    res = element.list_elements(offset, element_version, list_cb, list_ctx, prefix, delimiter, current_element_version);
    PT_RETURN(res != OK, res, "list_elements failed handle=0x%lx", handle);

    element.copy_attr(post_attr);

    return OK;
}

EStoreRes Ingest::get_attr_internal(EHandle handle, SystemAttr *attr, BuffersGuard *buffers_guard)
{
    if (!attr) {
        return OK;
    }
    PTC_DEBUG("get attr for handle=0x%lx", handle);
    Element element;
    element.init(_eio, _shard_md, _handles_table, buffers_guard);
    EStoreRes res = element.read_handle_block(handle);
    PT_RETURN(res != OK, res, "read_handle_block failed handle=0x%lx", handle);
    *attr = *element.get_attr();

    return OK;
}

EStoreRes Ingest::write(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, IOVecs *io_vecs,
                        SystemAttr *pre_attr, SystemAttr *post_attr)
{
    DataBuffersGuard data_buff_guard(_eio, io_vecs);
    // TODO reduce num of buffers by supporting return_buffer in the guard
    BuffersGuard buffers_guard(_eio, 14);
    DataElement element;
    element.init(_eio, _shard_md, _handles_table, &buffers_guard);

    EStoreRes res = element.io_start(handle, offset);
    PT_RETURN(res != OK, res, "io_start for handle=0x%lx failed", handle);

    element.copy_attr(pre_attr);
    OP_CALLBACK_RETURN(op_cb, cb_ctx, element.get_attr());

    uint64_t data_len = io_vecs->total_length();
    if (data_len == 0) {
        element.copy_attr(post_attr);
        return OK;
    }
    if (data_len > MAX_IO_SIZE) {
        PTC_ERROR("Writes larger than 1MB are not supported len=%lu", data_len);
        return EStoreRes::INVAL;
    }

    res = element.write(handle, offset, io_vecs, data_len);
    PT_RETURN(res != OK, res, "write to handle=0x%lx failed", handle);

    element.copy_attr(post_attr);

    return OK;
}

EStoreRes Ingest::read(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint32_t len, IOVecs *res_vecs,
                       IOVecs *alloc_vecs, uint32_t *bytes_read, bool *eof, SystemAttr *pre_attr, SystemAttr *post_attr)
{
    // TODO make this method shorter
    PT_INFO(DATA, "read handle=0x%lx offset=%lu len=%u", handle, offset, len);
    if (len > MAX_IO_SIZE) {
        PT_ERROR(DATA, "reads larger than 1MB are not supported len=%u", len);
        return EStoreRes::INVAL;
    }

    BuffersGuard buffers_guard(_eio, 7);
    DataElement element;
    element.init(_eio, _shard_md, _handles_table, &buffers_guard);

    EStoreRes res = element.io_start(handle, offset);
    PT_RETURN(res != OK, res, "io_start for handle=0x%lx failed", handle);

    // TODO data might be split between multiple bitmap blocks
    // TODO locks
    element.copy_attr(pre_attr);
    OP_CALLBACK_RETURN(op_cb, cb_ctx, element.get_attr());

    alloc_vecs->count = 0;
    DataBuffersGuard data_guard(_eio, alloc_vecs);
    res = element.read(offset, len, res_vecs, alloc_vecs, bytes_read, eof);
    PT_RETURN(res != OK, res, "read failed handle=0x%lx offset=%lu len=%u", handle, offset, len);

    element.copy_attr(post_attr);
    // data buffers will be freed by the caller
    data_guard.disown();

    return OK;
}

EStoreRes Ingest::get_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SystemAttr *attr, ExtendedAttrs *user_xattr,
                           ExtendedAttrs *proto_xattr)
{
    BuffersGuard buffers_guard(_eio, 2);

    EStoreRes res = get_attr_internal(handle, attr, &buffers_guard);
    PT_RETURN(res != OK, res, "get_attr_internal failed handle=0x%lx", handle);

    OP_CALLBACK_RETURN(op_cb, cb_ctx, attr);

    return OK;
}

EStoreRes Ingest::set_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SettableAttr *sattr, uint64_t ctime_guard,
                 ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr, SystemAttr *pre_attr, SystemAttr *post_attr)
{
    BuffersGuard buffers_guard(_eio, 7);

    DataElement element;
    element.init(_eio, _shard_md, _handles_table, &buffers_guard);
    EStoreRes res = element.read_handle_block(handle);
    PT_RETURN(res != OK, res, "read_handle_block failed handle=0x%lx", handle);
    element.copy_attr(pre_attr);

    OP_CALLBACK_RETURN(op_cb, cb_ctx, element.get_attr());

    if (element.is_data() && sattr->flags & AttrFlag::SIZE) {
        res = element.truncate(sattr->size);
        PT_RETURN(res != OK, res, "truncate failed handle=0x%lx size=%lu", handle, sattr->size);
    }

    if (ctime_guard != 0 && element.get_attr()->ctime != ctime_guard) {
        PTC_WARN("ctime_guard=%lu differs from current ctime=%lu", ctime_guard, element.get_attr()->ctime);
        return EStoreRes::NOT_SYNC;
    }
    element.update_mc_times();
    element.set_attr(sattr);
    res = element.write_handle_block();
    PT_RETURN(res != OK, res, "write_handle_block failed handle=0x%lx", handle);

    element.copy_attr(post_attr);
    return OK;
}

void Ingest::alloc_data_buffers(IOVecs *iovecs)
{
    _eio->alloc_data_buffers(iovecs);
}

void Ingest::free_data_buffers(IOVecs *iovecs)
{
    _eio->free_data_buffers(iovecs);
}

}
