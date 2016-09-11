#include "data_bitmap_block.hpp"
#include "data_range_block.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE

namespace EStore {

using EStoreRes::OK;

void DataBitmapBlock::init(EStore::MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::DATA_BITMAP_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    add_used_bytes(sizeof(DataBitmapInfo));
    DataBitmapInfo *bitmap_info = (DataBitmapInfo *)payload_start();
    bitmap_info->base_offset = UINT64_MAX;
    bitmap_info->extents.n_extents = 0;
}

void DataBitmapBlock::set_base_offset(uint64_t base_offset)
{
    DataBitmapInfo *bitmap_info = (DataBitmapInfo *)payload_start();
    bitmap_info->base_offset = base_offset;
}

EStoreRes DataBitmapBlock::add_extent(uint64_t offset, uint32_t len, EAddress addr)
{
    // adding an extend might overwrite a part or one or even multiple existing extents
    DataBitmapInfo *bitmap_info = (DataBitmapInfo *)payload_start();
    DEBUG_ASSERT(bitmap_info->base_offset != UINT64_MAX);

    ASSERT(offset - bitmap_info->base_offset < UINT32_MAX);
    uint32_t relative_offset = (uint32_t)(offset - bitmap_info->base_offset);

    BitmapExtents *extents = &bitmap_info->extents;
    // look for an existing extent to merge with
    LOOP(bitmap_info->extents.n_extents, i) {
        BitmapExtent *extent = &extents->extents[i];
        if (extent->_content_addr.as_number() == addr.as_number() && extent->adjacent_overlap(relative_offset, len)) {
            extent->merge(relative_offset, len);
            // TODO there might be more than one that can be merged
            return OK;
        }
    }
    // need to add a new extent
    if (space_left() < sizeof(BitmapExtent)) {
        return EStoreRes::NO_MEM;
    }
    BitmapExtent *extent = &extents->extents[extents->n_extents];
    DEBUG_ASSERT(offset - bitmap_info->base_offset < UINT32_MAX);
    extent->_offset = relative_offset;
    extent->_len = len;
    extent->_content_addr = addr;
    extents->n_extents++;
    add_used_bytes(sizeof(BitmapExtent));

    return OK;
}

EStoreRes DataBitmapBlock::get_content_addrs(uint64_t offset, uint32_t len, uint16_t *n_addrs, EAddress *content_addrs)
{
    DataBitmapInfo *bitmap_info = (DataBitmapInfo *)payload_start();
    DEBUG_ASSERT(bitmap_info->base_offset != UINT64_MAX);
    uint32_t relative_offset = (uint32_t)(offset - bitmap_info->base_offset);
    BitmapExtents *extents = &bitmap_info->extents;

    uint16_t max_addr = *n_addrs;
    *n_addrs = 0;
    LOOP(bitmap_info->extents.n_extents, i) {
        BitmapExtent *extent = &extents->extents[i];
        if (extent->overlaps(relative_offset, len)) {
            if (*n_addrs == max_addr) {
                return EStoreRes::NO_MEM;
            }
            // TODO each addr should only be returned once
            content_addrs[*n_addrs] = extent->_content_addr;
            (*n_addrs)++;
        }
    }
    return OK;
}

void DataBitmapBlock::trace()
{
    DataBitmapInfo *bitmap_info = (DataBitmapInfo *)payload_start();
    LOOP(bitmap_info->extents.n_extents, i) {
        BitmapExtent *extent = &bitmap_info->extents.extents[i];
        PT_DEBUG(DATA, "extents(%lu offset=%u len=%u", i, extent->_offset, extent->_len);
    }
}

}
