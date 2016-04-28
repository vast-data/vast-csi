#include "p_spin_lock.h"

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

void p_spin_lock_trylock(PSpinLock *lock)
{
    P_ASSERT(pthread_spin_trylock(lock) == 0);
}

void p_spin_lock_unlock(PSpinLock *lock)
{
    P_ASSERT(pthread_spin_unlock(lock) == 0);
}
