/* Copyright (C) Vast Data Ltd. */

/*!
 * \file event.hpp
 * \brief An event object for cross-fiber coordination
 */
#pragma once

#include "plasma/utils/types.hpp"
#include "plasma/data/dlist.hpp"

namespace P {

namespace FiberSync {

class Event {
public:
    enum class State : byte {
        CLEARED,
        SET
    };

    /*!
     * Initialize an event. The event starts off in the CLEAR state, meaning fibers calling wait() will block.
    */
    void init();

    /*!
     * Destroy an event object. Can be called only when no pending fibers are waiting for the event to be set.
     */
    void destroy();

    /*!
     * Wait for the event to be set. If the event is already set, return immediately. Otherwise, block.
     */
    void wait();

    /*!
     * Set the event. Can only be called if the event was previously cleared.
     * This function releases all waiting fibers and doesn't yield the CPU.
     */
    void set();

    bool is_set() { return _state == State::SET; }

    /*!
     * Clear the event. Can only be called if the event was previously set.
     */
    void clear();

    /*!
     * Release a single waiting fiber. Can only be called if the event was previously cleared.
     * After callign this function the event stays cleared.
     */
    void release_one();

    /*!
     * Release all waiting fibers. Can only be called if the event was previously cleared.
     * After callign this function the event stays cleared.
     */
    void release_all();

private:
    DList::Anchor _wait_anchor;
    State _state;
};

}
}
