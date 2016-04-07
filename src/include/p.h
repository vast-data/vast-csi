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
#include <string.h>

typedef int32_t p_index;
#define P_INVALID_INDEX -1

#include "plasma/p_assert.h"
#include "plasma/memory/p_alloc.h"
#include "plasma/memory/p_pool.h"
#include "plasma/data/p_dlist.h"
#include "plasma/data/p_hash.h"
#include "plasma/fiber/p_fiber.h"
#include "plasma/utils.h"
#include "plasma/time.h"
