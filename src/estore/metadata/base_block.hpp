/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <stdint.h>
#include "estore/io/estore_io.hpp"
#include "plasma/utils/compiler.hpp"
#include "estore/defs/estore_defs.hpp"

namespace EStore {

// TODO add back pointer to parent block
struct BlockHeader {
    uint8_t type;
    uint8_t version;
    uint16_t used_bytes;
} PACKED;

// helper macros to deal with blocks holding variable size content list, assumes each content struct has a len field
// and that the list is finalized with a content struct with len 0
#define NEXT_CONTENT(TYPE, X) ((TYPE *)((char*)X + (sizeof(TYPE) + X->len)))
#define TRAVERSE_CONTENT_FROM(CONTENT_TYPE, X, FROM) \
    for (CONTENT_TYPE *X = (CONTENT_TYPE *)FROM; X->len > 0; X = NEXT_CONTENT(CONTENT_TYPE, X))
#define TRAVERSE_CONTENT(CONTENT_TYPE, X) TRAVERSE_CONTENT_FROM(CONTENT_TYPE, X, payload_start())

#define ZERO_LAST(CONTENT_TYPE) \
    DEBUG_ASSERT(&(((CONTENT_TYPE *)(payload_end()))->len) < (uint16_t *)(get_buffer()->get_data() + get_size())) \
    ((CONTENT_TYPE *)(payload_end()))->len = 0;

class BaseBlock {
public:
    virtual void init(MIOBuffer *buffer);
    uint16_t space_left() { return get_size() - get_used_bytes(); }
    BlockHeader *get_header() const { return (BlockHeader *)header_offset(); }
    MIOBuffer *get_buffer() const { return _buffer; }
    // replace the internal buffer with the given buffer
    void replace_buffer(MIOBuffer *buffer);
    uint16_t get_size() const { return _buffer->get_data_size(); }
    uint16_t get_used_bytes() const { return get_header()->used_bytes; }
    BlockType get_type() const { return (BlockType)get_header()->type; }
    void set_version(uint8_t version) { get_header()->version = version; }
    void set_buffer(MIOBuffer *buffer);

protected:
    P::byte *header_offset() const { return _buffer->get_data(); }
    P::byte *payload_start() const { return _buffer->get_data() + sizeof(BlockHeader); }
    P::byte *payload_end() const { return _buffer->get_data() + get_header()->used_bytes - sizeof(uint16_t); }
    void add_used_bytes(uint16_t bytes) { get_header()->used_bytes += bytes; }
    void set_type(BlockType type) { get_header()->type = (uint8_t)type; }

private:
    MIOBuffer *_buffer;
};

}
