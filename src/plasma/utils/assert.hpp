/* Copyright (C) Vast Data Ltd. */

/*!
 * \file assert.hpp
 * \brief Assertion macros
 */
#pragma once

#include <iostream>

#include "compiler.hpp"
#include "macros.hpp"

#define ASSERT_OP(left, operator, right, message) ASSERT_MSG(left operator right, "(" << left << " " #operator " " << right << ") " message)

#define ASSERT_EQUAL(left, right) \
    ASSERT_OP(left, ==, right, "")

#define ASSERT_MSG(expr, message) {                                     \
        if (unlikely(!(expr))) {                                        \
            PANIC("assertion failed: (" #expr ") " message);            \
        }                                                               \
    }

#define ASSERT(expr) ASSERT_MSG(expr, "")


#define ASSERT_NOT_NULL(P) \
    ASSERT_MSG(P != nullptr, MACRO_STRINGIFY(P) " is NULL")

#define PANIC(message) {                                                \
        std::cerr << "PANIC: " message "\nat file: " __FILE__ " line: " MACRO_STRINGIFY(__LINE__) " func: " << __PRETTY_FUNCTION__ << "\n"; \
        std::abort();                                                   \
}

#ifdef DEBUG
  #define DEBUG_ASSERT(expr, message) ASSERT_MSG(expr, message)
  #define DEBUG_ASSERT_OP(left, operator, right, message) ASSERT_OP(left, operator, right, message)
#else
  #define DEBUG_ASSERT(expr, message)
  #define DEBUG_ASSERT_OP(left, operator, right, message)
#endif

// make nullptr_t printable (can be passed into ASSERT_OP)
template<class C, class T>
std::basic_ostream<C, T>& operator<<(std::basic_ostream<C, T>& os, std::nullptr_t)
{
    return os << (void*) nullptr;
}
