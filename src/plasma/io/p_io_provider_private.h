/* Copyright (C) Vast Data Ltd. */
#pragma once

#include <stddef.h>
#include "../data/p_dlist.h"

typedef struct PDevIO PDevIO;

typedef struct PIOProvider PIOProvider;

struct PIOProvider {
    PDList active_devices;
    PDListAnchor active_devices_anchor;
    size_t device_count;
    PDevIO *devices;
};
