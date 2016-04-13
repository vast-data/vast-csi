/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber_internal.h
 * \brief The internal fiber API
 */
#pragma once

#include <p.h>
#include <setjmp.h>

typedef enum {
    STATE_READY,
    STATE_RUNNING,
    STATE_SUSPENDED,
    STATE_FREE
} p_fiber_state;

typedef struct p_fiber_group p_fiber_group;
struct p_fiber_group {
    p_index index;
    size_t stack_size;
    p_dlist_anchor ready_queue;
    p_pool *stacks;
    p_index stacks_partition;
};

struct p_fiber {
    jmp_buf jmp_buf;
    void (*func)(void *arg);
    void *arg;
    void *stack;
    p_fiber *parent;
    p_fiber_group *group;
    p_fiber_state state; // currently used for debug purposes
    uint64_t switch_time; // updated when a fiber is resumed or suspended
    union {
        uint32_t join_count;
    };
};

#define P_FIBER_STACK_UNDERFLOW_MAGIC 0xDEADBEEF

/*!
 * Return the currently running fiber.
 */
p_fiber *p_get_current_fiber(void);

/*!
 * Resume a fiber. Should be used by providers or sync primitives.
 */
void p_fiber_resume(p_fiber *fiber);

/*!
 * Resume a fiber. Should be used by providers or sync primitives.
 * This function can be used to resume a fiber and deque it from a provider's
 * queue at the same time.
 */
void p_fiber_resume_and_deque(p_fiber *fiber, p_dlist_anchor *anchor);

/*!
 * Should be called from a provider or sync primitive in the context of a running fiber.
 */
void p_fiber_suspend(void);

/*!
 * Should be called from a provider or sync primitive in the context of a running fiber.
 * This function accepts a queue argument for suspending the fiber and storing it in a queue at the same time.
 */
void p_fiber_suspend_and_queue(p_dlist_anchor *queue);

/*!
 * Run a fiber. Should be called from the scheduler.
 */
void p_fiber_run(p_fiber *fiber);

/*!
 * Destroy a fiber and release its resources.
 */
void p_fiber_destroy(p_fiber *fiber);
