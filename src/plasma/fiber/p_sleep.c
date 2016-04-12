/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <pthread.h>

#include "p_scheduler_internal.h"
#include "p_sleep_internal.h"

#define MILLI_TO_MICRO(n) ((n) * 1000)
#define MICRO_TO_NANO(n) ((n) * 1000)
#define NANO_TO_MICRO(n) ((n) / 1000)
#define SEC_TO_MICRO(n) (MILLI_TO_MICRO(n) * 1000)
#define NO_PENDING_FIBERS UINT64_MAX
#define FIRST_SLEEP_STATE STATE_SLEEP_100_MILLI

static uint64_t interval_to_micro[] = {MILLI_TO_MICRO(100),
                                       SEC_TO_MICRO(1),
                                       SEC_TO_MICRO(10),
                                       SEC_TO_MICRO(60)};

void p_sleep_init()
{
    LOOP(p_get_scheduler()->group_count, i)
        p_get_scheduler()->groups[i].wakeup_time = NO_PENDING_FIBERS;
}

uint64_t p_sleep(p_sleep_interval interval)
{
    p_scheduler *scheduler = p_get_scheduler();
    uint64_t start_time = p_get_time_nano();
    scheduler->groups[scheduler->last_group].wakeup_time = MIN(scheduler->groups[scheduler->last_group].wakeup_time,
                                                               start_time + MICRO_TO_NANO(interval_to_micro[interval]));
    p_fiber_suspend((p_fiber_state) (interval + FIRST_SLEEP_STATE));
    return (uint64_t) NANO_TO_MICRO(p_get_time_nano() - start_time);
}

uint64_t p_sleep_multi(p_sleep_interval interval, uint32_t count)
{
    uint64_t total = interval_to_micro[interval] * count;
    uint64_t micros = 0;
    while (total > micros) {
        micros += p_sleep(interval);
    }
    return micros;
}

void p_sleep_poll(p_fiber_group *group)
{
    uint64_t time;

    if (group->wakeup_time == NO_PENDING_FIBERS || (time = p_get_time_nano()) < group->wakeup_time)
        return;

    group->wakeup_time = NO_PENDING_FIBERS;
    LOOP(INTERVAL_COUNT, i) {
        p_dlist_anchor anchor = group->states[i + FIRST_SLEEP_STATE];
        while (!p_dlist_is_empty(group->queue, anchor)) {
            p_fiber *fiber = p_pool_index_to_address(group->fibers, anchor);
            uint64_t fiber_wakeup = fiber->switch_time + MICRO_TO_NANO(interval_to_micro[i]);
            if (fiber_wakeup <= time) {
                p_scheduler_change_fiber_state(fiber, STATE_READY);
                anchor = group->states[i + FIRST_SLEEP_STATE];
            } else {
                group->wakeup_time = MIN(group->wakeup_time, fiber_wakeup);
                break;
            }
        }
    }
}

uint64_t p_fast_sleep(uint64_t usecs)
{
    uint64_t time, start_time = p_get_time_nano();
    while ((time = p_get_time_nano()) < start_time + MICRO_TO_NANO(usecs)) {
        p_fiber_yield();
    }
    return NANO_TO_MICRO(time - start_time);
}
