/* Copyright (C) Vast Data Ltd. */
#pragma once

#include <p.h>

typedef struct PQlock PQlock;

struct PQlock {
    PFiber *owner;
    PDListAnchor  anchor;
};
