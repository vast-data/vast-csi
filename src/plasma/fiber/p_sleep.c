/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <pthread.h>

#include "p_sleep_internal.h"
#include "p_scheduler_internal.h"

#define MILLI_TO_MICRO(n) ((n) * 1000)
#define MICRO_TO_NANO(n) ((n) * 1000)
#define NANO_TO_MICRO(n) ((n) / 1000)
#define SEC_TO_MICRO(n) (MILLI_TO_MICRO(n) * 1000)
#define NO_PENDING_FIBERS UINT64_MAX

static uint64_t interval_to_micro[] = {MILLI_TO_MICRO(100),
                                       SEC_TO_MICRO(1),
                                       SEC_TO_MICRO(10),
                                       SEC_TO_MICRO(60)};

struct PTimerQueues {
    uint64_t wakeup_time;
    PDListAnchor queues[SLEEP_INTERVAL_COUNT];
};

PTimerQueues *p_timer_queues_init()
{
    PTimerQueues *timer_queues = p_safe_malloc(sizeof(PTimerQueues));
    LOOP(SLEEP_INTERVAL_COUNT, i)
        p_dlistanchor_init(&timer_queues->queues[i]);
    timer_queues->wakeup_time = NO_PENDING_FIBERS;
    return timer_queues;
}

void p_timer_queues_destroy(PTimerQueues *timer_queues)
{
    p_free(timer_queues);
}

uint64_t p_sleep(PSleepInterval interval)
{
    PTimerQueues *timer_queues = p_get_scheduler()->timer_queues;
    uint64_t start_time = p_get_time_nano();
    timer_queues->wakeup_time = MIN(timer_queues->wakeup_time,
                                    start_time + MICRO_TO_NANO(interval_to_micro[interval]));
    p_fiber_suspend_and_queue(&timer_queues->queues[interval]);
    return (uint64_t) NANO_TO_MICRO(p_get_time_nano() - start_time);
}

uint64_t p_sleep_multi(PSleepInterval interval, uint32_t count)
{
    uint64_t total = interval_to_micro[interval] * count;
    uint64_t micros = 0;
    while (total > micros) {
        micros += p_sleep(interval);
    }
    return micros;
}

void p_timer_queues_poll(PTimerQueues *timer_queues, PScheduler *scheduler)
{
    uint64_t time;

    if (timer_queues->wakeup_time == NO_PENDING_FIBERS || (time = p_get_time_nano()) < timer_queues->wakeup_time)
        return;

    timer_queues->wakeup_time = NO_PENDING_FIBERS;
    LOOP(SLEEP_INTERVAL_COUNT, i) {
        PDListAnchor* anchor = &timer_queues->queues[i];
        PDList queue;
        p_dlist_init(&queue, anchor, scheduler->fiber_queues);
        while (!p_dlist_is_empty(&queue)) {
            PFiber *fiber = p_pool_index_to_address(scheduler->fiber_pool, p_dlist_get_first(&queue));
            uint64_t fiber_wakeup = fiber->switch_time + MICRO_TO_NANO(interval_to_micro[i]);
            if (fiber_wakeup <= time) {
                p_fiber_pop_and_resume(anchor);
            } else {
                timer_queues->wakeup_time = MIN(timer_queues->wakeup_time, fiber_wakeup);
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
