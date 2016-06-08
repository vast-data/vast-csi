/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_module.hpp
 * \brief The plasma module.
 *
 * This module is initialized per silo (like all modules). Therefore, some plasma sub components which are global (like messaging) are initialized elsewhere (explicitly in the environment).
 */
#pragma once

#include <plasma/execution/env.hpp>
#include "module_interface.hpp"
#include "plasma/execution/silo.hpp"
#include "plasma/execution/config.hpp"

class PModule : public ModuleInterface {
public:
    virtual void *init(P::Silo *silo, P::Conf::ConfigSetting *setting);
    virtual void start();
    static ModuleId get_id() { return ModuleId::P; }
    static const char *get_name() { return "P"; }
};

