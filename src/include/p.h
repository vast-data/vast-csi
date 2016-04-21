/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p.h
 * \brief Plasma's API
 */
#pragma once

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <libconfig.h>

typedef int32_t PIndex;
#define P_INVALID_INDEX -1

#include "plasma/p_assert.h"
#include "plasma/memory/p_alloc.h"
#include "plasma/memory/p_pool.h"
#include "plasma/data/p_ilist.h"
#include "plasma/data/p_dlist.h"
#include "plasma/data/p_hash.h"
#include "plasma/fiber/p_fiber.h"
#include "plasma/fiber/p_scheduler.h"
#include "plasma/fiber/p_sleep.h"
#include "plasma/backtrace.h"
#include "plasma/utils.h"
#include "plasma/time.h"
