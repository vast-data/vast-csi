/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber_internal.h
 * \brief The internal fiber API
 */
#pragma once

#include <p.h>
#include <setjmp.h>

typedef enum {
    FIBER_STATE_READY,
    FIBER_STATE_RUNNING,
    FIBER_STATE_SUSPENDED,
    FIBER_STATE_FREE
} PFiberState;

typedef struct PFiberGroup PFiberGroup;
struct PFiberGroup {
    PIndex index;
    size_t stack_size;
    PDlistAnchor ready_queue;
    PPool *stacks;
    PIndex stacks_partition;
    PFiberGroup *next_group;
    ModuleId module_id;
};

struct PFiber {
    jmp_buf jmp_buf;
    void (*func)(void *arg);
    void *arg;
    void *stack;
    PFiber *parent;
    PFiberGroup *group;
    PFiberState state; // currently used for debug purposes
    uint64_t switch_time; // updated when a fiber is resumed or suspended
    union {
        uint32_t join_count;
        PRWlockType rw_lock_type;
    };
};

#define P_FIBER_STACK_UNDERFLOW_MAGIC 0xDEADBEEF

/*!
 * Return the currently running fiber.
 */
PFiber *p_get_current_fiber(void);

/*!
 * Resume a fiber. Should be used by providers or sync primitives.
 */
void p_fiber_resume(PFiber *fiber);

/*!
 * Resume a fiber. Should be used by providers or sync primitives.
 * This function can be used to resume a fiber and deque it from a provider's
 * queue at the same time.
 */
PFiber *p_fiber_pop_and_resume(PDlistAnchor *anchor);

/*!
 * Get the next fiber to be popped without popping it.
 */
PFiber *p_fiber_queue_peek(PDlistAnchor *anchor);

/*!
 * Should be called from a provider or sync primitive in the context of a running fiber.
 */
void p_fiber_suspend(void);

/*!
 * Should be called from a provider or sync primitive in the context of a running fiber.
 * This function accepts a queue argument for suspending the fiber and storing it in a queue at the same time.
 */
void p_fiber_suspend_and_queue(PDlistAnchor *queue);

/*!
 * Run a fiber. Should be called from the scheduler.
 */
void p_fiber_run(PFiber *fiber);

/*!
 * Destroy a fiber and release its resources.
 */
void p_fiber_destroy(PFiber *fiber);
