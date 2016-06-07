/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_module.hpp
 * \brief The plasma module.
 *
 * This module is initialized per silo (like all modules). Therefore, some plasma sub components which are global (like messaging) are initialized elsewhere (explicitly in the environment).
 */
#pragma once

#include "plasma/execution/silo.hpp"
#include "plasma/execution/config.hpp"

void *p_module_init(P::Silo *silo, P::Conf::ConfigSetting *setting);
void p_module_start(void);
