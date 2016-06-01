#include <string.h>

#include "p_dbuffer.h"

#include "../p_assert.h"
#include "../utils.h"

typedef struct Buffer Buffer;

struct Buffer {
    uint8_t *mem;
    uint32_t size;
    uint32_t write_index;
};

static void buffer_init(Buffer *buf, uint32_t size)
{
    buf->mem = p_safe_malloc(size);
    buf->size = size;
    buf->write_index = 0;
}

static void buffer_destroy(Buffer *buf)
{
    p_free(buf->mem);
}

static inline bool buffer_has_room(Buffer *buf, P_DBUFFER_LENGTH_TYPE length)
{
    length += sizeof(length); // for this record's length
    length += sizeof(length); // for the next records length as the reader expects the last record to have a length byte of 0
    P_DEBUG_ASSERT(length <= buf->size);
    return buf->write_index + length <= buf->size;
}

static void buffer_write(Buffer *buf, void *data, P_DBUFFER_LENGTH_TYPE length)
{
    P_DEBUG_ASSERT(buffer_has_room(buf, length));
    memcpy(buf->mem + buf->write_index, &length, sizeof(length));
    memcpy(buf->mem + buf->write_index + sizeof(length), data, length);
    buf->write_index += length + sizeof(length);
    length = 0;
    memcpy(buf->mem + buf->write_index, &length, sizeof(length)); // mark next record as empty
}

static void buffer_read(Buffer *buf, uint32_t offset, void *out_data, P_DBUFFER_LENGTH_TYPE length)
{
    P_DEBUG_ASSERT(length > 0);
    memcpy(out_data, buf->mem + offset, length);
}

static inline void buffer_reset(Buffer *buf)
{
    buf->write_index = 0;
}

struct PDbuffer {
    Buffer *buffers;
    volatile uint32_t generation;
    uint8_t buffer_count;
};

static inline Buffer *current_buffer(PDbuffer *dbuf)
{
    return &dbuf->buffers[dbuf->generation % dbuf->buffer_count];
}

PDbuffer *p_dbuffer_init(uint8_t buffer_count, uint32_t size)
{
    PDbuffer *dbuf = p_safe_malloc(sizeof(PDbuffer));
    dbuf->buffer_count = buffer_count;
    dbuf->buffers = p_safe_malloc(sizeof(Buffer) * buffer_count);
    dbuf->generation = 0;
    LOOP(buffer_count, i)
        buffer_init(&dbuf->buffers[i], size / buffer_count);
    return dbuf;
}

void p_dbuffer_destroy(PDbuffer *dbuf)
{
    LOOP(dbuf->buffer_count, i)
        buffer_destroy(&dbuf->buffers[i]);
    p_free(dbuf);
}

void p_dbuffer_write(PDbuffer *dbuf, void *data, P_DBUFFER_LENGTH_TYPE length)
{
    P_ASSERT(length <= P_DBUFFER_MAX_RECORD);
    Buffer *buf = current_buffer(dbuf);
    if (!buffer_has_room(buf, length)) {
        dbuf->generation++;
        buf = current_buffer(dbuf);
        buffer_reset(buf);
    }
    buffer_write(buf, data, length);
}

static void reader_reset(PDbufferReader *reader, P_DBUFFER_LENGTH_TYPE *buffers_lost OUT)
{
    uint32_t generation = reader->generation;
    reader->read_index = 0;
    if (reader->dbuf->generation >= reader->dbuf->buffer_count)
        reader->generation = reader->dbuf->generation - reader->dbuf->buffer_count + 1;
    else
        reader->generation = 0;
    if (buffers_lost != NULL)
        *buffers_lost = (uint16_t) (reader->generation - generation);
}

void p_dbuffer_reader_init(PDbufferReader *reader, PDbuffer *dbuf)
{
    reader->dbuf = dbuf;
    reader_reset(reader, NULL);
}

static inline bool reader_overflow(PDbufferReader *reader)
{
    return reader->dbuf->generation - reader->generation >= reader->dbuf->buffer_count;
}

PDbufferReadResult p_dbuffer_read(PDbufferReader *reader, void *data OUT, P_DBUFFER_LENGTH_TYPE *length OUT, bool force)
{
    if (!force && reader->generation == reader->dbuf->generation)
        return PDBUFFER_READ_NOTHING;

    if (reader_overflow(reader))
        goto overflow;

    buffer_read(current_buffer(reader->dbuf), reader->read_index, length, P_DBUFFER_LENGTH_BYTES);

    if (reader_overflow(reader))
        goto overflow;

    if (*length == 0) {
        reader->generation++;
        reader->read_index = 0;
        if (force)
            return PDBUFFER_READ_NOTHING;
        return PDBUFFER_READ_NEXT;
    }

    buffer_read(current_buffer(reader->dbuf), reader->read_index + P_DBUFFER_LENGTH_BYTES, data, *length);
    if (reader_overflow(reader))
        goto overflow;

    reader->read_index += *length + P_DBUFFER_LENGTH_BYTES;
    return PDBUFFER_READ_SUCCESS;

overflow:
    reader_reset(reader, length);
    return PDBUFFER_READ_OVERFLOW;
}
