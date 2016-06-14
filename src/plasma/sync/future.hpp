/* Copyright (C) Vast Data Ltd. */

/*!
 * \file future.hpp
 * \brief An future object for cross-fiber coordination
 */
#pragma once

#include "../fiber/fiber.hpp"

namespace P {

namespace Sync {

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
    void init();

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
    static void wait_subset(Future futures[], uint32_t total_count, uint32_t subset_count);

    /*!
     * Wait for all futures to be set. If the futures are already set, return immediately. Otherwise, block.
     */
    static void wait_all(Future futures[], uint32_t count);

    /*!
     * Wait for any of the futures to be set. If even one of the futures is already set, return immediately. Otherwise, block.
     */
    static void wait_any(Future futures[], uint32_t count);

    /*!
     * Wait for the future to be set. If the future is already set, return immediately. Otherwise, block.
     */
    void wait();

    /*!
     * Set the future. Can only be called if the future is UNSET or WAITED.
     * This function releases the waiting fiber and doesn't yield the CPU.
     */
    void set();

protected:

    bool try_unmark_waiting();

    bool try_mark_waiting();

    P::Fiber *_owner;
    State _state;
};

}
}
