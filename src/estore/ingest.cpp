#include <estore/metadata/data_bitmap_block.hpp>
#include <estore/metadata/data_range_block.hpp>
#include <estore/metadata/data_content_block.hpp>
#include "plasma/trace/emitter.hpp"
#include "estore/metadata/composite_block.hpp"
#include "estore/metadata/handle_block.hpp"
#include "estore/metadata/name_range_block.hpp"
#include "plasma/utils/assert.hpp"
#include "estore/metadata/name_bitmap_block.hpp"
#include "estore/metadata/name_content_block.hpp"
#include "ingest.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE

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

    CompositeBlock composite_block;
    composite_block.init(buffers_guard.get_next());
    EStoreRes res = _handles_table->read(ROOT_HANDLE, composite_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to read root handle");

    HandleBlock handle_block;
    // we are not supposed to find root
    res = composite_block.export_contained_block(ROOT_HANDLE, BlockType::HANDLE_BLOCK, &handle_block);
    PT_RETURN(res == OK, EStoreRes::EXIST, "root already exist");

    handle_block.init(buffers_guard.get_next());
    handle_block.set_handle(ROOT_HANDLE);
    handle_block.set_ranges_addr(EMPTY_EADDRESS);
    SystemAttr *attr = handle_block.get_attr();
    set_default_attr(attr, ROOT_HANDLE, true);
    attr->element_flags = (uint64_t)ElementFlags::DIR;

    res = composite_block.add_contained_block(ROOT_HANDLE, &handle_block);
    PT_RETURN(res != OK, res, "add_contained_block failed");

    res = _handles_table->write(ROOT_HANDLE, composite_block.get_buffer());
    PT_RETURN(res != OK, res, "_handles_table->write failed");

    return OK;
}

void Ingest::set_default_attr(SystemAttr *attr, EHandle handle, bool is_container)
{
    memset(attr, 0, sizeof(*attr));
    attr->mode = 0777;
    attr->nlink = 1;
    attr->uid = 0;
    attr->gid = 0;
    attr->used = 0;
    attr->fileid = handle;
    attr->atime = P::get_time_nano();
    attr->mtime = attr->atime;
    attr->ctime = attr->atime;
    attr->create_verifier = 0;
    attr->expires = 0;
    attr->element_version = 0;
    attr->element_flags = 0;
    if (is_container) {
        attr->internal_flags = (uint64_t)InternalFlags::CONTAINER;
        attr->size = NVRAM_MD_BLOCK_SIZE;
    } else {
        attr->internal_flags = (uint64_t)InternalFlags::DATA;
        attr->size = 0;
    }
    // attr->byte md5_hash[16]; is left zero
}

EStoreRes Ingest::read_block(CompositeBlock *composite_block, EAddress addr, EHandle owner, BaseBlock *block)
{
    PT_DEBUG(DATA, "addr=0x%lx owner handle=0x%lx type=%hhu", addr.as_number(), owner, (uint8_t)block->get_type());
    if (addr.addr_type == EAddrType::NONE) {
        return OK;
    } else if (addr.addr_type == EAddrType::CONTAINED) {
        EStoreRes res = composite_block->export_contained_block(owner, block->get_type(), block);
        PT_RETURN(res != OK, res, "export_contained_block failed owner=0x%lx", owner);
    } else {
        EStoreRes res = _eio->read_md(addr, block->get_buffer(), false, nullptr);
        PT_RETURN(res != OK, res, "failed to read from addr=0x%lx", addr.as_number());
    }
    return OK;
}

EStoreRes Ingest::create(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, CreateFlags create_flags,
                         uint64_t verifier, SettableAttr *sattr, ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr,
                         EHandle *element_handle, SystemAttr *element_attr, SystemAttr *pre_pattr, SystemAttr *post_pattr)
{
    PT_INFO(DATA, "create parent=0x%lx name=%s", parent, name);
    // TODO reduce the number of required buffer by returning no longer used buffers to the guard
    BuffersGuard buffers_guard(_eio, 8);

    CompositeBlock parent_composite_block;
    HandleBlock parent_handle_block;
    NameRangeBlock range_block;
    NameBitmapBlock bitmap_block;

    bool range_updated;
    EStoreRes res = read_parent_blocks(parent, name, &buffers_guard, &parent_composite_block, &parent_handle_block,
                                       &range_block, &bitmap_block, &range_updated);
    PT_RETURN(res != OK, res, "read_parent_blocks failed parent=0x%lx", parent);

    copy_attr(&parent_handle_block, pre_pattr);
    OP_CALLBACK_RETURN(op_cb, cb_ctx, parent_handle_block.get_attr());

    // allocate a new handle and append it to the write buffer
    EAddress content_addr;
    res = write_new_handle(&buffers_guard, name, sattr, create_flags, &content_addr, element_handle, element_attr);
    PT_RETURN(res != OK, res, "write_new_handle failed name=%s content_addr=0x%lx", name, content_addr.as_number());

    update_mc_times(&parent_handle_block);
    EAddress range_addr = parent_handle_block.get_ranges_addr();
    res = update_parent(&buffers_guard, range_addr, &range_block, range_updated, &bitmap_block, parent,
                        &parent_composite_block, name, content_addr);
    PT_RETURN(res != OK, res, "update_parent failed");

    // TODO trigger bitmap split if about to run out of space

    copy_attr(&parent_handle_block, post_pattr);

    PT_INFO(DATA, "created handle=0x%lx name=%s under parent=0x%lx", *element_handle, name, parent);

    return OK;
}

