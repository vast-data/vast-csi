/* Copyright (C) Vast Data Ltd. */

/*!
 * \file macros.hpp
 * \brief Macro related macros
 */
#pragma once

#include <string.h>
#include "assert.hpp"
#include "types.hpp"

#define MIN(a, b) ((a) > (b) ? (b) : (a))
#define MAX(a, b) ((a) < (b) ? (b) : (a))

#define NUM_ELEMENTS(array) (sizeof(array) / sizeof((array)[0]))


// as defined in the linux kernel
#define likely(x)      __builtin_expect(!!(x), 1)
#define unlikely(x)    __builtin_expect(!!(x), 0)
#define container_of(ptr, type, member) ({                      \
        auto __mptr = (ptr);                                    \
        (type *)( (byte *)__mptr - offsetof(type,member) );})

#define CONCAT_IMPL( x, y ) x##y
#define MACRO_CONCAT( x, y ) CONCAT_IMPL( x, y )

#define STRINGIFY_IMPL(x) #x
#define MACRO_STRINGIFY(x) STRINGIFY_IMPL(x)

#define LOOP_FROM_TYPE(type, start, until, i)   for (type i = (type) (start); i < (type) (until); ++i)
#define LOOP_TYPE(type, until, i)               LOOP_FROM_TYPE(type, 0, until, i)
#define LOOP_FROM(start, until, i)              LOOP_FROM_TYPE(size_t, start, until, i)
#define LOOP(until, i)                          LOOP_FROM(0, until, i)

// Todo: should we enforce same type here?
#define PTR2IDX(ptr, base_ptr) ((Index)((ptr) - (base_ptr)))

/*!
 * The macro_is_set was found here: http://stackoverflow.com/questions/5464170/using-definedmacro-inside-the-c-if-statement
 */
#define MACRO_IS_SET(macro) MACRO_IS_SET_(macro)
#define MACROTEST_1 ,
#define MACRO_IS_SET_(value) MACRO_IS_SET__(MACROTEST_##value)
#define MACRO_IS_SET__(comma) MACRO_IS_SET___(comma 1, 0)
#define MACRO_IS_SET___(_, v, ...) v

/*!
 * The following macro magic is copied from https://codecraft.co/2014/11/25/variadic-macros-tricks/
 */
#define _GET_NTH_ARG(_1, _2, _3, _4, _5, _6, _7, _8, _9, _10, _11, _12, N, ...) N

#define _fe_0(_call, ...)
#define _fe_1(_call, x) _call(x)
#define _fe_2(_call, x, ...) _call(x) _fe_1(_call, __VA_ARGS__)
#define _fe_3(_call, x, ...) _call(x) _fe_2(_call, __VA_ARGS__)
#define _fe_4(_call, x, ...) _call(x) _fe_3(_call, __VA_ARGS__)
#define _fe_5(_call, x, ...) _call(x) _fe_4(_call, __VA_ARGS__)
#define _fe_6(_call, x, ...) _call(x) _fe_5(_call, __VA_ARGS__)
#define _fe_7(_call, x, ...) _call(x) _fe_6(_call, __VA_ARGS__)
#define _fe_8(_call, x, ...) _call(x) _fe_7(_call, __VA_ARGS__)
#define _fe_9(_call, x, ...) _call(x) _fe_8(_call, __VA_ARGS__)
#define _fe_10(_call, x, ...) _call(x) _fe_9(_call, __VA_ARGS__)
#define _fe_11(_call, x, ...) _call(x) _fe_10(_call, __VA_ARGS__)

/*!
 * Provide a for-each construct for variadic macros. Supports up
 * to 12 args.
 *
 * Example usage1:
 *     #define FWD_DECLARE_CLASS(cls) class cls;
 *     CALL_MACRO_X_FOR_EACH(FWD_DECLARE_CLASS, Foo, Bar)
 */
