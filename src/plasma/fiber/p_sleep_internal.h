/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_sleep_internal.h
 * \brief An internal sleep API for the fiber scheduler
 */
#pragma once

#include <p.h>

typedef struct p_scheduler p_scheduler;
typedef struct p_timer_queues p_timer_queues;

p_timer_queues *p_timer_queues_init(void);
void p_timer_queues_destroy(p_timer_queues *timer_queue);
void p_timer_queues_poll(p_timer_queues *timer_queue, p_scheduler *scheduler);
