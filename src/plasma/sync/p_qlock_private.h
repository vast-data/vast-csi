/* Copyright (C) Vast Data Ltd. */
#pragma once

#include <p.h>

typedef struct PQlock PQlock;

struct PQlock {
    PFiber *owner;
    PDlistAnchor anchor;
};

#define P_QLOCK_INIT {.anchor = P_DLIST_ANCHOR_INIT, .owner = NULL}
