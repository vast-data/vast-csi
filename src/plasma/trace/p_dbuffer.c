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

static inline bool buffer_has_room(Buffer *buf, uint8_t length)
{
    length++; // for this record's length
    length++; // for the next records length as the reader expects the last record to have a length byte of 0
    P_DEBUG_ASSERT(length < buf->size);
    return buf->write_index + length < buf->size;
}

static void buffer_write(Buffer *buf, void *data, uint8_t length)
{
    P_DEBUG_ASSERT(buffer_has_room(buf, length));
    buf->mem[buf->write_index] = length;
    memcpy(buf->mem + buf->write_index + 1, data, length);
    buf->write_index += length + 1;
    buf->mem[buf->write_index] = 0; // mark next record as empty
}

static void buffer_read(Buffer *buf, uint32_t offset, uint8_t *out_data, uint8_t length)
{
    P_DEBUG_ASSERT(length > 0);
    memcpy(out_data, buf->mem + offset, length);
}

static inline void buffer_reset(Buffer *buf)
{
    buf->write_index = 0;
}

#define BUFFER_COUNT 2

struct PDbuffer {
    Buffer buffers[BUFFER_COUNT];
    volatile uint32_t generation;
};

static inline Buffer *current_buffer(PDbuffer *dbuf)
{
    return &dbuf->buffers[dbuf->generation % BUFFER_COUNT];
}

PDbuffer *p_dbuffer_init(uint32_t size)
{
    PDbuffer *dbuf = p_safe_malloc(sizeof(PDbuffer));
    dbuf->generation = 0;
    LOOP(BUFFER_COUNT, i)
        buffer_init(&dbuf->buffers[i], size / BUFFER_COUNT);
    return dbuf;
}

void p_dbuffer_destroy(PDbuffer *dbuf)
{
    LOOP(BUFFER_COUNT, i)
        buffer_destroy(&dbuf->buffers[i]);
    p_free(dbuf);
}

void p_dbuffer_write(PDbuffer *dbuf, void *data, uint8_t length)
{
    P_ASSERT(length > 0);
    Buffer *buf = current_buffer(dbuf);
    if (!buffer_has_room(buf, length)) {
        dbuf->generation++;
        buf = current_buffer(dbuf);
        buffer_reset(buf);
    }
    buffer_write(buf, data, length);
}

static void reader_reset(PDbufferReader *reader, uint8_t *buffers_lost OUT)
{
    reader->read_index = 0;
    if (buffers_lost != NULL)
        *buffers_lost = (uint8_t) (reader->dbuf->generation - reader->generation - 1);
    if (reader->dbuf->generation >= BUFFER_COUNT)
        reader->generation = reader->dbuf->generation - BUFFER_COUNT + 1;
    else
        reader->generation = 0;
}

void p_dbuffer_reader_init(PDbufferReader *reader, PDbuffer *dbuf)
{
    reader->dbuf = dbuf;
    reader_reset(reader, NULL);
}

static inline bool reader_overflow(PDbufferReader *reader)
{
    return reader->dbuf->generation - reader->generation >= BUFFER_COUNT;
}

PDbufferReadResult p_dbuffer_read(PDbufferReader *reader, void *data OUT, uint8_t *length OUT, bool force)
{
    if (!force && reader->generation == reader->dbuf->generation)
        return PDBUFFER_READ_NOTHING;

    if (reader_overflow(reader))
        goto overflow;

    buffer_read(current_buffer(reader->dbuf), reader->read_index, length, 1);

    if (reader_overflow(reader))
        goto overflow;

    if (*length == 0) {
        reader->generation++;
        reader->read_index = 0;
        return PDBUFFER_READ_NOTHING;
    }

    buffer_read(current_buffer(reader->dbuf), reader->read_index + 1, data, *length);
    if (reader_overflow(reader))
        goto overflow;

    reader->read_index += *length + 1;
    return PDBUFFER_READ_SUCCESS;

overflow:
    reader_reset(reader, length);
    return PDBUFFER_READ_OVERFLOW;
}
