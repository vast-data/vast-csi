/* Copyright (C) Vast Data Ltd. */

/*!
 * \file spin_lock.hpp
 * \brief A SpinLock for inter-thread co-ordination
 */
#pragma once

#include <atomic>
#include "../utils/assert.hpp"

namespace P {

class SpinLock {
public:

    void init() {

    }

    void lock() {
        while(_lock.test_and_set(std::memory_order_acquire)) {

        }
    }

    void unlock() {
        _lock.clear(std::memory_order_release);
    }

    void destroy() {
        DEBUG_ASSERT_OP(_lock, ==, ATOMIC_FLAG_INIT, "SpinLock destroyed while locked.");
    }

private:
    std::atomic_flag _lock = ATOMIC_FLAG_INIT; // atomic_flag requires static initialization
};

}
