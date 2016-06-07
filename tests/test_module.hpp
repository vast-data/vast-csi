/* Copyright (C) Vast Data Ltd. */

/*!
 * \file test_module.hpp
 * \brief A test module.
 */
#pragma once

#include "plasma/execution/silo.hpp"
#include "plasma/execution/config.hpp"

void *test_module_init(P::Silo *silo, P::Conf::ConfigSetting *setting);
void test_module_start(void);

bool test_module_is_init();
bool test_module_is_started();
