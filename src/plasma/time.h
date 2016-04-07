/* Copyright (C) Vast Data Ltd. */
#pragma once

#include <p.h>

// fixed
uint64_t p_get_time_nano(void);
// can be changed by ntp, admin, etc'
uint64_t p_get_clock_time_nano(void);
