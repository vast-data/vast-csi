/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber.h
 * \brief A user-level thread implementation.
 *
 */
#pragma once

#include <p.h>
#include <setjmp.h>

typedef struct p_fiber p_fiber;

typedef struct p_fiber_group_config p_fiber_group_config;

struct p_fiber_group_config {
    size_t stack_size;
    p_index fiber_count;
};

typedef struct p_scheduler_config p_scheduler_config;

struct p_scheduler_config {
    p_fiber_group_config *fiber_groups;
    size_t group_count;
};

p_fiber *p_fiber_init(size_t group_index, void (*func)(void *arg), void *arg);
void p_fiber_yield(void);

void p_scheduler_init(p_scheduler_config *config);
void p_scheduler_destroy(void);
void p_scheduler_run(void);
