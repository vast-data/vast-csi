#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/data/ilist.hpp"
#include "plasma/utils/extent.hpp"
#include "base_block.hpp"

namespace EStore {

class ExtentsContainer;

class ContentExtent : public P::Extent<uint64_t> {
public:
    LAddress _data_addr;
    // TODO optimize by keeping each handle only once in the block
    EHandle _handle;
} PACKED;
ASSERT_NO_VTABLE(ContentExtent);;

struct ContentExtents {
    uint16_t n_extents;
    ContentExtent extents[0];
};

class DataContentBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;
    // add an extent to the end of the block
    EStoreRes WARN_UNUSED add_extent(EHandle handle, uint64_t offset, uint32_t len, LAddress data_addr);
    EStoreRes WARN_UNUSED get_extents(EHandle handle, uint64_t offset, uint32_t len, uint16_t *n_extents INOUT,
                                      ContentExtent *extents OUT);
    EStoreRes WARN_UNUSED export_extents(EHandle handle, uint64_t offset, uint32_t len,
                                         ExtentsContainer *extents_container);
    void trace();
};

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

class ExtentsContainer {
public:
    void init(uint64_t offset, uint32_t len);

    // add an extent overwriting overlapping extents if found
    EStoreRes WARN_UNUSED add_extent(ContentExtent *content_extent);
    DataExtent *get_next(DataExtent *extent);

    void trace();
    void sanity_check();

private:
    DataExtent *alloc();
    void free(DataExtent *extent);
    EStoreRes add_contains(DataExtent *containing_extent, ContentExtent *new_extent);

private:
    static const uint16_t MAX_EXTENTS = 1024;
    uint16_t _n_used;
    DataExtent _extents[MAX_EXTENTS];
    P::IList _extents_list;
    P::IList _free_list;
    P::Extent<uint64_t> _container_extent;

    void add_contained(DataExtent *contained_extent, ContentExtent *new_extent, bool *content_added);

    EStoreRes add_overlaps(DataExtent *overlapping_extent, ContentExtent *new_extent, bool *content_added);
};


}

