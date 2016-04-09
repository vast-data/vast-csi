/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_scheduler_internal.h
 * \brief The internal fiber scheduler API
 */
#pragma once

#include <p.h>
#include <setjmp.h>
#include "p_fiber.h"
#include "p_fiber_internal.h"

typedef struct p_scheduler p_scheduler;
struct p_scheduler {
    jmp_buf caller;
    size_t group_count;
    size_t last_group;
    p_fiber_group *groups;
    p_fiber *current_fiber;
};

extern __thread p_scheduler sched;

void p_scheduler_set_fiber_state(p_fiber *fiber, p_fiber_state state);
void __attribute__((noreturn)) p_scheduler_continue(void);
