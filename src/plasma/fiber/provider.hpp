/* Copyright (C) Vast Data Ltd. */

/*!
 * \file provider.hpp
 * \brief Common provider functionality
 */
#pragma once

#include "fiber.hpp"

namespace P {

class Provider {
public:
    static const uint64_t IDLE_TIME_MILLI = 5;
    static const SleepInterval IDLE_SLEEP_INTERVAL = P::SleepInterval::SLEEP_1_MILLI;

    static void wakeup_if_sleeping(Fiber *fiber);
};  // class Provider

}  // namespace P
