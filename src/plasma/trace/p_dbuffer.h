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

typedef struct PDbuffer PDbuffer;

PDbuffer *p_dbuffer_init(uint32_t size);
void p_dbuffer_destroy(PDbuffer *dbuf);
void p_dbuffer_write(PDbuffer *dbuf, void *data, uint8_t length);

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
    PDBUFFER_READ_OVERFLOW,
} PDbufferReadResult;

PDbufferReadResult p_dbuffer_read(PDbufferReader *dbuf_reader, void *data OUT, uint8_t *length OUT, bool force);
