/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_event.h
 * \brief An event object for cross-fiber coordination
 */
#pragma once

#include <p.h>

#include "p_event_private.h"

/*!
 * Initialize an event. The event starts off in the CLEAR state, meaning fibers calling p_event_wait() will block.
 * An event can also be defined and initialized in a single line:
 \code{.c}
 PEvent event = P_EVENT_INIT;
 \endcode
*/
void p_event_init(PEvent *event);

/*!
 * Destroy an event object. Can be called only when no pending fibers are waiting for the event to be set.
 */
void p_event_destroy(PEvent *event);

/*!
 * Wait for the event to be set. If the event is already set, return immediately. Otherwise, block.
 */
void p_event_wait(PEvent *event);

/*!
 * Set the event. Can only be called if the event was previously cleared.
 * This function releases all waiting fibers and doesn't yield the CPU.
 */
void p_event_set(PEvent *event);

/*!
 * Clear the event. Can only be called if the event was previously set.
 */
void p_event_clear(PEvent *event);

/*!
 * Release a single waiting fiber. Can only be called if the event was previously cleared.
 * After callign this function the event stays cleared.
 */
void p_event_release_one(PEvent *event);

/*!
 * Release all waiting fibers. Can only be called if the event was previously cleared.
 * After callign this function the event stays cleared.
 */
void p_event_release_all(PEvent *event);
