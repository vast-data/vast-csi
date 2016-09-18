/* Copyright (C) Vast Data Ltd. */

/*!
 * \file rw_spinlock.hpp
 * \brief A read/write spinLock for inter-thread co-ordination
 */
#pragma once

#include "plasma/utils/assert.hpp"
#include "plasma/utils/macros.hpp"
#include <atomic>

namespace P {

namespace Sync {

class RWSpinLock {
public:

    // Lock bitmap layout:
    // W | P |Reader count
    // 0 | 1 | 2 ... 32
    enum State : uint32_t {
        UNLOCKED =      0,
        WLOCKED =       1 << 0,
        WPENDING =      1 << 1,
        RLOCK_BASE =    1 << 2
    };

    void init() { _state = State::UNLOCKED; }

    void destroy() { DEBUG_ASSERT_OP(_state, ==, UNLOCKED); }


    bool rtrylock()
    {
        State old_state = (State)_state.fetch_add(State::RLOCK_BASE);
        if (reader_disabled(old_state)) {
            _state -= State::RLOCK_BASE;

            // detect negative values early
            DEBUG_ASSERT_OP((uint32_t)_state, <, 10000000);
            return false;
        }

        // Stop this before the overflow...
        DEBUG_ASSERT_OP((uint32_t)old_state, <, 10000000);
        return true;
    }

    void rlock()
    {
        if (likely(rtrylock())) {
            return;
        }

        retry_until_rlock();
    }

    void runlock()
    {
        _state -= State::RLOCK_BASE;
        DEBUG_ASSERT_OP((uint32_t)_state, <, 10000000);
    }

    bool wtrylock()
    {
        uint32_t expected = State::UNLOCKED;
        return _state.compare_exchange_strong(expected, State::WLOCKED);
    }

    void wlock()
    {
        if (likely(wtrylock())){
            return;
        }

        retry_until_wlock();
    }

    void wunlock()
    {
        _state -= State::WLOCKED;
    }

private:

    bool writer_pending(State s) { return (s & State::WPENDING) != 0; }
    bool reader_disabled (State s) { return (s & (State::WLOCKED | State::WPENDING)) != 0; }
    bool has_readers (State s) { return reader_count(s) > 0; }
    bool has_writer (State s) { return (s & State::WLOCKED) != 0; }
    bool no_lockers (State s) { return (s | State::WPENDING) == State::WPENDING; }
    uint32_t reader_count(State s) { return s / State::RLOCK_BASE; }

    void retry_until_rlock();
    void retry_until_wlock();

    static constexpr RetryParams write_retry =  { .max_spinning_attempts = 200, .attempts_per_yield = 10, .max_attempts = 1000000};
    static constexpr RetryParams read_retry =  { .max_spinning_attempts = 200, .attempts_per_yield = 10, .max_attempts = 1000000};

    std::atomic<uint32_t> _state;
};

}
}
