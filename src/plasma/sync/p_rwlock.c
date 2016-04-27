#include "../fiber/p_scheduler_internal.h"

#include "p_rwlock.h"

void p_rwlock_init(PRWlock *lock)
{
    lock->writer = NULL;
    lock->wait_anchor = P_DLIST_ANCHOR_INIT;
    lock->read_count = 0;
    lock->state = P_RWLOCK_FREE;
}

void p_rwlock_destroy(PRWlock *lock)
{
    P_ASSERT(lock->writer == NULL);
    P_ASSERT(lock->read_count == 0);
    P_ASSERT(lock->state == P_RWLOCK_FREE);
    P_ASSERT(lock->wait_anchor == P_DLIST_ANCHOR_INIT);
}

void p_rwlock_lock_read(PRWlock *lock)
{
    PFiber *fiber = p_get_current_fiber();
    fiber->rw_lock_type = P_RWLOCK_READ;

    switch(lock->state) {
    case P_RWLOCK_FREE:
        P_ASSERT(lock->read_count == 0);
        P_ASSERT(lock->writer == NULL);
        lock->state = P_RWLOCK_READ;
        lock->read_count++;
        break;
    case P_RWLOCK_READ:
        P_ASSERT(lock->read_count > 0);
        // if there are waiters, there's a writer before us and we should suspend
        if (lock->wait_anchor != P_DLIST_ANCHOR_INIT) {
            p_fiber_suspend_and_queue(&lock->wait_anchor);
        } else { // otherwise, we join the current readers
            lock->read_count++;
        }
        break;
    case P_RWLOCK_WRITE:
        p_fiber_suspend_and_queue(&lock->wait_anchor);
        break;
    }
}

void p_rwlock_lock_write(PRWlock *lock)
{
    PFiber *fiber = p_get_current_fiber();
    fiber->rw_lock_type = P_RWLOCK_WRITE;

    switch(lock->state) {
    case P_RWLOCK_FREE:
        P_ASSERT(lock->read_count == 0);
        P_ASSERT(lock->writer == NULL);
        lock->state = P_RWLOCK_WRITE;
        lock->writer = fiber;
        break;
    case P_RWLOCK_READ:
        P_ASSERT(lock->read_count > 0);
        p_fiber_suspend_and_queue(&lock->wait_anchor);
        break;
    case P_RWLOCK_WRITE:
        p_fiber_suspend_and_queue(&lock->wait_anchor);
        break;
    }
}

void p_rwlock_unlock(PRWlock *lock)
{
    PFiber *fiber = p_get_current_fiber();
    P_ASSERT(lock->state == fiber->rw_lock_type);
    switch(fiber->rw_lock_type) {
    case P_RWLOCK_FREE:
        P_PANIC();
    case P_RWLOCK_READ:
        P_ASSERT(lock->read_count > 0);
        lock->read_count--;
        if (lock->read_count == 0)
            lock->state = P_RWLOCK_FREE;
        break;
    case P_RWLOCK_WRITE:
        P_ASSERT(lock->writer == fiber);
        lock->writer = NULL;
        lock->state = P_RWLOCK_FREE;
        break;
    }

    // give the lock to the next pending fiber
    if (lock->state == P_RWLOCK_FREE) {
        do {
            fiber = p_fiber_queue_peek(&lock->wait_anchor);
            if (fiber == NULL)
                break;
            if (fiber->rw_lock_type == P_RWLOCK_WRITE) {
                // already locked for read
                if (lock->state == P_RWLOCK_READ) {
                    break;
                } else { // lock is free. lock and return
                    lock->state = P_RWLOCK_WRITE;
                    p_fiber_pop_and_resume(&lock->wait_anchor);
                    break;
                }
            } else { // add a reader
                lock->state = P_RWLOCK_READ;
                lock->read_count++;
                p_fiber_pop_and_resume(&lock->wait_anchor);
            }
        } while(true);
    }
}
