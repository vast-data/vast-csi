#include "extents_aggregator.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

using EStoreRes::OK;

void ExtentsAggregator::init(uint64_t offset, uint32_t len)
{
    LOOP(MAX_HANDLES, i) {
        _handles[i].handle = INVALID_EHANDLE;
        _handles[i].extents_list.init();
    }
    _free_list.init();
    _n_used = 0;
    _boundary_extent._offset = offset;
    _boundary_extent._len = len;
}

DataExtent *ExtentsAggregator::alloc()
{
    if (_n_used < MAX_EXTENTS) {
        return &_extents[_n_used++];
    }
    if (!_free_list.empty()) {
        P::IList::Node *element = _free_list.get_first();
        element->remove();
        DataExtent *res = p_container_of(element, DataExtent, _node);
        return res;
    }
    return nullptr;
}

void ExtentsAggregator::free(DataExtent *extent)
{
    _free_list.append(&extent->_node);
}

EStoreRes ExtentsAggregator::add_contains(DataExtent *containing_extent, ContentExtent *new_extent)
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

void ExtentsAggregator::add_contained(DataExtent *contained_extent, ContentExtent *new_extent, bool *content_added)
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

EStoreRes ExtentsAggregator::add_overlaps(DataExtent *overlapping_extent, ContentExtent *new_extent, bool *content_added)
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

EStoreRes ExtentsAggregator::add_extent(ContentExtent *content_extent)
{
    PTC_DEV("ADDING\t\t- handle=0x%lx offset=%lu len=%u addr=0x%lx",
            content_extent->_handle, content_extent->_offset, content_extent->_len, content_extent->_data_addr.as_number());
    if (_boundary_extent._offset < UINT64_MAX) {
        if (content_extent->_offset < _boundary_extent._offset) {
            // fix address offset
            content_extent->_data_addr.offset += _boundary_extent._offset - content_extent->_offset;
        }
        content_extent->intersect(&_boundary_extent);
    }

    P::IList *extents_list = get_handle_list(content_extent->_handle);
    bool content_added = false;
    ILIST_ITER_SAFE(extents_list, element) {
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
    extents_list->get_last()->append(&new_extent->_node);
    return OK;
}

DataExtent *ExtentsAggregator::get_next(EHandle handle, DataExtent *extent)
{
    P::IList *extents_list = get_handle_list(handle);
    if (extent == nullptr) {
        if (extents_list->empty()) {
            return nullptr;
        } else {
            P::IList::Node *node = extents_list->get_first();
            return p_container_of(node, DataExtent, _node);
        }
    }
    P::IList::Node *node = extent->_node.next();
    if (extents_list->is_last(node)) {
        return nullptr;
    }
    return p_container_of(node, DataExtent, _node);
}

void ExtentsAggregator::trace()
{
    PT_DEBUG(DATA, "tracing extents offset=%lu len=%u", _boundary_extent._offset, _boundary_extent._len);
    LOOP(MAX_HANDLES, i) {
        ILIST_ITER(&_handles[i].extents_list, element) {
            DataExtent *data_extent = p_container_of(element, DataExtent, _node);
            PT_DEBUG(DATA, "extent offset=%lu len=%u addr=0x%lx addr_offset=%lu",
                     data_extent->_offset, data_extent->_len, data_extent->_data_addr.as_number(),
                     data_extent->_data_addr.offset);
        }
    }
}

void ExtentsAggregator::sanity_check()
{
    DataExtent *prev = nullptr;
    LOOP(MAX_HANDLES, i) {
        ILIST_ITER(&_handles[i].extents_list, element) {
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

P::IList *ExtentsAggregator::get_handle_list(EHandle handle)
{
    HandleExtents *handle_extents = &_handles[handle % MAX_HANDLES];
    if (handle_extents->handle == INVALID_EHANDLE) {
        handle_extents->handle = handle;
    } else if (handle_extents->handle != handle) {
        // TODO support more handles
        PANIC("handle slot taken");
    }
    return &handle_extents->extents_list;
}

}
