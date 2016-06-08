/* Copyright (C) Vast Data Ltd. */

/*!
 * \file assert.hpp
 * \brief Assertion macros
 */
#pragma once

#include <iostream>

#include "compiler.hpp"
#include "macros.hpp"

#define PANIC(message) {                                                \
        std::cerr << "PANIC: " message "\nat file: " __FILE__ " line: " MACRO_STRINGIFY(__LINE__) " func: " << __PRETTY_FUNCTION__ << "\n"; \
        std::abort();                                                   \
    }

// NOTE: the assert macros all accept '...' as a way to pass an optional message.
#define ASSERT(expr, ...) {                                             \
        if (unlikely(!(expr))) {                                        \
            PANIC("assertion failed: (" #expr ") " __VA_ARGS__);        \
        }                                                               \
    }

#define ASSERT_OP(left, operator, right, ...)                           \
    ASSERT(left operator right, "(" << left << " " #operator " " << right << ") " __VA_ARGS__)

#define ASSERT_EQUAL(left, right, ...)          \
    ASSERT_OP(left, ==, right, ##__VA_ARGS__)

#define ASSERT_NOT_NULL(P)                                              \
    ASSERT(P != nullptr, MACRO_STRINGIFY(P) " is NULL")

#ifdef DEBUG
  #define DEBUG_ASSERT(expr, ...) ASSERT(expr, ##__VA_ARGS__)
  #define DEBUG_ASSERT_OP(left, operator, right, ...) \
      ASSERT_OP(left, operator, right, ##__VA_ARGS__)
#else
  #define DEBUG_ASSERT(expr, ...)
  #define DEBUG_ASSERT_OP(left, operator, right, ...)
#endif

// make nullptr_t printable (can be passed into ASSERT_OP)
template<class C, class T>
std::basic_ostream<C, T>& operator<<(std::basic_ostream<C, T>& os, std::nullptr_t)
{
    return os << (void*) nullptr;
}
