/* Copyright (C) Vast Data Ltd. */

/*!
 */
#include <p.h>
#include <setjmp.h>

#include "p_scheduler_internal.h"

static __thread p_scheduler *sched;

p_scheduler *p_get_scheduler()
{
    return sched;
}

/*!
 * This function is used to find or allocate a pool of stacks. The reason to reuse the same pool
 * between several groups is to avoid cache pollution: when a fiber in one group ends and releases
 * the stack it can be reused by a new fiber in a different group.
 */
static p_pool *find_or_allocate_stacks(p_scheduler_config *config, p_index group_index, p_index *partition)
{
    // search for an existing group with the same stack size
    p_fiber_group *group = &sched->groups[group_index];
    p_pool *pool = NULL;
    *partition = 0;
    LOOP(group_index, i)
        if (sched->groups[i].stack_size == group->stack_size) {
            pool = sched->groups[i].stacks;
            (*partition)++;
        }
    if (pool != NULL)
        return pool;

    // allocate a pool that accomodates the fiber_count of all groups with same stack_size
    p_index num_partitions = 0;
    p_index partitions[sched->group_count];
    LOOP_FROM(group_index, sched->group_count, i)
        if (config->fiber_groups[i].stack_size == group->stack_size)
            partitions[num_partitions++] = config->fiber_groups[i].fiber_count;
    return p_pool_partitioned_init(group->stack_size, num_partitions, partitions);
}

void p_scheduler_init(p_scheduler_config *config)
{
    P_ASSERT(sched == NULL);
    sched = p_safe_malloc(sizeof(p_scheduler));

    sched->current_fiber = NULL;
    sched->running_fiber_count = 0;
    sched->last_group = 0;
    sched->group_count = config->group_count;
    sched->groups = p_safe_cache_aligned_malloc(sizeof(p_fiber_group) * (size_t) sched->group_count);

    p_fiber_group_config *fiber_config;
    p_fiber_group *group;
    p_index partitions[config->group_count];
    p_index fibers = 0;

    LOOP(sched->group_count, i) {
        fiber_config = &config->fiber_groups[i];
        group = &sched->groups[i];
        group->index = (p_index) i;
        group->stack_size = fiber_config->stack_size;
        group->ready_queue = P_DLIST_ANCHOR_INIT;
        partitions[i] = fiber_config->fiber_count;
        fibers += fiber_config->fiber_count;
        group->stacks = find_or_allocate_stacks(config, (p_index) i, &group->stacks_partition);
    }

    sched->fiber_pool = p_pool_partitioned_init(sizeof(p_fiber), config->group_count, partitions);
    sched->fiber_queue = p_dlist_init(fibers);
    sched->timer_queues = p_timer_queues_init();
}

void p_scheduler_destroy()
{
    p_fiber_group *fiber_group;
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
    p_dlist_destroy(sched->fiber_queue);
    p_pool_destroy(sched->fiber_pool);
    p_free(sched->groups);
    p_free(sched);
    sched = NULL;
}

void p_scheduler_continue()
{
    p_index fiber_index;
    p_index group_index = sched->last_group;
    p_fiber_group *group;

    while (sched->running_fiber_count > 0) {
        do {
            group_index = (group_index + 1) % sched->group_count;
            group = &sched->groups[group_index];
            fiber_index = p_dlist_pop(sched->fiber_queue, &group->ready_queue);
            if (fiber_index != P_INVALID_INDEX) {
                sched->last_group = group_index;
                p_fiber_run(p_pool_index_to_address(sched->fiber_pool, fiber_index));
            }
        } while (group_index != sched->last_group);

        p_timer_queues_poll(sched->timer_queues, sched);
    }
    longjmp(sched->caller, true);
}

void p_scheduler_run()
{
    if (!setjmp(sched->caller))
        p_scheduler_continue();
}
