/* Copyright (C) Vast Data Ltd. */

/*!
 */
#include <p.h>
#include <setjmp.h>

#include "p_scheduler_internal.h"

static __thread PScheduler *sched;

PScheduler *p_get_scheduler()
{
    return sched;
}

/*!
 * This function is used to find or allocate a pool of stacks. The reason to reuse the same pool
 * between several groups is to avoid cache pollution: when a fiber in one group ends and releases
 * the stack it can be reused by a new fiber in a different group.
 */
static PPool *find_or_allocate_stacks(PSchedulerConfig *config, PIndex group_index, PIndex *partition)
{
    // search for an existing group with the same stack size
    PFiberGroup *group = &sched->groups[group_index];
    PPool *pool = NULL;
    *partition = 0;
    LOOP(group_index, i)
        if (sched->groups[i].stack_size == group->stack_size) {
            pool = sched->groups[i].stacks;
            (*partition)++;
        }
    if (pool != NULL)
        return pool;

    // allocate a pool that accommodates the fiber_count of all groups with same stack_size
    PIndex num_partitions = 0;
    PIndex partitions[sched->group_count];
    LOOP_FROM(group_index, sched->group_count, i)
        if (config->fiber_groups[i].stack_size == group->stack_size)
            partitions[num_partitions++] = config->fiber_groups[i].fiber_count;
    return p_pool_partitioned_init(group->stack_size, num_partitions, partitions);
}

void p_scheduler_init(PSchedulerConfig *config)
{
    P_ASSERT(sched == NULL);
    sched = p_safe_malloc(sizeof(PScheduler));

    sched->current_fiber = NULL;
    sched->running_fiber_count = 0;
    sched->curr_job_id = 0;
    sched->group_count = config->group_count;
    sched->groups = p_safe_cache_aligned_malloc(sizeof(PFiberGroup) * (size_t) sched->group_count);

    PFiberGroupConfig *fiber_config;
    PFiberGroup *group, *last_group = NULL, *first_group = NULL;
    PIndex partitions[config->group_count];
    PIndex fibers = 0;

    LOOP(sched->group_count, i) {
        fiber_config = &config->fiber_groups[i];
        group = &sched->groups[i];
        group->index = (PIndex) i;
        group->stack_size = fiber_config->stack_size;
        group->module_id = fiber_config->module_id;
        p_dlistanchor_init(&group->ready_queue);
        partitions[i] = fiber_config->fiber_count;
        fibers += fiber_config->fiber_count;
        if (fiber_config->fiber_count > 0) {
            group->stacks = find_or_allocate_stacks(config, (PIndex) i, &group->stacks_partition);
            if (last_group == NULL)
                first_group = group;
            else
                last_group->next_group = group;
            last_group = group;
        } else {
            group->stacks = NULL;
        }
    }
    last_group->next_group = first_group;
    sched->last_group = last_group;
    sched->fiber_pool = p_pool_partitioned_init(sizeof(PFiber), config->group_count, partitions);
    sched->fiber_queues = p_dlistpool_init(fibers);
    sched->timer_queues = p_timer_queues_init();
}

void p_scheduler_destroy()
{
    P_ASSERT(sched->running_fiber_count == 0);

    PFiberGroup *fiber_group;
    LOOP(sched->group_count, i) {
        fiber_group = &sched->groups[i];
        if (fiber_group->stacks != NULL) {
            // delete all other pointers to the same stack pool
            LOOP(sched->group_count, j)
                if (i != j && sched->groups[j].stacks == fiber_group->stacks)
                    sched->groups[j].stacks = NULL;
            p_pool_destroy(fiber_group->stacks);
        }
    }
    p_timer_queues_destroy(sched->timer_queues);
    p_dlistpool_destroy(sched->fiber_queues);
    p_pool_destroy(sched->fiber_pool);
    p_free(sched->groups);
    p_free(sched);
    sched = NULL;
}

void p_scheduler_continue()
{
    PIndex fiber_index;
    PFiberGroup *group = sched->last_group;

    while (sched->running_fiber_count > 0) {
        do {
            group = group->next_group;
            PDList queue;
            p_dlist_init(&queue, &group->ready_queue, sched->fiber_queues);
            fiber_index = p_dlist_pop(&queue);
            if (fiber_index != P_INVALID_INDEX) {
                sched->last_group = group;
                p_fiber_run(p_pool_index_to_address(sched->fiber_pool, fiber_index));
            }
        } while (group != sched->last_group);

        p_timer_queues_poll(sched->timer_queues, sched);
    }
    longjmp(sched->caller, true);
}

void p_scheduler_run()
{
    if (!setjmp(sched->caller))
        p_scheduler_continue();
}
