/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_sleep_internal.h
 * \brief An internal sleep API for the fiber scheduler
 */
#pragma once

#include <p.h>

void p_sleep_init(void);
void p_sleep_poll(p_fiber_group *group);
