/* Copyright (C) Vast Data Ltd. */

/*!
 * \file lock_guard.hpp
 * \brief Lock guards for safe lock usage.
 */
#pragma once

template <typename T>
class LockGuard {
public:
    LockGuard(T *lock): _lock(lock) {
        _lock->lock();
    };

    ~LockGuard()
        {
            _lock->unlock();
        }

private:
    T *_lock;
};
