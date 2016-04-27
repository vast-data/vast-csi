#pragma once

#include <p.h>

typedef enum {
    P_RWLOCK_FREE,
    P_RWLOCK_READ,
    P_RWLOCK_WRITE
} PRWlockType;

typedef struct PRWlock PRWlock;

struct PRWlock {
    PFiber *writer; // isn't required, used for debugging
    PDlistAnchor wait_anchor;
    uint32_t read_count;
    PRWlockType state;
};

#define P_RWLOCK_INIT {                     \
        .writer = NULL,                     \
        .wait_anchor = P_DLIST_ANCHOR_INIT, \
        .read_count = 0,                    \
        .state = P_RWLOCK_FREE              \
    }
