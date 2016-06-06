/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber.h
 * \brief The fiber API
 */
#pragma once

#include "../utils.h"
#include "../../defs.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PFiber PFiber;

/*!
 * Initialize a fiber.
 *
 * \param group_index the index of the fiber_group (configured in p_scheduler_init()).
 * \param func a function to be called when the fiber is started.
 * \param arg an argument to be passed to the func.
 * \return a pointer to a fiber or NULL if the pool is empty.
 */
PFiber *p_fiber_init(PIndex group_index, void (*func)(void *arg), void *arg, bool parent_will_join);

/*!
 * A fiber should call this function to yield the CPU. Should be used in CPU-intensive code.
 */
void p_fiber_yield(void);

/*!
 * Block until all children finished.
 */
void p_fiber_join_all(void);

/*!
 * Get the module id of the current running fiber (determined by its fiber group)
 */
ModuleId p_fiber_get_module_id(void);

/*!
 * Get the current/last job id performed by this fiber
 */
uint32_t p_fiber_get_job_id(PFiber *fiber);

/*!
 * Return the currently running fiber.
 */
PFiber *p_get_current_fiber(void);

#ifdef __cplusplus
}
#endif
