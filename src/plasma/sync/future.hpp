/* Copyright (C) Vast Data Ltd. */

/*!
 * \file future.hpp
 * \brief An future object for cross-fiber coordination
 */
#pragma once

#include "../fiber/fiber.hpp"
#include "../utils/assert.hpp"

namespace P {

namespace Sync {

template < class T = void* >
class Future {

public:

    enum class State : byte {
        UNSET,
        WAITED,
        SET
    };

    /*!
     * Initializes a future structure.
     * /param is optional. can hold a value that should be valid only once the future is set.
     */
    void init(T value = nullptr);

    /*!
     * Destroy an future object. Can be called only when no pending fibers are waiting for the future to be set.
     */
    void destroy();

    /*!
     * Check if future value is set.
     */
    bool is_set();

    /*!
     * Wait for subset_count futures to be set. If this amount futures (or more) are already set, return immediately. Otherwise, block.
     */
    static void wait_subset(Future<T> futures[], uint32_t total_count, uint32_t subset_count);

    /*!
     * Wait for all futures to be set. If the futures are already set, return immediately. Otherwise, block.
     */
    static void wait_all(Future<T> futures[], uint32_t count);

    /*!
     * Wait for any of the futures to be set. If even one of the futures is already set, return immediately. Otherwise, block.
     */
    static void wait_any(Future<T> futures[], uint32_t count);

    /*!
     * Wait for the future to be set. If the future is already set, return immediately. Otherwise, block.
     */
    void wait();

    /*!
     * Set the future. Can only be called if the future is UNSET or WAITED.
     * This function releases the waiting fiber and doesn't yield the CPU.
     */
    void set();

    /*!
     * Returns the future's value. Can only be called if the future is SET.
     */
    T get_value();

private:

    bool try_unmark_waiting();

    bool try_mark_waiting();

    P::Fiber *_owner;
    State _state;
    T _value;
};

template <class T>
void Future<T>::init(T value)
{
    _owner = Fiber::get_current();
    _value = value;
    _state = State::UNSET;
}

template <class T>
void Future<T>::destroy()
{
    ASSERT(_state == State::SET);
}

template <class T>
bool Future<T>::try_unmark_waiting()
{
    if (is_set()) {
        return false;
    }

    _state = State::UNSET;
    return true;
}

template <class T>
bool Future<T>::try_mark_waiting()
{
    if (is_set()) {
        return false;
    }

    _state = State::WAITED;
    return true;
}

template <class T>
bool Future<T>::is_set()
{
    return _state == State::SET;
}

template <class T>
void Future<T>::wait_subset(Future<T> futures[], uint32_t total_count, uint32_t subset_count)
{
    uint32_t set_count = 0;
    auto this_fiber = Fiber::get_current();

    LOOP(total_count, i) {
        ASSERT(futures[i]._owner == this_fiber);
        if (futures[i].is_set()) {
            set_count++;
        }
    }

    if(set_count < subset_count) {
        LOOP(total_count, i) {
            futures[i].try_mark_waiting();
        }

        auto suspend_state = this_fiber->get_suspend_state();
        suspend_state->waited_future_count = subset_count - set_count;

        this_fiber->suspend();

        uint32_t set_count_after_suspend = 0;
        LOOP(total_count, i) {
            if(!futures[i].try_unmark_waiting()) {
                set_count_after_suspend++;
            }
        }

        ASSERT_OP(set_count_after_suspend, >=, subset_count, "");
    }
}

template <class T>
void Future<T>::wait_any(Future<T> futures[], uint32_t count)
{
    wait_subset(futures, count, 1);
}

template <class T>
void Future<T>::wait_all(Future<T> futures[], uint32_t count)
{
    wait_subset(futures, count, count);
}

template <class T>
void Future<T>::wait()
{
    wait_any(this, 1);
}

template <class T>
void Future<T>::set()
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

template <class T>
T Future<T>::get_value()
{
    return _value;
}

}
}
