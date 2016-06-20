/* Copyright (C) Vast Data Ltd. */

/*!
 * \file sem.hpp
 * \brief A counting semaphore for cross-fiber coordination
 */
#pragma once

#include "plasma/data/dlist.hpp"

namespace P {

namespace FiberSync {

class Sem {
public:
    /*!
     * Initialize a semaphore. A semaphore can also be defined and initialized in a single line:
     \code{.c}
     PSem sem = P_SEM_INIT(8);
     \endcode
    */
    void init(uint32_t value);

    /*!
     * Increment the semaphore's value by a given value. Does not release the CPU.
     */
    void inc(uint32_t count);

    /*!
     * Try decrementing the semaphore's value by a given count. If the value isn't big enough,
     * don't do anything and return false. Otherwise, return true.
     */
    bool trydec(uint32_t count);

    /*!
     * Decrement the given count from the semaphore's value. If the value isn't big enough this function shall release the CPU and block.
     */
    void dec(uint32_t count);

    /*!
     * Get the current semaphore value
     */
    uint32_t value() { return _value; }

    void destroy();

private:
    uint32_t _value;
    DList::Anchor _wait_anchor;
};

}
}

