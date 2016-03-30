/* Copyright (C) Vast Data Ltd. */

/*!
 * \file assert.h
 * \brief Assert and panic functions
 */
#pragma once

#include <assert.h>

#define P_ASSERT(expression) assert(expression)
#define P_PANIC() P_ASSERT(false)
