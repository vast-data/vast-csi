#include "p_ring.h"

struct PRing {
    uint8_t *buffer;
    uint32_t write_index;
    uint32_t read_index;
    uint32_t size;
};

PRing *p_ring_init(uint32_t size)
{
    PRing *ring = p_safe_malloc(sizeof(PRing));
    ring->size = size;
    ring->buffer = p_safe_cache_aligned_malloc(size);
    ring->write_index = 0;
    ring->read_index = 0;
    return ring;
}

void p_ring_destroy(PRing *ring)
{
    p_free(ring->buffer);
    p_free(ring);
}

static inline void make_room(PRing *ring, uint32_t length)
{
    uint32_t available = (ring->size + ring->write_index - ring->read_index) % ring->size;
    while (available < length) {
        uint8_t record_length = *(ring->buffer + ring->read_index);
        ring->read_index = (ring->read_index + record_length) % ring->size;
        available += record_length;
    }
}

static void write_chunk(PRing *ring, uint8_t *data, uint8_t length)
{
    uint32_t end = ring->write_index + length;
    if (end < ring->size) {
        memcpy(ring->buffer + ring->write_index, data, length);
        ring->write_index += length;
    } else {
        memcpy(ring->buffer + ring->write_index, data, end % ring->size);
        memcpy(ring->buffer, data + end % ring->size, end - ring->size);
        ring->write_index = end - ring->size;
    }
}

void p_ring_write(PRing *ring, uint8_t *data, uint8_t length)
{
    P_ASSERT(length < ring->size);
    make_room(ring, length + 1);
    write_chunk(ring, &length, sizeof(uint8_t));
    write_chunk(ring, data, length);
}
