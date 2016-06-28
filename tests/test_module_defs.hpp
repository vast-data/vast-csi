#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <stdint.h>

typedef struct AddArgs {
    uint64_t a;
    uint64_t b;
} AddArgs;

typedef struct MultiplyArgs {
    uint64_t a;
    uint64_t b;
    uint64_t c;
} MultiplyArgs;

typedef struct AddRes {
    uint64_t sum;
} AddRes;
typedef AddRes MultiplyRes;