#define CALL_MACRO_X_FOR_EACH(x, ...)                                   \
    _GET_NTH_ARG("ignored", ##__VA_ARGS__,                              \
                 _fe_11, _fe_10, _fe_9, _fe_8, _fe_7, _fe_6, _fe_5, _fe_4, _fe_3, _fe_2, _fe_1, _fe_0)(x, ##__VA_ARGS__)

/*!
 * The following macros provide a template for creating an enum
 * Along with helper functions that convert between enum values and strings.
 */

// TODO get rid of the  "_CPP" once the c code is gone
#define DEFINE_LOOKUP_ID_CPP(x) x
#define DEFINE_LOOKUP_PROTOTYPES_CPP(list, name, id_to_string, string_to_id) \
    enum class name : P::byte {                                              \
        list(DEFINE_LOOKUP_ID_CPP)                                           \
    };                                                                       \
    const char *id_to_string(name id);                                       \
    name string_to_id(const char *string);

#define DEFINE_LOOKUP_STRING_CPP(x) #x
#define DEFINE_LOOKUP_IMPLEMENTATION_CPP(list, name, array, id_to_string, string_to_id) \
    static const char *array[] = {                                      \
        list(DEFINE_LOOKUP_STRING_CPP),                                 \
        nullptr                                                         \
    };                                                                  \
    const char *id_to_string(name id)                                   \
    {                                                                   \
        return array[(P::byte)id];                                      \
    }                                                                   \
    name string_to_id(const char *string)                               \
    {                                                                   \
        for (P::byte i = 0; array[i] != nullptr; i++)                   \
            if (strcmp(array[i], string) == 0)                          \
                return (name)i;                                         \
        PANIC("invalid " #name);                                        \
    }

/*!
 * Use the following macro to easily define multi-line strings.
 */
#define QUOTE(...) #__VA_ARGS__



struct RetryParams {
    const uint32_t max_spinning_attempts;
    const uint32_t attempts_per_yield;
    const uint32_t max_attempts;
};

// Performs loop_body until it breaks.
// Spins for max_spinning_attempts iterations, than performs yield every attempts_per_yield iterations
// and eventually panics if we've reached max_attempts iterations.
#define INNER_RETRY_LOOP(var_attempt_count, var_max_spinning_attempts, var_attempts_per_yield, var_max_attempts, max_spinning_attempts, attempts_per_yield, max_attempts, loop_body)  \
    do { uint64_t var_attempt_count = 0;                                                \
    static const uint32_t var_max_spinning_attempts = max_spinning_attempts;            \
    static const uint32_t var_attempts_per_yield = attempts_per_yield;                  \
    static const uint32_t var_max_attempts = max_attempts;                              \
                                                                                        \
    while (true) {                                                                      \
        var_attempt_count++;                                                            \
        if (var_attempt_count > var_max_spinning_attempts) {                            \
            if (unlikely(var_attempt_count > var_max_attempts)) {                       \
                PANIC("maximum retries reached: " << var_attempt_count << "attempts");  \
            }                                                                           \
            if (var_attempt_count % var_attempts_per_yield == 0) {                      \
                P::Fiber::yield();                                                      \
            }                                                                           \
        }                                                                               \
        loop_body                                                                       \
    } } while (false);

#define RETRY_LOOP_PARAMS(max_spinning_attempts, attempts_per_yield, max_attempts, loop_body)                           \
        INNER_RETRY_LOOP(MACRO_CONCAT(attempt_count_, __COUNTER__) , MACRO_CONCAT(max_spinning_attempts_, __COUNTER__), \
                         MACRO_CONCAT(attempts_per_yield_, __COUNTER__), MACRO_CONCAT(max_attempts_, __COUNTER__),      \
                         max_spinning_attempts, attempts_per_yield, max_attempts, loop_body)

#define RETRY_LOOP(retry_params, loop_body)                                             \
        RETRY_LOOP_PARAMS(retry_params.max_spinning_attempts, retry_params.attempts_per_yield, retry_params.max_attempts, loop_body)                                  \

