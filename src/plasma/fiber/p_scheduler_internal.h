/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_scheduler_internal.h
 * \brief The internal fiber scheduler API
 */
#pragma once

#include <p.h>
#include <setjmp.h>

#include "p_fiber_internal.h"
#include "p_sleep_internal.h"

typedef struct p_scheduler p_scheduler;
struct p_scheduler {
    jmp_buf caller;
    p_index last_group;
    p_index group_count;
    p_fiber_group *groups;
    p_fiber *current_fiber;
    p_pool *fiber_pool;
    p_dlist *fiber_queue;
    p_index running_fiber_count;
    p_timer_queues *timer_queues;
};

p_scheduler *p_get_scheduler(void);
void __attribute__((noreturn)) p_scheduler_continue(void);
