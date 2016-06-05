/* Copyright (C) Vast Data Ltd. */

/*!
 * \file utils.h
 * \brief A collection of useful utilities
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

typedef int32_t PIndex;
#define P_INVALID_INDEX (-1)

typedef uint8_t byte;

#define MIN(a, b) ((a) > (b) ? (b) : (a))
#define MAX(a, b) ((a) < (b) ? (b) : (a))

#define NUM_ELEMENTS(array) (sizeof(array) / sizeof((array)[0]))

#define LOOP_FROM_TYPE(type, start, until, i)   for (type i = (type) (start); i < (type) (until); ++i)
#define LOOP_TYPE(type, until, i)               LOOP_FROM_TYPE(type, 0, until, i)
#define LOOP_FROM(start, until, i)              LOOP_FROM_TYPE(size_t, start, until, i)
#define LOOP(until, i)                          LOOP_FROM(0, until, i)

// Todo: should we enforce same type here?
#define PTR2IDX(ptr, base_ptr) ((PIndex)((ptr) - (base_ptr)))

// Todo: when we move to C++ we should use reinterpret cast here and allow cast-align warning again.
#define MEMBER2OBJECT(member_ptr, object_type, member_name) ((object_type*)((byte*)member_ptr - offsetof(object_type, member_name)))

#define P_CACHE_LINE_BYTES (64)
#define P_CACHE_ALIGNED __attribute__ ((aligned(P_CACHE_LINE_BYTES)))
#define P_PACKED __attribute__ ((packed)))

// as defined in the linux kernel
#define likely(x)      __builtin_expect(!!(x), 1)
#define unlikely(x)    __builtin_expect(!!(x), 0)

#define IN
#define OUT
#define INOUT
#define UNUSED __attribute__((unused))
#define WARN_UNUSED __attribute__((warn_unused_result))
#define NO_RETURN __attribute__((noreturn))

#define CONCAT_IMPL( x, y ) x##y
#define MACRO_CONCAT( x, y ) CONCAT_IMPL( x, y )

// Performs loop_body until it breaks.
// Spins for max_spinning_attempts iterations, than performs yield every attempts_per_yield iterations
// and eventually panics if we've reached max_attempts iterations.
#define INNER_RETRY_LOOP(var_attempt_count, var_max_spinning_attempts, var_attempts_per_yield, var_max_attempts, max_spinning_attempts, attempts_per_yield, max_attempts, loop_body)  \
    do { uint64_t var_attempt_count = 0;                                        \
    static const uint32_t var_max_spinning_attempts = max_spinning_attempts;    \
    static const uint32_t var_attempts_per_yield = attempts_per_yield;          \
    static const uint32_t var_max_attempts = max_attempts;                      \
                                                                                \
    while (true) {                                                              \
        var_attempt_count++;                                                    \
        if (var_attempt_count > var_max_spinning_attempts) {                    \
            if (unlikely(var_attempt_count > var_max_attempts)) {               \
                P_PANIC();                                                      \
            }                                                                   \
            if (var_attempt_count % var_attempts_per_yield == 0) {              \
                p_fiber_yield();                                                \
            }                                                                   \
        }                                                                       \
        loop_body                                                               \
    } } while (false);

#define RETRY_LOOP(max_spinning_attempts, attempts_per_yield, max_attempts, loop_body)                                  \
        INNER_RETRY_LOOP(MACRO_CONCAT(attempt_count_, __COUNTER__) , MACRO_CONCAT(max_spinning_attempts_, __COUNTER__), \
                         MACRO_CONCAT(attempts_per_yield_, __COUNTER__), MACRO_CONCAT(max_attempts_, __COUNTER__),      \
                         max_spinning_attempts, attempts_per_yield, max_attempts, loop_body)

bool p_is_power_of_two (uintmax_t x);
void p_ensure_directory_exists(const char *dir);
