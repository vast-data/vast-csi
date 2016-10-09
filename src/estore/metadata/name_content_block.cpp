#include "name_content_block.hpp"
#include "name_bitmap_block.hpp"
#include <string.h>

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

void NameContentBlock::init(MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::NAME_CONTENT_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    add_used_bytes(sizeof(uint16_t));
    ZERO_LAST(NameHandle);
}

EStoreRes NameContentBlock::add_handle(const char *name, EHandle handle)
{
    size_t name_len = strnlen(name, get_size()) + 1;
    uint16_t required_space = sizeof(NameHandle) + name_len;
    if (space_left() < required_space) {
        PTC_DEBUG("out of space space_left=%hu required_space=%hu", space_left(), required_space);
        trace();
        return EStoreRes::NO_MEM;
    }

    NameHandle *name_handle = (NameHandle *)(payload_end());
    name_handle->handle = handle;
    name_handle->len = name_len;
    memcpy(name_handle->name, name, name_len);
    add_used_bytes(required_space);
    ZERO_LAST(NameHandle);
    return EStoreRes::OK;
}

EStoreRes NameContentBlock::get_handle(const char *name, EHandle *handle)
{
    TRAVERSE_CONTENT(NameHandle, name_handle) {
        if (strncmp(name_handle->name, name, name_handle->len) == 0) {
            *handle = name_handle->handle;
            return EStoreRes::OK;
        }
    }
    return EStoreRes::NOENT;
}

EStoreRes NameContentBlock::traverse(uint32_t start_hash, NameContentBlock::TraverseCallback cb, void *cb_ctx)
{
    bool found = false;
    if (start_hash == 0) {
        found = true;
    }
    TRAVERSE_CONTENT(NameHandle, name_handle) {
        uint32_t hash = NameBitmapBlock::name_hash(name_handle->name);
        if (!found) {
            if (hash == start_hash) {
                found = true;
            }
        }
        if (found) {
            EStoreRes res = cb(name_handle->name, name_handle->len, hash, name_handle->handle, cb_ctx);
            if (res != EStoreRes::OK) {
                return res;
            }
        }
    }

    return EStoreRes::OK;
}

void NameContentBlock::trace()
{
    int i = 0;
    TRAVERSE_CONTENT(NameHandle, name_handle) {
        PTC_DEBUG("handle(%d)=0x%lx name=%s", i, name_handle->handle, name_handle->name);
        ++i;
    }
}

}
