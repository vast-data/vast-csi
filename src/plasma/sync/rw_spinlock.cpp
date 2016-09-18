#include "rw_spinlock.hpp"
#include "plasma/internal.hpp"
#include "plasma/fiber/fiber.hpp"

namespace P {

namespace Sync {

void RWSpinLock::retry_until_wlock()
{
    uint32_t current_state = State::UNLOCKED; //TODO: the UNLOCKED value is just so the compiler won't warn this might be uninitialized at line 21. Perhaps RETRY_LOOP should be fixed and this can be uninitialized.
    RETRY_LOOP_TILL_PANIC(write_retry, Fiber::thread_or_fiber_yield,
        RETRY_LOOP_TILL_PANIC(write_retry, Fiber::thread_or_fiber_yield,
            current_state = _state.load();
            if (!has_writer((State)current_state)) {
                break;
            }
        )

        // current state is not locked for write
        if (!writer_pending((State)current_state)) {
            uint32_t pending_state = current_state | State::WPENDING;
            if (!_state.compare_exchange_weak(current_state, pending_state)) {
                continue;
            }
        }

        // pending write
    RETRY_LOOP_TILL_PANIC(write_retry, Fiber::thread_or_fiber_yield,
            current_state = _state.load();

            if (no_lockers((State)current_state)) {
                // can try and finally lock
                if (_state.compare_exchange_weak(current_state, State::WLOCKED)) {
                    return;
                }
            }

            if (!writer_pending((State)current_state)) {
                break;
            }
        )
    )
}

void RWSpinLock::retry_until_rlock()
{
    RETRY_LOOP_TILL_PANIC(read_retry, Fiber::thread_or_fiber_yield,
        if(rtrylock()) {
            break;
        }
    )
}

}
}
