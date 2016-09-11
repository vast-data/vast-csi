#include "data_range_block.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE

namespace EStore {

using EStoreRes::OK;

void DataRangeBlock::init(EStore::MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::DATA_RANGE_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    add_used_bytes(sizeof(Ranges));
    Ranges *ranges = (Ranges *)payload_start();
    ranges->n_ranges = 0;
}

EStoreRes DataRangeBlock::add_range(uint64_t offset, EAddress addr)
{
    Ranges *ranges = (Ranges *)payload_start();
    uint16_t range_index = 0;
    if (ranges->n_ranges > 0) {
        range_index = find_range_index(offset);
        if (ranges->ranges[range_index]._offset == offset) {
            PT_DEBUG(DATA, "replacing address for offset=%lu", offset);
            ranges->ranges[range_index].data_bitmap_addr = addr;
            return OK;
        }
        if (space_left() < sizeof(Range)) {
            return EStoreRes::NO_MEM;
        }
        // make room for the new range
        range_index++;
        for (uint16_t i = ranges->n_ranges; i > range_index; --i) {
            ranges->ranges[i] = ranges->ranges[i - 1];
        }
    }
    ranges->ranges[range_index]._offset = offset;
    ranges->ranges[range_index].data_bitmap_addr = addr;
    ranges->n_ranges++;
    add_used_bytes(sizeof(Range));

    return OK;
}

EAddress DataRangeBlock::get_range(uint64_t offset)
{
    Ranges *ranges = (Ranges *)payload_start();
    if (ranges->n_ranges == 0) {
        return EMPTY_EADDRESS;
    }
    uint16_t range_index = find_range_index(offset);
    if (ranges->ranges[range_index]._offset + DATA_RANGE_SHARD_SIZE < offset) {
        PT_DEBUG(DATA, "found range is out of shard, range_index=%hu range offset=%lu offset=%lu", range_index,
                 ranges->ranges[range_index]._offset, offset);
        // offset is outside the shard range
        return EMPTY_EADDRESS;
    }
    return ranges->ranges[range_index].data_bitmap_addr;
}

uint16_t DataRangeBlock::find_range_index(uint64_t offset)
{
    // TODO limit data ranges scope
    Ranges *ranges = (Ranges *)payload_start();
    DEBUG_ASSERT(ranges->n_ranges > 0);
    uint16_t res = 0;
    for (uint16_t i = 1; i < ranges->n_ranges; ++i) {
        if (ranges->ranges[i]._offset > offset) {
            return res;
        }
        res = i;
    }
    return res;
}

void DataRangeBlock::trace_ranges()
{
    Ranges *ranges = (Ranges *)payload_start();
    for (uint16_t i = 0; i < ranges->n_ranges; ++i) {
        Range *range = &ranges->ranges[i];
        PT_DEBUG(DATA, "range(%u) offset=%lu addr=0x%lx",i, range->_offset, range->data_bitmap_addr.as_number());
    }
}

}

