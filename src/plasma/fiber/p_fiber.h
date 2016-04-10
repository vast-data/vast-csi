/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber.h
 * \brief The fiber API
 */
#pragma once

#include <p.h>

typedef struct p_fiber p_fiber;

/*!
 * Initialize a fiber.
 *
 * \param group_index the index of the fiber_group (configured in p_scheduler_init()).
 * \param func a function to be called when the fiber is started.
 * \param arg an argument to be passed to the func.
 * \return a pointer to a fiber or NULL if the pool is empty.
 */
p_fiber *p_fiber_init(size_t group_index, void (*func)(void *arg), void *arg);

/*!
 * A fiber should call this function to yield the CPU. Should be used in CPU-intensive code.
 */
void p_fiber_yield(void);

/*!
 * A parent fiber can call this function to wait for a single child fiber to finish.
 */
void p_join(p_fiber *fiber);

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
void p_join_add(p_fiber *fiber);

/*!
 * Refer to p_join_init().
 */
void p_join_all(void);
