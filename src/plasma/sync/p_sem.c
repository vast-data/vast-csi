#include "../fiber/p_scheduler_internal.h"

#include "p_sem.h"

void p_sem_init(PSem *sem, uint32_t value)
{
    sem->value = value;
    sem->wait_anchor = P_DLIST_ANCHOR_INIT;
}

void p_sem_inc(PSem *sem, uint32_t count)
{
    sem->value += count;

    do {
        PFiber *fiber = p_fiber_queue_peek(&sem->wait_anchor);
        if (fiber == NULL || sem->value < fiber->sem_count)
            break;
        sem->value -= fiber->sem_count;
        p_fiber_pop_and_resume(&sem->wait_anchor);
    } while (true);
}

bool p_sem_trydec(PSem *sem, uint32_t count)
{
    if (sem->value < count)
        return false;
    p_sem_dec(sem, count);
    return true;
}

void p_sem_dec(PSem *sem, uint32_t count)
{
    if (sem->value < count) {
        p_get_current_fiber()->sem_count = count;
        p_fiber_suspend_and_queue(&sem->wait_anchor);
    } else {
        sem->value -= count;
    }
}

void p_sem_destroy(PSem *sem)
{
    P_ASSERT(sem->wait_anchor == P_DLIST_ANCHOR_INIT);
}
