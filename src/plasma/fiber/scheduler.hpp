/* Copyright (C) Vast Data Ltd. */

/*!
 * \file scheduler.hpp
 * \brief The fiber scheduler API
 */
#pragma once

#include <setjmp.h>

#include "../../vdefs.hpp"
#include "../../modules/module_interface.hpp"
#include "../utils/types.hpp"
#include "../utils/compiler.hpp"
#include "../memory/pool.hpp"
#include "../data/dlist.hpp"
#include "../time.h"
#include "fiber.hpp"
#include "sleep.hpp"

namespace P {

typedef struct FiberGroupConfig FiberGroupConfig;

struct FiberGroupConfig {
    size_t stack_size;
    Index fiber_count;
    ModuleId module_id;
};

typedef struct SchedulerConfig SchedulerConfig;

struct SchedulerConfig {
    FiberGroupConfig *fiber_groups;
    Index group_count;
};

class Scheduler {

    friend class Fiber;

public:
    /*!
     * Initialize a scheduler. This should be executed once per pthread
     * since the scheduler is stored in thread-local storage.
     */
    static void init(SchedulerConfig *config);
    static void destroy();
    static void run();

    // the following functions are the internal interface used by the fiber framework
    static Scheduler *get() {
        return _sched;
    }
    static TimerQueues *get_timer_queues() {
        return &(get()->_timer_queues);
    }
    static void NO_RETURN schedule();

private:
    Pool *find_or_allocate_stacks(SchedulerConfig *config, Index group_index, Index *partition OUT);

    jmp_buf _caller;
    Pool _fiber_pool;
    DList::Pool _fiber_queues;
    TimerQueues _timer_queues;
    Fiber *_current_fiber;
    FiberGroup *_last_group;
    FiberGroup *_groups;
    Index _group_count;
    Index _running_fiber_count;
    uint32_t _curr_job_id;

    static thread_local Scheduler *_sched;
};

}
