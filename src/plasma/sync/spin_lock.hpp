/* Copyright (C) Vast Data Ltd. */

/*!
 * \file cpool.h
 * \brief A fixed-block concurrent pool for efficient memory management.
 *
 * Uses a per SILO cache in order to reduce locking. In case the silo cache is empty a spinlock is taken.
 */
#pragma once

#include <atomic>

namespace P {

class SpinLock {
public:

    void lock() {
        while(_lock.test_and_set(std::memory_order_acquire)) {

        }
    }

    void unlock() {
        _lock.clear(std::memory_order_release);
    }

private:
    std::atomic_flag _lock = ATOMIC_FLAG_INIT;
};

}
