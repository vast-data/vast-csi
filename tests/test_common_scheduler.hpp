/* Copyright (C) Vast Data Ltd. */

/*!
 * \file test_common_scheduler.hpp
 * \brief A collection of useful scheduler related definitions for tests
 */

#pragma once

#include "plasma/fiber/scheduler.hpp"

#define PAGE_SIZE 4096
static P::FiberGroupConfig fiber_groups[] = {
    {0, 0},
    {PAGE_SIZE * 16, 40},
    {PAGE_SIZE * 8, 30},
    {PAGE_SIZE * 8, 20},
    {PAGE_SIZE * 4, 10},
};
static P::SchedulerConfig scheduler_config = {
    fiber_groups, NUM_ELEMENTS(fiber_groups)
};

enum test_fiber_group {
    FG_EMPTY,
    FG_A,
    FG_B,
    FG_C,
    FG_D
};
