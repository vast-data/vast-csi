/* Copyright (C) Vast Data Ltd. */

/*!
 * \file qlock.hpp
 * \brief A lock for cross-fiber coordination
 */
#pragma once

#include "plasma/fiber/fiber.hpp"
#include "plasma/data/dlist.hpp"

namespace P {

namespace FiberSync {

class Qlock {
public:

    /*!
     * Initialize a qlock object.
     */
    void init();

    /*!
     * Lock a PQlock. Blocks if the lock is already locked.
     */
    void lock();

    /*!
     * Lock a PQlock if it's currently unlocked. Returns whether the lock was available and is now locked by the caller.
     */
    bool trylock();

    /*!
     * Release a PQlock. Doesn't release the CPU.
     */
    void unlock();

    void destroy();

private:

    bool is_locked();

    Fiber *_owner;
    DList::Anchor _anchor;
};

}
}
