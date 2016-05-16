#pragma once

#include <p.h>

typedef enum {
    P_EVENT_CLEARED,
    P_EVENT_SET
} PEventState;

typedef struct PEvent PEvent;

struct PEvent {
    PDListAnchor wait_anchor;
    PEventState state;
};

#define P_EVENT_INIT {                         \
        .wait_anchor = P_DLIST_ANCHOR_INIT,    \
        .state = P_EVENT_CLEARED,              \
    }
