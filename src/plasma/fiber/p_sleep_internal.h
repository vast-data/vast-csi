/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_sleep_internal.h
 * \brief An internal sleep API for the fiber scheduler
 */
#pragma once

#include <p.h>

typedef struct PScheduler PScheduler;
typedef struct PTimerQueues PTimerQueues;

PTimerQueues *p_timer_queues_init(void);
void p_timer_queues_destroy(PTimerQueues *timer_queue);
void p_timer_queues_poll(PTimerQueues *timer_queue, PScheduler *scheduler);
