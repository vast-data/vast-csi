/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_sleep.h
 * \brief A sleep API for fibers
 */
#pragma once

#include <p.h>

// The following enum should match the fiber states in p_fiber_internal.h
typedef enum {
    SLEEP_100_MILLI,
    SLEEP_1_SECOND,
    SLEEP_10_SECOND,
    SLEEP_MINUTE,
    SLEEP_INTERVAL_COUNT
} p_sleep_interval;

/*!
 * Sleep for at least a given interval (100ms, 1 sec, etc').
 *
 * \return number of microseconds spent in sleep.
 */
uint64_t p_sleep(p_sleep_interval interval);

/*!
 * Sleep for at least a given interal times count.
 *
 * \return number of microseconds spent in sleep.
 */
uint64_t p_sleep_multi(p_sleep_interval interval, uint32_t count);

/*!
 * Sleep implemented using busy wait for short custom intervals.
 * Note that this function wastes a lot of CPU.
 */
uint64_t p_fast_sleep(uint64_t usecs);
