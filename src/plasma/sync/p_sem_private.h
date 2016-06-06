#pragma once

#include <stdint.h>
#include "../data/p_dlist.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PSem PSem;

struct PSem {
    uint32_t value;
    PDListAnchor wait_anchor;
};

#define P_SEM_INIT(value) {                 \
        .value = value,                     \
        .wait_anchor = P_DLIST_ANCHOR_INIT, \
    }

#ifdef __cplusplus
}
#endif

