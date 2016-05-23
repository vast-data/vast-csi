#pragma once

#include <p.h>

typedef enum {
    P_FUTURE_UNSET,
    P_FUTURE_WAITED,
    P_FUTURE_SET
} PFutureState;

typedef struct PFuture PFuture;

struct PFuture {
    PFiber *owner;
    PFutureState state;
    void* value;
};
