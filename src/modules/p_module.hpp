/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_module.hpp
 * \brief The Platform module.
 */
#pragma once

#include "module_interface.hpp"
#include "p_module_agent.hpp"
#include "control/agent.hpp"

namespace P {

class PModule : public ModuleInterface {
public:
    virtual void init(Silo *silo, Conf::ConfigSetting *setting);

    virtual void start() {}

    virtual Control::BaseAgent *get_control_agent() { return &_agent; }

    static ModuleId get_id() { return ModuleId::P; }

    static void generate_config(P::Conf::ConfigSetting *module_config);
    static void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources);

private:
    PModuleAgent _agent;
};  // class PModule

}  // namespace P
