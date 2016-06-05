/* Copyright (C) Vast Data Ltd. */

/*!
 * \file macros.hpp
 * \brief Macro related macros
 */
#pragma once

#define CONCAT_IMPL( x, y ) x##y
#define MACRO_CONCAT( x, y ) CONCAT_IMPL( x, y )

#define STRINGIFY_IMPL(x) #x
#define MACRO_STRINGIFY(x) STRINGIFY_IMPL(x)
