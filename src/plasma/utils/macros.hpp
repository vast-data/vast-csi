/* Copyright (C) Vast Data Ltd. */

/*!
 * \file macros.hpp
 * \brief Macro related macros
 */
#pragma once

#define MIN(a, b) ((a) > (b) ? (b) : (a))
#define MAX(a, b) ((a) < (b) ? (b) : (a))

#define NUM_ELEMENTS(array) (sizeof(array) / sizeof((array)[0]))

#define CONCAT_IMPL( x, y ) x##y
#define MACRO_CONCAT( x, y ) CONCAT_IMPL( x, y )

#define STRINGIFY_IMPL(x) #x
#define MACRO_STRINGIFY(x) STRINGIFY_IMPL(x)

#define LOOP_FROM_TYPE(type, start, until, i)   for (type i = (type) (start); i < (type) (until); ++i)
#define LOOP_TYPE(type, until, i)               LOOP_FROM_TYPE(type, 0, until, i)
#define LOOP_FROM(start, until, i)              LOOP_FROM_TYPE(size_t, start, until, i)
#define LOOP(until, i)                          LOOP_FROM(0, until, i)
