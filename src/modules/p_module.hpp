/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_module.hpp
 * \brief The Platform module.
 */
#pragma once

#include "module_interface.hpp"
#include "p_module_agent.hpp"
#include "plasma/control/agent.hpp"

namespace P {

class PModule : public ModuleInterface {
public:
    virtual void init(Silo *silo, Conf::ConfigSetting *setting);

    virtual void start() {}

    virtual Control::Agent *get_control_agent() { return &_agent; }

    static ModuleId get_id() { return ModuleId::P; }

    static const char *get_name() { return "P"; }

private:
    PModuleAgent _agent;
};  // class PModule

}  // namespace P
