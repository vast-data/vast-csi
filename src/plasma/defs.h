/* Copyright (C) Vast Data Ltd. */

/*!
 * \file defs.h
 * \brief General definitions
 */
#pragma once

#include <stdint.h>

typedef int32_t p_index;
#define P_INVALID_INDEX -1

#define P_CACHE_LINE_BYTES 64
#define P_CACHE_ALIGNED __attribute__ ((aligned(P_CACHE_LINE_BYTES)))
#define P_PACKED __attribute__ ((packed)))