EStoreRes Ingest::lookup(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool case_sensitive,
                         EHandle *element, SystemAttr *element_attr, SystemAttr *parent_attr)
{
    PT_INFO(DATA, "lookup parent=0x%lx name=%s", parent, name);
    BuffersGuard buffers_guard(_eio, 5);

    CompositeBlock parent_composite_block;
    HandleBlock parent_handle_block;
    EStoreRes res = read_handle_block(parent, &parent_composite_block, &parent_handle_block, &buffers_guard);
    PT_RETURN(res != OK, res, "read_handle_block failed handle=0x%lx", parent);
    
    // Verify the parent is allowed to have children
    if (!parent_handle_block.is_container_element()) {
        PT_ERROR(DATA, "element 0x%lx is not allowed to have children", parent);
        return EStoreRes::NOT_A_CONTAINER;
    }
    copy_attr(&parent_handle_block, parent_attr);
    OP_CALLBACK_RETURN(op_cb, cb_ctx, parent_handle_block.get_attr());

    // get ranges block
    NameRangeBlock range_block;
    range_block.init(buffers_guard.get_next());
    EAddress range_addr = parent_handle_block.get_ranges_addr();
    res = read_block(&parent_composite_block, range_addr, parent, &range_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", range_addr.as_number());

    if (range_addr.addr_type == EAddrType::NONE) {
        // if the ranges block does not exist
        PT_INFO(DATA, "handle=0x%lx does not have a range block", parent);
        return EStoreRes::NOENT;
    }

    // get bitmap block
    NameBitmapBlock bitmap_block;
    bitmap_block.init(buffers_guard.get_next());
    EAddress bitmap_addr = range_block.get_address(name);
    res = read_block(&parent_composite_block, bitmap_addr, parent, &bitmap_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", bitmap_addr.as_number());

    if (bitmap_addr.addr_type == EAddrType::NONE) {
        PT_INFO(DATA, "failed to get bitmap block handle=0x%lx", parent);
        return EStoreRes::NOENT;
    }

    // get content block addr
    EAddress content_addr;
    res = bitmap_block.get_addr(name, &content_addr);
    if (res == EStoreRes::NOENT) {
        PT_INFO(DATA, "element not found handle=0x%lx name=%s", parent, name);
        return EStoreRes::NOENT;
    }
    PT_RETURN(res != OK, res, "failed to get content block addr name=%s", name);

    // read content block
    NameContentBlock content_block;
    content_block.init(buffers_guard.get_next());
    res = read_block(&parent_composite_block, content_addr, parent, &content_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", content_addr.as_number());

    res = content_block.get_handle(name, element);
    PT_RETURN(res != OK, res, "get_handle failed name=%s", name);

    PT_INFO(DATA, "found handle=0x%lx for parent=0x%lx name=%s", *element, parent, name);

    res = get_attr_internal(*element, element_attr, &buffers_guard);
    PT_RETURN(res != OK, res, "get_attr_internal for handle=0x%lx failed", *element);

    return OK;
}

EStoreRes Ingest::list_elements(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint64_t element_version,
                                ListCallback rd_cb, void *rd_ctx, const char *prefix, char delimiter,
                                uint64_t *current_element_version, SystemAttr *post_attr)
{

    return OK;
}

EStoreRes Ingest::write_new_handle(BuffersGuard *buffers_guard, const char *name, SettableAttr *sattr,
                                   CreateFlags create_flags, EAddress *content_addr, EHandle *new_handle,
                                   SystemAttr *element_attr)
{
    // TODO lock handle bucket
    CompositeBlock handle_composite_block;
    handle_composite_block.init(buffers_guard->get_next());
    // TODO is rand() good enough?
    VirtualBucketId virt_bucket = rand() % N_VIRTUAL_BUCKETS;
    EStoreRes res = _handles_table->read_by_virt_bucket(virt_bucket, handle_composite_block.get_buffer());
    PT_RETURN(res != OK, res, "read_by_virt_bucket failed virt_id=%lu", virt_bucket);
    // find a free handle id within the bucket
    ASSERT(handle_composite_block.get_type() == BlockType::COMPOSITE_BLOCK);
    // TODO find free handle index
    *new_handle = _handles_table->build_handle(1, virt_bucket);
    // TODO in case the bucket has too many handles retry

    ShardId shard_id = HandlesTable::handle_to_shard_id(*new_handle);
    // name does not exist, add it to the content block on the write buffer
    WriteBuffer *write_buffer = _shard_md->get_ingest_buffer(shard_id);
    ASSERT_NOT_NULL(write_buffer);
    // TODO back pointer
    // TODO deal with invalid_state ret val
    res = write_buffer->append_name_content(buffers_guard, name, *new_handle, content_addr);
    PT_RETURN(res != OK, res, "failed to append name content");

    // write handle block to the handles table
    HandleBlock new_handle_block;
    new_handle_block.init(buffers_guard->get_next());
    new_handle_block.set_handle(*new_handle);
    new_handle_block.set_ranges_addr(EMPTY_EADDRESS);
    set_default_attr(new_handle_block.get_attr(), *new_handle, create_flags & CreateFlags::HAS_CHILDREN);
    set_handle_attr(sattr, new_handle_block.get_attr());

    res = handle_composite_block.add_contained_block(*new_handle, &new_handle_block);
    // TODO deal with no space
    PT_RETURN(res != OK, res, "add_contained_block failed");

    res = _handles_table->write(*new_handle, handle_composite_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write new handle bucket");

    if (element_attr) {
        *element_attr = *new_handle_block.get_attr();
    }

    return OK;
}

EStoreRes Ingest::update_parent(BuffersGuard *buffers_guard, EAddress range_addr, NameRangeBlock *range_block,
                                bool range_updated, NameBitmapBlock *bitmap_block, EHandle parent,
                                CompositeBlock *parent_composite_block, const char *name, EAddress content_addr)
{
    EAddress bitmap_addr = range_block->get_address(name);
    if (bitmap_addr.addr_type == EAddrType::CONTAINED) {
        // bitmap block is contained within a composite block, replace its buffer so it will have space to contain new
        // names
        bitmap_block->replace_buffer(buffers_guard->get_next());
    }

    // add the address of the content block to the bitmap
    EStoreRes res = bitmap_block->add_name(name, content_addr);
    PT_RETURN(res != OK && res != EStoreRes::NO_MEM, res, "failed to update bitmap block");
    if (res == EStoreRes::NO_MEM) {
        // TODO out of space in the bitmap block, need to add another one and update the range block
        PANIC("not implemented");
        range_updated = true;
    }

    bool update_table = false;
    if (range_updated) {
        if (range_addr.addr_type == EAddrType::CONTAINED || range_addr.addr_type == EAddrType::NONE) {
            res = parent_composite_block->replace_contained_block(parent, range_block);
            // TODO handle the case the composite block has no space
            PT_RETURN(res != OK, res, "replace_contained_block failed parent=0x%lx", parent);
            update_table = true;
        } else {
            ASSERT(range_addr.addr_type == EAddrType::MD_BLOCKS);
        }
    }

    if (bitmap_addr.addr_type == EAddrType::CONTAINED || bitmap_addr.addr_type == EAddrType::NONE) {
        res = parent_composite_block->replace_contained_block(parent, bitmap_block);
        // TODO handle the case the composite block has no space
        PT_RETURN(res != OK, res, "replace_contained_block failed parent=0x%lx", parent);
        update_table = true;
    } else {
        ASSERT(bitmap_addr.addr_type == EAddrType::MD_BLOCKS);
    }

    if (update_table) {
        res = _handles_table->write(parent, parent_composite_block->get_buffer());
        PT_RETURN(res != OK, res, "_handles_table->write failed parent=0x%lx", parent);
    }

    if (bitmap_addr.addr_type == EAddrType::MD_BLOCKS) {
        res = _eio->write_md(bitmap_addr, bitmap_block->get_buffer());
        PT_RETURN(res != OK, res, "_eio->write failed addr=0x%lx", bitmap_addr.as_number());
    }
    if (range_updated && range_addr.addr_type == EAddrType::MD_BLOCKS) {
        res = _eio->write_md(range_addr, range_block->get_buffer());
        PT_RETURN(res != OK, res, "_eio->write failed addr=0x%lx", range_addr.as_number());
    }

    return OK;
}

void Ingest::set_handle_attr(SettableAttr *sattr, SystemAttr *handle_attr)
{
    if (sattr == nullptr) {
        return;
    }
    if (sattr->flags & MODE) {
        handle_attr->mode = sattr->mode;
    }
    if (sattr->flags & UID) {
        handle_attr->uid = sattr->uid;
    }
    if (sattr->flags & GID) {
        handle_attr->gid = sattr->gid;
    }
    if (sattr->flags & SIZE) {
        handle_attr->size = sattr->size;
        // TODO truncate
        PANIC("not implemented");
    }
    if (sattr->flags & ATIME) {
        handle_attr->atime = sattr->atime;
    }
    if (sattr->flags & MTIME) {
        handle_attr->mtime = sattr->mtime;
    }
    if (sattr->flags & ELEMENT_FLAGS) {
        handle_attr->element_flags = sattr->element_flags;
    }
}

EStoreRes Ingest::get_attr_internal(EHandle handle, SystemAttr *attr, BuffersGuard *buffers_guard)
{
    if (!attr) {
        return OK;
    }
    PT_DEBUG(DATA, "get attr for handle=0x%lx", handle);
    CompositeBlock composite_block;
    HandleBlock handle_block;
    EStoreRes res = read_handle_block(handle, &composite_block, &handle_block, buffers_guard);
    PT_RETURN(res != OK, res, "read_handle_block failed handle=0x%lx", handle);
    *attr = *handle_block.get_attr();

    return OK;
}

EStoreRes Ingest::read_handle_block(EHandle handle, CompositeBlock *composite_block, HandleBlock *handle_block,
                                    BuffersGuard *buffers_guard)
{
    composite_block->init(buffers_guard->get_next());
    EStoreRes res = _handles_table->read(handle, composite_block->get_buffer());
    PT_RETURN(res != OK, res, "failed to read handle=0x%lx", handle);
    DEBUG_ASSERT(composite_block->get_type() == BlockType::COMPOSITE_BLOCK);
    res = composite_block->export_contained_block(handle, BlockType::HANDLE_BLOCK, handle_block);
    PT_RETURN(res != OK, res, "export_contained_block failed owner=0x%lx", handle);

    return OK;
}

EStoreRes Ingest::read_parent_blocks(EHandle parent, const char *name, BuffersGuard *buffers_guard,
                                     CompositeBlock *composite_block, HandleBlock *handle_block,
                                     NameRangeBlock *range_block, NameBitmapBlock *bitmap_block, bool *range_updated)
{
    EStoreRes res = read_handle_block(parent, composite_block, handle_block, buffers_guard);
    PT_RETURN(res != OK, res, "read_handle_block failed handle=0x%lx", parent);

    // Verify the parent is allowed to have children
    if (!handle_block->is_container_element()) {
        PT_ERROR(DATA, "element 0x%lx is not allowed to have children", parent);
        return EStoreRes::NOT_A_CONTAINER;
    }

    // get ranges block
    range_block->init(buffers_guard->get_next());
    EAddress range_addr = handle_block->get_ranges_addr();
    res = read_block(composite_block, range_addr, parent, range_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", range_addr.as_number());

    // get bitmap block
    bitmap_block->init(buffers_guard->get_next());
    EAddress bitmap_addr = range_block->get_address(name);
    res = read_block(composite_block, bitmap_addr, parent, bitmap_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", bitmap_addr.as_number());

    *range_updated = false;
    if (range_addr.addr_type == EAddrType::NONE) {
        // if the ranges block does not exist attempt to add it to the handle composite block
        handle_block->set_ranges_addr(CONTAINED_EADDRESS);
        *range_updated = true;
    }
    // TODO lock bitmap (should use guards for locks)

    if (bitmap_addr.addr_type == EAddrType::NONE) {
        // if the bitmap block did not exist we'll attempt to add it to the handle composite block
        // TODO will " " range always be first?
        res = range_block->add_range(" ", CONTAINED_EADDRESS);
        PT_RETURN(res != OK, res, "add_range failed");
        *range_updated = true;
    }

    // get content block
    EAddress content_addr;
    res = bitmap_block->get_addr(name, &content_addr);
    PT_RETURN(res != OK && res != EStoreRes::NOENT, res, "failed to get content block addr name=%s", name);
    if (res == EStoreRes::OK) {
        // TODO name hash is present in the bitmap need to check if the name is on the content block and resolve hash collisions
        // TODO if name is present check if create flag allows overwrite
        // TODO check verifiers if a verifier was given
        PANIC("not implemented");
    }

    return OK;
}

void Ingest::update_mc_times(HandleBlock *handle_block)
{
    SystemAttr *attr = handle_block->get_attr();
    attr->ctime = P::get_time_nano();
    attr->mtime = attr->ctime;
}

EStoreRes Ingest::io_start(EHandle handle, uint64_t offset, BuffersGuard *buffers_guard, CompositeBlock *composite_block,
                           HandleBlock *handle_block, DataRangeBlock *range_block, DataBitmapBlock *bitmap_block)
{
    EStoreRes res = read_handle_block(handle, composite_block, handle_block, buffers_guard);
    PT_RETURN(res != OK, res, "failed to read handle=0x%lx block", handle);

    if (!handle_block->is_data_element()) {
        PT_ERROR(DATA, "element 0x%lx is not allowed to store data", handle);
        return EStoreRes::NOT_A_DATA_ELEMENT;
    }

    // TODO locks
    range_block->init(buffers_guard->get_next());
    EAddress range_addr = handle_block->get_ranges_addr();
    res = read_block(composite_block, range_addr, handle, range_block);
    PT_RETURN(res != OK, res, "failed to read range block addr=0x%lx", range_addr.as_number());

    // read bitmap block
    bitmap_block->init(buffers_guard->get_next());
    EAddress bitmap_addr = range_block->get_range(offset);
    res = read_block(composite_block, bitmap_addr, handle, bitmap_block);
    PT_RETURN(res != OK, res, "failed to read bitmap block addr=0x%lx", bitmap_addr.as_number());


    return OK;
}

EStoreRes Ingest::write(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, IOVecs *io_vecs,
                        SystemAttr *pre_attr, SystemAttr *post_attr)
{
    PT_INFO(DATA, "write handle=0x%lx offset=%lu", handle, offset);
    // TODO reduce num of buffers by supporting return_buffer in the guard
    BuffersGuard buffers_guard(_eio, 10);

    CompositeBlock composite_block;
    HandleBlock handle_block;
    DataRangeBlock range_block;
    DataBitmapBlock bitmap_block;

    EStoreRes res = io_start(handle, offset, &buffers_guard, &composite_block, &handle_block, &range_block, &bitmap_block);
    PT_RETURN(res != OK, res, "io_start for handle=0x%lx failed", handle);

    copy_attr(&handle_block, pre_attr);
    OP_CALLBACK_RETURN(op_cb, cb_ctx, handle_block.get_attr());

    uint64_t data_len = io_vecs->total_length();
    if (data_len == 0) {
        copy_attr(&handle_block, post_attr);
        return OK;
    }
    // align write to allowed IO size
    printf("io_vecs->count=%u io_vecs->iovecs[io_vecs->count - 1].iov_len=%lu\n", io_vecs->count, io_vecs->iovecs[io_vecs->count - 1].iov_len);
    io_vecs->iovecs[io_vecs->count - 1].iov_len = IO_ALIGN_UP(io_vecs->iovecs[io_vecs->count - 1].iov_len);
    printf("io_vecs->iovecs[io_vecs->count - 1].iov_len=%lu\n", io_vecs->iovecs[io_vecs->count - 1].iov_len);

    bool range_updated = false;
    EAddress range_addr = handle_block.get_ranges_addr();
    if (range_addr.addr_type == EAddrType::NONE) {
        PT_DEBUG(DATA, "need to create a range block for handle=0x%lx", handle);
        // need to create a range block, try to do it in the composite block
        range_addr.addr_type = EAddrType::CONTAINED;
        handle_block.set_ranges_addr(range_addr);
        range_updated = true;
    }

    ShardId shard_id = resolve_shard_id(handle, offset);
    PT_DEBUG(DATA, "handle=0x%lx offset=%lu shard_id=%hu", handle, offset, shard_id);
    WriteBuffer *write_buffer = _shard_md->get_ingest_buffer(shard_id);

    EAddress bitmap_addr = range_block.get_range(offset);
    if (bitmap_addr.addr_type == EAddrType::NONE) {
        uint64_t base_offset = (offset / DATA_RANGE_SHARD_SIZE) * DATA_RANGE_SHARD_SIZE;
        // need to create a new bitmap block, try to do it in the composite block
        PT_DEBUG(DATA, "need to create a bitmap block for handle=0x%lx base_offset=%lu offset=%lu",
                 handle, base_offset, offset);

        if (base_offset == 0) {
            // the first bitmap is
            bitmap_addr.addr_type = EAddrType::CONTAINED;
        } else {
            res = write_buffer->alloc_md_block(&buffers_guard, &bitmap_addr);
            // TODO handle write buffer switch?
            PT_RETURN(res != OK, res, "alloc_internal failed handle=0x%lx offset=%lu", handle, offset);
        }
        bitmap_block.set_base_offset(base_offset);

        if (range_addr.addr_type == EAddrType::CONTAINED) {
            range_block.replace_buffer(buffers_guard.get_next());
        }
        res = range_block.add_range(base_offset, bitmap_addr);
        // TODO handle range block full outside of the composite block
        PT_RETURN(res != OK, res, "add_range failed to handle=0x%lx offset=%lu", handle, offset);
        range_updated = true;

    }
    // TODO write might cover multiple bitmap blocks
    // TODO write short data (less than 512) bytes inline

    // write data
    EAddress data_addr;
    res = write_buffer->alloc_data_chunk(&buffers_guard, IO_ALIGN_UP(data_len), &data_addr);
    // TODO handle switching write buffer
    PT_RETURN(res != OK, res, "failed to allocate data chunk handle=0x%lx data_len=%lu", handle, data_len);

    PT_DEBUG(DATA, "writing data handle=0x%lx addr=0x%lx data_len=%lu", handle, data_addr.as_number(), data_len);
    res = _eio->write_data(data_addr, io_vecs);
    PT_RETURN(res != OK, res, "write_data failed handle=0x%lx addr=0x%lx data_len=%lu",
              handle, data_addr.as_number(), data_len);
    
    // update content block
    EAddress content_addr;
    res = write_buffer->append_data_content(&buffers_guard, handle, offset, data_len, data_addr, &content_addr);
    PT_RETURN(res != OK, res, "append_data_content failed handle=0x%lx addr=0x%lx data_len=%lu",
              handle, data_addr.as_number(), data_len);

    // TODO if the extent can be internally merged there is no need to replace the buffer and add it again to the composite block
    bitmap_block.replace_buffer(buffers_guard.get_next());
    res = bitmap_block.add_extent(offset, data_len, content_addr);
    // TODO handle bitmap being out of space
    PT_RETURN(res != OK, res, "add_extent failed handle=0x&lx offset=%lu offset=%lu data_len=%lu addr=0x%lx",
              handle, offset, data_len, content_addr.as_number());

    // update mtime and ctime
    update_mc_times(&handle_block);
    if (offset + data_len > handle_block.get_attr()->size) {
        // increase file size if needed
        handle_block.get_attr()->size = offset + data_len;
    }

    if (range_updated && range_addr.addr_type == EAddrType::CONTAINED) {
        res = composite_block.replace_contained_block(handle, &range_block);
        if (res != OK) {
            composite_block.trace_contained_blocks("out of space during write");
        }
        // TODO handle composite block being out of space
        PT_RETURN(res != OK, res, "replace_contained_block for range block failed handle=0x%lx", handle);
    }

    // write bitmap, range and handle blocks
    if (bitmap_addr.addr_type == EAddrType::CONTAINED) {
        PT_DEBUG(DATA, "updating bitmap block");
        res = composite_block.replace_contained_block(handle, &bitmap_block);
        // TODO handle composite block being out of space
        PT_RETURN(res != OK, res, "replace_contained_block for bitmap block failed handle=0x%lx", handle);
    }

    // TODO deal with handle block being outside of composite
    // TODO don't always update table
    res = _handles_table->write(handle, composite_block.get_buffer());
    PT_RETURN(res != OK, res, "_handles_table->write failed parent=0x%lx", handle);

    if (bitmap_addr.addr_type == EAddrType::MD_BLOCKS || bitmap_addr.addr_type == EAddrType::WRITE_BUFFER) {
        res = _eio->write_md(bitmap_addr, bitmap_block.get_buffer());
        PT_RETURN(res != OK, res, "_eio->write failed addr=0x%lx", bitmap_addr.as_number());
    }
    if (range_updated && range_addr.addr_type == EAddrType::MD_BLOCKS) {
        res = _eio->write_md(range_addr, range_block.get_buffer());
        PT_RETURN(res != OK, res, "_eio->write failed addr=0x%lx", range_addr.as_number());
    }

    copy_attr(&handle_block, post_attr);

    // TODO add a guard to free the data buffers
    _eio->free_data_buffers(io_vecs);

    return OK;
}

ShardId Ingest::resolve_shard_id(EHandle handle, uint64_t offset) const
{
    return HandlesTable::handle_to_shard_id(handle) + ((offset / DATA_RANGE_SHARD_SIZE) % P::N_SHARDS);
}

uint32_t Ingest::fill_hole(uint64_t prev_offset, uint64_t extent_offset, IOVecs *res_vecs, IOVecs *alloc_vecs,
                           uint32_t n_buffers, uint16_t *curr_buffer, uint32_t *buffer_offset)
{
    uint32_t bytes_filled = 0;
    uint64_t hole_len = extent_offset - prev_offset;
    while (hole_len > 0 && n_buffers > *curr_buffer) {
        res_vecs->iovecs[res_vecs->count].iov_base = (char *)alloc_vecs->iovecs[*curr_buffer].iov_base + *buffer_offset;
        res_vecs->iovecs[res_vecs->count].iov_len = P_MIN(hole_len, DATA_BUFFER_SIZE - *buffer_offset);
        memset(res_vecs->iovecs[res_vecs->count].iov_base, 0, res_vecs->iovecs[res_vecs->count].iov_len);
        hole_len -= res_vecs->iovecs[res_vecs->count].iov_len;
        bytes_filled += res_vecs->iovecs[res_vecs->count].iov_len;
        res_vecs->count++;
        if (*buffer_offset >= DATA_BUFFER_SIZE) {
            *buffer_offset = 0;
            (*curr_buffer)++;
        }
    }
    return bytes_filled;
}

EStoreRes Ingest::read(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint32_t len, IOVecs *res_vecs,
                       IOVecs *alloc_vecs, uint32_t *bytes_read, bool *eof, SystemAttr *pre_attr, SystemAttr *post_attr)
{
    // TODO make this method shorter
    PT_INFO(DATA, "read handle=0x%lx offset=%lu len=%u", handle, offset, len);
    if (len > UNIT_MiB) {
        PT_ERROR(DATA, "reads larger than 1MB are not supported len=%u", len);
        return EStoreRes::INVAL;
    }
    *eof = false;
    *bytes_read = 0;

    BuffersGuard buffers_guard(_eio, 7);
    CompositeBlock composite_block;
    HandleBlock handle_block;
    DataRangeBlock range_block;
    DataBitmapBlock bitmap_block;

    EStoreRes res = io_start(handle, offset, &buffers_guard, &composite_block, &handle_block, &range_block, &bitmap_block);
    PT_RETURN(res != OK, res, "io_start for handle=0x%lx failed", handle);

    // TODO data might be split between multiple bitmap blocks
    // TODO locks
    copy_attr(&handle_block, pre_attr);
    OP_CALLBACK_RETURN(op_cb, cb_ctx, handle_block.get_attr());

    if (offset + len >= handle_block.get_attr()->size) {
        len = handle_block.get_attr()->size - offset;
    }
    if (len == 0) {
        *eof = true;
        copy_attr(&handle_block, post_attr);
        return OK;
    }

    // build the extents list that composes the read
    uint16_t n_addrs = 64;
    EAddress content_addrs[n_addrs];
    // get content blocks that contain relevant extents
    res = bitmap_block.get_content_addrs(offset, len, &n_addrs, content_addrs);
    // TODO handle the case in which there are more than n_addrs 
    PT_RETURN(res != OK, res, "get_content_addrs failed handle=0x%lx offset=%lu len=%u", handle, offset, len);

    // feed the extents into the extents container which deals internally with data overwrites and aligns the
    // extents to the extent being read
    ExtentsContainer extents_container;
    extents_container.init(offset, len);
    MIOBuffer *buffer = buffers_guard.get_next();
    LOOP(n_addrs, i) {
        DataContentBlock content_block;
        content_block.init(buffer);
        res = _eio->read_md(content_addrs[i], content_block.get_buffer());
        PT_RETURN(res != OK, res, "read_md failed handle=0x%lx addr=0x%lx", handle, content_addrs[i].as_number());

        res = content_block.export_extents(handle, offset, len, &extents_container);
        //  TODO handle the case in which the extents_container is out of space (push out extents with higher offset)
        PT_RETURN(res != OK, res, "get_extents failed handle=0x%lx offset=%lu len=%u", handle, offset, len);
    }

    // allocate data buffers
    uint32_t n_buffers = (len / DATA_BUFFER_SIZE) + (len % DATA_BUFFER_SIZE ? 1 : 0) + 1;
    ASSERT(n_buffers <= res_vecs->count);
    alloc_vecs->count = n_buffers;
    alloc_vecs->iovecs = res_vecs->iovecs;
    _eio->alloc_data_buffers(alloc_vecs);
    // TODO add a guard to free the buffers in case of a failure
    PT_RETURN(alloc_vecs->count < n_buffers, EStoreRes::NO_MEM,
              "alloc_data_buffers failed handle=0x%lx n_buffers=%u allocated_buffers=%u",
              handle, n_buffers, alloc_vecs->count);

    // the first part of the res vector is taken by the allocated buffers
    // TODO check size calc of res vecs
    uint32_t max_results = res_vecs->count - alloc_vecs->count;
    res_vecs->iovecs = &alloc_vecs->iovecs[alloc_vecs->count];
    // vectors used for reading the data in an aligned manner
    IOVec read_vec[res_vecs->count];
    uint16_t curr_read_vec = 0;
    IOVecs read_vecs[res_vecs->count];
    uint16_t curr_read_vecs = 0;

    uint16_t curr_buffer = 0;
    uint32_t buffer_offset = 0;
    res_vecs->count = 0;

    // read the extents
    uint64_t prev_offset = offset;
    DataExtent *extent = extents_container.get_next(nullptr);
    // since reads must be aligned both on disk and in memory we need to manage 3 iovecs. one for the memory we use
    // (alloc_vecs) the second for the read operations (read_vec) and the last for the data we return (res_vecs).
    for (; extent != nullptr; extent = extents_container.get_next(extent)) {
        if (prev_offset < extent->_offset) {
            // we got a hole, need to fill the result buffer with zeros
            *bytes_read += fill_hole(prev_offset, extent->_offset, res_vecs, alloc_vecs, n_buffers,
                                     &curr_buffer, &buffer_offset);
        }
        read_vecs[curr_read_vecs].iovecs = &read_vec[curr_read_vec];
        read_vecs[curr_read_vecs].count = 0;
        // align read offset
        EAddress read_addr = extent->_data_addr;
        read_addr.offset = IO_ALIGN_DOWN(read_addr.offset);
        uint64_t offset_diff = extent->_data_addr.offset - read_addr.offset;
        printf("offset_diff=%lu\n", offset_diff);
        while (extent->_len > 0) {
            DEBUG_ASSERT(curr_buffer < n_buffers);
            // TODO make sure the reads are aligned
            read_vec[curr_read_vec].iov_base = (char *)alloc_vecs->iovecs[curr_buffer].iov_base + buffer_offset;
            res_vecs->iovecs[res_vecs->count].iov_base = (char *)read_vec[curr_read_vec].iov_base + offset_diff;
            uint32_t read_len = P_MIN(extent->_len, DATA_BUFFER_SIZE - buffer_offset);
            read_vec[curr_read_vec].iov_len = IO_ALIGN_UP(read_len + offset_diff);
            // the size relevant to the user is the min value between what he asked to read and what we are going to read
            uint32_t res_vec_len = P_MIN(read_vec[curr_read_vec].iov_len - offset_diff, extent->_len);
            res_vecs->iovecs[res_vecs->count].iov_len = res_vec_len;
            printf("extent->_len=%u read_len=%u res_vec_len=%u buffer_offset=%u iov_len=%lu\n",
                   extent->_len, read_len, res_vec_len, buffer_offset, read_vec[curr_read_vec].iov_len);
            buffer_offset += read_vec[curr_read_vec].iov_len;
            read_vecs[curr_read_vecs].count++;
            res_vecs->count++;
            curr_read_vec++;
            // TODO check if res can be merged with the prev one
            extent->_len -= res_vec_len;
            if (buffer_offset >= DATA_BUFFER_SIZE) {
                buffer_offset = 0;
                curr_buffer++;
            }
            // TODO check if we are out of res_vecs / memory
            (*bytes_read) += res_vec_len;
            // offset_diff applies only for the first item in the vector
            offset_diff = 0;
        }

        // TODO pass a future and do async reads (will require more read vecs)
        res = _eio->read_data(read_addr, &read_vecs[curr_read_vecs], nullptr);
        PT_RETURN(res != OK, res, "read_data failed handle=0x%lx offset=%lu len=%u", handle, offset, len);
        curr_read_vecs++;
    }

    if (offset + (*bytes_read) >= handle_block.get_attr()->size) {
        *eof = true;
    }
    return OK;
}

EStoreRes Ingest::get_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SystemAttr *attr, ExtendedAttrs *user_xattr,
                           ExtendedAttrs *proto_xattr)
{
    BuffersGuard buffers_guard(_eio, 2);

    EStoreRes res = get_attr_internal(handle, attr, &buffers_guard);
    PT_RETURN(res != OK, res, "get_attr_internal failed handle=0x%lx", handle);
    if (op_cb) {
        op_cb(attr, cb_ctx);
    }

    return OK;
}

void Ingest::alloc_data_buffers(IOVecs *iovecs)
{
    _eio->alloc_data_buffers(iovecs);
}

void Ingest::free_data_buffers(IOVecs *iovecs)
{
    printf("count=%u\n", iovecs->count);
    _eio->free_data_buffers(iovecs);
}

void Ingest::copy_attr(HandleBlock *handle_block, SystemAttr *attr)
{
    if (attr) {
        *attr = *handle_block->get_attr();
    }
}

}
