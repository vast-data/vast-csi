#include <estore/defs/estore_defs.hpp>
#include "estore/defs/estore_defs.hpp"
#include "data_content_block.hpp"
#include "extents_aggregator.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

using EStoreRes::OK;

void DataContentBlock::init(EStore::MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::DATA_CONTENT_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    add_used_bytes(sizeof(ContentExtents));
    ContentExtents *extents = (ContentExtents *)payload_start();
    extents->n_extents = 0;
}

EStoreRes DataContentBlock::add_extent(EHandle handle, uint64_t offset, uint32_t len, LAddress data_addr)
{
    ContentExtents *extents = (ContentExtents *)payload_start();
    ContentExtent *extent = &extents->extents[extents->n_extents];
    if (space_left() < sizeof(ContentExtent)) {
        PTC_DEBUG("out of space space_left=%hu", space_left());
        return EStoreRes::NO_MEM;
    }
    extent->_handle = handle;
    extent->_offset = offset;
    extent->_len = len;
    extent->_data_addr = data_addr;
    extents->n_extents++;
    add_used_bytes(sizeof(ContentExtent));
    return OK;
}

EStoreRes DataContentBlock::alloc_extent(uint16_t *extent_index)
{
    ContentExtents *extents = (ContentExtents *)payload_start();
    *extent_index = extents->n_extents;
    EStoreRes res = add_extent(INVALID_EHANDLE, 0, 0, Layout::EMPTY_ADDRESS);
    if (res != OK) {
        return res;
    }
    return OK;
}

void DataContentBlock::set_extent(uint16_t extent_index, EHandle handle, uint64_t offset, uint32_t len, LAddress data_addr)
{
    ContentExtents *extents = (ContentExtents *)payload_start();
    DEBUG_ASSERT_OP(extent_index, <=, extents->n_extents);
    ContentExtent *extent = &extents->extents[extent_index];
    extent->_handle = handle;
    extent->_offset = offset;
    extent->_len = len;
    extent->_data_addr = data_addr;
}

EStoreRes DataContentBlock::export_extents(EHandle handle, uint64_t offset, uint32_t len, ExtentsAggregator *aggregator)
{
    ContentExtents *block_extents = (ContentExtents *)payload_start();
    LOOP(block_extents->n_extents, i) {
        ContentExtent *extent = &block_extents->extents[i];
        if (extent->_handle == handle && extent->overlaps(offset, len)) {
            EStoreRes res = aggregator->add_extent(extent);
            PT_RETURN(res != OK, res, "add_extent failed");
        }
    }
    return OK;
}

EStoreRes DataContentBlock::export_all(ExtentsAggregator *aggregator)
{
    ContentExtents *block_extents = (ContentExtents *)payload_start();
    LOOP(block_extents->n_extents, i) {
        EStoreRes res = aggregator->add_extent(&block_extents->extents[i]);
        PT_RETURN(res != OK, res, "add_extent failed");
    }
    return OK;
}

void DataContentBlock::trace()
{
    ContentExtents *block_extents = (ContentExtents *)payload_start();
    LOOP(block_extents->n_extents, i) {
        ContentExtent *extent = &block_extents->extents[i];
        PTC_DEBUG("extent(%lu) handle=0x%lx offset=%lu len=%u addr=0x%lx", i,
                  extent->_handle, extent->_offset, extent->_len, extent->_data_addr.as_number());
    }
}

}
