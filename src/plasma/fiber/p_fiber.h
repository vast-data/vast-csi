/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber.h
 * \brief The fiber API
 */
#pragma once

#include <p.h>

typedef struct PFiber PFiber;

/*!
 * Initialize a fiber.
 *
 * \param group_index the index of the fiber_group (configured in p_scheduler_init()).
 * \param func a function to be called when the fiber is started.
 * \param arg an argument to be passed to the func.
 * \return a pointer to a fiber or NULL if the pool is empty.
 */
PFiber *p_fiber_init(PIndex group_index, void (*func)(void *arg), void *arg);

/*!
 * A fiber should call this function to yield the CPU. Should be used in CPU-intensive code.
 */
void p_fiber_yield(void);

/*!
 * A parent fiber can call this function to wait for a single child fiber to finish.
 */
void p_join(PFiber *fiber);

/*!
 * When a parent fiber needs to wait for the completion of several fibers it should execute the following sequence:
 * 1. p_join_init()
 * 2. For each child fiber: p_join_add(fiber).
 * 3. Block until all children finished: p_join_all().
 */
void p_join_init(void);

/*!
 * Refer to p_join_init().
 */
void p_join_add(PFiber *fiber);

/*!
 * Refer to p_join_init().
 */
void p_join_all(void);

/*!
 * Get the module id of the current running fiber (determined by its fiber group)
 */
ModuleId p_fiber_get_module_id(void);
