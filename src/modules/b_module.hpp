/* Copyright (C) Vast Data Ltd. */

/*!
 * \file b_module.hpp
 * \brief The Env module.
 *
 * B - Box Module
 */
#pragma once

#include "plasma/execution/env.hpp"
#include "module_interface.hpp"
#include "plasma/execution/silo.hpp"
#include "plasma/execution/config.hpp"
#include "b_module_agent.hpp"
#include "lock_manager/lock_manager_server.hpp"

class BModule : public ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting);

    virtual void start();

    virtual Control::BaseAgent *get_control_agent() { return &_agent; }

    static ModuleId get_id() { return ModuleId::B; }

    static void generate_config(P::Conf::ConfigSetting *module_config);
    static void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources);

private:
    BModuleAgent _agent;
    LockManager::LockManagerServerImpl _lock_manager_server;
};
