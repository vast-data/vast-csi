/* Copyright (C) Vast Data Ltd. */

/*!
 * \file i_module.h
 * \brief The interface module.
 */
#pragma once

#include <p.h>

void *i_module_init(PSilo *silo, PConfigSetting *setting);
void i_module_start(void);
