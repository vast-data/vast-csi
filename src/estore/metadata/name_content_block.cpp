#include "name_content_block.hpp"
#include <string.h>

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
    size_t name_len = strnlen(name, get_size());
    if (space_left() < sizeof(NameHandle) + name_len + sizeof(uint16_t)) {
        return EStoreRes::NO_MEM;
    }

    NameHandle *name_handle = (NameHandle *)(payload_end());
    name_handle->handle = handle;
    name_handle->len = name_len;
    memcpy(name_handle->name, name, name_len);
    add_used_bytes(sizeof(NameHandle) + name_handle->len);
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

void NameContentBlock::trace_handles()
{
    int i = 0;
    TRAVERSE_CONTENT(NameHandle, name_handle) {
        printf("handle(%d)=0x%lx name=%s\n", i, name_handle->handle, name_handle->name);
        ++i;
    }
}

}
