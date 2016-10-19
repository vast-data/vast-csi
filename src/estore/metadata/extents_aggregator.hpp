/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "data_content_block.hpp"

namespace EStore {

class DataExtent : public P::Extent<uint64_t> {
public:
    void init() { _node.init(); }
    void init_from(ContentExtent *content_extent) {
        init();
        copy_from(content_extent);
    }
    void copy_from(ContentExtent *content_extent) {
        _data_addr = content_extent->_data_addr;
        _offset = content_extent->_offset;
        _len = content_extent->_len;
    }

    LAddress _data_addr;
    P::IList::Node _node;
};

struct HandleExtents {
    EHandle handle;
    // TODO a more efficient implementation would be to use an interval tree
    P::IList extents_list;
};

// The ExtentsAggregator is responsible for aggregating extents from one or more handles and overwriting old extents
// with newer extents.
// TODO The current implementation is inefficient and does not have the notion of snapshots. Future implementation should be
// tree based, be able to support snapshots and grow when more meta data is added by consuming data buffers.
class ExtentsAggregator {
public:
    void init(uint64_t offset, uint32_t len);

    // add an extent, overwriting overlapping extents if found
    EStoreRes WARN_UNUSED add_extent(ContentExtent *content_extent);
    DataExtent *get_next(EHandle handle, DataExtent *extent);

    void trace();
    void sanity_check();

private:
    DataExtent *alloc();
    void free(DataExtent *extent);
    EStoreRes add_contains(DataExtent *containing_extent, ContentExtent *new_extent);
    EStoreRes add_overlaps(DataExtent *overlapping_extent, ContentExtent *new_extent, bool *content_added);
    void add_contained(DataExtent *contained_extent, ContentExtent *new_extent, bool *content_added);
    P::IList *get_handle_list(EHandle handle);

private:
    static const uint16_t MAX_EXTENTS = 1024 * 16;
    static const uint16_t MAX_HANDLES = 1024;

    uint16_t _n_used;
    DataExtent _extents[MAX_EXTENTS];
    HandleExtents _handles[MAX_HANDLES];
    P::IList _free_list;
    P::Extent<uint64_t> _boundary_extent;

};

}

