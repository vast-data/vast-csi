/* Copyright (C) Vast Data Ltd. */

/*!
 * \file assert.hpp
 * \brief Assertion macros
 */
#pragma once

#include <iostream>

#include "compiler.hpp"
#include "macros.hpp"

#define ASSERT_OP(left, operator, right, message) ASSERT(left operator right, "(" << left << " " #operator " " << right << ") " message)

#define ASSERT(expr, message) {                                         \
        if (unlikely(!(expr))) {                                        \
            PANIC("assertion failed: (" #expr ") " message);            \
        }                                                               \
    }

#define PANIC(message) {                                                \
        std::cerr << "PANIC: " message "\nat file: " __FILE__ " line: " MACRO_STRINGIFY(__LINE__) " func: " << __PRETTY_FUNCTION__ << "\n"; \
        std::abort();                                                   \
}

#ifdef DEBUG
  #define DEBUG_ASSERT(expr, message) ASSERT(expr, message)
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
