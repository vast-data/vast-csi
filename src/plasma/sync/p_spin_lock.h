/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_spin_lock.h
 * \brief A spin lock for cross-thread coordination.
 */
#pragma once

#include <p.h>
#include <pthread.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef pthread_spinlock_t PSpinLock;

void p_spin_lock_init(PSpinLock *lock);
void p_spin_lock_destroy(PSpinLock *lock);
void p_spin_lock_lock(PSpinLock *lock);
bool p_spin_lock_trylock(PSpinLock *lock);
void p_spin_lock_unlock(PSpinLock *lock);

#ifdef __cplusplus
}
#endif

