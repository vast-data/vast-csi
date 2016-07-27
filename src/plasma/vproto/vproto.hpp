#include "plasma/utils/types.hpp"

#pragma once

namespace P { namespace VProto {

class StructHeader {
public:
    void init(uint32_t size, uint8_t next_index)
    {
        _size = size;
        _next_index = next_index;
    }

    uint32_t get_size() { return _size; }
    uint8_t get_next_index() { return _next_index; }

private:
    uint32_t _size : 20;
    uint8_t _next_index;
    uint32_t _reserved;
};
static_assert(sizeof(StructHeader) == 8, "sizeof(StructHeader) should be 8 bytes");

class ArrayPtr {
public:
    void init(uint32_t offset, uint32_t size, uint16_t count, uint8_t next_index)
    {
        _offset = offset;
        _count = count;
        _size = size;
        _next_index = next_index;
    }

    uint32_t get_offset() { return _offset; }
    uint16_t get_count() { return _count; }
    uint32_t get_size() { return _size; }
    uint8_t get_next_index() { return _next_index; }

private:
    uint16_t _count;
    uint8_t _next_index;
    uint32_t _offset : 20;
    uint32_t _size : 20;
} __attribute__((packed, aligned(8)));
static_assert(sizeof(ArrayPtr) == 8, "sizeof(ArrayPtr) should be 8 bytes");

class RootStruct {
protected:
    StructHeader _vproto_header;
};

class EmbeddedStruct {

};

}}
