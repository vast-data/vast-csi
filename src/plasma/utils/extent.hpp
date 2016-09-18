/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <cstdint>
#include <cstddef>
#include "assert.hpp"

namespace P {

template <typename T>
class Extent {
public:
    bool overlaps(T offset, uint32_t len) {
        return !((offset + len) <= _offset || (_offset + _len) <= offset);
    }

    // return true if the extent is adjacent or overlapping
    bool adjacent_overlap(T offset, uint32_t len) {
        Extent<T> extent = { _offset, _len + 1};
        return extent.overlaps(offset, len + 1);
    }

    bool overlaps(Extent<T> *other) {
        return overlaps(other->_offset, other->_len);
    }

    bool contained_by(Extent<T> *other) {
        return other->_offset <= _offset && _offset + _len <= other->_offset + other->_len;
    }

    bool contains(Extent<T> *other) { return other->contained_by(this); }

    bool strictly_contains(Extent<T> *other) {
        return _offset < other->_offset && other->_offset + other->_len < _offset + _len;
    }

    // remove parts of this extent that don't intersect with the given extent
    void intersect(Extent<T> *other) {
        DEBUG_ASSERT(overlaps(other));
        if (_offset < other->_offset) {
            _len -= (other->_offset - _offset);
            _offset = other->_offset;
        }
        uint32_t other_end = other->_offset + other->_len;
        if (other_end < _offset + _len) {
            _len = other_end - _offset;
        }
    }

    // remove parts of this extent that intersect with the given extent
    void crop(Extent<T> *other) {
        DEBUG_ASSERT(overlaps(other));
        if (_offset < other->_offset) {
            _len  = other->_offset - _offset;
        } else {
            uint32_t end = _offset + _len;
            _offset = other->_offset + other->_len;
            _len = end - _offset;
        }
    }

    void merge(T offset, uint32_t len) {
        DEBUG_ASSERT(adjacent_overlap(offset, len));
        uint32_t end = _offset + _len;
        if (offset < _offset) {
            _len += _offset - offset;
            _offset = offset;
        }
        if (end < offset + len) {
            _len = (offset + len) - _offset;
        }
    }

    T _offset;
    uint32_t _len;
};

}
