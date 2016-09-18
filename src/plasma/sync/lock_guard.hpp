/* Copyright (C) Vast Data Ltd. */

/*!
 * \file lock_guard.hpp
 * \brief Lock guards for safe lock usage.
 */
#pragma once

namespace P {

namespace Sync {

#define GEN_GUARD(NAME, LOCK, UNLOCK)   \
    template <typename T>               \
    class NAME {                        \
    public:                             \
        NAME(T *lock): _lock(lock) {    \
            _lock->LOCK();              \
        }                               \
                                        \
        ~NAME()                         \
        {                               \
            _lock->UNLOCK();            \
        }                               \
                                        \
    private:                            \
        T *_lock;                       \
    }


GEN_GUARD(LockGuard, lock, unlock);
GEN_GUARD(WLockGuard, wlock, wunlock);
GEN_GUARD(RLockGuard, rlock, runlock);

}
}
