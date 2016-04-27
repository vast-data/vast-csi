/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_qlock.h
 * \brief A lock for inter-fiber coordination
 */
#pragma once

#include <p.h>

#include "p_qlock_private.h"

/*!
 * Initialize a qlock object. A qlock can also be defined and initialized in a single line:
\code{.c}
    PQlock lock = P_QLOCK_INIT;
\endcode
 */
void p_qlock_init(PQlock *lock);

/*!
 * Lock a PQlock. Blocks if the lock is already locked.
 */
void p_qlock_lock(PQlock *lock);

/*!
 * Lock a PQlock if it's currently unlocked. Returns whether the lock was available and is now locked by the caller.
 */
bool p_qlock_trylock(PQlock *lock);

/*!
 * Release a PQlock. Doesn't release the CPU.
 */
void p_qlock_unlock(PQlock *lock);

void p_qlock_destroy(PQlock *lock);
