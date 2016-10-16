#include <estore/defs/estore_defs.hpp>
#include "data_range_block.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

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

EStoreRes DataRangeBlock::add_range(uint64_t offset, LAddress addr)
{
    Ranges *ranges = (Ranges *)payload_start();
    uint16_t range_index = 0;
    if (ranges->n_ranges > 0) {
        range_index = find_range_index(offset);
        if (ranges->ranges[range_index].offset == offset) {
            PTC_INFO("replacing address for offset=%lu", offset);
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
    ranges->ranges[range_index].offset = offset;
    ranges->ranges[range_index].data_bitmap_addr = addr;
    ranges->n_ranges++;
    add_used_bytes(sizeof(Range));

    return OK;
}

void DataRangeBlock::set_output_len(uint16_t found_index, uint64_t offset, uint64_t *len)
{
    if (len == nullptr) {
        return;
    }
    Ranges *ranges = (Ranges *)payload_start();
    uint64_t next_shard_offset = POW2_ROUND_UP(offset + 1, DATA_RANGE_SHARD_SIZE);
    uint64_t available_len;
    if (found_index == UINT16_MAX || found_index + 1 == ranges->n_ranges) {
        *len = P_MIN(next_shard_offset - offset, *len);
        return;
    }
    uint64_t next_offset = ranges->ranges[found_index + 1].offset;
    if (next_offset > next_shard_offset) {
        available_len = next_shard_offset - offset;
    } else {
        available_len = ranges->ranges[found_index + 1].offset - offset;
    }
    DEBUG_ASSERT_OP(available_len, <=, DATA_RANGE_SHARD_SIZE);
    *len = P_MIN(*len, available_len);
}

LAddress DataRangeBlock::get_range(uint64_t offset, uint64_t *len)
{
    Ranges *ranges = (Ranges *)payload_start();
    if (ranges->n_ranges == 0) {
        set_output_len(UINT16_MAX, offset, len);
        return Layout::EMPTY_ADDRESS;
    }
    uint16_t range_index = find_range_index(offset);
    if (ranges->ranges[range_index].offset + DATA_RANGE_SHARD_SIZE <= offset) {
        PTC_DEBUG("range is out of shard, range_index=%hu range offset=%lu offset=%lu", range_index,
                  ranges->ranges[range_index].offset, offset);
        // offset is outside the shard range
        set_output_len(UINT16_MAX, offset, len);
        return Layout::EMPTY_ADDRESS;
    }
    set_output_len(range_index, offset, len);
    return ranges->ranges[range_index].data_bitmap_addr;
}

uint16_t DataRangeBlock::find_range_index(uint64_t offset)
{
    Ranges *ranges = (Ranges *)payload_start();
    DEBUG_ASSERT(ranges->n_ranges > 0);
    uint16_t res = 0;
    for (uint16_t i = 1; i < ranges->n_ranges; ++i) {
        if (ranges->ranges[i].offset > offset) {
            return res;
        }
        res = i;
    }
    return res;
}

EStoreRes DataRangeBlock::traverse(uint64_t start_offset, DataRangeBlock::TraverseCallback cb, void *cb_ctx)
{
    Ranges *ranges = (Ranges *)payload_start();
    if (ranges->n_ranges == 0) {
        return OK;
    }
    for (uint16_t i = find_range_index(start_offset); i < ranges->n_ranges; ++i) {
        Range *range = &ranges->ranges[i];
        EStoreRes res = cb(range->data_bitmap_addr, range->offset, cb_ctx);
        if (res != OK) {
            return res;
        }
    }
    return OK;
}

void DataRangeBlock::trace()
{
    Ranges *ranges = (Ranges *)payload_start();
    for (uint16_t i = 0; i < ranges->n_ranges; ++i) {
        Range *range = &ranges->ranges[i];
        PTC_DEBUG("range(%u) offset=%lu addr=0x%lx",i, range->offset, range->data_bitmap_addr.as_number());
    }
}

}
