#include <p.h>

typedef enum {
    PDBUFFER_READ_SUCCESS,
    PDBUFFER_READ_NOTHING,
    PDBUFFER_READ_OVERFLOW,
} PDbufferReadResult;

typedef struct PDbuffer PDbuffer;

PDbuffer *p_dbuffer_init(uint32_t size);
void p_dbuffer_destroy(PDbuffer *dbuf);
void p_dbuffer_write(PDbuffer *dbuf, void *data, uint8_t length);

typedef struct PDbufferReader PDbufferReader;

struct PDbufferReader {
    PDbuffer *dbuf;
    uint32_t generation;
    uint8_t read_index;
};

void p_dbuffer_reader_init(PDbufferReader *reader, PDbuffer *dbuf);
PDbufferReadResult p_dbuffer_read(PDbufferReader *dbuf_reader, void *out_data, uint8_t *out_length, bool force);
