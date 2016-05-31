/* Copyright (C) Vast Data Ltd. */
#pragma once

#include <p.h>

typedef struct PDevIO PDevIO;

typedef struct PIOProvider PIOProvider;

struct PIOProvider {
    PDList active_devices;
    PDListAnchor active_devices_anchor;
    size_t device_count;
    PDevIO *devices;
};
