/* Copyright (C) Vast Data Ltd. */

/*!
 * \file compiler.hpp
 * \brief Compiler related macros
 */
#pragma once

// as defined in the linux kernel
#define likely(x)      __builtin_expect(!!(x), 1)
#define unlikely(x)    __builtin_expect(!!(x), 0)

#define IN
#define OUT
#define INOUT
#define UNUSED __attribute__((unused))
#define WARN_UNUSED __attribute__((warn_unused_result))
#define NO_RETURN __attribute__((noreturn))

#define CACHE_LINE_BYTES (64)
#define CACHE_ALIGNED __attribute__ ((aligned(P_CACHE_LINE_BYTES)))
#define PACKED __attribute__ ((packed)))
