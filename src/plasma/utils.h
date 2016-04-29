/* Copyright (C) Vast Data Ltd. */

/*!
 * \file utils.h
 * \brief A collection of useful utilities
 */
#pragma once

#include <p.h>

#define MIN(a, b) ((a) > (b) ? (b) : (a))
#define MAX(a, b) ((a) < (b) ? (b) : (a))

#define NUM_ELEMENTS(array) (sizeof(array) / sizeof(array[0]))

#define LOOP(until, i) for (size_t i = 0; i < (size_t) (until); i++)
#define LOOP_FROM(start, until, i) for (size_t i = (size_t) (start); i < (size_t) (until); i++)

#define P_CACHE_LINE_BYTES 64
#define P_CACHE_ALIGNED __attribute__ ((aligned(P_CACHE_LINE_BYTES)))
#define P_PACKED __attribute__ ((packed)))

bool p_is_power_of_two (uintmax_t x);
