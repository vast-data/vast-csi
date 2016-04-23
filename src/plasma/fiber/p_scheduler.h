/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_scheduler.h
 * \brief The fiber scheduler API
 */
#pragma once

#include <p.h>

typedef struct PFiberGroupConfig PFiberGroupConfig;

struct PFiberGroupConfig {
    size_t stack_size;
    PIndex fiber_count;
    ModuleId module_id;
};

typedef struct PSchedulerConfig PSchedulerConfig;

struct PSchedulerConfig {
    PFiberGroupConfig *fiber_groups;
    PIndex group_count;
};

/*!
 * Initialize a scheduler. This should be executed once per pthread since
 * the scheduler is stored in thread-local storage.
 */
void p_scheduler_init(PSchedulerConfig *config);
void p_scheduler_destroy(void);
void p_scheduler_run(void);
