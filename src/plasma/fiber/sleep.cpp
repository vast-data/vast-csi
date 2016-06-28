/* Copyright (C) Vast Data Ltd. */
#include "sleep.hpp"

#include "../utils/macros.hpp"
#include "../utils/time.hpp"
#include "scheduler.hpp"

namespace P {

static const uint64_t NO_PENDING_FIBERS = UINT64_MAX;
static const uint64_t interval_to_micro[] = {MILLI_TO_MICRO(100),
                                             SEC_TO_MICRO(1),
                                             SEC_TO_MICRO(10),
                                             SEC_TO_MICRO(60)};

void TimerQueues::init() {
    LOOP((byte) SleepInterval::SLEEP_INTERVAL_COUNT, i)
        _queues[i].init();
    _wakeup_time = NO_PENDING_FIBERS;
}

void TimerQueues::destroy() {

}

uint64_t TimerQueues::sleep(SleepInterval interval)
{
    TimerQueues *timer_queues = Scheduler::get()->get_timer_queues();
    uint64_t start_time = get_time_nano();
    timer_queues->_wakeup_time = MIN(timer_queues->_wakeup_time, start_time + MICRO_TO_NANO(interval_to_micro[(byte) interval]));
    Fiber::suspend_and_queue(&timer_queues->_queues[(byte) interval]);
    return (uint64_t) NANO_TO_MICRO(get_time_nano() - start_time);
}

uint64_t TimerQueues::sleep_multi(SleepInterval interval, uint32_t count)
{
    uint64_t total = interval_to_micro[(byte) interval] * count;
    uint64_t micros = 0;
    while (total > micros) {
        micros += sleep(interval);
    }
    return micros;
}

void TimerQueues::poll()
{
    uint64_t time;

    if (_wakeup_time == NO_PENDING_FIBERS || (time = get_time_nano()) < _wakeup_time)
        return;

    _wakeup_time = NO_PENDING_FIBERS;
    LOOP(SleepInterval::SLEEP_INTERVAL_COUNT, i) {
        DList::Anchor *anchor = &_queues[i];
        Fiber *fiber;
        while ((fiber = Fiber::queue_peek(anchor)) != nullptr) {
            uint64_t fiber_wakeup = fiber->get_switch_time() + MICRO_TO_NANO(interval_to_micro[i]);
            if (fiber_wakeup <= time) {
                Fiber::pop_and_resume(anchor);
            } else {
                _wakeup_time = MIN(_wakeup_time, fiber_wakeup);
                break;
            }
        }
    }
}

uint64_t TimerQueues::fast_sleep(uint64_t usecs)
{
    uint64_t time, start_time = get_time_nano();
    while ((time = get_time_nano()) < start_time + MICRO_TO_NANO(usecs)) {
        Fiber::yield();
    }
    return NANO_TO_MICRO(time - start_time);
}


}
