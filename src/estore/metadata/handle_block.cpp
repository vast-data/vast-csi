#include "plasma/utils/assert.hpp"
#include "handle_block.hpp"

namespace EStore {

void HandleBlock::init(MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::HANDLE_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    ASSERT(space_left() >= sizeof(HandleInfo));
    add_used_bytes(sizeof(HandleInfo));
}

void HandleBlock::set_handle(EHandle handle)
{
    HandleInfo *handle_info = (HandleInfo *)payload_start();
    handle_info->handle = handle;
}

EHandle HandleBlock::get_handle()
{
    HandleInfo *handle_info = (HandleInfo *)payload_start();
    return handle_info->handle;
}

SystemAttr *HandleBlock::get_attr()
{
    HandleInfo *handle_info = (HandleInfo *)payload_start();
    return &handle_info->attr;
}

EAddress HandleBlock::get_ranges_addr()
{
    HandleInfo *handle_info = (HandleInfo *)payload_start();
    return handle_info->ranges_addr;
}

void HandleBlock::set_ranges_addr(EAddress ranges_addr)
{
    HandleInfo *handle_info = (HandleInfo *)payload_start();
    handle_info->ranges_addr = ranges_addr;
}

}


