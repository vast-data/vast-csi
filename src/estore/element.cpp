#include <estore/defs/estore_defs.hpp>
#include "element.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

using EStoreRes::OK;
using P::ShardId;

void Element::init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table, BuffersGuard *buffers_guard)
{
    _eio = eio;
    _shard_md = shard_md;
    _handles_table = handles_table;
    _buffers_guard = buffers_guard;

    _composite_block.init(_buffers_guard->get_next());
    _handle_block.init(_buffers_guard->get_next());
}

EStoreRes Element::read_block(LAddress addr, EHandle owner, BaseBlock *block)
{
    PTC_DEBUG("addr=0x%lx owner handle=0x%lx type=%hhu", addr.as_number(), owner, (uint8_t)block->get_type());
    if (addr.addr_type == LAddrType::NONE) {
        return OK;
    } else if (addr.addr_type == LAddrType::CONTAINED) {
        EStoreRes res = _composite_block.export_contained_block(owner, block->get_type(), block);
        PT_RETURN(res != OK, res, "export_contained_block failed owner=0x%lx", owner);
    } else {
        EStoreRes res = _eio->read_md(addr, block->get_buffer(), false, nullptr);
        PT_RETURN(res != OK, res, "failed to read from addr=0x%lx", addr.as_number());
    }
    return OK;
}

EStoreRes Element::read_handle_block(EHandle handle)
{
    EStoreRes res = _handles_table->read(handle, _composite_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to read handle=0x%lx", handle);
    DEBUG_ASSERT(_composite_block.get_type() == BlockType::COMPOSITE_BLOCK);

    // TODO support handle block being outside the composite block
    res = _composite_block.export_contained_block(handle, BlockType::HANDLE_BLOCK, &_handle_block);
    PT_RETURN(res != OK, res, "export_contained_block failed owner=0x%lx", handle);

    return OK;
}

EStoreRes Element::create_root()
{
    EStoreRes res = _handles_table->read(ROOT_HANDLE, _composite_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to read root handle");

    // we are not supposed to find root
    res = _composite_block.export_contained_block(ROOT_HANDLE, BlockType::HANDLE_BLOCK, &_handle_block);
    PT_RETURN(res == OK, EStoreRes::EXIST, "root already exist");

    _handle_block.set_handle(ROOT_HANDLE);
    _handle_block.set_ranges_addr(Layout::EMPTY_ADDRESS);
    SystemAttr *attr = get_attr();
    set_default_attr(attr, ROOT_HANDLE, ROOT_HANDLE, true);
    attr->element_flags = (uint64_t)ElementFlags::DIR;

    res = _composite_block.add_contained_block(ROOT_HANDLE, &_handle_block);
    PT_RETURN(res != OK, res, "add_contained_block failed");

    res = _handles_table->write(ROOT_HANDLE, _composite_block.get_buffer());
    PT_RETURN(res != OK, res, "_handles_table->write failed");

    return OK;
}

EStoreRes Element::write_new_handle(const char *name, SettableAttr *sattr, CreateFlags create_flags, LAddress *content_addr,
                                    EHandle parent_handle, EHandle *new_handle, SystemAttr *element_attr)
{
    // TODO lock handle bucket
    // TODO find something better than rand() (RAND_MAX is smaller than N_VIRTUAL_BUCKETS)
    VirtualBucketId virt_bucket = rand() % N_VIRTUAL_BUCKETS;
    EStoreRes res = _handles_table->read_by_virt_bucket(virt_bucket, _composite_block.get_buffer());
    PT_RETURN(res != OK, res, "read_by_virt_bucket failed virt_id=%lu", virt_bucket);
    // find a free handle id within the bucket
    ASSERT(_composite_block.get_type() == BlockType::COMPOSITE_BLOCK);
    // TODO find free handle index
    *new_handle = _handles_table->build_handle(1, virt_bucket);
    // TODO in case the bucket has too many handles retry

    ShardId shard_id = _handles_table->handle_to_shard_id(parent_handle);
    // name does not exist, add it to the content block on the write buffer
    WriteBuffer *write_buffer = _shard_md->get_ingest_buffer(shard_id);
    ASSERT_NOT_NULL(write_buffer);
    // TODO back pointer
    // TODO deal with invalid_state ret val
    res = write_buffer->append_name_content(_buffers_guard, parent_handle, name, *new_handle, content_addr);
    PT_RETURN(res != OK, res, "failed to append name content");

    // write handle block to the handles table
    _handle_block.set_handle(*new_handle);
    _handle_block.set_ranges_addr(Layout::EMPTY_ADDRESS);
    set_default_attr(get_attr(), parent_handle, *new_handle, create_flags & CreateFlags::HAS_CHILDREN);
    set_attr(sattr);

    res = _composite_block.add_contained_block(*new_handle, &_handle_block);
    // TODO deal with no space
    PT_RETURN(res != OK, res, "add_contained_block failed");

    // TODO handle the case in which the parent and child reside in the same bucket
    res = _handles_table->write(*new_handle, _composite_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write new handle bucket");

    if (element_attr) {
        *element_attr = *get_attr();
    }

    return OK;
}

EStoreRes Element::write_handle_block()
{
    // TODO support handle block being outside the composite block
    EStoreRes res = _handles_table->write(get_handle(), _composite_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write new handle bucket");

    return OK;
}

void Element::update_mc_times()
{
    SystemAttr *attr = _handle_block.get_attr();
    attr->ctime = P::get_time_nano();
    attr->mtime = attr->ctime;
}

void Element::copy_attr(SystemAttr *attr)
{
    if (attr) {
        *attr = *_handle_block.get_attr();
    }
}

void Element::set_default_attr(SystemAttr *attr, EHandle parent, EHandle handle, bool is_container)
{
    memset(attr, 0, sizeof(*attr));
    attr->mode = 0777;
    attr->nlink = 1;
    attr->uid = 0;
    attr->gid = 0;
    attr->used = 0;
    attr->fileid = handle;
    attr->parent = parent;
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

void Element::set_attr(SettableAttr *sattr)
{
    SystemAttr *handle_attr = get_attr();
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

}
