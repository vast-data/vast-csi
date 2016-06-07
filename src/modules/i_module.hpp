/* Copyright (C) Vast Data Ltd. */

/*!
 * \file i_module.hpp
 * \brief The interface module.
 */
#pragma once

#include "plasma/execution/silo.hpp"
#include "plasma/execution/config.hpp"

void *i_module_init(P::Silo *silo, P::Conf::ConfigSetting *setting);
void i_module_start(void);
