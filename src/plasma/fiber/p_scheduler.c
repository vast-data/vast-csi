/* Copyright (C) Vast Data Ltd. */

/*!
 */
#include <p.h>
#include <setjmp.h>
#include "p_scheduler_internal.h"
#include "p_fiber_internal.h"
#include "p_sleep_internal.h"

__thread p_scheduler sched;

static p_pool *find_or_allocate_stacks(p_scheduler_config *config, size_t group_index)
{
    // search for an existing group with the same stack size
    p_fiber_group *group = &sched.groups[group_index];
    LOOP(group_index, i)
        if (sched.groups[i].stack_size == group->stack_size)
            return sched.groups[i].stacks;

    // allocate a pool that accomodates the fiber_count of all groups with same stack_size
    p_index fibers = config->fiber_groups[group_index].fiber_count;
    LOOP_FROM(group_index + 1, sched.group_count, i)
        if (config->fiber_groups[i].stack_size == group->stack_size)
            fibers += config->fiber_groups[i].fiber_count;
    return p_pool_init(fibers, group->stack_size);
}

void p_scheduler_init(p_scheduler_config *config)
{
    sched.current_fiber = NULL;
    sched.last_group = 0;
    sched.group_count = config->group_count;
    sched.groups = p_safe_cache_aligned_alloc(sizeof(p_fiber_group) * sched.group_count);

    p_fiber_group_config *fiber_config;
    p_fiber_group *group;

    LOOP(sched.group_count, i) {
        fiber_config = &config->fiber_groups[i];
        group = &sched.groups[i];
        group->stack_size = fiber_config->stack_size;
        group->fibers = p_pool_init(fiber_config->fiber_count, sizeof(p_fiber));
        group->queue = p_dlist_init(fiber_config->fiber_count);
        LOOP(STATE_COUNT, j) {
            group->states[j] = P_DLIST_ANCHOR_INIT;
        }
        group->stacks = find_or_allocate_stacks(config, i);
    }

    p_sleep_init();
}

void p_scheduler_destroy()
{
    p_fiber_group *fiber_group;
    LOOP(sched.group_count, i) {
        fiber_group = &sched.groups[i];
        p_dlist_destroy(fiber_group->queue);
        p_pool_destroy(fiber_group->fibers);
        if (fiber_group->stacks != NULL) {
            // delete all other pointers to the same stack pool
            LOOP(sched.group_count, j)
                if (i != j && sched.groups[j].stacks == fiber_group->stacks)
                    sched.groups[j].stacks = NULL;
            p_pool_destroy(fiber_group->stacks);
        }
    }
    p_free(sched.groups);
}

void p_scheduler_set_fiber_state(p_fiber *fiber, p_fiber_state state)
{
    fiber->state = state;
    p_dlist_append(fiber->group->queue,
                   &fiber->group->states[state],
                   p_pool_address_to_index(fiber->group->fibers, fiber));
}

void p_scheduler_change_fiber_state(p_fiber *fiber, p_fiber_state state)
{
    p_dlist_remove(fiber->group->queue,
                   &fiber->group->states[fiber->state],
                   p_pool_address_to_index(fiber->group->fibers, fiber));
    p_scheduler_set_fiber_state(fiber, state);
}

void p_scheduler_continue()
{
    p_index fiber_index;
    size_t group_index = sched.last_group;
    p_fiber_group *group;
    bool fibers_pending = true;
    while (fibers_pending) {
        fibers_pending = false;
        do {
            group_index = (group_index + 1) % sched.group_count;
            group = &sched.groups[group_index];
            fiber_index = p_dlist_pop(group->queue, &group->states[STATE_READY]);
            if (fiber_index != P_INVALID_INDEX) {
                sched.last_group = group_index;
                p_fiber_run(p_pool_index_to_address(group->fibers, fiber_index));
            }
            if (!fibers_pending)
                fibers_pending = !p_dlist_is_empty(group->queue, group->states[STATE_JOIN]) ||
                    !p_dlist_is_empty(group->queue, group->states[STATE_SLEEP_100_MILLI]) ||
                    !p_dlist_is_empty(group->queue, group->states[STATE_SLEEP_1_SECOND]) ||
                    !p_dlist_is_empty(group->queue, group->states[STATE_SLEEP_10_SECOND]) ||
                    !p_dlist_is_empty(group->queue, group->states[STATE_SLEEP_1_MINUTE]);
        } while (group_index != sched.last_group);
        p_sleep_poll(group);
    }
    longjmp(sched.caller, true);
}

void p_scheduler_run()
{
    if (!setjmp(sched.caller))
        p_scheduler_continue();
}
