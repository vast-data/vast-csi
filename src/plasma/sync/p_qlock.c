#include "../fiber/p_scheduler_internal.h"

#include "p_qlock.h"

void p_qlock_init(PQlock *lock)
{
    p_dlistanchor_init(&lock->anchor);
    lock->owner = NULL;
}

static bool is_locked(PQlock *lock)
{
    return lock->owner != NULL;
}

void p_qlock_lock(PQlock *lock)
{
    if (is_locked(lock)) {
        P_ASSERT(lock->owner != p_get_current_fiber());
        p_fiber_suspend_and_queue(&lock->anchor);
    }
    lock->owner = p_get_current_fiber();
}

bool p_qlock_trylock(PQlock *lock)
{
    if (is_locked(lock))
        return false;
    p_qlock_lock(lock);
    return true;
}

void p_qlock_unlock(PQlock *lock)
{
    P_ASSERT(lock->owner == p_get_current_fiber());
    lock->owner = NULL;
    p_fiber_pop_and_resume(&lock->anchor);
}

void p_qlock_destroy(PQlock *lock)
{
    P_ASSERT(!is_locked(lock));
}
