#include "plasma/utils/assert.hpp"
#include "composite_block.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE

namespace EStore {

using EStoreRes::OK;

void CompositeBlock::init(MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::COMPOSITE_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    ASSERT(space_left() >= sizeof(ContainedBlock));
    add_used_bytes(sizeof(uint16_t));
    ZERO_LAST(ContainedBlock);
}

EStoreRes CompositeBlock::add_contained_block(EHandle owner, const BaseBlock *block)
{
    if (space_left() < sizeof(ContainedBlock) + block->get_used_bytes()) {
        PT_WARN(DATA, "failed to add block space_left=%hu block_size=%hu", space_left(), block->get_used_bytes());
        return EStoreRes::NO_MEM;
    }

    // TODO verify its not already there
    ContainedBlock *contained_block = (ContainedBlock *)(payload_end());
    contained_block->owner = owner;
    contained_block->type = block->get_type();
    contained_block->len = block->get_used_bytes() + MIO_OVERHEAD;
    P::byte *block_pos = payload_end() + sizeof(ContainedBlock);
    memcpy(block_pos, block->get_buffer()->get_mio_vec()->iov_base, contained_block->len);
    add_used_bytes(sizeof(ContainedBlock) + contained_block->len);
    ZERO_LAST(ContainedBlock);
    return OK;
}

EStoreRes CompositeBlock::remove_contained_block(EHandle owner, BlockType type)
{
    TRAVERSE_CONTENT(ContainedBlock, contained_block) {
        if (contained_block->type == type && contained_block->owner == owner) {
            uint16_t len = contained_block->len;
            P::byte *end_offset = (P::byte *)contained_block + sizeof(ContainedBlock) + len;
            // move the data that follows the contained block on top of the contained block
            memmove(contained_block, end_offset, payload_end() - end_offset);
            get_header()->used_bytes -= (sizeof(ContainedBlock) + len);
            ZERO_LAST(ContainedBlock);
            return OK;
        }
    }
    return EStoreRes::NOENT;
}

EStoreRes CompositeBlock::replace_contained_block(EHandle owner, const BaseBlock *block)
{
    (void)remove_contained_block(owner, block->get_type());
    return add_contained_block(owner, block);
}

EStoreRes WARN_UNUSED CompositeBlock::export_contained_block(EHandle owner, BlockType type, BaseBlock *block)
{
    DEBUG_ASSERT(get_type() == BlockType::COMPOSITE_BLOCK);
    TRAVERSE_CONTENT(ContainedBlock, contained_block) {
        if (contained_block->type == type && contained_block->owner == owner) {
            contained_block->buffer.init((P::byte *)contained_block + sizeof(ContainedBlock), contained_block->len);
            block->set_buffer(&contained_block->buffer);
            DEBUG_ASSERT_OP((uint8_t)block->get_type(), ==, (uint8_t)type);
            return OK;
        }
    }
    return EStoreRes::NOENT;
}

void CompositeBlock::trace_contained_blocks(const char *msg)
{
    PT_DEBUG(DATA, "%s", msg);
    TRAVERSE_CONTENT(ContainedBlock, block) {
        PT_DEBUG(DATA, "owner=0x%lx type=%hhu len=%hu", block->owner, block->type, block->len);
    }
}

}
