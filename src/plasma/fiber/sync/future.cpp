#include "future.hpp"
#include "plasma/utils/assert.hpp"

namespace P {

namespace FiberSync {

void Future::init()
{
    _owner = Fiber::get_current();
    _state = State::UNSET;
}

void Future::destroy()
{
    ASSERT(_state == State::SET);
}

bool Future::try_unmark_waiting()
{
    if (is_set()) {
        return false;
    }

    _state = State::UNSET;
    return true;
}

bool Future::try_mark_waiting()
{
    if (is_set()) {
        return false;
    }

    _state = State::WAITED;
    return true;
}

bool Future::is_set()
{
    return _state == State::SET;
}

void Future::wait_subset(Future *futures[], uint32_t total_count, uint32_t subset_count)
{
    uint32_t set_count = 0;
    auto this_fiber = Fiber::get_current();

    LOOP(total_count, i) {
        ASSERT(futures[i]->_owner == this_fiber);
        if (futures[i]->is_set()) {
            set_count++;
        }
    }

    if(set_count < subset_count) {
        LOOP(total_count, i) {
            futures[i]->try_mark_waiting();
        }

        auto suspend_state = this_fiber->get_suspend_state();
        suspend_state->waited_future_count = subset_count - set_count;

        this_fiber->suspend();

        uint32_t set_count_after_suspend = 0;
        LOOP(total_count, i) {
            if(!futures[i]->try_unmark_waiting()) {
                set_count_after_suspend++;
            }
        }

        ASSERT_OP(set_count_after_suspend, >=, subset_count, "");
    }
}

void Future::wait_any(Future *futures[], uint32_t count)
{
    wait_subset(futures, count, 1);
}

void Future::wait_all(Future *futures[], uint32_t count)
{
    wait_subset(futures, count, count);
}

void Future::wait()
{
    Future *futures[1];
    futures[0] = this;
    wait_any(futures, 1);
}

void Future::set()
{
    ASSERT(_state != State::SET);
    State old_state = _state;
    _state = State::SET;
    if (old_state == State::WAITED) {
        auto suspend_state = _owner->get_suspend_state();
        ASSERT_OP(suspend_state->waited_future_count, >, 0, "");
        suspend_state->waited_future_count--;
        if (suspend_state->waited_future_count == 0) {
            _owner->resume();
        }
    }
}

}
}
