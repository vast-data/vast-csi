#pragma once

#include <p.h>

typedef struct PSem PSem;

struct PSem {
    uint32_t value;
    PDlistAnchor wait_anchor;
};

#define P_SEM_INIT(value) {                 \
        .value = value,                     \
        .wait_anchor = P_DLIST_ANCHOR_INIT, \
    }
