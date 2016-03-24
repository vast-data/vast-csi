/* Copyright (C) Vast Data, Inc - All Rights Reserved
 * Unauthorized copying of this file, via any medium is strictly
 * prohibited proprietary and confidential.
 */

/*!
 * \file defs.h
 * \brief General definitions
 */
#pragma once

#include <stdint.h>

typedef int32_t p_index;
#define P_INVALID_INDEX -1

#define P_CACHE_LINE_BYTES 64
#define P_STRUCT_CACHE_ALIGNED __attribute__ ((aligned(P_CACHE_LINE_BYTES)))
#define P_STRUCT_PACKED __attribute__ ((packed)))
