/* Copyright (C) Vast Data Ltd. */

/*!
 * \file rwlock.hpp
 * \brief A readers-writers lock for cross-fiber coordination
 *
 * A readers-writers lock allows a single writer or multiple readers hold a lock.
 * It can be used to implement barriers or shared access to a memory region.
 */
#pragma once

#include "plasma/data/dlist.hpp"

namespace P {

class Fiber;

namespace FiberSync {

class RWlock {
public:
    enum class Type : byte {
        FREE,
        READ,
        WRITE
    };

    /*!
     * Initialize a rwlock object. A rwlock can also be defined and initialized in a single line:
     \code{.c}
     PRWlock lock = P_RWLOCK_INIT;
     \endcode
    */
    void init();

    /*!
     * Lock the lock for read operations. If the lock is free or currently used by readers and there are no pending writers,
     * the lock is taken and the function returns without yielding the CPU. Otherwise, the function blocks until the lock is freed.
     */
    void lock_read();

    /*!
     * Lock the lock for write operations. If the lock is free, it is taken and the function returns without yielding the CPU.
     * Otherwise, the function blocks until the lock is freed.
     */
    void lock_write();

    // TODO: wouldn't it be safer if we had unlock_read() & unlock_write()?
    //       ASSERT that we don't perform what we meant.
    //       it is also better documentation in the caller code.
    /*!
     * Release the lock. This function doesn't yield the CPU.
     */
    void unlock();

    void destroy();

    bool is_locked() const { return _state == Type::FREE; }

private:

    Fiber *_writer; // isn't required, used for debugging
    DList::Anchor _wait_anchor;
    uint32_t _read_count;
    Type _state;
};

}
}
