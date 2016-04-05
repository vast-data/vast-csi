/* Copyright (C) Vast Data Ltd. */
#pragma once

#include <p.h>

#define NUM_ELEMENTS(array) (sizeof(array) / sizeof(array[0]))

#define LOOP(until, i) for (size_t i = 0; i < (until); i++)

#define P_CACHE_LINE_BYTES 64
#define P_CACHE_ALIGNED __attribute__ ((aligned(P_CACHE_LINE_BYTES)))
#define P_PACKED __attribute__ ((packed)))

int is_power_of_two (uintmax_t x);
