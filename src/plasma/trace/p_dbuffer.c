#include "p_dbuffer.h"

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

static bool buffer_has_room(Buffer *buf, uint8_t length)
{
    // leave room for the record, its length and the length of the next record
    P_DEBUG_ASSERT(length + 2 < buf->size);
    return buf->write_index + length + 2 < buf->size;
}

static void buffer_write(Buffer *buf, void *data, uint8_t length)
{
    P_DEBUG_ASSERT(buffer_has_room(buf, length));
    buf->mem[buf->write_index] = length;
    memcpy(buf->mem + buf->write_index + 1, data, length);
    buf->write_index += length + 1;
}

static void buffer_read(Buffer *buf, uint32_t offset, uint8_t *out_data, uint8_t length)
{
    P_DEBUG_ASSERT(length > 0);
    memcpy(out_data, buf->mem + offset, length);
}

static void buffer_reset(Buffer *buf)
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
    P_ASSERT(length > 0 && length <= UINT8_MAX);
    Buffer *buf = current_buffer(dbuf);
    if (!buffer_has_room(buf, length)) {
        dbuf->generation++;
        buf = current_buffer(dbuf);
        buffer_reset(buf);
    }
    buffer_write(buf, data, length);
}

static void reader_reset(PDbufferReader *reader)
{
    reader->read_index = 0;
    if (reader->dbuf->generation >= BUFFER_COUNT)
        reader->generation = reader->dbuf->generation - BUFFER_COUNT + 1;
    else
        reader->generation = 0;
}

void p_dbuffer_reader_init(PDbufferReader *reader, PDbuffer *dbuf)
{
    reader->dbuf = dbuf;
    reader_reset(reader);
}

static bool reader_overflow(PDbufferReader *reader)
{
    return reader->dbuf->generation - reader->generation >= BUFFER_COUNT;
}

PDbufferReadResult p_dbuffer_read(PDbufferReader *reader, void *out_data, uint8_t *out_length, bool force)
{
    if (!force && reader->generation == reader->dbuf->generation)
        return PDBUFFER_READ_NOTHING;

    if (reader_overflow(reader))
        goto overflow;

    buffer_read(current_buffer(reader->dbuf), reader->read_index, out_length, 1);

    if (reader_overflow(reader))
        goto overflow;

    if (*out_length == 0) {
        reader->generation++;
        reader->read_index = 0;
        return PDBUFFER_READ_NOTHING;
    }

    buffer_read(current_buffer(reader->dbuf), reader->read_index + 1, out_data, *out_length);
    if (reader_overflow(reader))
        goto overflow;

    reader->read_index += *out_length + 1;
    return PDBUFFER_READ_SUCCESS;

overflow:
    reader_reset(reader);
    return PDBUFFER_READ_OVERFLOW;
}
