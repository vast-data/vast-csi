#include "../fiber/p_scheduler_internal.h"

#include "p_future.h"

void p_future_init(PFuture *future OUT, void* value)
{
    future->owner = p_get_current_fiber();
    future->value = value;
    future->state = P_FUTURE_UNSET;
}

void p_future_destroy(PFuture *future)
{
    P_ASSERT(future->state == P_FUTURE_SET);
}

static bool p_future_unmark_waiting(PFuture *future)
{
    if (p_future_is_set(future)) {
        return false;
    }

    future->state = P_FUTURE_UNSET;
    return true;
}


static bool p_future_mark_waiting(PFuture *future)
{
    if (p_future_is_set(future)) {
        return false;
    }

    future->state = P_FUTURE_WAITED;
    return true;
}

bool p_future_is_set(PFuture *future)
{
    return future->state == P_FUTURE_SET;
}

void p_future_wait_subset(PFuture futures[], size_t total_count, size_t subset_count)
{
    size_t set_count = 0;
    LOOP(total_count, i) {
        if (p_future_is_set(&futures[i])) {
            set_count++;
        }
    }

    size_t first_waiting = 0;
    while (set_count < subset_count) {
        LOOP_FROM(first_waiting, total_count, curr_future) {
            if (!p_future_mark_waiting(&futures[curr_future])) {
                if (first_waiting == curr_future) {
                   first_waiting++;
                }
            }
        }

        p_fiber_suspend();

        set_count = 0;
        LOOP_FROM(first_waiting, total_count, curr_future) {
            if (!p_future_unmark_waiting(&futures[curr_future])) {
                if (first_waiting == curr_future) {
                    first_waiting++;
                }
                set_count++;
            }
        }
    }
}

void p_future_wait_any(PFuture futures[], size_t count)
{
    p_future_wait_subset(futures, count, 1);
}

void p_future_wait(PFuture *future)
{
    p_future_wait_any(future, 1);
}

void p_future_wait_all(PFuture futures[], size_t count)
{
    LOOP(count, i) {
        p_future_wait(&futures[i]);
    }
}

void p_future_set(PFuture *future)
{
    P_ASSERT(future->state != P_FUTURE_SET);
    PFutureState old_state = future->state;
    future->state = P_FUTURE_SET;
    if (old_state == P_FUTURE_WAITED) {
        p_fiber_resume(future->owner);
    }
}
