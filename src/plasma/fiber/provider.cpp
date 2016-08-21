/* Copyright (C) Vast Data Ltd. */

#include "provider.hpp"
#include "sleep.hpp"

namespace P {

/* static */ void Provider::wakeup_if_sleeping(Fiber *fiber)
{
    // The only case in which a provider fiber is SUSPENDED is when it's sleeping.
    if (fiber->get_state() == Fiber::State::SUSPENDED) {
        TimerQueues::wakeup(fiber, fiber->get_suspend_state()->sleep_interval);
    }

}

}  // namespace P
