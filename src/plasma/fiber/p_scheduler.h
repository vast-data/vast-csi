/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_scheduler.h
 * \brief The fiber scheduler API
 */
#pragma once

#include <p.h>

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

/*!
 * Initialize a scheduler. This should be executed once per pthread since
 * the scheduler is stored in thread-local storage.
 */
void p_scheduler_init(p_scheduler_config *config);
void p_scheduler_destroy(void);
void p_scheduler_run(void);
