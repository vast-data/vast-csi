/* Copyright (C) Vast Data Ltd. */

/*!
 * \file sleep.hpp
 * \brief Fiber sleep functionality
 */
#pragma once

#include "../utils/types.hpp"
#include "../data/dlist.hpp"

namespace P {

// This should be kept in sync with interval_to_micro (defined in sleep.cpp).
enum class SleepInterval: byte {
    SLEEP_1_MILLI,
    SLEEP_100_MILLI,
    SLEEP_1_SECOND,
    SLEEP_10_SECOND,
    SLEEP_MINUTE,
    SLEEP_INTERVAL_COUNT
};

class Fiber;

class TimerQueues {

public:
    static const uint64_t NO_PENDING_FIBERS = UINT64_MAX;

    // API for the scheduler
    void init();
    uint64_t poll();  // returns the wakeup time
    void destroy();

    // API for fiber implementors

    /*!
     * Sleep for at least a given interval (100ms, 1 sec, etc').
     *
     * \return number of microseconds spent in sleep.
     */
    static uint64_t sleep(SleepInterval interval);

    /*!
     * Sleep for at least a given interval times count.
     *
     * \return number of microseconds spent in sleep.
     */
    static uint64_t sleep_multi(SleepInterval interval, uint32_t count);

    /*!
     * Sleep implemented using busy wait for short custom intervals.
     * Note that this function wastes a lot of CPU.
     */
    static uint64_t fast_sleep(uint64_t usecs);

    /*!
     * Wake up the given fiber, i.e. call pop_and_resume
     */
    static void wakeup(Fiber *fiber, SleepInterval interval);

private:
    uint64_t _wakeup_time;
    DList::Anchor _queues[(byte) SleepInterval::SLEEP_INTERVAL_COUNT];

};  // class TimerQueues

}  // namespace P
