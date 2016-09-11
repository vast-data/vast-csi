#include "estore/defs/estore_defs.hpp"
#include "base_block.hpp"

namespace EStore {

void BaseBlock::init(MIOBuffer *buffer)
{
    _buffer = buffer;
#ifdef DEBUG
    memset(_buffer->get_mio_vec()->iov_base, 0, _buffer->get_mio_vec()->iov_len);
#endif
    BlockHeader *header = get_header();
    header->used_bytes = sizeof(BlockHeader);
    header->type = (uint8_t)BlockType::INVALID_BLOCK_TYPE;
    header->version = 0;
}

void BaseBlock::replace_buffer(MIOBuffer *buffer)
{
    memcpy(buffer->get_data(), _buffer->get_data(), get_header()->used_bytes);
    set_buffer(buffer);
}

void BaseBlock::set_buffer(MIOBuffer *buffer)
{
    _buffer = buffer;
}


}


