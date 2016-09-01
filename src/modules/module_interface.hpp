/* Copyright (C) Vast Data Ltd. */

/*!
 * \file module_interface.hpp
 * \brief The interface for modules in our system.
 */

#pragma once

#include "defs.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/execution/config.hpp"

namespace P {
    class Silo;

    namespace Control {
        class Agent;
    }
}

class ModuleInterface {
public:
    // Each inheriting module should call Agent::init() on its agent.
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting) = 0;
    virtual void start() = 0;

    virtual P::Control::Agent* get_control_agent() = 0;
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
