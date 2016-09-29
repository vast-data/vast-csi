/* Copyright (C) Vast Data Ltd. */

/*!
 * \file i_module.hpp
 * \brief The interface module.
 */
#pragma once

#include "module_interface.hpp"
#include "estore/estore.hpp"
#include "control/agent.hpp"
#include "control/dev_agent/dev_agent.hpp"
#include "plasma/execution/config.hpp"
#include "proto/nfs3/nfs_proto.hpp"


class IModule : public ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting);
    virtual void start();
    virtual Control::BaseAgent* get_control_agent() { return &_agent; }
    static ModuleId get_id() { return ModuleId::I; }

    static void generate_config(P::Conf::ConfigSetting *module_config);
    static void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources);

private:
    Nfs::NfsProto _nfs;
    EStore::EStore _estore;
    Control::DevAgent _dev_agent;
    Control::BaseAgent _agent;
};
