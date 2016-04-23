/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_module.h
 * \brief The plasma module.
 *
 * This module is initialized per silo (like all modules). Therefore, some plasma sub components which are global (like messaging) are initialized elsewhere (explicitly in the environment).
 */
#pragma once

#include <p.h>

void *p_module_init(PSilo *silo);
void p_module_start(void);
