#include "data_content_block.hpp"

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
    DEBUG_ASSERT(len > 0);
    ContentExtents *extents = (ContentExtents *)payload_start();
    ContentExtent *extent = &extents->extents[extents->n_extents];
    if (space_left() < sizeof(ContentExtent)) {
        PTC_DEBUG("out of space space_left=%hu", space_left());
        trace();
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

EStoreRes DataContentBlock::get_extents(EHandle handle, uint64_t offset, uint32_t len, uint16_t *n_extents,
                                        ContentExtent *extents)
{
    ContentExtents *block_extents = (ContentExtents *)payload_start();
    uint16_t max_extents = *n_extents;
    *n_extents = 0;
    LOOP(block_extents->n_extents, i) {
        ContentExtent *extent = &block_extents->extents[i];
        if (extent->_handle == handle && extent->overlaps(offset, len)) {
            if (*n_extents == max_extents) {
                return EStoreRes::NO_MEM;
            }
            extents[*n_extents] = *extent;
            (*n_extents)++;
        }
    }
    return OK;
}

EStoreRes DataContentBlock::export_extents(EHandle handle, uint64_t offset, uint32_t len, ExtentsContainer *extents_container)
{
    ContentExtents *block_extents = (ContentExtents *)payload_start();
    LOOP(block_extents->n_extents, i) {
        ContentExtent *extent = &block_extents->extents[i];
        if (extent->_handle == handle && extent->overlaps(offset, len)) {
            EStoreRes res = extents_container->add_extent(extent);
            PT_RETURN(res != OK, res, "add_extent failed");
        }
    }
    return OK;
}

void DataContentBlock::trace()
{
    ContentExtents *block_extents = (ContentExtents *)payload_start();
    LOOP(block_extents->n_extents, i) {
        ContentExtent *extent = &block_extents->extents[i];
        PTC_DEBUG("extent(%lu) offset=%lu len=%u addr=0x%lx", i, extent->_offset, extent->_len, extent->_data_addr.as_number());
    }
}

void ExtentsContainer::init(uint64_t offset, uint32_t len)
{
    _extents_list.init();
    _free_list.init();
    _n_used = 0;
    _container_extent._offset = offset;
    _container_extent._len = len;
}

DataExtent *ExtentsContainer::alloc()
{
    if (_n_used < MAX_EXTENTS) {
        return &_extents[_n_used++];
    }
    if (!_free_list.empty()) {
        printf("free alloc\n");
        P::IList::Node *element = _free_list.get_first();
        element->remove();
        DataExtent *res = p_container_of(element, DataExtent, _node);
        return res;
    }
    return nullptr;
}

void ExtentsContainer::free(DataExtent *extent)
{
    _free_list.append(&extent->_node);
}

EStoreRes ExtentsContainer::add_contains(DataExtent *containing_extent, ContentExtent *new_extent)
{
    PT_DEV(DATA, "CONTAINS\t- offset=%lu len=%u addr=0x%lx",
           containing_extent->_offset, containing_extent->_len, containing_extent->_data_addr.as_number());
    // overwrite the middle of an existing extent, need to split it and place the new one in the middle
    DataExtent *mid_data_extent = alloc();
    DataExtent *end_data_extent = alloc();
    PT_RETURN(mid_data_extent == nullptr || end_data_extent == nullptr, EStoreRes::NO_MEM, "out of space");
    mid_data_extent->init_from(new_extent);
    end_data_extent->init();
    end_data_extent->_data_addr = containing_extent->_data_addr;
    end_data_extent->_offset = mid_data_extent->_offset + mid_data_extent->_len;
    end_data_extent->_data_addr.offset += end_data_extent->_offset - containing_extent->_offset;
    end_data_extent->_len = containing_extent->_offset + containing_extent->_len - end_data_extent->_offset;
    containing_extent->_len = mid_data_extent->_offset - containing_extent->_offset;
    containing_extent->_node.append(&mid_data_extent->_node);
    mid_data_extent->_node.append(&end_data_extent->_node);
    return OK;
}

void ExtentsContainer::add_contained(DataExtent *contained_extent, ContentExtent *new_extent, bool *content_added)
{
    PT_DEV(DATA, "CONTAINED_BY\t- offset=%lu len=%u addr=0x%lx",
           contained_extent->_offset, contained_extent->_len, contained_extent->_data_addr.as_number());
    // full overwrite
    if (*content_added) {
        // the content block was already added just need to remove this one
        contained_extent->_node.remove();
        free(contained_extent);
    } else {
        contained_extent->copy_from(new_extent);
    }
    *content_added = true;
}

EStoreRes ExtentsContainer::add_overlaps(DataExtent *overlapping_extent, ContentExtent *new_extent, bool *content_added)
{
    PT_DEV(DATA, "OVERLAP\t\t- offset=%lu len=%u addr=0x%lx",
           overlapping_extent->_offset, overlapping_extent->_len, overlapping_extent->_data_addr.as_number());

    // partial overwrite, crop the existing extent and add the new one according to
    overlapping_extent->crop(new_extent);
    if (!(*content_added)) {
        DataExtent *alloc_extent = alloc();
        PT_RETURN(alloc_extent == nullptr, EStoreRes::NO_MEM, "out of space");
        alloc_extent->init_from(new_extent);
        if (alloc_extent->_offset < overlapping_extent->_offset) {
            overlapping_extent->_node.prepend(&alloc_extent->_node);
            // fix address offset
            overlapping_extent->_data_addr.offset += overlapping_extent->_offset - alloc_extent->_offset;
        } else {
            overlapping_extent->_node.append(&alloc_extent->_node);
        }
    }
    *content_added = true;
    return OK;
}

EStoreRes ExtentsContainer::add_extent(ContentExtent *content_extent)
{
    PT_DEV(DATA, "ADDING\t\t- offset=%lu len=%u addr=0x%lx",
           content_extent->_offset, content_extent->_len, content_extent->_data_addr.as_number());
    if (content_extent->_offset < _container_extent._offset) {
        // fix address offset
        content_extent->_data_addr.offset += _container_extent._offset - content_extent->_offset;
    }
    content_extent->intersect(&_container_extent);

    bool content_added = false;
    ILIST_ITER_SAFE(&_extents_list, element) {
        DataExtent *curr_extent = p_container_of(element, DataExtent, _node);
        if (curr_extent->strictly_contains(content_extent)) {
            return add_contains(curr_extent, content_extent);
        }
        if (curr_extent->contained_by(content_extent)) {
            add_contained(curr_extent, content_extent, &content_added);
            continue;
        }
        if (curr_extent->overlaps(content_extent)) {
            EStoreRes res = add_overlaps(curr_extent, content_extent, &content_added);
            PT_RETURN(res != OK, res, "add_overlaps failed");
            continue;
        }
        if (curr_extent->_offset > content_extent->_offset) {
            if (content_added) {
                PT_DEV(DATA, "ADD PREV- CONTENT ALREADY ADDED");
                return OK;
            }
            PT_DEV(DATA, "ADD PREV\t\t- curr_extent offset=%lu len=%u addr=0x%lx",
                   curr_extent->_offset, curr_extent->_len, curr_extent->_data_addr.as_number());
            // append before the first element that is bigger than the new one
            DataExtent *new_extent = alloc();
            PT_RETURN(new_extent == nullptr, EStoreRes::NO_MEM, "out of space");
            new_extent->init_from(content_extent);
            curr_extent->_node.prepend(&new_extent->_node);
            return OK;
        }
    }
    // append at the end
    if (content_added) {
        PT_DEV(DATA, "ADD LAST- CONTENT ALREADY ADDED");
        return OK;
    }
    PT_DEV(DATA, "ADD LAST");
    DataExtent *new_extent = alloc();
    PT_RETURN(new_extent == nullptr, EStoreRes::NO_MEM, "out of space");
    new_extent->init_from(content_extent);
    _extents_list.get_last()->append(&new_extent->_node);
    return OK;
}

DataExtent *ExtentsContainer::get_next(DataExtent *extent)
{
    if (extent == nullptr) {
        if (_extents_list.empty()) {
            return nullptr;
        } else {
            P::IList::Node *node = _extents_list.get_first();
            return p_container_of(node, DataExtent, _node);
        }
    }
    P::IList::Node *node = extent->_node.next();
    if (_extents_list.is_end(node)) {
        return nullptr;
    }
    return p_container_of(node, DataExtent, _node);
}

void ExtentsContainer::trace()
{
    PT_DEBUG(DATA, "tracing extents offset=%lu len=%u", _container_extent._offset, _container_extent._len);
    ILIST_ITER(&_extents_list, element) {
        DataExtent *data_extent = p_container_of(element, DataExtent, _node);
        PT_DEBUG(DATA, "extent offset=%lu len=%u addr=0x%lx addr_offset=%lu",
               data_extent->_offset, data_extent->_len, data_extent->_data_addr.as_number(), data_extent->_data_addr.offset);
    }
}

void ExtentsContainer::sanity_check()
{
    DataExtent *prev = nullptr;
    ILIST_ITER(&_extents_list, element) {
        DataExtent *data_extent = p_container_of(element, DataExtent, _node);
        if (prev == nullptr) {
            prev = data_extent;
            continue;
        }
        ASSERT(!data_extent->overlaps(prev));
        ASSERT(prev->_offset < data_extent->_offset);
        prev = data_extent;
    }
}


}