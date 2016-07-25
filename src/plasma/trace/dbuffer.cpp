/* Copyright (C) Vast Data Ltd. */
#include <cstring>

#include "dbuffer.hpp"

#include "../utils/assert.hpp"

namespace P { namespace Trace {

void Buffer::init(uint32_t size)
{
    _mem = new byte[size];
    _size = size;
    _write_index = 0;
}

void Buffer::destroy()
{
    delete[] _mem;
}

inline bool Buffer::has_room(P_DBUFFER_LENGTH_TYPE length)
{
    length += sizeof(length); // for this record's length
    length += sizeof(length); // for the next records length as the reader expects the last record to have a length byte of 0
    DEBUG_ASSERT(length <= _size);
    return _write_index + length <= _size;
}

void Buffer::write(void *data, P_DBUFFER_LENGTH_TYPE length)
{
    DEBUG_ASSERT(has_room(length));
    memcpy(_mem + _write_index, &length, sizeof(length));
    memcpy(_mem + _write_index + sizeof(length), data, length);
    _write_index += length + sizeof(length);
    length = 0;
    memcpy(_mem + _write_index, &length, sizeof(length)); // mark next record as empty
}

void Buffer::read(uint32_t offset, void *data OUT, P_DBUFFER_LENGTH_TYPE length)
{
    DEBUG_ASSERT(length > 0);
    memcpy(data, _mem + offset, length);
}

void Buffer::reset()
{
    _write_index = 0;
}

Buffer *DBuffer::get_buffer(uint64_t generation)
{
    return &_buffers[generation % _buffer_count];
}

void DBuffer::init(uint8_t buffer_count, uint32_t size)
{
    ASSERT_EQUAL(size % buffer_count, 0, "size cannot be divided by buffer_count with no remainder");
    _buffer_count = buffer_count;
    _buffers = new Buffer[buffer_count];
    _generation = 0;
    LOOP(buffer_count, i)
        _buffers[i].init(size / buffer_count);
}

void DBuffer::destroy()
{
    LOOP(_buffer_count, i)
        _buffers[i].destroy();
    delete[] _buffers;
}

void DBuffer::flush()
{
    _generation++;
    get_buffer(_generation)->reset();
}

void DBuffer::write(void *data, P_DBUFFER_LENGTH_TYPE length)
{
    ASSERT_OP(length, <=, P_DBUFFER_MAX_RECORD, "record size bigger than max");
    auto buf = get_buffer(_generation);
    if (!buf->has_room(length)) {
        flush();
        buf = get_buffer(_generation);
    }
    buf->write(data, length);
}

void DBufferReader::reset(P_DBUFFER_LENGTH_TYPE *buffers_lost OUT)
{
    uint32_t generation = _read_generation;
    _read_index = 0;
    if (_dbuf->_generation >= _dbuf->_buffer_count)
        _read_generation = _dbuf->_generation - _dbuf->_buffer_count + 1;
    else
        _read_generation = 0;
    if (buffers_lost != nullptr)
        *buffers_lost = (uint16_t) (_read_generation - generation);
}

void DBufferReader::init(DBuffer *dbuf)
{
    _dbuf = dbuf;
    reset(nullptr);
}

bool DBufferReader::overflow()
{
    ASSERT_OP(_read_generation, <=, _dbuf->_generation, "Somehow the reader got in front of the writer");
    return _dbuf->_generation - _read_generation >= _dbuf->_buffer_count;
}

DBufferReader::ReadResult DBufferReader::read(void *data OUT, P_DBUFFER_LENGTH_TYPE *length OUT, bool force)
{
    // when force==true we are allowed to read from the writer's buffer.
    if (!force && _read_generation == _dbuf->_generation)
        return ReadResult::NOTHING;

    if (overflow())
        goto overflow;

    _dbuf->get_buffer(_read_generation)->read(_read_index, length, P_DBUFFER_LENGTH_BYTES);

    if (overflow())
        goto overflow;

    if (*length == 0) {
        // when force==true and we reached the end of the buffer, there's no next buffer to go to
        ReadResult result = ReadResult::NOTHING;
        if (!force || _read_generation < _dbuf->_generation) {
            _read_generation++;
            _read_index = 0;
            result = ReadResult::NEXT;
        }
        return result;
    }

    _dbuf->get_buffer(_read_generation)->read(_read_index + P_DBUFFER_LENGTH_BYTES, data, *length);
    if (overflow())
        goto overflow;

    _read_index += *length + P_DBUFFER_LENGTH_BYTES;
    return ReadResult::SUCCESS;

overflow:
    reset(length);
    return ReadResult::OVERFLOW;
}

}}
