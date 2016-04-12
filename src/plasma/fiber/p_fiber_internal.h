/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber_internal.h
 * \brief The internal fiber API
 */
#pragma once

#include <p.h>

typedef enum {
    STATE_READY,
    STATE_RUNNING,
    STATE_JOIN,
    STATE_SLEEP_100_MILLI,
    STATE_SLEEP_1_SECOND,
    STATE_SLEEP_10_SECOND,
    STATE_SLEEP_1_MINUTE,
    STATE_COUNT
} p_fiber_state;

typedef struct p_fiber_group p_fiber_group;
struct p_fiber_group {
    p_dlist_anchor states[STATE_COUNT];
    uint64_t wakeup_time;
    size_t stack_size;
    p_pool *stacks;
    p_pool *fibers;
    p_dlist *queue;
};

struct p_fiber {
    jmp_buf jmp_buf;
    void (*func)(void *arg);
    void *arg;
    void *stack;
    p_fiber *parent;
    p_fiber_group *group;
    p_fiber_state state;
    uint64_t switch_time;
    union {
        uint32_t join_count;
    };
};

p_fiber *p_get_current_fiber(void);
void p_fiber_resume(p_fiber *fiber);
void p_fiber_suspend(p_fiber_state state);
void p_fiber_run(p_fiber *fiber);
void p_fiber_destroy(p_fiber *fiber);
