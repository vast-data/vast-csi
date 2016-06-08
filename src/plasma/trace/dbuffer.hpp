/* Copyright (C) Vast Data Ltd. */

/*!
 * \file dbuffer.hpp
 * \brief a double buffer that can be used as a lockless queue with variable sized records
 */
#pragma once

#include "../utils/types.hpp"
#include "../utils/compiler.hpp"

#define P_DBUFFER_LENGTH_TYPE uint16_t
#define P_DBUFFER_LENGTH_BYTES sizeof(P_DBUFFER_LENGTH_TYPE)
// the buffer with the largest record still needs to hold its size and an empty size indicating its the last
#define P_DBUFFER_MAX_RECORD (UINT16_MAX - (P_DBUFFER_LENGTH_BYTES * 2))

namespace P { namespace Trace {

class Buffer {
public:
    void init(uint32_t size);
    void destroy();
    bool has_room(P_DBUFFER_LENGTH_TYPE length);
    void write(byte data[], P_DBUFFER_LENGTH_TYPE length);
    void read(uint32_t offset, byte data[] OUT, P_DBUFFER_LENGTH_TYPE length);
    void reset();

private:
    byte *_mem;
    uint32_t _size;
    uint32_t _write_index;
};

class DBuffer {
    friend class DBufferReader;

public:
    void init(uint8_t buffer_count, uint32_t size);
    void destroy();
    void write(byte data[], P_DBUFFER_LENGTH_TYPE length);

private:
    Buffer *current_buffer();

    Buffer *_buffers;
    volatile uint32_t _generation;
    uint8_t _buffer_count;
};

class DBufferReader {
public:
    enum class ReadResult : byte {
        SUCCESS,
        NOTHING,
        NEXT,
        OVERFLOW,
    };

    void init(DBuffer *dbuf);

    /*!
     * Read a record.
     *
     * \param data out pointer to a buffer big enough to hold the maximal trace record.
     * \param length out pointer to a length. Upon SUCCESS will contain the size of the record. Upon OVERFLOW will contain the number of lost buffers.
     * \param force allow the reader to read from the writer's current buffer. This is usually passed during teardown, only after the writer has stopped writing, otherwise we could lose traces.
     * \return SUCCESS means a record has been written, NOTHING means there's no data to read and the user should try again later, NEXT means we moved to the next buffer and should retry.
     */
    ReadResult read(byte data[], P_DBUFFER_LENGTH_TYPE *length, bool force);

private:
    void reset(P_DBUFFER_LENGTH_TYPE *buffers_lost OUT);
    bool overflow();

    DBuffer *_dbuf;
    uint32_t _generation;
    uint32_t _read_index;
};

}}
