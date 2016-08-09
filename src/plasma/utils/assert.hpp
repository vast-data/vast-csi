/* Copyright (C) Vast Data Ltd. */

/*!
 * \file assert.hpp
 * \brief Assertion macros
 */
#pragma once

#include <iostream>
#include <sstream>

#include "compiler.hpp"
#include "macros.hpp"
#include "backtrace.hpp"
#include "plasma/trace/emitter.hpp"

#define PANIC(message) do { \
        std::ostringstream msg_string;                                  \
        msg_string << "" message;                                       \
        P_TRACE(P::Trace::Channel::CONTROL, P::Trace::Severity::ERROR, ComponentId::PLASMA, "PANIC: %s", msg_string.str().c_str()); \
        std::cerr << "PANIC: " << msg_string.str() << "\nat file: " __FILE__ " line: " MACRO_STRINGIFY(__LINE__) " func: " << __PRETTY_FUNCTION__ << "\n"; \
        P::Backtracer::show_backtrace();                                \
        std::abort();                                                   \
    } while(0)

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

// assert for functions that set errno
#define ASSERT_ERRNO(expr, ...)                                        \
    ASSERT(expr, "errno: " << errno << " "  __VA_ARGS__)


#ifdef DEBUG
  #define DEBUG_ASSERT(expr, ...) ASSERT(expr, ##__VA_ARGS__)
  #define DEBUG_ASSERT_OP(left, operator, right, ...) \
      ASSERT_OP(left, operator, right, ##__VA_ARGS__)
#else
  #define DEBUG_ASSERT(expr, ...)
  #define DEBUG_ASSERT_OP(left, operator, right, ...)
#endif

#define ASSERT_NO_VTABLE(cls) static_assert(!std::is_polymorphic<cls>::value, #cls " has a virtual table")

// make nullptr_t printable (can be passed into ASSERT_OP)
template<class C, class T>
std::basic_ostream<C, T>& operator<<(std::basic_ostream<C, T>& os, std::nullptr_t)
{
    return os << (void*) nullptr;
}
