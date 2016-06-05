/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_assert.h
 * \brief Assert and panic functions
 */
#pragma once

#include <assert.h>

#ifdef DEBUG
  #define P_DEBUG_ASSERT(expression) P_ASSERT(expression)
#else
  #define P_DEBUG_ASSERT(expression)
#endif

#define P_ASSERT(expression) assert(expression)
#define P_PANIC() abort();

#ifdef __cplusplus
  #define P_STATIC_ASSERT static_assert
#else
  #define P_STATIC_ASSERT _Static_assert
#endif
