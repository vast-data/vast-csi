/* Copyright (C) Vast Data Ltd. */

/*!
 * \file time.h
 * \brief Functions for getting the current time
 */
#pragma once

#include <stdint.h>

#define MAGNITUDE(n)        ((n) * 1000)

#define MICRO_TO_NANO(n)    MAGNITUDE(n)
#define MILLI_TO_MICRO(n)   MAGNITUDE(n)
#define SEC_TO_MILLI(n)     MAGNITUDE(n)

#define MILLI_TO_NANO(n)    MICRO_TO_NANO(MILLI_TO_MICRO(n))
#define SEC_TO_MICRO(n)     MILLI_TO_MICRO(SEC_TO_MILLI(n))

#define SEC_TO_NANO(n)      MICRO_TO_NANO(SEC_TO_MICRO(n))


#define MINITUDE(n)         ((n) / 1000)

#define NANO_TO_MICRO(n)    MINITUDE(n)
#define MICRO_TO_MILLI(n)   MINITUDE(n)
#define MILLI_TO_SEC(n)     MINITUDE(n)

#define NANO_TO_MILLI(n)    MICRO_TO_MILLI(NANO_TO_MICRO(n))
#define MICRO_TO_SEC(n)     MILLI_TO_SEC(MICRO_TO_MILLI(n))

#define NANO_TO_SEC(n)      MICRO_TO_SEC(NANO_TO_MICRO(n))

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
