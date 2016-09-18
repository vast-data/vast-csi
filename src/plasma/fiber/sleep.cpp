/* Copyright (C) Vast Data Ltd. */
#include "sleep.hpp"

#include "../utils/macros.hpp"
#include "../utils/time.hpp"
#include "scheduler.hpp"
#include "fiber.hpp"

namespace P {

// This should be kept in sync with SleepInterval.
static const uint64_t interval_to_micro[] = {MILLI_TO_MICRO(1),    // SLEEP_1_MILLI
                                             MILLI_TO_MICRO(100),  // SLEEP_100_MILLI
                                             SEC_TO_MICRO(1),      // SLEEP_1_SECOND
                                             SEC_TO_MICRO(10),     // SLEEP_10_SECOND
                                             SEC_TO_MICRO(60)};    // SLEEP_MINUTE
static_assert(NUM_ELEMENTS(interval_to_micro) == (size_t)SleepInterval::SLEEP_INTERVAL_COUNT,
              "interval_to_micro size mismatch");

void TimerQueues::init() {
    LOOP((byte) SleepInterval::SLEEP_INTERVAL_COUNT, i)
        _queues[i].init();
    _wakeup_time = NO_PENDING_FIBERS;
}

void TimerQueues::destroy() {

}

/* static */ uint64_t TimerQueues::sleep(SleepInterval interval)
{
    TimerQueues *timer_queues = Scheduler::get()->get_timer_queues();
    uint64_t start_time = get_time_nano();
    timer_queues->_wakeup_time = P_MIN(timer_queues->_wakeup_time,
                                       start_time + MICRO_TO_NANO(interval_to_micro[(byte) interval]));

    Fiber::get_current()->get_suspend_state()->sleep_interval = interval;

    Fiber::suspend_and_queue(&timer_queues->_queues[(byte) interval]);
    return (uint64_t) NANO_TO_MICRO(get_time_nano() - start_time);
}

/* static */ uint64_t TimerQueues::sleep_multi(SleepInterval interval, uint32_t count)
{
    uint64_t total = interval_to_micro[(byte) interval] * count;
    uint64_t micros = 0;
    while (total > micros) {
        micros += sleep(interval);
    }
    return micros;
}

uint64_t TimerQueues::poll()
{
    uint64_t time;

    if (_wakeup_time == NO_PENDING_FIBERS || (time = get_time_nano()) < _wakeup_time)
        return _wakeup_time;

    _wakeup_time = NO_PENDING_FIBERS;
    LOOP(SleepInterval::SLEEP_INTERVAL_COUNT, i) {
        DList::Anchor *anchor = &_queues[i];
        Fiber *fiber;
        while ((fiber = Fiber::queue_peek(anchor)) != nullptr) {
            uint64_t fiber_wakeup = fiber->get_switch_time() + MICRO_TO_NANO(interval_to_micro[i]);
            if (fiber_wakeup <= time) {
                Fiber::pop_and_resume(anchor);
            } else {
                _wakeup_time = P_MIN(_wakeup_time, fiber_wakeup);
                break;
            }
        }
    }

    return _wakeup_time;
}

/* static */ uint64_t TimerQueues::fast_sleep(uint64_t usecs)
{
    uint64_t time, start_time = get_time_nano();
    while ((time = get_time_nano()) < start_time + MICRO_TO_NANO(usecs)) {
        Fiber::yield();
    }
    return NANO_TO_MICRO(time - start_time);
}

/* static */ void TimerQueues::wakeup(Fiber *fiber, UNUSED SleepInterval interval)
{
    TimerQueues *timer_queues = Scheduler::get()->get_timer_queues();
    fiber->pop_and_resume(&timer_queues->_queues[(byte) fiber->get_suspend_state()->sleep_interval]);
}

}
