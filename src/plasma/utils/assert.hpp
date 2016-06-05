/* Copyright (C) Vast Data Ltd. */

/*!
 * \file assert.hpp
 * \brief Assertion macros
 */
#pragma once

#include <iostream>

#include "compiler.hpp"
#include "macros.hpp"

#define ASSERT_OP(left, operator, right, message) ASSERT(left operator right, message " (" << left << " " #operator " " << right << ")")

#define ASSERT(expr, message) {                                         \
        if (unlikely(!(expr))) {                                        \
            PANIC("assertion failed: " message " (" #expr ")");         \
        }                                                               \
    }

#define PANIC(message) {                                                \
        std::cerr << "PANIC: " message "\nat file: " __FILE__ " line: " MACRO_STRINGIFY(__LINE__) " func: " << __PRETTY_FUNCTION__ << "\n"; \
        std::abort();                                                   \
}
