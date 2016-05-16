#include "../fiber/p_scheduler_internal.h"

#include "p_event.h"

void p_event_init(PEvent *event)
{
    p_dlistanchor_init(&event->wait_anchor);
    event->state = P_EVENT_CLEARED;
}

void p_event_destroy(PEvent *event)
{
    P_ASSERT(p_dlistanchor_is_empty(&event->wait_anchor));
}

void p_event_wait(PEvent *event)
{
    if (event->state == P_EVENT_SET) {
        P_ASSERT(p_dlistanchor_is_empty(&event->wait_anchor));
        return;
    }
    p_fiber_suspend_and_queue(&event->wait_anchor);
}

void p_event_set(PEvent *event)
{
    p_event_release_all(event);
    event->state = P_EVENT_SET;
}

void p_event_clear(PEvent *event)
{
    P_ASSERT(event->state == P_EVENT_SET);
    event->state = P_EVENT_CLEARED;
}

void p_event_release_one(PEvent *event)
{
    P_ASSERT(event->state == P_EVENT_CLEARED);
    p_fiber_pop_and_resume(&event->wait_anchor);
}

void p_event_release_all(PEvent *event)
{
    P_ASSERT(event->state == P_EVENT_CLEARED);
    PFiber *fiber;
    do {
        fiber = p_fiber_pop_and_resume(&event->wait_anchor);
    } while(fiber != NULL);
}
