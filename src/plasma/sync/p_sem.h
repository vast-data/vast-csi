/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_sem.h
 * \brief A counting semaphore for cross-fiber coordination
 */
#pragma once

#include <p.h>

#include "p_sem_private.h"

/*!
 * Initialize a semaphore. A semaphore can also be defined and initialized in a single line:
 \code{.c}
 PSem sem = P_SEM_INIT(8);
 \endcode
*/
void p_sem_init(PSem *sem, uint32_t value);

/*!
 * Increment the semaphore's value by a given value. Does not release the CPU.
 */
void p_sem_inc(PSem *sem, uint32_t count);

/*!
 * Try decrementing the semaphore's value by a given count. If the value isn't big enough,
 * don't do anything and return false. Otherwise, return true.
 */
bool p_sem_trydec(PSem *sem, uint32_t count);

/*!
 * Decrement the given count from the semaphore's value. If the value isn't big enough this function shall release the CPU and block.
 */
void p_sem_dec(PSem *sem, uint32_t count);

void p_sem_destroy(PSem *sem);
