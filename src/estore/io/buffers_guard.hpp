/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore_io.hpp"

namespace EStore {

class BuffersGuard {
public:
    BuffersGuard(EStoreIO *eio, uint16_t n_buffers) {
        DEBUG_ASSERT(n_buffers < MAX_BUFFERS);
        _eio = eio;
        _n_buffers = n_buffers;
        _used_buffers = 0;
        _eio->alloc_md_buffers(n_buffers, _buffers);
    }

    ~BuffersGuard() {
        free();
        _n_buffers = 0;
    }

    void free() {
        _eio->free_md_buffers(_n_buffers, _buffers);
    }

    MIOBuffer *get_next() {
        DEBUG_ASSERT(_used_buffers < _n_buffers);
        MIOBuffer *res = &_buffers[_used_buffers];
        _used_buffers++;
        return res;
    }

private:
    static const uint16_t MAX_BUFFERS = 16;
    EStoreIO *_eio;
    uint16_t _n_buffers;
    uint16_t _used_buffers;
    MIOBuffer _buffers[MAX_BUFFERS];
};

class DataBuffersGuard {
public:
    DataBuffersGuard(EStoreIO *eio, P::IO::IOVecs *iovecs) {
        _eio = eio;
        _iovecs = iovecs;
    }

    ~DataBuffersGuard() {
        free();
    }

    void free() {
        if (_iovecs) {
            _eio->free_data_buffers(_iovecs);
        }
    }

    void disown() {
        _iovecs = nullptr;
    }

private:
    EStoreIO *_eio;
    P::IO::IOVecs *_iovecs;
};


}



