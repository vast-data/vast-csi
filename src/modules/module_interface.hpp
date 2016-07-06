/* Copyright (C) Vast Data Ltd. */

/*!
 * \file module_interface.hpp
 * \brief The interface for modules in our system.
 */

#pragma once

#include "defs.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/execution/config.hpp"
#include "plasma/control/agent.hpp"

namespace P {
    class Silo;
}

class ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting) = 0;
    virtual void start() = 0;

    P::Control::Agent control_agent;
};

/*!
 * Defines the API for creating module instances
 */
class ModuleFactory {
public:
    virtual ModuleInterface *create() = 0;
    virtual const char *get_name() = 0;
    virtual ModuleId get_id() = 0;
};

void register_modules();
