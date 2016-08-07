/* Copyright (C) Vast Data Ltd. */
#include "scheduler.hpp"

#include "plasma/utils/assert.hpp"
#include "plasma/utils/compiler.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/memory/alloc.hpp"

namespace P {

thread_local Scheduler *Scheduler::_sched = nullptr;

/*!
 * This function is used to find or allocate a pool of stacks. The reason to reuse the same pool
 * between several groups is to avoid cache pollution: when a fiber in one groupends and releases
 * the stack it can be reused by a new fiber in a different group.
 */
Pool *Scheduler::find_or_allocate_stacks(SchedulerConfig *config, Index group_index, Index *partition OUT) {
    // search for an existing group with the same stack size
    FiberGroup *group = &_groups[group_index];
    Pool *pool = nullptr;
    *partition = 0;
    LOOP(group_index, i)
        if (_groups[i].stack_size == group->stack_size) {
            pool = _groups[i].stacks;
            (*partition)++;
        }
    if (pool != nullptr)
        return pool;

    // allocate a pool that accommodates the fiber_count of all groups with same stack_size
    Index num_partitions = 0;
    Index partitions[config->group_count];
    LOOP_FROM(group_index, config->group_count, i)
        if (config->fiber_groups[i].stack_size == group->stack_size) {
            partitions[num_partitions++] = config->fiber_groups[i].fiber_count;
        }
    pool = new Pool();

    size_t block_size = group->stack_size;
#ifdef DEBUG
    block_size += PAGE_SIZE_BYTES;
#endif
    pool->partitioned_init(block_size, num_partitions, partitions, PAGE_SIZE_BYTES);

    return pool;
}

void Scheduler::init(SchedulerConfig *config) {
    ASSERT_EQUAL(_sched, nullptr);

    _sched = new Scheduler();
    _sched->_current_fiber = nullptr;
    _sched->_running_fiber_count = 0;
    _sched->_curr_job_id = 1; // save 0 for trace records not created within fibers
    _sched->_group_count = config->group_count;
    _sched->_groups = new FiberGroup[_sched->_group_count];

    FiberGroupConfig *fiber_config;
    FiberGroup *group, *last_group = nullptr;
    _sched->_first_group = nullptr;
    Index partitions[config->group_count];
    Index fibers = 0;

    LOOP_TYPE(Index, _sched->_group_count, i) {
        fiber_config = &config->fiber_groups[i];
        group = &_sched->_groups[i];
        group->index = i;
        group->stack_size = fiber_config->stack_size;
        group->module_id = fiber_config->module_id;
        group->ready_queue.init();
        partitions[i] = fiber_config->fiber_count;
        fibers += fiber_config->fiber_count;
        if (fiber_config->fiber_count > 0) {
            group->stacks = _sched->find_or_allocate_stacks(config, i, &group->stacks_partition);
            if (last_group == nullptr)
                _sched->_first_group = group;
            else
                last_group->next_group = group;
            last_group = group;
        } else {
            group->stacks = nullptr;
        }
    }
    last_group->next_group = _sched->_first_group;
    _sched->_last_group = last_group;
    _sched->_fiber_pool.partitioned_init(sizeof(Fiber), config->group_count, partitions);
    _sched->_fiber_queues.init(fibers);
    _sched->_timer_queues.init();
}

void Scheduler::destroy() {
    ASSERT_OP(_sched, !=, nullptr, "Scheduler not initialized");
    ASSERT_OP(_sched->_running_fiber_count, ==, 0, "Destroying scheduler while fibers are running");

    FiberGroup *fiber_group;
    LOOP(_sched->_group_count, i) {
        fiber_group = &_sched->_groups[i];
        if (fiber_group->stacks != nullptr) {
            // delete all other pointers to the same stack pool
            LOOP(_sched->_group_count, j)
                if (i != j && _sched->_groups[j].stacks == fiber_group->stacks)
                    _sched->_groups[j].stacks = nullptr;
            fiber_group->stacks->destroy();
        }
    }
    _sched->_timer_queues.destroy();
    _sched->_fiber_queues.destroy();
    _sched->_fiber_pool.destroy();
    delete[] _sched->_groups;
    delete _sched->_sched;
    _sched = nullptr;
}

void NO_RETURN Scheduler::schedule() {
    Index fiber_index;
    FiberGroup *group = _sched->_last_group;
    Fiber *fiber;

    while (_sched->_running_fiber_count > 0) {
        group = group->next_group;
        if (group == _sched->_first_group) {
            _sched->_timer_queues.poll();
        }
        DList queue;
        queue.init(&group->ready_queue, &_sched->_fiber_queues);
        fiber_index = queue.pop();
        if (fiber_index != INVALID_INDEX) {
            _sched->_last_group = group;
            fiber = (Fiber*) _sched->_fiber_pool.index_to_address(fiber_index);
            fiber->run();
            // this will never execute
        }
    }
    longjmp(_sched->_caller, true);
}

void Scheduler::run() {
    ASSERT_OP(_sched, !=, nullptr, "Scheduler not initialized");
    if (!setjmp(_sched->_caller))
        schedule();
}

}
