/* Copyright (C) Vast Data Ltd. */

/*!
 * \file atomic.h
 * \brief Atomic data types and utility functions.
 */
#pragma once

// volatile does not ensure atomicity on types larger than machine word size
typedef volatile int32_t Atomic32;
typedef volatile int64_t Atomic64;
typedef volatile uint32_t AtomicU32;
typedef volatile uint64_t AtomicU64;
