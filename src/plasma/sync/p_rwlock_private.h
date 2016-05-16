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
    PDListAnchor wait_anchor;
    uint32_t read_count;
    PRWlockType state;
};
