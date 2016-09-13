/* Copyright (C) Vast Data Ltd. */

/*!
 * \file c_module.hpp
 * \brief The Controller module.
 *
 * Leader election should make sure a single instance of this module is be running at any given time.
 */
#pragma once

#include "c_module.hpp"
#include "control/agent.hpp"
#include "control/imdb/system.hpp"
#include "control/imdb/component.hpp"
#include "control/cluster/component.hpp"
#include "plasma/execution/silo.hpp"

namespace Control {

class CModule : public ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting);

    virtual void start();

    virtual BaseAgent *get_control_agent() { return nullptr; }

    static ModuleId get_id() { return ModuleId::C; }

    static void generate_config(P::Conf::ConfigSetting *module_config);
    static void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources);

private:
    BaseAgent _agent;
    Cluster _cluster;
    TreeDB _tree;
    System *_system;
};

} // namespace Control
