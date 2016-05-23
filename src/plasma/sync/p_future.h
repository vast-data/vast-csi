/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_future.h
 * \brief An future object for cross-fiber coordination
 */
#pragma once

#include <p.h>

#include "p_future_private.h"

/*!
 *
*/
void p_future_init(PFuture *future, void *value);

/*!
 * Destroy an future object. Can be called only when no pending fibers are waiting for the future to be set.
 */
void p_future_destroy(PFuture *future);

/*!
 * Check if future value is set.
 */
bool p_future_is_set(PFuture *future);

/*!
 * Wait for subset_count futures to be set. If this amount futures (or more) are already set, return immediately. Otherwise, block.
 */
void p_future_wait_subset(PFuture futures[], uint32_t total_count, uint32_t subset_count);

/*!
 * Wait for all futures to be set. If the futures are already set, return immediately. Otherwise, block.
 */
void p_future_wait_all(PFuture futures[], uint32_t count);

/*!
 * Wait for any of the futures to be set. If even one of the futures is already set, return immediately. Otherwise, block.
 */
void p_future_wait_any(PFuture futures[], uint32_t count);

/*!
 * Wait for the future to be set. If the future is already set, return immediately. Otherwise, block.
 */
void p_future_wait(PFuture *future);

/*!
 * Set the future. Can only be called if the future is UNSET or WAITED.
 * This function releases the waiting fiber and doesn't yield the CPU.
 */
void p_future_set(PFuture *future);

/*!
 * Returns the future's value. Can only be called if the future is SET.
 */
void *p_future_get_value(PFuture *future);
