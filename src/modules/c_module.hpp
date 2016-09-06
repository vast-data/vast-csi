/* Copyright (C) Vast Data Ltd. */

/*!
 * \file c_module.hpp
 * \brief The Controller module.
 *
 * Leader election should make sure a single instance of this module is be running at any given time.
 */
#pragma once

#include "c_module.hpp"
#include "plasma/execution/silo.hpp"
#include "plasma/control/agent.hpp"

namespace Control {

class CModule : public ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting);

    virtual void start();

    virtual BaseAgent *get_control_agent() { return nullptr; }

    static ModuleId get_id() { return ModuleId::C; }

    static const char *get_name() { return "C"; }

private:
    BaseAgent _agent;
};

} // namespace Control
