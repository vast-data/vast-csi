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

typedef struct PScheduler PScheduler;
struct PScheduler {
    jmp_buf caller;
    PIndex group_count;
    PFiberGroup *last_group;
    PFiberGroup *groups;
    PFiber *current_fiber;
    PPool *fiber_pool;
    PDListPool *fiber_queues;
    PIndex running_fiber_count;
    uint64_t curr_job_id;
    PTimerQueues *timer_queues;
};

PScheduler *p_get_scheduler(void);
void NO_RETURN p_scheduler_continue(void);
