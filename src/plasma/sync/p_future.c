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

static bool p_future_try_unmark_waiting(PFuture *future)
{
    if (p_future_is_set(future)) {
        return false;
    }

    future->state = P_FUTURE_UNSET;
    return true;
}

static bool p_future_try_mark_waiting(PFuture *future)
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

void p_future_wait_subset(PFuture futures[], uint32_t total_count, uint32_t subset_count)
{
    uint32_t set_count = 0;
    PFiber* this_fiber = p_get_current_fiber();

    LOOP(total_count, i) {
        P_ASSERT(futures[i].owner == this_fiber);
        if (p_future_is_set(&futures[i])) {
            set_count++;
        }
    }

    if(set_count < subset_count) {
        LOOP(total_count, i) {
            p_future_try_mark_waiting(&futures[i]);
        }

        this_fiber->waited_future_count = subset_count - set_count;

        p_fiber_suspend();

        uint32_t set_count_after_suspend = 0;
        LOOP(total_count, i) {
            if(!p_future_try_unmark_waiting(&futures[i])) {
                set_count_after_suspend++;
            }
        }

        P_ASSERT(set_count_after_suspend >= subset_count);
    }
}

void p_future_wait_any(PFuture futures[], uint32_t count)
{
    p_future_wait_subset(futures, count, 1);
}

void p_future_wait_all(PFuture futures[], uint32_t count)
{
    p_future_wait_subset(futures, count, count);
}

void p_future_wait(PFuture *future)
{
    p_future_wait_any(future, 1);
}

void p_future_set(PFuture *future)
{
    P_ASSERT(future->state != P_FUTURE_SET);
    PFutureState old_state = future->state;
    future->state = P_FUTURE_SET;
    if (old_state == P_FUTURE_WAITED) {
        P_ASSERT(future->owner->waited_future_count > 0);
        future->owner->waited_future_count--;
        if (future->owner->waited_future_count == 0) {
            p_fiber_resume(future->owner);
        }
    }
}

void* p_future_get_value(PFuture *future)
{
    return future->value;
}
