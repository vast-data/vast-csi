/* Copyright (C) Vast Data Ltd. */

/*!
 * \file time.h
 * \brief Functions for getting the current time
 */
#pragma once

#include <p.h>

#define MILLI_TO_MICRO(n) ((n) * 1000)
#define MICRO_TO_NANO(n) ((n) * 1000)
#define NANO_TO_MICRO(n) ((n) / 1000)
#define SEC_TO_MICRO(n) (MILLI_TO_MICRO(n) * 1000)

/*!
 * Get the current time in nano seconds. This function is VERY fast and returns a
 * monotonically rising value not affected by the system time, ntp, etc'.
 * This clock will NOT be synchronized between processes.
 *
 * This function uses an assembly command called rtdscp to get the number of cycles
 * the processor executed since it was started. It then converts it to nano seconds
 * by caching the time the processor started and ratio between cycles and nano seconds.
 */
uint64_t p_get_time_nano(void);

/*!
 * Get the current time in nano seconds. This returns the value of a system wide clock
 * that can go back or forward if changed by an administrator or ntp.
 */
uint64_t p_get_clock_time_nano(void);
