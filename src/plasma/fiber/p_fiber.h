/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber.h
 * \brief A user-level thread implementation.
 *
 */
#pragma once

#include <p.h>
#include <setjmp.h>

typedef struct p_fiber p_fiber;

p_fiber *p_fiber_init(void (*func)(void *arg), void *arg);
void p_fiber_yield(void);

void p_scheduler_init(void);
void p_scheduler_destroy(void);
void p_scheduler_run(void);
