#include "p_spin_lock.h"
#include <errno.h>

void p_spin_lock_init(PSpinLock *lock)
{
    P_ASSERT(pthread_spin_init(lock, PTHREAD_PROCESS_PRIVATE) == 0);
}

void p_spin_lock_destroy(PSpinLock *lock)
{
    P_ASSERT(pthread_spin_destroy(lock) == 0);
}

void p_spin_lock_lock(PSpinLock *lock)
{
    P_ASSERT(pthread_spin_lock(lock) == 0);
}

bool p_spin_lock_trylock(PSpinLock *lock)
{
    int result = pthread_spin_trylock(lock);
    if (result == 0) {
        return true;
    } else {
        P_ASSERT(result == EBUSY);
        return false;
    }
}

void p_spin_lock_unlock(PSpinLock *lock)
{
    P_ASSERT(pthread_spin_unlock(lock) == 0);
}
