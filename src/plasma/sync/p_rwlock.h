/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_rwlock.h
 * \brief A readers-writers lock for inter-fiber coordination
 *
 * A readers-writers lock allows a single writer or multiple readers hold a lock.
 * It can be used to implement barriers or shared access to a memory region.
 */
#pragma once

#include <p.h>

#include "p_rwlock_private.h"

/*!
 * Initialize a rwlock object. A rwlock can also be defined and initialized in a single line:
 \code{.c}
 PRWlock lock = P_RWLOCK_INIT;
 \endcode
*/
void p_rwlock_init(PRWlock *lock);

/*!
 * Lock the lock for read operations. If the lock is free or currently used by readers and there are no pending writers,
 * the lock is taken and the function returns without yielding the CPU. Otherwise, the function blocks until the lock is freed.
 */
void p_rwlock_lock_read(PRWlock *lock);

/*!
 * Lock the lock for write operations. If the lock is free, it is taken and the function returns without yielding the CPU.
 * Otherwise, the function blocks until the lock is freed.
 */
void p_rwlock_lock_write(PRWlock *lock);

/*!
 * Release the lock. This function doesn't yield the CPU.
 */
void p_rwlock_unlock(PRWlock *lock);

void p_rwlock_destroy(PRWlock *lock);
