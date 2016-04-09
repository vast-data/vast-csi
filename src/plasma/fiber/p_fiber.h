/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_fiber.h
 * \brief The fiber API
 */
#pragma once

#include <p.h>

typedef struct p_fiber p_fiber;

p_fiber *p_fiber_init(size_t group_index, void (*func)(void *arg), void *arg);
void p_fiber_yield(void);

void p_join(p_fiber *fiber);
void p_join_init(void);
void p_join_add(p_fiber *fiber);
void p_join_all(void);
