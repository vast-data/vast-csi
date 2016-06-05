/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_dbuffer.h
 * \brief a double buffer that can be used as a lockless queue with variable sized records
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

#include "../memory/p_alloc.h"
#include "../utils.h"

#define P_DBUFFER_LENGTH_TYPE uint16_t
#define P_DBUFFER_LENGTH_BYTES sizeof(P_DBUFFER_LENGTH_TYPE)
// the buffer with the largest record still needs to hold its size and an empty size indicating its the last
#define P_DBUFFER_MAX_RECORD (UINT16_MAX - (P_DBUFFER_LENGTH_BYTES * 2))

typedef struct PDbuffer PDbuffer;

/*!
 * Initialize a dbuffer.
 *
 * \param buffer_count number of underlying buffers
 * \param size size of the buffer in bytes. Would be divided by buffer_count and passed to each buffer.
 */
PDbuffer *p_dbuffer_init(uint8_t buffer_count, uint32_t size);
void p_dbuffer_destroy(PDbuffer *dbuf);

/*!
 * Write a record to the dbuffer. This function always succeeds and always writes the data
 */
void p_dbuffer_write(PDbuffer *dbuf, void *data, P_DBUFFER_LENGTH_TYPE length);

typedef struct PDbufferReader PDbufferReader;

struct PDbufferReader {
    PDbuffer *dbuf;
    uint32_t generation;
    uint32_t read_index;
};

void p_dbuffer_reader_init(PDbufferReader *reader, PDbuffer *dbuf);

typedef enum {
    PDBUFFER_READ_SUCCESS,
    PDBUFFER_READ_NOTHING,
    PDBUFFER_READ_NEXT,
    PDBUFFER_READ_OVERFLOW,
} PDbufferReadResult;

/*!
 * Read a record.
 *
 * \param dbuf_reader the reader.
 * \param data out pointer to a buffer big enough to hold the maximal trace record.
 * \param length out pointer to a length. Upon SUCCESS will contain the size of the record. Upon OVERFLOW will contain the number of lost buffers.
 * \param force allow the reader to read from the writer's current buffer. This is usually passed during teardown, only after the writer has stopped writing, otherwise we could lose traces.
 * \return SUCCESS means a record has been written, NOTHING means there's no data to read and the user should try again later, NEXT means we moved to the next buffer and should retry.
 */
PDbufferReadResult p_dbuffer_read(PDbufferReader *dbuf_reader, void *data OUT, P_DBUFFER_LENGTH_TYPE *length OUT, bool force);
